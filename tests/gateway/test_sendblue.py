"""Tests for the Sendblue gateway adapter."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig


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
        import asyncio
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
        import asyncio
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
