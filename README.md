# Telegram IFTTT

Self-hosted Telegram workflow automation for ordinary user accounts and Bot API integrations.

The approved architecture is documented in [the design specification](docs/superpowers/specs/2026-09-10-telegram-ifttt-design.md). The implementation is split into a Python runtime, account-scoped Telegram adapters, and deployment shells. Ordinary accounts use Telethon MTProto and support encrypted QR/phone-code/2FA login sessions; Bot Tokens use the Bot API for sending, update polling, and callback answers.

## Docker deployment

```bash
cp .env.example .env
# replace TG_IFTTT_ADMIN_TOKEN with a long random value, then edit the selected Telegram adapter settings
# Prefer `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`; if a value contains $, wrap the whole value in single quotes in .env.
docker compose up -d --build
```

The React console is exposed on `http://localhost:8080` by default; the API is on `http://localhost:8000`. SQLite, account sessions, workflow versions, and checkpoints are stored in the `tg_ifttt_data` volume. Put the public ports behind HTTPS when exposing them to the internet. After changing `.env`, use `docker compose up -d --build --force-recreate` so the new environment reaches the API container.

### Visual workflow editor

The React console is the primary workflow editor. It follows the Node-RED interaction model without leaving the application:

- drag a built-in node from the left palette onto the canvas, or click it to add one at the center;
- drag a node by its body to reposition it, then drag its right handle to another node to create a connection;
- click a node to edit its action, or click a connection to edit its branch condition;
- press `Delete` / `Backspace` to remove the selected node or connection; removing a node also removes its attached connections;
- use the mouse wheel or the `-` / `+` controls to zoom, drag the empty canvas to pan, and use fit/reset/minimap controls for navigation.

Node positions and the last canvas viewport are stored in the workflow's `ui` layout and survive API saves, reloads, and version restoration. The editor only exposes the project's built-in Telegram actions and safe expressions.

Docker also starts an optional password-protected Node-RED compatibility editor at `http://localhost:8080/nodered/` (direct port `1880` by default). The default Node-RED username is `admin`; its password falls back to `TG_IFTTT_ADMIN_TOKEN`. Set `TG_IFTTT_NODERED_PASSWORD` in `.env` if a separate password is preferred. Its flow file is persisted in the `tg_ifttt_nodered_data` volume.

Node-RED remains an authoring/compatibility surface only. The Python engine remains the only executor, so the supplied `tg-*` nodes report an editor-only error if deployed inside Node-RED. The API compiler accepts only the supplied safe node types and rejects arbitrary nodes such as `function`, `exec`, `inject`, or third-party nodes. This keeps ordinary-account sessions, Bot Tokens, SQLite checkpoints, and Qinglong behavior in one runtime.

To edit a workflow in the compatibility editor, open “配置文件” in the React console and choose “Node-RED 兼容”, or export a Flow from the authenticated API, import the returned `flow` array in Node-RED, then export the edited Flow and send it back through the API:

```bash
curl -s -H "Authorization: Bearer $TG_IFTTT_ADMIN_TOKEN" \
  http://localhost:8000/api/workflows/daily/nodered | jq '.flow' > daily.flow.json

# Import daily.flow.json in Node-RED, edit and export it again, then:
curl -s -X PUT -H "Authorization: Bearer $TG_IFTTT_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @daily.flow.json \
  http://localhost:8000/api/workflows/daily/nodered
```

The native React canvas remains the source of truth for normal editing. Node-RED Flow JSON is only a portable compatibility format; the Python API remains the source of truth for executable workflow versions.

The API service can also run alone:

```bash
docker build -t tg-ifttt-api .
docker run --rm -p 8000:8000 --env-file .env -v tg_ifttt_data:/data tg-ifttt-api
```

## Development

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

The offline example demonstrates the core flow without connecting to Telegram:

```bash
python3 -m tg_ifttt.cli.qinglong --config examples/config.yaml
```

The Qinglong entrypoint is a single generated Python file. It reads config.yaml or config.json beside itself and can discover workflow files under a sibling workflows directory:

```bash
python3 scripts/build_qinglong_runner.py --output tg_ifttt_qinglong.py
python3 tg_ifttt_qinglong.py --config examples/config.yaml
# For a Qinglong polling task, poll telegram.event workflows once and exit.
python3 tg_ifttt_qinglong.py --config config.yaml --poll-events
```

Offline mode is explicit with `adapter: fake`. For an ordinary-account Qinglong run, use `adapter: mtproto` and configure `api_id`/`api_hash` (or `TG_IFTTT_API_ID`/`TG_IFTTT_API_HASH`). `TG_IFTTT_MASTER_KEY` is optional: when it is unset, account sessions are stored as plaintext StringSessions; when it is set to a valid 32-byte key, sessions are encrypted at rest. For Bot API, use `adapter: bot_api` and `TG_IFTTT_BOT_TOKEN`. Workflow files only select the account ID. Plaintext sessions are sensitive credentials: protect the SQLite volume and do not expose it to other users.

To disable encryption in an existing Docker deployment, remove or comment out `TG_IFTTT_MASTER_KEY` in `.env`, then run `docker compose up -d --build --force-recreate`. Existing encrypted sessions still require their original key; if no account has been logged in successfully yet, there is nothing to migrate.

Bot Tokens cannot impersonate an ordinary user to click a keyboard. Workflows that need `/start` followed by a button click must select a logged-in ordinary MTProto account; Bot API workflows can send messages, receive updates, and answer callback queries addressed to the bot.

The Docker service includes authenticated workflow management, startup recovery, minute-granularity cron scheduling, fixed-time calendar schedules, event-driven `telegram.event` triggers (continuous MTProto listeners and Bot API long polling), Webhook/API entry points, and the React visual editor. In the editor, a schedule runs every N calendar days at a fixed hour/minute/second; optional random seconds are stable per workflow date and never move the second past 59. Fixed-time schedules use `Asia/Shanghai` by default; set `TG_IFTTT_TIMEZONE` to override it. Tune the background loops with `TG_IFTTT_RECOVERY_INTERVAL`, `TG_IFTTT_SCHEDULER_INTERVAL`, and `TG_IFTTT_EVENT_POLL_INTERVAL`. Never put Telegram sessions, Bot Tokens, or API secrets in workflow files or the repository.

For Telegram send and button nodes, the runtime automatically waits for a newer message or an in-place panel refresh before advancing to the next non-wait node. This wait is persisted as a checkpoint, so delayed bot replies and service restarts do not repeat the preceding action. Use `telegram.wait_message` when a workflow needs an explicit sender or content filter. For button nodes that search automatically, `after_message_id: "{{ steps.send_start.message_id }}"` can be added as an extra message boundary; do not use the sent `/start` message as the button source with the `message` field.
