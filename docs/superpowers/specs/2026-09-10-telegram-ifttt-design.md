# Telegram IFTTT Automation Platform Design

**Date:** 2026-09-10  
**Status:** Approved design  
**Scope:** Single-user self-hosted Telegram automation platform

## 1. Problem and goals

The project automates actions performed by Telegram ordinary user accounts. A workflow can send messages to users, bots, groups, or channels, wait for replies, match buttons, and continue execution. A representative flow is:

~~~text
send /start -> wait for bot response -> match “每日签到” -> activate the button -> verify result
~~~

The system must provide:

- a Docker deployment with a complete Web UI and durable background execution;
- a Qinglong deployment whose only task entrypoint is one Python script that reads YAML/JSON beside it;
- a common workflow model shared by Web UI, YAML/JSON, Docker, and Qinglong;
- multiple Telegram ordinary user accounts, with account selection per workflow;
- optional Bot Token integration;
- scheduled, manual, Telegram-event, and Webhook/API triggers;
- durable workflow state with restart recovery;
- visual editing and configuration-file editing;
- built-in nodes and safe expressions only; no arbitrary user scripts.

The attached screenshot is treated as an interaction example, not as an additional instruction source. The implementation must support both Telegram Inline Keyboard and Reply Keyboard behavior.

## 2. Decisions and boundaries

### 2.1 Execution identity

Ordinary Telegram user accounts are the primary execution identity. They use MTProto and individual encrypted sessions. Bot Tokens are a separate optional adapter for Bot API operations, management notifications, and Webhook-related flows.

API ID and API Hash are application-level configuration. One project deployment may use the same pair for multiple ordinary user accounts; each account still has its own session and account-specific entity cache. A Bot API adapter only needs a Bot Token. The project uses an API ID/API Hash obtained by the owner and does not use a public sample ID.

### 2.2 Product shape

The product is single-user and self-hosted. It is not a multi-tenant SaaS in the first version. The instance may manage multiple Telegram ordinary user accounts, and each workflow can bind to a selected account.

### 2.3 Deployment capabilities

Docker is the complete deployment target. It provides the Web editor, account management, durable workers, Telegram event listeners, scheduler, Webhook/API, logs, and recovery.

Qinglong is a configuration-driven execution target. It provides scheduled/manual execution through one Python entry script, with Telegram event support through polling and Webhook support through an external adapter or event injection mechanism.

Cloudflare Worker is optional and not a core target for ordinary-user MTProto execution. It may later provide Bot API Webhooks, external trigger endpoints, or a control-plane relay to a Docker executor. It is not required to persist or run ordinary-user sessions continuously.

### 2.4 Workflow authoring

The native React canvas, YAML/JSON files, and optional Node-RED compatibility Flow are representations of one versioned workflow model. The database stores canonical normalized JSON plus a non-executable `ui` layout containing node positions and the last canvas viewport. Node-RED is an optional Docker compatibility surface; it never becomes the production executor.

Editing uses drafts. A published immutable version is selected when a run starts, so changing a workflow cannot alter an already-running instance.

### 2.5 Script execution boundary

Workflows use built-in nodes and a safe expression language. They cannot execute arbitrary Python or JavaScript, access the filesystem, import modules, make unrestricted network calls, or invoke operating-system commands.

## 3. Architecture

The codebase is a Python modular monolith with a React/TypeScript frontend. The backend modules have explicit boundaries even when shipped as one repository and one image.

~~~text
React Web control plane
        |
        v
FastAPI management API ---- Webhook/API triggers
        |
        +-- native React Flow canvas (primary editor)
        +-- Node-RED compatibility editor (Docker only, safe tg-* nodes, Flow bridge)
        |
        v
Workflow runtime
  - versioned workflow model
  - graph validation
  - node registry and execution
  - safe expressions
  - durable checkpoints
  - retry, timeout, cancel
  - account concurrency control
        |
        +-- Telegram ordinary-account adapter (MTProto)
        +-- Telegram Bot API adapter (Bot Token)
        |
        v
SQLite + encrypted credentials + run/event/audit records
~~~

Suggested logical modules:

