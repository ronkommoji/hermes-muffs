---
sidebar_label: 'Sendblue (iMessage / SMS)'
description: Connect Hermes to iMessage and SMS through the Sendblue cloud API using ngrok and automatic webhook registration.
---

# Sendblue (iMessage / SMS)

[Sendblue](https://sendblue.com/) provides a hosted API for iMessage and SMS. Unlike [BlueBubbles](bluebubbles.md), you do not run a Mac server — you use Sendblue phone numbers and API keys.

Hermes:

- Listens for inbound messages on a **local HTTP port** (default **8646**).
- Expects a **public HTTPS URL** (typically **[ngrok](https://ngrok.com/)**) pointing at that port, set as `SENDBLUE_WEBHOOK_PUBLIC_URL`.
- On gateway start, **registers** `SENDBLUE_WEBHOOK_PUBLIC_URL` + `/sendblue-webhook` with Sendblue as a **receive** webhook.

## Prerequisites

- Sendblue account with **API Key ID**, **API Secret**, and a **Sendblue number** (`SENDBLUE_FROM_NUMBER`, E.164).
- [ngrok](https://ngrok.com/) (or another HTTPS tunnel) installed.

## Quick setup

1. Run the setup wizard: `hermes setup gateway` and choose **Sendblue**, or set variables in `~/.hermes/.env`:

   - `SENDBLUE_API_KEY_ID`
   - `SENDBLUE_API_SECRET_KEY`
   - `SENDBLUE_FROM_NUMBER` (e.g. `+15551234567`)
   - `SENDBLUE_WEBHOOK_PUBLIC_URL` (e.g. `https://abc123.ngrok-free.app` — **no trailing path**)

2. Start the gateway (or install the service): `hermes gateway`

3. In a **second** terminal, tunnel the webhook port (default 8646):

   ```bash
   ngrok http 8646
   ```

4. Copy the **HTTPS** forwarding URL into `SENDBLUE_WEBHOOK_PUBLIC_URL` and **restart the gateway** so Hermes re-registers the webhook. Free ngrok URLs change when the tunnel restarts — update the env var when that happens, or use a reserved ngrok domain.

## Security

- Use **HTTPS** for `SENDBLUE_WEBHOOK_PUBLIC_URL` (required).
- Set `SENDBLUE_WEBHOOK_SECRET` to match the secret Sendblue sends in the `sb-signing-secret` header. If unset, Hermes still accepts webhooks but logs a warning (verify signing in production).

## Allowlists and home channel

- `SENDBLUE_ALLOWED_USERS` — comma-separated E.164 numbers allowed to DM the bot (optional; otherwise use global gateway allow-all / pairing behavior).
- `SENDBLUE_GROUP_ALLOWED_USERS` — comma-separated Hermes chat IDs for groups: `sendblue:group:<uuid>` (optional).
- `SENDBLUE_HOME_CHANNEL` — default target for cron and notifications (E.164 or `sendblue:group:...`).

## Troubleshooting

- **No inbound messages:** Confirm ngrok is running, `SENDBLUE_WEBHOOK_PUBLIC_URL` matches the current HTTPS URL, and the gateway restarted after changing it.
- **Registration errors:** Check gateway logs; ensure API key headers are correct and the public URL is reachable from the internet.

See also: [Environment variables](/docs/reference/environment-variables) (search for `SENDBLUE_`).
