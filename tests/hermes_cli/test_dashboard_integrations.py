"""Tests for dashboard third-party integration helpers."""

from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_integrations_snapshot_keys(isolated_home):
    from hermes_cli.dashboard_integrations import integrations_snapshot

    root = Path(__file__).resolve().parents[2]
    s = integrations_snapshot(root)
    assert set(s.keys()) == {"google_workspace", "github", "mcp"}
    assert "authenticated" in s["google_workspace"]
    assert "has_client_secret" in s["google_workspace"]
    assert "connected" in s["github"]
    assert "server_count" in s["mcp"]


def test_google_workspace_store_client_secret_json_rejects_invalid(isolated_home):
    from hermes_cli.dashboard_integrations import google_workspace_store_client_secret_json

    root = Path(__file__).resolve().parents[2]
    r = google_workspace_store_client_secret_json(root, {"foo": "bar"})
    assert r.get("ok") is False