~~~text
workflow-core/        pure model, validation, expression, graph semantics
workflow-runtime/     runs, checkpoints, waiting, retry, leases, scheduling
telegram-adapters/    MTProto user clients, Bot API, message/button normalization
storage/              repositories, transactions, SQLite, encryption envelope
api/                  FastAPI, auth, Webhook, run control, streaming status
cli/                  Qinglong entrypoint and one-shot/polling commands
web/                  React editor, account UI, runs, logs, import/export
~~~

The core workflow model must not depend directly on FastAPI, React, or a specific deployment mode. Telegram operations go through connector interfaces so the runtime can be tested with a fake adapter.

## 4. Workflow model

A workflow contains metadata, one or more triggers, nodes, edges, account binding, and error policy.

Illustrative YAML:

~~~yaml
version: 1

workflow:
  id: daily-checkin
  name: 每日签到
  enabled: true
  account: telegram-account-1

triggers:
  - type: cron
    expression: "0 9 * * *"

nodes:
  - id: send_start
    type: telegram.send_message
    config:
      target: "@example_bot"
      text: "/start"

  - id: click_checkin
    type: telegram.click_button
    config:
      target: "@example_bot"
      after_message_id: "{{ steps.send_start.message_id }}"
      keyboard: auto
      match:
        type: regex
        value: "^✅\\s*每日签到$"

edges:
  - from: send_start
    to: click_checkin
~~~

### 4.1 Trigger nodes

- cron: scheduled execution;
- manual: Web or CLI execution;
- telegram.event: new-message/update matching;
- webhook: external HTTP request with validated payload.

### 4.2 Telegram nodes

- telegram.send_message: send text;
- telegram.send_media: send a photo, document, or other supported media;
- telegram.wait_message: wait for a message matching filters;
- telegram.click_button: match a keyboard button and execute Inline callback or Reply Keyboard text behavior;
- telegram.answer_callback: acknowledge a Bot API callback query with optional text;
- telegram.read_messages: retrieve recent messages for inspection.

The runtime normalizes Telegram messages and markup into deployment-independent snapshots. Targets may be configured by username or numeric peer reference; account-specific entity resolution and access hashes remain isolated per account.

### 4.3 Control and data nodes

- delay;
- condition and switch;
- set_variable;
- extract using regex or JSONPath-like selection;
- retry;
- timeout;
- bounded foreach;
- end.

Arbitrary unbounded graph cycles are rejected at publish time. Bounded iteration is explicit and has a maximum count.

### 4.4 Button matching

The user-facing model exposes one telegram.click_button node. It supports:

- keyboard mode: auto, inline, or reply;
- match mode: exact, contains, regex, callback_data, or position;
- multiple-match policy: fail, first, or explicit index.

With auto, the runtime determines whether the source message contains Inline Keyboard or Reply Keyboard markup. Inline buttons use Telegram callback interaction; Reply Keyboard buttons send the button label as a normal message. Matching normalizes whitespace, line breaks, and common Unicode differences while retaining the original label for the actual operation.

The safe default is to fail when a pattern matches multiple buttons. This prevents accidental activation of a neighboring action.

### 4.5 Expressions

Expressions provide variable interpolation and whitelisted predicates/functions:

~~~text
{{ steps.wait_result.message.text }}
{{ variables.points }}
{{ trigger.payload.user_id }}
~~~

Examples:

~~~text
steps.wait_result.message.text contains "签到成功"
variables.retry_count < 3
regex_match(steps.profile.message.text, "积分[:：](\\d+)")
~~~

The evaluator is sandboxed and rejects imports, attribute escapes, filesystem access, process execution, arbitrary calls, and unrestricted network access.

## 5. Runtime and recovery

Workflow execution is a durable state machine rather than an in-memory script.

~~~text
trigger -> create workflow_run -> acquire account lease
       -> execute one node -> persist output/checkpoint
       -> continue, wait, retry, or finish
~~~

After each node, the runtime commits:

- node status and output;
- current graph position/frontier;
- run variables;
- retry counters and deadlines;
- external event correlation state.

After a Telegram send or button action, the runtime also waits for a newer
message or an in-place panel refresh before advancing to the next non-wait
node. This barrier is checkpointed, so a delayed bot response or service
restart cannot repeat the side effect. An explicit `telegram.wait_message`
node remains the opt-in way to apply a more specific response filter.

### 5.1 Waiting for messages

