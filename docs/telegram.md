# Telegram bot setup

Residents can approve visitors from Telegram as well as the web app. The bot is optional:
with no token configured, everything else works and the bot endpoints answer 404.

## 1. Create the bot (owner, once, ~2 minutes)

1. In Telegram, open **@BotFather** → `/newbot` → pick a display name (e.g. "GateSense Demo")
   and a username ending in `bot` (e.g. `GateSenseDemoBot`).
2. BotFather replies with a **token** like `123456789:AA…`. Treat it like a password.
3. Put it in your local `.env` (never in git, never in a chat):

   ```
   TELEGRAM_BOT_TOKEN=123456789:AA...
   TELEGRAM_BOT_USERNAME=GateSenseDemoBot
   TELEGRAM_WEBHOOK_SECRET=<any long random string, e.g. from a password manager>
   ```

   For the deployed demo (Phase 8) the same three go into the hosting dashboard's secrets.

## 2. Point Telegram at the API (needs a public HTTPS URL)

Telegram can only call a public HTTPS address, so this step happens once the API is
deployed (Phase 8), or locally through a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`).
Register the webhook with your token and secret (run this on your own machine):

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<your-api-host>/api/v1/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET" \
  -d 'allowed_updates=["message","callback_query"]'
```

Telegram then sends `X-Telegram-Bot-Api-Secret-Token` with every call; the API rejects
calls without the right value (401).

## 3. How a resident links their account

1. In the app (or `/docs`): `POST /api/v1/telegram/link-code` as the resident.
2. Open the returned `link` (`https://t.me/<bot>?start=<code>`) on the phone and press
   **Start**. The bot replies "Linked to GateSense as …". The code works once, for 10 minutes.
3. From now on each visitor request for their flat arrives with **Approve / Deny** buttons.
   `DELETE /api/v1/telegram/link` unlinks.

## What the bot never does

It never asks for a password, never receives anything but `/start <code>` and button
presses, and only acts for residents of the visit's flat. Every message sent is logged in
the `notifications` table (one row per resident per request, so retries don't double-send).
