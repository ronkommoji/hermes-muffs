# Deploying Hermes on a Hetzner VPS (alongside another agent)

This guide assumes you already SSH into the server, you run **another stack** (“nanobot”) on **`nanobot.ascentsolns.com`**, and you want **Hermes** on **`hermes.ascentsolns.com`** without clashes.

Hermes keeps its **state** under **`HERMES_HOME`** (default `~/.hermes`). Nanobot almost certainly uses **different paths, ports, and services**. The main clash risks are: **same Linux user + same ports**, **same Telegram bot token**, or **one reverse proxy overwriting the other**.

---

## 1. Isolation strategy (recommended)

**Use a dedicated Unix user for Hermes** (e.g. `hermes`). That gives you:

- Separate home → separate default `~/.hermes`
- Separate systemd **user** services (no fighting nanobot’s units)
- Clear ownership of files and processes

```bash
sudo adduser --disabled-password --gecos "" hermes
sudo mkdir -p /opt/hermes-app
sudo chown hermes:hermes /opt/hermes-app
```

You can install the **code** under `/opt/hermes-app/hermes-agent` and keep **data** in `/home/hermes/.hermes` (default), or set **`HERMES_HOME`** to something like `/opt/hermes-data` — both are fine if **only the `hermes` user** writes there.

You *can* run Hermes as your existing user instead; then just use a **different `HERMES_HOME`** and **different dashboard/gateway ports** if nanobot already uses **9119** or **8642**.

**Check for port conflicts:**

```bash
ss -tlnp | grep -E '9119|8642'
```

If nanobot (or anything else) already listens on **9119**, pick another dashboard port (e.g. **9120**) in the systemd unit below. Same for **8642** if you expose the Hermes gateway API.

---

## 2. DNS (Ascent Solutions)

In your DNS provider (where `ascentsolns.com` is hosted):

1. **A record** (or AAAA for IPv6): **`hermes.ascentsolns.com`** → your **Hetzner server public IP**.

Wait for propagation (often minutes; TTL dependent).

---

## 3. Firewall (Hetzner Cloud + UFW example)

- Hetzner **Cloud Firewall**: allow **22** (SSH), **80**, **443**. Do **not** need to expose **9119** or **8642** publicly if you reverse-proxy **only** on 443.
- On the VPS (optional but common), **UFW**:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Hermes **dashboard** and **gateway API** should listen on **`127.0.0.1`**; only **Caddy/nginx** faces the internet.

---

## 4. Install Hermes (native, no Docker)

As user **`hermes`**:

```bash
sudo -iu hermes
cd /opt/hermes-app
# If git is not installed: sudo apt update && sudo apt install -y git curl build-essential
git clone https://github.com/YOUR_ORG/hermes-agent.git
cd hermes-agent
```

Install **Python 3.12+** (Debian/Ubuntu example):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[all]"
```

Build the **web dashboard** assets (needed once, and again after `git pull` if you use the dashboard):

```bash
cd web && npm ci && npm run build && cd ..
```

Run **interactive setup** (model, keys, optional messaging):

```bash
hermes setup
```

Configure your **messaging platform** (Telegram bot, etc.) per the docs; use a **different bot token** than nanobot if both are on Telegram.

---

## 5. Gateway (messaging) as a systemd service

Still as **`hermes`**, install the unit:

```bash
hermes gateway install
hermes gateway start
# hermes gateway status
```

That creates a **user-scoped** unit like `hermes-gateway.service` (default profile). It should **not** collide with nanobot’s units if nanobot runs under another user or uses different unit names.

If the **OpenAI-compatible API / health** on **8642** is only needed **locally** for the dashboard, keep the default **bind to localhost** in config (do not publish **8642** on `0.0.0.0` unless you intend to).

---

## 6. Web dashboard locally + subdomain with TLS

The dashboard is sensitive (config, keys UI). **Recommended pattern:**

1. Uvicorn listens on **`127.0.0.1:9119`** (default `hermes dashboard --host 127.0.0.1 --port 9119`).
2. **Caddy** (or nginx) terminates TLS for **`hermes.ascentsolns.com`** and reverse-proxies to **`127.0.0.1:9119`**.
3. Add **HTTP basic auth** or **IP allowlist** in the proxy — Hermes’s own auth is a **per-process session token**, not a full login product.

**Environment for dashboard** (if gateway runs on same machine — so the UI shows gateway health):

```bash
export GATEWAY_HEALTH_URL=http://127.0.0.1:8642
```

Create a **systemd user** service for the dashboard, e.g. `~/.config/systemd/user/hermes-dashboard.service`:

```ini
[Unit]
Description=Hermes web dashboard
After=network-online.target