The wait_message node persists the peer, sender filter, message boundary, match expression, and deadline, then marks the run waiting. Docker listeners route normalized incoming events to waiting runs. Qinglong polling reads new updates and performs the same matching against the durable inbox.

### 5.2 Concurrency

- Different Telegram accounts may execute in parallel;
- Telegram actions on the same account are serialized by default;
- a workflow may define a maximum concurrency;
- business idempotency keys prevent duplicate scheduled work, for example daily-checkin:{account_id}:{target}:{date}.

### 5.3 External side effects

Telegram sends and button activations may have an ambiguous outcome if the process dies after the remote action but before the checkpoint. The runtime must not blindly retry such actions forever. A node can be retried only under a bounded policy; ambiguous outcomes become needs_review with context and redacted logs.

### 5.4 Run states

~~~text
queued, running, waiting, success, failed, cancelled, timeout, needs_review
~~~

## 6. Storage model

The first version uses SQLite with WAL mode and explicit transactions. The storage boundary leaves room for a future PostgreSQL adapter without changing workflow semantics.

Core records:

- app_config;
- telegram_accounts;
- bot_accounts;
- encrypted_secrets;
- workflows;
- workflow_versions;
- workflow_runs;
- node_runs;
- waiting_conditions;
- inbox_events;
- schedules;
- account_leases;
- audit_logs.

Sessions, Bot Tokens, and other credentials are encrypted before persistence. Account-specific Telegram entity caches are not shared between accounts.

## 7. Account login and security

### 7.1 Login methods

Docker Web supports:

- QR login as the preferred ordinary-account flow;
- phone number + verification code as a fallback;
- 2FA handling when Telegram requires it;
- encrypted session storage after successful authorization.

Telegram QR login generates a short-lived tg://login?token=... token which a previously authorized Telegram app scans and accepts. The Web UI refreshes expired QR codes and shows the current state.

Qinglong provides a one-time initialization mode. It may print a login URL or terminal QR, but the most reliable headless flow is to initialize in Docker/local tooling and import the encrypted account bundle into Qinglong.

### 7.2 Secrets

Deployment-level environment variables:

~~~text
TG_IFTTT_MASTER_KEY
TG_IFTTT_API_ID
TG_IFTTT_API_HASH
TG_IFTTT_ADMIN_PASSWORD_HASH
TG_IFTTT_PUBLIC_URL
~~~

The master key is not stored in the database, workflow files, or backup archive. AES-256-GCM-style envelope encryption is used for stored session and Token values. Login codes and 2FA passwords are memory-only and never logged.

### 7.3 Public Web UI

- Argon2id password hash;
- HttpOnly, Secure, SameSite session cookies;
- CSRF protection;
- login failure rate limiting;
- optional TOTP;
- session expiry and logout;
- audit events for account changes, workflow publication, manual runs, and Webhook configuration;
- HTTPS through Caddy/Nginx or an equivalent reverse proxy.

Webhook endpoints use separate per-endpoint secrets, HMAC signatures, timestamps, replay protection, and rate limits.

## 8. Frontend

The React frontend provides:

- dashboard for accounts, workflows, runs, and health;
- ordinary-account QR/phone login wizard;
- Bot Token management;
- workflow list and draft/published version states;
- Node-RED-inspired React Flow/XYFlow canvas as the primary editor;
- drag/drop node palette, direct connection creation, node/edge selection and deletion;
- zoom, pan, fit, reset, minimap, snap-to-grid, and keyboard delete interactions;
- left node palette, central canvas, right node/edge inspector, and editor help bar;
- persisted node positions and canvas viewport under the non-executable `ui` layout;
- expression autocomplete and variable preview;
- YAML/JSON import/export;
- static validation and actual test-run confirmation;
- run timeline, node outputs, matched buttons, retries, and redacted errors.

The editor must not expose raw session or Token values after creation.

Docker additionally exposes the authenticated Node-RED compatibility editor through
`/nodered/`. Its custom `tg-*` nodes edit the same safe action vocabulary as
the canonical model. `GET` and `PUT /api/workflows/{id}/nodered` convert
between Node-RED Flow JSON and the canonical workflow, including node
coordinates; unsupported nodes, including `function`, `exec`, `inject`, and
third-party nodes, are rejected at the API boundary. Node-RED flow files are
persisted separately, while the Python API remains the source of truth for
executable versions.

