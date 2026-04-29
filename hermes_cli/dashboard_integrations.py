"""Dashboard helpers for third-party integration setup (Google Workspace, GitHub)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_cli.config import get_hermes_home, load_config


def _google_setup_script(repo_root: Path) -> Path:
    return (
        repo_root
        / "skills"
        / "productivity"
        / "google-workspace"
        / "scripts"
        / "setup.py"
    )


def _hermes_subprocess_env() -> dict[str, str]:
    return {**os.environ, "HERMES_HOME": str(get_hermes_home().resolve())}


def run_google_workspace_setup(
    repo_root: Path,
    args: list[str],
    *,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    """Run skills/productivity/google-workspace/scripts/setup.py with *args*.

    Returns (exit_code, stdout, stderr).
    """
    script = _google_setup_script(repo_root)
    if not script.is_file():
        return (
            127,
            "",
            f"Google Workspace setup script not found at {script}",
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_hermes_subprocess_env(),
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "Timed out running Google Workspace setup."
    except OSError as e:
        return 1, "", str(e)


def google_workspace_connection_info(repo_root: Path) -> Dict[str, Any]:
    """Return UI-friendly Google Workspace OAuth state for the active HERMES_HOME."""
    home = get_hermes_home()
    token_path = home / "google_token.json"
    secret_path = home / "google_client_secret.json"
    pending_path = home / "google_oauth_pending.json"

    code, out, err = run_google_workspace_setup(repo_root, ["--check"], timeout=60.0)
    authenticated = code == 0
    partial = "partial" in out.lower() if out else False
    summary = (out or err or "").strip()

    return {
        "authenticated": authenticated,
        "partial_scopes": partial,
        "has_client_secret": secret_path.is_file(),
        "has_token_file": token_path.is_file(),
        "pending_oauth": pending_path.is_file(),
        "check_exit_code": code,
        "detail": summary[-2000:] if summary else None,
    }


def _extract_auth_url_from_setup_stdout(stdout: str) -> Optional[str]:
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            return line
    # Fallback: first URL-like token in blob
    m = re.search(r"https://[^\s\"']+", stdout or "")
    return m.group(0) if m else None


def google_workspace_begin_oauth(repo_root: Path) -> Dict[str, Any]:
    """Run --auth-url and return {ok, auth_url?, error?}."""
    code, out, err = run_google_workspace_setup(repo_root, ["--auth-url"], timeout=120.0)
    if code != 0:
        msg = (err or out or "Failed to build authorization URL.").strip()
        return {"ok": False, "error": msg[-4000:]}
    url = _extract_auth_url_from_setup_stdout(out)
    if not url:
        return {
            "ok": False,
            "error": "Setup ran but no URL was found in output. "
            "Install Google deps: pip install 'hermes-agent[google]'",
        }
    return {"ok": True, "auth_url": url}


def google_workspace_store_client_secret_json(
    repo_root: Path, secret_obj: dict[str, Any]
) -> Dict[str, Any]:
    """Validate and persist OAuth client JSON via setup.py."""
    if "installed" not in secret_obj and "web" not in secret_obj:
        return {
            "ok": False,
            "error": "Invalid OAuth client JSON — expected 'installed' (Desktop) or 'web' key.",
        }
    import tempfile

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(secret_obj, tmp)
            tmp_path = tmp.name
        code, out, err = run_google_workspace_setup(
            repo_root,
            ["--client-secret", tmp_path],
            timeout=60.0,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if code != 0:
        return {"ok": False, "error": (err or out or "client-secret failed").strip()[-4000:]}
    return {"ok": True, "message": (out or "Saved.").strip()}


def google_workspace_exchange_code(repo_root: Path, code_or_url: str) -> Dict[str, Any]:
    raw = (code_or_url or "").strip()
    if not raw:
        return {"ok": False, "error": "Authorization code is empty."}
    code, out, err = run_google_workspace_setup(
        repo_root,
        ["--auth-code", raw],
        timeout=120.0,
    )
    if code != 0:
        return {"ok": False, "error": (err or out or "Exchange failed").strip()[-4000:]}
    return {"ok": True, "message": (out or "Authenticated.").strip()}


def google_workspace_revoke(repo_root: Path) -> Dict[str, Any]:
    code, out, err = run_google_workspace_setup(repo_root, ["--revoke"], timeout=120.0)
    # revoke exits 0 even when no token; still ok for UI
    return {
        "ok": True,
        "message": (out or err or "Done.").strip()[-4000:],
        "exit_code": code,
    }


def github_connection_info() -> Dict[str, Any]:
    """Detect GitHub auth: gh CLI, GITHUB_TOKEN, or GH_TOKEN."""
    token_from_env = bool(
        (os.environ.get("GITHUB_TOKEN") or "").strip()
        or (os.environ.get("GH_TOKEN") or "").strip()
    )
    try:
        from hermes_cli.config import load_env

        data = load_env()
        token_from_env = token_from_env or bool((data.get("GITHUB_TOKEN") or "").strip())
        token_from_env = token_from_env or bool((data.get("GH_TOKEN") or "").strip())
    except Exception:
        pass

    gh_ok = False
    gh_hint: Optional[str] = None
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            env=_hermes_subprocess_env(),
        )
        gh_ok = proc.returncode == 0
        if not gh_ok and (proc.stderr or proc.stdout):
            gh_hint = (proc.stderr or proc.stdout).strip()[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        gh_hint = "GitHub CLI (gh) is not installed or not on PATH."

    return {
        "connected": gh_ok or token_from_env,
        "gh_cli_authenticated": gh_ok,
        "token_in_env": token_from_env,
        "gh_hint": gh_hint,
    }


def mcp_servers_summary() -> Dict[str, Any]:
    """Lightweight MCP config summary from config.yaml."""
    try:
        cfg = load_config() or {}
        servers = (cfg.get("mcp_servers") or {}) if isinstance(cfg, dict) else {}
        if not isinstance(servers, dict):
            servers = {}
        names = sorted(servers.keys())
        return {
            "configured": bool(names),
            "server_count": len(names),
            "server_names": names,
        }
    except Exception as e:
        return {"configured": False, "server_count": 0, "server_names": [], "error": str(e)}


def integrations_snapshot(repo_root: Path) -> Dict[str, Any]:
    return {
        "google_workspace": google_workspace_connection_info(repo_root),
        "github": github_connection_info(),
        "mcp": mcp_servers_summary(),
    }
