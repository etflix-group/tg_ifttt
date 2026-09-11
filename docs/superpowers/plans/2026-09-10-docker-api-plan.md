# Docker Service and API Implementation Plan

> **Goal:** Provide a durable single-user Docker service around the workflow engine, including authenticated workflow management, ordinary-account login APIs, manual execution, recovery, and webhook entry points.

## Constraints

- Keep the service single-user and self-hosted; bearer authentication is deployment-scoped.
- Reuse the existing canonical workflow model, SQLite repositories, encrypted account sessions, and `WorkflowEngine`.
- Never return sessions, API hashes, Bot Tokens, master keys, phone codes, or 2FA passwords.
- Every write validates the workflow before persistence and stores a content-addressed version.
- Docker must run without a reverse proxy, while documenting that public exposure still requires HTTPS and a strong admin token.
- Background execution must be restart-safe: queued/running/waiting runs are discovered from SQLite and resumed by the service.

## Task 1: Repository and dependency surface

- [x] Add FastAPI and Uvicorn runtime dependencies.
- [x] Add workflow/run listing methods and a durable service configuration object.
- [x] Add API tests with a temporary SQLite database and an injected fake adapter.

## Task 2: Authentication and application factory

- [x] Implement a constant-time bearer-token dependency for the single owner.
- [x] Require `TG_IFTTT_ADMIN_TOKEN` in public service mode; allow an explicit test token in the factory.
- [x] Build `create_app(database_path, adapter=None, admin_token=None)` without network side effects.
- [x] Expose `/api/health` without auth and protect all management/data endpoints.

## Task 3: Workflow, run, and webhook APIs

- [x] `GET/POST/PUT /api/workflows` loads, validates, stores, and exports canonical JSON.
- [x] `POST /api/workflows/{id}/run` creates and resumes a manual run.
- [x] `GET /api/runs` and `GET /api/runs/{id}` expose status, checkpoints, waiting conditions, and outputs without secrets.
- [x] `POST /api/webhooks/{workflow_id}` validates the route, starts a run with a bounded JSON payload, and returns the run ID.
- [x] Use typed HTTP errors for validation, missing resources, and engine failures.

## Task 4: Account and login APIs

- [x] `GET /api/accounts` returns masked account summaries.
- [x] Add QR begin/poll/refresh, phone begin, code submit, 2FA submit, and disconnect endpoints backed by `SessionManager`.
- [x] Keep login state in memory only; durable account session is written only after authorization succeeds.
- [x] Expose the Bot API adapter as a configured deployment capability without exposing its token.

## Task 5: Recovery worker and Docker packaging

- [x] Implement async recovery, minute-granularity cron scheduling, and polling-based Telegram event loops that resume work from SQLite.
- [x] Add a service entrypoint that initializes the database, creates the configured adapter, starts FastAPI, and shuts down cleanly.
- [x] Add Dockerfile, compose file, persistent data volume, healthcheck, and `.env.example`.
- [ ] Run a container build/smoke check when a Docker daemon is available.

  API tests, the full Python regression suite, Compose configuration validation, and the frontend production build pass locally; the Docker image build was not run because this machine's Docker daemon socket is unavailable.

## Acceptance criteria

- Unauthenticated health works; all other API routes reject missing/invalid bearer tokens.
- Invalid workflow graphs never reach storage.
- A manual run is persisted before execution and its status/output can be read after app recreation.
- Webhook payloads are bounded and become the run trigger payload.
- Login endpoints expose only non-secret state and encrypted account summaries.
- A restart recovery pass resumes queued/running/waiting runs without resetting checkpoints.
- Docker configuration persists SQLite data and does not require Cloudflare Worker state.
