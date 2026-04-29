"""Sendblue iMessage/SMS platform adapter.

Uses the Sendblue cloud API (https://api.sendblue.co) for outbound messages and
an aiohttp webhook for inbound ``receive`` events. Inbound delivery requires a
public HTTPS URL — use ``SENDBLUE_WEBHOOK_PUBLIC_URL`` or
``SENDBLUE_AUTO_NGROK`` to run (or attach to) ngrok and discover the URL from
the ngrok agent API. On connect, Hermes registers the full webhook URL with
Sendblue via ``POST /api/account/webhooks``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    ProcessingOutcome,
    SendResult,
    cache_audio_from_bytes,
    cache_document_from_bytes,
    cache_image_from_bytes,
)
from gateway.platforms.helpers import redact_phone, strip_markdown

logger = logging.getLogger(__name__)

SENDBLUE_API_BASE = "https://api.sendblue.co"
DEFAULT_WEBHOOK_HOST = "0.0.0.0"
DEFAULT_WEBHOOK_PORT = 8646
DEFAULT_WEBHOOK_PATH = "/sendblue-webhook"
MAX_TEXT_LENGTH = 18_000
GROUP_PREFIX = "sendblue:group:"
_DEDUPE_CAP = 8192


def check_sendblue_requirements() -> bool:
    try:
        import aiohttp  # noqa: F401
        import httpx  # noqa: F401
    except ImportError:
        return False
    return True


def _is_https_url(url: str) -> bool:
    try:
        parsed = dict(urlparse(url.strip()))
        return parsed.get("scheme", "").lower() == "https"
    except Exception:
        return False


def _normalize_public_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def _truthy_env(key: str) -> bool:
    return os.getenv(key, "").strip().lower() in ("1", "true", "yes", "on")


def pick_ngrok_https_public_url(tunnels_payload: Any, local_port: int) -> Optional[str]:
    """Parse ngrok agent ``GET /api/tunnels`` JSON and return a matching https public URL.

    Prefer the tunnel whose ``config.addr`` (or similar) forwards to *local_port*.
    If none match but there is exactly one https tunnel, use that.
    """
    if not isinstance(tunnels_payload, dict):
        return None
    tunnels = tunnels_payload.get("tunnels")
    if not isinstance(tunnels, list):
        return None
    port_fragment = f":{local_port}"
    matching: List[str] = []
    fallback_https: List[str] = []
    for t in tunnels:
        if not isinstance(t, dict):
            continue
        if (t.get("proto") or "").lower() != "https":
            continue
        pub = (t.get("public_url") or "").strip()
        if not pub:
            continue
        cfg = t.get("config")
        addr = ""
        if isinstance(cfg, dict):
            addr = str(cfg.get("addr") or "")
        forward = str(
            t.get("forwards_to")
            or t.get("forwarding_to")
            or t.get("forward_addr")
            or ""
        )
        if port_fragment in addr or port_fragment in forward:
            matching.append(pub)
        else:
            fallback_https.append(pub)
    if matching:
        return _normalize_public_url(matching[0])
    if len(fallback_https) == 1:
        return _normalize_public_url(fallback_https[0])
    return None


class SendblueAdapter(BasePlatformAdapter):
    platform = Platform.SENDBLUE
    SUPPORTS_MESSAGE_EDITING = False
    MAX_MESSAGE_LENGTH = MAX_TEXT_LENGTH

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.SENDBLUE)
        extra = config.extra or {}
        self._api_key_id = (
            (extra.get("api_key_id") or os.getenv("SENDBLUE_API_KEY_ID", "")).strip()
        )
        self._api_secret_key = (
            (extra.get("api_secret_key") or os.getenv("SENDBLUE_API_SECRET_KEY", "")).strip()
        )
        self._from_number = (
            (extra.get("from_number") or os.getenv("SENDBLUE_FROM_NUMBER", "")).strip()
        )
        self._public_url = _normalize_public_url(
            extra.get("webhook_public_url") or os.getenv("SENDBLUE_WEBHOOK_PUBLIC_URL", "")
        )
        self._webhook_host = (
            extra.get("webhook_host")
            or os.getenv("SENDBLUE_WEBHOOK_HOST", DEFAULT_WEBHOOK_HOST)
        ).strip()
        self._webhook_port = int(
            extra.get("webhook_port")
            or os.getenv("SENDBLUE_WEBHOOK_PORT", str(DEFAULT_WEBHOOK_PORT))
        )
        wp = extra.get("webhook_path") or os.getenv(
            "SENDBLUE_WEBHOOK_PATH", DEFAULT_WEBHOOK_PATH
        )
        self._webhook_path = wp if str(wp).startswith("/") else f"/{wp}"
        self._webhook_secret = (
            extra.get("webhook_secret") or os.getenv("SENDBLUE_WEBHOOK_SECRET", "")
        ).strip()
        self._skip_register = os.getenv(
            "SENDBLUE_SKIP_WEBHOOK_REGISTER", ""
        ).lower() in ("1", "true", "yes")
        self._http: Optional[httpx.AsyncClient] = None
        self._runner = None
        self._seen_handles: Set[str] = set()
        self._ngrok_proc: Any = None
        self._ngrok_owned = False

    @staticmethod
    def _reactions_enabled() -> bool:
        return os.getenv("SENDBLUE_REACTIONS", "false").lower() not in (
            "false",
            "0",
            "no",
        )

    @staticmethod
    def _is_imessage_service(raw: Any) -> bool:
        """Tapbacks apply to iMessage only, not SMS."""
        if not isinstance(raw, dict):
            return True
        svc = str(raw.get("service") or "").strip().upper()
        if not svc:
            return True
        return svc != "SMS"

    @property
    def _receive_url(self) -> str:
        return f"{self._public_url}{self._webhook_path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "sb-api-key-id": self._api_key_id,
            "sb-api-secret-key": self._api_secret_key,
        }

    async def connect(self) -> bool:
        if not self._api_key_id or not self._api_secret_key:
            logger.error("[sendblue] SENDBLUE_API_KEY_ID and SENDBLUE_API_SECRET_KEY are required")
            return False
        if not self._from_number:
            logger.error("[sendblue] SENDBLUE_FROM_NUMBER is required")
            return False

        auto_ngrok = _truthy_env("SENDBLUE_AUTO_NGROK")
        if not auto_ngrok:
            if not self._public_url:
                logger.error(
                    "[sendblue] SENDBLUE_WEBHOOK_PUBLIC_URL is required "
                    "(or set SENDBLUE_AUTO_NGROK=true to start ngrok and discover the URL)"
                )
                return False
            if not _is_https_url(self._public_url):
                logger.error(
                    "[sendblue] SENDBLUE_WEBHOOK_PUBLIC_URL must be an https:// URL (Sendblue webhook policy)"
                )
                return False
        elif self._public_url and not _is_https_url(self._public_url):
            logger.error(
                "[sendblue] SENDBLUE_WEBHOOK_PUBLIC_URL must be an https:// URL (Sendblue webhook policy)"
            )
            return False

        if not self._acquire_platform_lock(
            "sendblue-api-key",
            self._api_key_id,
            "Sendblue API credentials",
        ):
            return False

        self._http = httpx.AsyncClient(timeout=30.0)
        self._ngrok_proc = None
        self._ngrok_owned = False

        from aiohttp import web

        app = web.Application()
        app.router.add_get("/health", lambda _: web.Response(text="ok"))
        app.router.add_post(self._webhook_path, self._handle_webhook)

        self._runner = web.AppRunner(app)
        try:
            await self._runner.setup()
            site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
            await site.start()
        except OSError as exc:
            logger.error(
                "[sendblue] cannot bind webhook listener %s:%s — %s",
                self._webhook_host,
                self._webhook_port,
                exc,
            )
            await self._runner.cleanup()
            self._runner = None
            await self._http.aclose()
            self._http = None
            self._release_platform_lock()
            return False

        try:
            if auto_ngrok:
                discovered = await self._ensure_ngrok_public_url()
                if not discovered:
                    raise RuntimeError("ngrok_public_url")
                self._public_url = discovered
                logger.info("[sendblue] public webhook base URL: %s", self._public_url)
            elif not _is_https_url(self._public_url):
                raise RuntimeError("bad_public_url")

            if not self._skip_register:
                ok = await self._register_receive_webhook()
                if not ok:
                    raise RuntimeError("webhook_register")
        except RuntimeError:
            await self._teardown_ngrok_child()
            if self._runner:
                await self._runner.cleanup()
                self._runner = None
            if self._http:
                await self._http.aclose()
                self._http = None
            self._release_platform_lock()
            return False

        self._mark_connected()
        logger.info(
            "[sendblue] webhook listening on http://%s:%s%s (public %s)",
            self._webhook_host,
            self._webhook_port,
            self._webhook_path,
            self._receive_url,
        )
        return True

    async def _ngrok_fetch_tunnels_json(self, api_base: str) -> Optional[dict]:
        assert self._http is not None
        try:
            resp = await self._http.get(f"{api_base}/api/tunnels", timeout=2.0)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    async def _ensure_ngrok_public_url(self) -> Optional[str]:
        """Use a running ngrok agent or spawn ``ngrok http 127.0.0.1:<port>`` and read the HTTPS URL."""
        api_base = _normalize_public_url(
            os.getenv("SENDBLUE_NGROK_API", "http://127.0.0.1:4040")
        )
        if not api_base.lower().startswith("http"):
            api_base = f"http://{api_base}"
        ngrok_bin = (os.getenv("SENDBLUE_NGROK_BIN", "ngrok") or "ngrok").strip()
        if not ngrok_bin:
            ngrok_bin = "ngrok"

        for _ in range(20):
            payload = await self._ngrok_fetch_tunnels_json(api_base)
            if payload:
                url = pick_ngrok_https_public_url(payload, self._webhook_port)
                if url:
                    return url
            await asyncio.sleep(0.25)

        logger.info(
            "[sendblue] starting %s http 127.0.0.1:%s (SENDBLUE_AUTO_NGROK)",
            ngrok_bin,
            self._webhook_port,
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                ngrok_bin,
                "http",
                f"127.0.0.1:{self._webhook_port}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error(
                "[sendblue] ngrok executable not found (%r). Install ngrok or set SENDBLUE_NGROK_BIN.",
                ngrok_bin,
            )
            return None
        self._ngrok_proc = proc
        self._ngrok_owned = True

        for _ in range(120):
            await asyncio.sleep(0.25)
            if proc.returncode is not None:
                logger.error(
                    "[sendblue] ngrok exited early with code %s",
                    proc.returncode,
                )
                return None
            payload = await self._ngrok_fetch_tunnels_json(api_base)
            if payload:
                url = pick_ngrok_https_public_url(payload, self._webhook_port)
                if url:
                    return url

        logger.error(
            "[sendblue] timed out waiting for ngrok HTTPS URL (%s/api/tunnels)",
            api_base,
        )
        return None

    async def _teardown_ngrok_child(self) -> None:
        proc = self._ngrok_proc
        if not self._ngrok_owned or proc is None:
            self._ngrok_proc = None
            self._ngrok_owned = False
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception:
            pass
        self._ngrok_proc = None
        self._ngrok_owned = False

    async def _register_receive_webhook(self) -> bool:
        assert self._http is not None
        receive_url = self._receive_url
        try:
            resp = await self._http.post(
                f"{SENDBLUE_API_BASE}/api/account/webhooks",
                headers=self._headers(),
                json={"webhooks": [receive_url], "type": "receive"},
            )
            if resp.status_code >= 400:
                logger.error(
                    "[sendblue] webhook registration failed: %s %s",
                    resp.status_code,
                    resp.text[:500],
                )
                return False
            logger.info("[sendblue] registered receive webhook: %s", receive_url)
            return True
        except Exception as exc:
            logger.error("[sendblue] webhook registration error: %s", exc)
            return False

    async def disconnect(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        await self._teardown_ngrok_child()
        if self._http:
            await self._http.aclose()
            self._http = None
        self._release_platform_lock()
        self._mark_disconnected()

    def format_message(self, content: str) -> str:
        return strip_markdown(content)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        client = self._http
        close_after = False
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)
            close_after = True
        try:
            formatted = self.format_message(content)
            chunks = self.truncate_message(formatted)
            last = SendResult(success=True)
            for chunk in chunks:
                body: Dict[str, Any] = {
                    "content": chunk,
                    "from_number": self._from_number,
                }
                if chat_id.startswith(GROUP_PREFIX):
                    body["group_id"] = chat_id[len(GROUP_PREFIX) :]
                else:
                    body["number"] = chat_id
                try:
                    resp = await client.post(
                        f"{SENDBLUE_API_BASE}/api/send-message",
                        headers=self._headers(),
                        json=body,
                    )
                except Exception as exc:
                    logger.error("[sendblue] send error: %s", exc)
                    return SendResult(success=False, error=str(exc))
                if resp.status_code >= 400:
                    logger.error(
                        "[sendblue] send failed: %s %s",
                        resp.status_code,
                        resp.text[:300],
                    )
                    return SendResult(
                        success=False,
                        error=f"Sendblue HTTP {resp.status_code}",
                    )
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    data = {}
                mid = data.get("message_handle") or data.get("messageHandle")
                last = SendResult(success=True, message_id=str(mid) if mid else None)
            return last
        finally:
            if close_after and client is not None:
                await client.aclose()

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        if chat_id.startswith(GROUP_PREFIX):
            return {"name": chat_id, "type": "group", "chat_id": chat_id}
        return {"name": redact_phone(chat_id), "type": "dm", "chat_id": chat_id}

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """Show the iMessage/SMS typing indicator (DM only; groups not supported)."""
        client = self._http
        if not client or not self._from_number:
            return
        if chat_id.startswith(GROUP_PREFIX):
            logger.debug(
                "[sendblue] skip typing for group chat (API is recipient-number scoped)"
            )
            return
        body: Dict[str, Any] = {
            "from_number": self._from_number,
            "number": chat_id,
            "status": "typing",
        }
        try:
            resp = await client.post(
                f"{SENDBLUE_API_BASE}/api/send-typing-indicator",
                headers=self._headers(),
                json=body,
                timeout=5.0,
            )
            if resp.status_code >= 400:
                logger.debug(
                    "[sendblue] typing indicator HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.debug("[sendblue] typing indicator failed: %s", exc)

    async def _send_reaction(self, message_handle: str, reaction: str) -> None:
        client = self._http
        if not client or not message_handle:
            return
        body = {
            "from_number": self._from_number,
            "message_handle": message_handle,
            "reaction": reaction,
        }
        try:
            resp = await client.post(
                f"{SENDBLUE_API_BASE}/api/send-reaction",
                headers=self._headers(),
                json=body,
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.debug(
                    "[sendblue] reaction HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.debug("[sendblue] reaction failed: %s", exc)

    async def on_processing_start(self, event: MessageEvent) -> None:
        if not self._reactions_enabled():
            return
        if not self._is_imessage_service(event.raw_message):
            return
        mid = event.message_id
        if not mid:
            return
        # Tapback “emphasize” (‼️) — in-progress, analogous to Telegram 👀
        await self._send_reaction(mid, "emphasize")

    async def on_processing_complete(
        self, event: MessageEvent, outcome: ProcessingOutcome
    ) -> None:
        if not self._reactions_enabled():
            return
        if not self._is_imessage_service(event.raw_message):
            return
        mid = event.message_id
        if not mid or outcome == ProcessingOutcome.CANCELLED:
            return
        reaction = "like" if outcome == ProcessingOutcome.SUCCESS else "dislike"
        await self._send_reaction(mid, reaction)

    def _verify_webhook_secret(self, request) -> bool:
        if not self._webhook_secret:
            logger.warning(
                "[sendblue] SENDBLUE_WEBHOOK_SECRET not set — not verifying sb-signing-secret "
                "(set it to match your Sendblue webhook global secret)"
            )
            return True
        header = request.headers.get("sb-signing-secret", "")
        import hmac
        return hmac.compare_digest(
            (header or "").encode("utf-8"),
            self._webhook_secret.encode("utf-8"),
        )

    async def _handle_webhook(self, request):
        from aiohttp import web

        if not self._verify_webhook_secret(request):
            return web.Response(status=403, text="invalid signature")

        try:
            payload = await request.json()
        except Exception as exc:
            logger.error("[sendblue] webhook JSON error: %s", exc)
            return web.Response(status=400, text="bad json")

        if payload.get("is_outbound") is True:
            return web.Response(text="ok")

        status = str(payload.get("status") or "").upper()
        if status and status not in {"RECEIVED"}:
            return web.Response(text="ok")

        handle = str(payload.get("message_handle") or "").strip()
        if handle:
            if handle in self._seen_handles:
                return web.Response(text="ok")
            self._seen_handles.add(handle)
            if len(self._seen_handles) > _DEDUPE_CAP:
                self._seen_handles.clear()

        from_number = str(payload.get("from_number") or "").strip()
        content = str(payload.get("content") or "").strip()
        group_id = str(payload.get("group_id") or "").strip()
        media_url = str(payload.get("media_url") or "").strip()

        if from_number == self._from_number and not group_id:
            logger.debug("[sendblue] ignoring echo from own number")
            return web.Response(text="ok")

        if group_id:
            chat_id = f"{GROUP_PREFIX}{group_id}"
            chat_type = "group"
            user_id = from_number or chat_id
        else:
            chat_id = from_number
            chat_type = "dm"
            user_id = from_number

        if not chat_id:
            return web.Response(text="ok")

        logger.info(
            "[sendblue] inbound %s from %s (group=%s): %s",
            payload.get("service"),
            redact_phone(from_number),
            bool(group_id),
            (content or "")[:80],
        )

        source = self.build_source(
            chat_id=chat_id,
            chat_name=chat_id,
            chat_type=chat_type,
            user_id=user_id,
            user_name=from_number,
        )

        media_urls: List[str] = []
        media_types: List[str] = []
        msg_type = MessageType.TEXT

        if media_url and self._http:
            try:
                mresp = await self._http.get(media_url, timeout=30.0)
                mresp.raise_for_status()
                raw = mresp.content
                ctype = mresp.headers.get("content-type", "").lower()
                path_hint = media_url.split("?")[0].lower()
                ext = path_hint.rsplit(".", 1)[-1] if "." in path_hint else ""

                image_exts = {"jpg", "jpeg", "png", "gif", "webp", "heic"}
                audio_exts = {"mp3", "m4a", "aac", "wav", "ogg", "caf"}

                dot_ext = f".{ext}" if ext else ".jpg"
                if "image" in ctype or ext in image_exts:
                    cached = cache_image_from_bytes(raw, ext=dot_ext if ext in image_exts else ".jpg")
                    media_urls.append(cached)
                    media_types.append("image")
                    msg_type = MessageType.IMAGE
                elif "audio" in ctype or ext in audio_exts:
                    cached = cache_audio_from_bytes(raw, ext=dot_ext if ext in audio_exts else ".m4a")
                    media_urls.append(cached)
                    media_types.append("audio")
                    msg_type = MessageType.AUDIO
                else:
                    fname = f"attachment.{ext}" if ext else "attachment.bin"
                    cached = cache_document_from_bytes(raw, filename=fname)
                    media_urls.append(cached)
                    media_types.append("document")
                    msg_type = MessageType.DOCUMENT
            except Exception as exc:
                logger.warning("[sendblue] media download failed: %s", exc)

        text_out = content
        if not text_out and media_urls:
            text_out = "(attachment)"
        if not text_out and not media_urls:
            return web.Response(text="ok")

        event = MessageEvent(
            text=text_out,
            message_type=msg_type,
            source=source,
            raw_message=payload,
            message_id=handle or None,
            media_urls=media_urls,
            media_types=media_types,
        )

        task = asyncio.create_task(self.handle_message(event))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return web.Response(text="ok")


async def send_sendblue_direct(
    extra: Dict[str, Any],
    chat_id: str,
    message: str,
) -> Dict[str, Any]:
    """Send one message via Sendblue without running the webhook adapter."""
    api_key_id = (extra.get("api_key_id") or os.getenv("SENDBLUE_API_KEY_ID", "")).strip()
    secret = (extra.get("api_secret_key") or os.getenv("SENDBLUE_API_SECRET_KEY", "")).strip()
    from_number = (extra.get("from_number") or os.getenv("SENDBLUE_FROM_NUMBER", "")).strip()
    if not api_key_id or not secret or not from_number:
        return {"error": "Sendblue: missing API credentials or SENDBLUE_FROM_NUMBER"}

    body: Dict[str, Any] = {
        "content": strip_markdown(message),
        "from_number": from_number,
    }
    if chat_id.startswith(GROUP_PREFIX):
        body["group_id"] = chat_id[len(GROUP_PREFIX) :]
    else:
        body["number"] = chat_id

    headers = {
        "Content-Type": "application/json",
        "sb-api-key-id": api_key_id,
        "sb-api-secret-key": secret,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SENDBLUE_API_BASE}/api/send-message",
                headers=headers,
                json=body,
            )
        if resp.status_code >= 400:
            return {"error": f"Sendblue HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        mid = data.get("message_handle") or data.get("messageHandle")
        return {
            "success": True,
            "platform": "sendblue",
            "chat_id": chat_id,
            "message_id": str(mid) if mid else None,
        }
    except Exception as exc:
        return {"error": f"Sendblue send failed: {exc}"}
