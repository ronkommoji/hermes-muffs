"""Tests for the Sendblue gateway adapter."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType, ProcessingOutcome


def _make_adapter(monkeypatch, **extra):
    monkeypatch.setenv("SENDBLUE_API_KEY_ID", "key-id")
    monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "secret")
    monkeypatch.setenv("SENDBLUE_FROM_NUMBER", "+15550001111")
    monkeypatch.setenv("SENDBLUE_WEBHOOK_PUBLIC_URL", "https://example.ngrok-free.app")
    from gateway.platforms.sendblue import SendblueAdapter

    cfg = PlatformConfig(
        enabled=True,
        extra={
            "api_key_id": "key-id",
            "api_secret_key": "secret",
            "from_number": "+15550001111",
            "webhook_public_url": "https://example.ngrok-free.app",
            "webhook_path": "/sendblue-webhook",
            "webhook_host": "127.0.0.1",
            "webhook_port": 8646,
            **extra,
        },
    )
    return SendblueAdapter(cfg)


class TestSendblueConfigLoading:
    def test_apply_env_overrides_sendblue(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_API_KEY_ID", "kid")
        monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "sec")
        monkeypatch.setenv("SENDBLUE_FROM_NUMBER", "+19998887777")
        monkeypatch.setenv("SENDBLUE_WEBHOOK_PUBLIC_URL", "https://test.ngrok-free.app")
        monkeypatch.setenv("SENDBLUE_WEBHOOK_PORT", "9000")
        from gateway.config import GatewayConfig, _apply_env_overrides

        config = GatewayConfig()
        _apply_env_overrides(config)
        assert Platform.SENDBLUE in config.platforms
        sc = config.platforms[Platform.SENDBLUE]
        assert sc.enabled is True
        assert sc.extra["api_key_id"] == "kid"
        assert sc.extra["from_number"] == "+19998887777"
        assert sc.extra["webhook_public_url"] == "https://test.ngrok-free.app"
        assert sc.extra["webhook_port"] == 9000

    def test_home_channel_from_env(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_API_KEY_ID", "kid")
        monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "sec")
        monkeypatch.setenv("SENDBLUE_HOME_CHANNEL", "+15551234567")
        from gateway.config import GatewayConfig, _apply_env_overrides

        config = GatewayConfig()
        _apply_env_overrides(config)
        hc = config.platforms[Platform.SENDBLUE].home_channel
        assert hc is not None
        assert hc.chat_id == "+15551234567"

    def test_not_connected_without_required_extra(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_API_KEY_ID", "kid")
        monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "sec")
        monkeypatch.delenv("SENDBLUE_FROM_NUMBER", raising=False)
        from gateway.config import GatewayConfig, _apply_env_overrides

        config = GatewayConfig()
        _apply_env_overrides(config)
        assert Platform.SENDBLUE in config.platforms
        assert Platform.SENDBLUE not in config.get_connected_platforms()


class TestSendblueAdapter:
    def test_check_requirements(self):
        from gateway.platforms.sendblue import check_sendblue_requirements

        assert check_sendblue_requirements() is True

    def test_supports_message_editing_false(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        assert adapter.SUPPORTS_MESSAGE_EDITING is False

    def test_format_message_strips_markdown(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        assert "**hi**" not in adapter.format_message("**hi**")

    def test_send_builds_dm_body(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        posted = []

        async def fake_post(url, **kwargs):
            posted.append(kwargs.get("json", {}))
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: {"message_handle": "mh-1"}
            return r

        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        adapter._http = client

        result = asyncio.run(adapter.send("+19997776666", "hello"))

        assert result.success is True
        assert posted[0]["number"] == "+19997776666"
        assert posted[0]["from_number"] == "+15550001111"
        assert posted[0]["content"] == "hello"

    def test_send_group_uses_group_id(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        posted = []

        async def fake_post(url, **kwargs):
            posted.append(kwargs.get("json", {}))
            r = MagicMock()
            r.status_code = 200
            r.json = lambda: {}
            return r

        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        adapter._http = client

        asyncio.run(adapter.send("sendblue:group:g-uuid", "hi"))
        assert posted[0].get("group_id") == "g-uuid"
        assert "number" not in posted[0]

    def test_send_typing_dm_posts_indicator(self, monkeypatch):
        from gateway.platforms import sendblue as sb_mod

        adapter = _make_adapter(monkeypatch)
        posted = []

        async def fake_post(url, **kwargs):
            posted.append((url, kwargs.get("json", {})))
            r = MagicMock()
            r.status_code = 200
            return r

        client = MagicMock()
        client.post = AsyncMock(side_effect=fake_post)
        adapter._http = client

        asyncio.run(adapter.send_typing("+19997776666"))

        assert len(posted) == 1
        assert posted[0][0] == f"{sb_mod.SENDBLUE_API_BASE}/api/send-typing-indicator"
        assert posted[0][1]["number"] == "+19997776666"
        assert posted[0][1]["from_number"] == "+15550001111"
        assert posted[0][1]["status"] == "typing"

    def test_send_typing_skips_group(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        client = MagicMock()
        client.post = AsyncMock()
        adapter._http = client

        asyncio.run(adapter.send_typing("sendblue:group:g-uuid"))
        client.post.assert_not_called()

    def test_reactions_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SENDBLUE_REACTIONS", raising=False)
        from gateway.platforms.sendblue import SendblueAdapter

        assert SendblueAdapter._reactions_enabled() is False

    def test_reactions_enabled_when_env_set(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_REACTIONS", "true")
        from gateway.platforms.sendblue import SendblueAdapter

        assert SendblueAdapter._reactions_enabled() is True

    def test_on_processing_reactions_imessage(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_REACTIONS", "true")
        adapter = _make_adapter(monkeypatch)
        posted = []

        async def fake_post(url, **kwargs):
            posted.append((url, kwargs.get("json", {})))
            r = MagicMock()
            r.status_code = 200
            return r

        adapter._http = MagicMock()
        adapter._http.post = AsyncMock(side_effect=fake_post)

        src = adapter.build_source(
            chat_id="+19991112222",
            chat_name="c",
            chat_type="dm",
            user_id="+19991112222",
            user_name="u",
        )
        event = MessageEvent(
            text="hi",
            message_type=MessageType.TEXT,
            source=src,
            raw_message={"service": "iMessage"},
            message_id="mh-proc",
        )

        async def run():
            await adapter.on_processing_start(event)
            assert posted[0][1]["reaction"] == "emphasize"
            assert posted[0][1]["message_handle"] == "mh-proc"

            await adapter.on_processing_complete(event, ProcessingOutcome.SUCCESS)
            assert posted[1][1]["reaction"] == "like"

            await adapter.on_processing_complete(event, ProcessingOutcome.FAILURE)
            assert posted[2][1]["reaction"] == "dislike"

        asyncio.run(run())

    def test_on_processing_skips_sms_and_no_message_id(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_REACTIONS", "true")
        adapter = _make_adapter(monkeypatch)

        async def fake_post(url, **kwargs):
            r = MagicMock()
            r.status_code = 200
            return r

        adapter._http = MagicMock()
        adapter._http.post = AsyncMock(side_effect=fake_post)

        src = adapter.build_source(
            chat_id="+19991112222",
            chat_name="c",
            chat_type="dm",
            user_id="+19991112222",
            user_name="u",
        )
        sms_event = MessageEvent(
            text="hi",
            message_type=MessageType.TEXT,
            source=src,
            raw_message={"service": "SMS"},
            message_id="mh-sms",
        )
        im_event = MessageEvent(
            text="hi",
            message_type=MessageType.TEXT,
            source=src,
            raw_message={"service": "iMessage"},
            message_id=None,
        )

        async def run():
            await adapter.on_processing_start(sms_event)
            adapter._http.post.assert_not_awaited()
            await adapter.on_processing_start(im_event)
            adapter._http.post.assert_not_awaited()

        asyncio.run(run())

    def test_on_processing_complete_cancelled_no_post(self, monkeypatch):
        monkeypatch.setenv("SENDBLUE_REACTIONS", "true")
        adapter = _make_adapter(monkeypatch)
        adapter._http = MagicMock()
        adapter._http.post = AsyncMock()

        src = adapter.build_source(
            chat_id="+19991112222",
            chat_name="c",
            chat_type="dm",
            user_id="+19991112222",
            user_name="u",
        )
        event = MessageEvent(
            text="hi",
            message_type=MessageType.TEXT,
            source=src,
            raw_message={"service": "iMessage"},
            message_id="mh-x",
        )

        async def run():
            await adapter.on_processing_complete(event, ProcessingOutcome.CANCELLED)

        asyncio.run(run())
        adapter._http.post.assert_not_awaited()


def test_config_bridges_sendblue_reactions(monkeypatch, tmp_path):
    import yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "sendblue": {
                    "reactions": True,
                },
            }
        )
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SENDBLUE_REACTIONS", "")

    from gateway.config import load_gateway_config

    load_gateway_config()
    assert os.getenv("SENDBLUE_REACTIONS") == "true"


def test_config_bridges_sendblue_auto_ngrok(monkeypatch, tmp_path):
    import yaml

    (tmp_path / "config.yaml").write_text(
        yaml.dump({"sendblue": {"auto_ngrok": True}})
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SENDBLUE_AUTO_NGROK", "")

    from gateway.config import load_gateway_config

    load_gateway_config()
    assert os.getenv("SENDBLUE_AUTO_NGROK") == "true"


class TestSendblueNgrokUrl:
    def test_pick_ngrok_prefers_addr_matching_port(self):
        from gateway.platforms.sendblue import pick_ngrok_https_public_url

        data = {
            "tunnels": [
                {
                    "proto": "https",
                    "public_url": "https://abc.ngrok-free.app",
                    "config": {"addr": "http://127.0.0.1:8646"},
                },
            ]
        }
        assert pick_ngrok_https_public_url(data, 8646) == "https://abc.ngrok-free.app"

    def test_pick_ngrok_forwards_to_field(self):
        from gateway.platforms.sendblue import pick_ngrok_https_public_url

        data = {
            "tunnels": [
                {
                    "proto": "https",
                    "public_url": "https://z.ngrok-free.app",
                    "forwards_to": "http://127.0.0.1:9000",
                },
            ]
        }
        assert pick_ngrok_https_public_url(data, 9000) == "https://z.ngrok-free.app"

    def test_pick_ngrok_single_https_fallback(self):
        from gateway.platforms.sendblue import pick_ngrok_https_public_url

        data = {
            "tunnels": [
                {
                    "proto": "https",
                    "public_url": "https://only.ngrok-free.app",
                    "config": {"addr": "tcp://0.0.0.0:22"},
                },
            ]
        }
        assert pick_ngrok_https_public_url(data, 8646) == "https://only.ngrok-free.app"

    def test_pick_ngrok_no_match_multiple_https(self):
        from gateway.platforms.sendblue import pick_ngrok_https_public_url

        data = {
            "tunnels": [
                {
                    "proto": "https",
                    "public_url": "https://a.ngrok-free.app",
                    "config": {"addr": "http://127.0.0.1:1111"},
                },
                {
                    "proto": "https",
                    "public_url": "https://b.ngrok-free.app",
                    "config": {"addr": "http://127.0.0.1:2222"},
                },
            ]
        }
        assert pick_ngrok_https_public_url(data, 8646) is None
