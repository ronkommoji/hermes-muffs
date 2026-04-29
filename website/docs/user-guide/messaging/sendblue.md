---
sidebar_label: 'Sendblue (iMessage / SMS)'
description: Connect Hermes to iMessage and SMS through the Sendblue cloud API — ngrok, your own subdomain on a VPS, optional tunnel automation, and webhook registration.
---

# Sendblue (iMessage / SMS)

[Sendblue](https://sendblue.com/) provides a hosted API for iMessage and SMS. Unlike [BlueBubbles](bluebubbles.md), you do not run a Mac server — you use Sendblue phone numbers and API keys.

Hermes:

- Listens for inbound messages on a **local HTTP port** (default **8646**).
- Needs a **public HTTPS URL** for Sendblue to POST webhooks — either you set `SENDBLUE_WEBHOOK_PUBLIC_URL`, or you enable **`SENDBLUE_AUTO_NGROK`** and Hermes runs **[ngrok](https://ngrok.com/)** and discovers the URL from ngrok’s local API.
- On gateway start, **registers** the public base URL + `/sendblue-webhook` with Sendblue as a **receive** webhook.

## Prerequisites

- Sendblue account with **API Key ID**, **API Secret**, and a **Sendblue number** (`SENDBLUE_FROM_NUMBER`, E.164).
- For **automatic** tunnels: [ngrok](https://ngrok.com/) installed and on your `PATH` (or set `SENDBLUE_NGROK_BIN`). For **manual** tunnels, any HTTPS reverse proxy or tunnel is fine.

## Quick setup (automatic ngrok)

1. In `~/.hermes/.env` (or the setup wizard), set:

   - `SENDBLUE_API_KEY_ID`
   - `SENDBLUE_API_SECRET_KEY`
   - `SENDBLUE_FROM_NUMBER` (e.g. `+15551234567`)
   - `SENDBLUE_AUTO_NGROK=true`

   Leave **`SENDBLUE_WEBHOOK_PUBLIC_URL` unset** unless you use a stable reserved domain and manage ngrok yourself (see below).

2. Start the gateway: `hermes gateway`

Hermes brings up the webhook listener, then either attaches to an **already-running** ngrok session on port **4040** (if it already forwards to your webhook port) or starts **`ngrok http 127.0.0.1:8646`** as a child process, reads the HTTPS URL from `http://127.0.0.1:4040/api/tunnels`, and registers that URL with Sendblue. When the gateway exits, **child ngrok** is stopped automatically.

## Quick setup (manual public URL)

1. Set `SENDBLUE_WEBHOOK_PUBLIC_URL` to your **HTTPS** base URL (e.g. `https://abc123.ngrok-free.app` — **no path**). Do **not** set `SENDBLUE_AUTO_NGROK` (or set it to `false`).

2. Start the gateway: `hermes gateway`

3. In another terminal, tunnel the webhook port (default 8646), e.g. `ngrok http 8646`, and keep the forwarding URL in sync with `SENDBLUE_WEBHOOK_PUBLIC_URL` (restart the gateway after URL changes, or use a reserved ngrok domain).

## Production: VPS with your own subdomain

If the gateway runs on a **VPS with a public IP**, you usually **do not need ngrok**. Use a real hostname and terminate **HTTPS** on the server.

1. **DNS** — Create a record (e.g. `hermes.example.com`) pointing to the VPS (**A** or **AAAA**).

2. **TLS + reverse proxy** — Use Caddy, nginx + Let’s Encrypt, Traefik, or similar. Terminate HTTPS on **443** and proxy to the Hermes webhook listener.

3. **Path** — Sendblue calls the URL Hermes registers: your public **base** URL plus **`SENDBLUE_WEBHOOK_PATH`** (default **`/sendblue-webhook`**). Example vhost target:

   - Public: `https://hermes.example.com/sendblue-webhook`
   - Upstream: `http://127.0.0.1:8646/sendblue-webhook` (adjust host/port if you changed `SENDBLUE_WEBHOOK_HOST` / `SENDBLUE_WEBHOOK_PORT`).

4. **Environment** — Set **`SENDBLUE_WEBHOOK_PUBLIC_URL=https://hermes.example.com`** (HTTPS **only the origin**, no path — Hermes appends the webhook path). Leave **`SENDBLUE_AUTO_NGROK`** unset or **`false`**.

5. **Hardening (recommended)** — Bind the local listener to loopback only: **`SENDBLUE_WEBHOOK_HOST=127.0.0.1`** so only the reverse proxy can reach the gateway; open **443** on the firewall, not the raw webhook port.

6. **Register** — Start (or restart) **`hermes gateway`** so Hermes re-registers the receive webhook with Sendblue for the new public URL.

**Multiple gateways on one VPS** — Use a **different subdomain** and **backend port** per instance (and usually **separate Sendblue lines / API credentials** so inbound events are not delivered to both). Point each vhost at the matching `127.0.0.1:<port>`.

## Security

- Use **HTTPS** for `SENDBLUE_WEBHOOK_PUBLIC_URL` (required).
- Set `SENDBLUE_WEBHOOK_SECRET` to match the secret Sendblue sends in the `sb-signing-secret` header. If unset, Hermes still accepts webhooks but logs a warning (verify signing in production).

## Typing indicators and tapbacks

While the agent is running, Hermes refreshes the **typing indicator** during long replies (same pattern as other channels). This uses Sendblue’s `POST /api/send-typing-indicator` for **1:1 chats** (E.164 `chat_id`). **Group** chats do not get outbound typing from Hermes today — Sendblue’s typing API is scoped to a single recipient number.

Optional **tapbacks** on the user’s **inbound** message (iMessage only — not SMS):

- Set `SENDBLUE_REACTIONS=true` (or `sendblue.reactions: true` in `config.yaml`).
- **Processing:** `emphasize` (‼️) → **done:** `like` (success) or `dislike` (failure). Cancelled runs do not send a final tapback.

## Allowlists and home channel

- `SENDBLUE_ALLOWED_USERS` — comma-separated E.164 numbers allowed to DM the bot (optional; otherwise use global gateway allow-all / pairing behavior).
- `SENDBLUE_GROUP_ALLOWED_USERS` — comma-separated Hermes chat IDs for groups: `sendblue:group:<uuid>` (optional).
- `SENDBLUE_HOME_CHANNEL` — default target for cron and notifications (E.164 or `sendblue:group:...`).

## Troubleshooting

- **No inbound messages:** Confirm ngrok is running (tunnel mode) or `SENDBLUE_AUTO_NGROK` succeeded (check logs for the discovered public URL). On a **VPS**, confirm DNS, TLS, and the reverse proxy path reach `http://127.0.0.1:<SENDBLUE_WEBHOOK_PORT><SENDBLUE_WEBHOOK_PATH>`. `SENDBLUE_WEBHOOK_PUBLIC_URL` must match the HTTPS origin clients use (no path); restart the gateway after URL or proxy changes so Sendblue is re-registered.
- **Auto ngrok fails:** Ensure `ngrok` is installed (`which ngrok`). If another app uses a custom ngrok web UI port, set `SENDBLUE_NGROK_API` to that base URL. If you already run ngrok yourself, Hermes will reuse it when the tunnel forwards to `SENDBLUE_WEBHOOK_PORT`.
- **Registration errors:** Check gateway logs; ensure API key headers are correct and the public URL is reachable from the internet.

See also: [Environment variables](/docs/reference/environment-variables) (search for `SENDBLUE_`).