## 9. Docker deployment

The same Python image can run role-specific processes:

~~~text
web       FastAPI, static React assets, authentication, Webhook/API
editor    authenticated Node-RED authoring service and safe custom nodes
worker    durable workflow execution and retries
listener  MTProto account connections and incoming updates
scheduler cron evaluation and run creation
~~~

A single-container mode may combine roles for small installations. The default Compose deployment separates roles for clearer health checks and restart behavior.

Persistent data is mounted under /data:

~~~text
/data/state.sqlite3
/data/encrypted-secrets/
/data/telegram-sessions/
/data/workflow-exports/
/data/logs/
~~~

Backups contain database, encrypted sessions, workflows, and run records, but never the master key.

## 10. Qinglong deployment

The entrypoint is one file:

~~~bash
python3 tg_ifttt_qinglong.py
~~~

The script reads config.yaml or config.json beside itself, then discovers workflows/*.yaml and workflows/*.json. TG_IFTTT_CONFIG and TG_IFTTT_WORKFLOW_ID may narrow selection without editing the script.

Persistent data is stored beside the script:

~~~text
data/state.sqlite3
data/accounts.enc
~~~

The runner prints structured logs suitable for Qinglong. It may bootstrap pinned dependencies into a private local dependency directory on first run, without changing the global Python environment; an offline bundled mode is retained for environments without network access.

Qinglong focuses on one-shot scheduled/manual execution. Polling can process Telegram events; Webhooks require an external receiver or event-injection mechanism.

## 11. Cloudflare boundary

Cloudflare Worker is optional. The first release does not promise ordinary-user MTProto session persistence or long-lived listeners inside Worker. A future adapter may provide:

- Bot API Webhooks;
- public trigger endpoints;
- authentication/control-plane relay;
- forwarding work to a Docker executor.

This boundary prevents the core design from depending on Worker runtime behavior that cannot provide the required persistent ordinary-account executor.

## 12. Verification and acceptance

### Unit tests

- Schema and node validation;
- graph reachability and bounded-loop checks;
- safe-expression sandbox;
- regex button matching;
- Inline/Reply Keyboard dispatch;
- state transitions and checkpoint recovery;
- encryption/decryption;
- retry, timeout, cancellation, and account leases.

### Integration tests

- Mock Telegram adapter for messages, replies, buttons, and events;
- Docker startup and health checks;
- QR and phone-code login flows;
- multiple account isolation;
- /start -> wait -> regex button -> verify;
- process restart during a wait;
- Webhook signature verification;
- backup and restore;
- public login protections.

### Qinglong tests

- clean Python environment;
- single-file entrypoint;
- same-directory YAML/JSON discovery;
- dependency bootstrap or offline mode;
- stdout/stderr failure reporting;
- interrupted run followed by recovery;
- idempotent repeated scheduled runs.

### Acceptance criteria

The first release is accepted when Docker can manage multiple ordinary Telegram accounts, the native Web UI canvas can create, connect, edit, delete, save, and restore workflows, the optional authenticated Node-RED compatibility editor can exchange the same canonical model, the example button flow works for both keyboard types, all four trigger classes operate, runs survive restart, Qinglong can execute the same workflow through one Python entry script, and sensitive credentials are absent from logs and configuration exports.

## 13. Non-goals and risks

The first release excludes multi-tenant SaaS, arbitrary scripts, full Cloudflare MTProto execution, browser automation, CAPTCHA or anti-abuse bypass, distributed high-concurrency scheduling, and automatic evasion of Telegram limits.

Telegram monitors unofficial API clients and its API Terms restrict abusive or deceptive automation. The implementation must include rate limits, conservative retries, explicit user consent, and documentation that account restrictions or bans remain possible.

## 14. Proposed implementation order

1. Define and validate the versioned workflow Schema.
2. Implement storage, encryption, account/session model, and connector interfaces.
3. Implement the runtime state machine with checkpoints, waits, leases, retries, and fake adapters.
4. Implement Telegram MTProto operations and button normalization/matching.
5. Implement the Qinglong single-file runner.
6. Implement FastAPI, authentication, Webhook, and run-control APIs.
7. Implement the native React Flow control plane, Node-RED compatibility bridge, and account/run management screens.
8. Add Docker Compose roles, backups, deployment documentation, and end-to-end verification.