[Service]
Type=simple
Environment=HERMES_WEB_DIST=/opt/hermes-app/hermes-agent/hermes_cli/web_dist
Environment=GATEWAY_HEALTH_URL=http://127.0.0.1:8642
WorkingDirectory=/opt/hermes-app/hermes-agent
ExecStart=/opt/hermes-app/hermes-agent/.venv/bin/hermes dashboard --host 127.0.0.1 --port 9119 --no-open
Restart=on-failure

[Install]
WantedBy=default.target
```

Then:

```bash
loginctl enable-linger hermes   # as root, so user services survive logout
sudo -iu hermes
systemctl --user daemon-reload
systemctl --user enable --now hermes-dashboard.service
```

**Do not** use `hermes dashboard --insecure` on a public VPS unless you fully understand the warning: it exposes the control plane on the network interface you bind.

---

## 7. Caddy example for `hermes.ascentsolns.com`

Install Caddy; add a site file (path depends on distro — e.g. `/etc/caddy/Caddyfile`):

```caddyfile
hermes.ascentsolns.com {
    encode zstd gzip

    # Strongly recommended: basic auth in front of the dashboard.
    # Run:  caddy hash-password
    # Then paste username + bcrypt hash below (see Caddy basicauth docs).
    basicauth {
        youruser $2a$14$REPLACE_WITH_c_hash-password_OUTPUT
    }

    reverse_proxy 127.0.0.1:9119
}
```

Reload Caddy. Open **`https://hermes.ascentsolns.com`**.

**Nanobot** stays on its **own** host block (`nanobot.ascentsolns.com` → its upstream). No overlap as long as each block points to the correct **localhost** port.

---

## 8. Provider keys, Integrations UI, persona

- **API keys / .env**: via **`hermes setup`**, editing **`$HERMES_HOME/.env`**, or the dashboard **Keys** page when logged in through the proxy.
- **Google Workspace / GitHub quick connect**: dashboard **Integrations** page (if your build includes it), else follow repo skills / CLI.
- **Persona (Muffs)**: edit **`$HERMES_HOME/SOUL.md`** (or the profile under **`$HERMES_HOME/profiles/...`**). Your repo’s **`docker/SOUL.md`** / **`hermes_cli/default_soul.py`** only apply when that file is **created from defaults**; an existing install keeps its current `SOUL.md` until you replace it.

---

## 9. Coexistence checklist with nanobot

| Concern | What to verify |
|--------|----------------|
| **Unix user / home** | Hermes under `hermes` user (recommended) or separate `HERMES_HOME` |
| **Ports** | **9119** (dashboard), **8642** (gateway HTTP) not shared with nanobot on the same interface; use `ss -tlnp` |
| **systemd units** | Hermes: `hermes-gateway*.service`; nanobot: different names / user |
| **Reverse proxy** | Two **server_name** blocks; two upstream ports |
| **Telegram** | **Different bot** / token per product if both use Telegram |
| **TLS certs** | Caddy auto-HTTPS per host; no cert path collision |

---

## 10. Updates

```bash
sudo -iu hermes
cd /opt/hermes-app/hermes-agent
git pull
source .venv/bin/activate
pip install -e ".[all]"
cd web && npm ci && npm run build && cd ..
hermes update   # may restart gateway(s); follow CLI output
systemctl --user restart hermes-dashboard.service
```

---

## 11. If something fails

- **`hermes doctor`** — quick health signals.
- **Logs**: `~/.hermes/logs/` (or `HERMES_HOME/logs`) — `agent.log`, `errors.log`, `gateway.log`.
- **Gateway**: `hermes gateway status`.
- **Dashboard 401**: session token / reverse proxy stripping `X-Hermes-Session-Token` — prefer a simple proxy config; avoid caching `/api/*`.

---

*This file is a practical runbook for your domain layout; adjust paths (`/opt/hermes-app`) and git remote to match how you fork or mirror the repo.*
