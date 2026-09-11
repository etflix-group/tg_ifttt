"""FastAPI application for a single-user Docker deployment."""

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request, status

from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.domain.nodered import NodeRedFlowError, compile_node_red_flow, export_node_red_flow
from tg_ifttt.domain.validation import validate_workflow
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.runtime.triggers import EventListenerWorker, SchedulerWorker
from tg_ifttt.storage.account_repository import AccountRepository
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.factory import AdapterFactory, AdapterFactoryError

from .recovery import RecoveryWorker


def _version_id(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _run_json(run: Any) -> Dict[str, Any]:
    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "version_id": run.version_id,
        "account_id": run.account_id,
        "status": run.status,
        "current_node_id": run.current_node_id,
        "variables": run.variables,
        "trigger_payload": run.trigger_payload,
        "node_outputs": run.node_outputs,
        "retry_counts": run.retry_counts,
        "waiting": run.waiting,
        "checkpoint_seq": run.checkpoint_seq,
        "error": run.error,
    }


def _require_mapping(payload: Any, name: str = "payload") -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise HTTPException(status_code=422, detail="%s must be a JSON object" % name)
    return dict(payload)


def _resolve_execution_account(adapter: Any, requested: Any, workflow_account: Optional[str]) -> str:
    if requested is not None and str(requested).strip():
        return str(requested)
    if workflow_account is not None and workflow_account.strip():
        return workflow_account

    manager = getattr(adapter, "session_manager", None)
    repository = getattr(manager, "account_repository", None)
    if repository is None:
        return "default"
    accounts = repository.list_accounts()
    if len(accounts) == 1:
        return accounts[0].account_id
    if not accounts:
        raise HTTPException(
            status_code=409,
            detail="no ordinary Telegram account is connected; add an account or select an execution account",
        )
    raise HTTPException(
        status_code=422,
        detail="workflow must select an execution account because multiple Telegram accounts are connected",
    )


def create_app(
    database_path: Optional[Path] = None,
    adapter: Any = None,
    admin_token: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    adapter_config: Optional[Mapping[str, Any]] = None,
    recovery_interval: float = 15.0,
    scheduler_interval: float = 20.0,
    event_poll_interval: float = 5.0,
) -> FastAPI:
    """Create an isolated app instance; no Telegram network call occurs here."""

    token = admin_token or os.environ.get("TG_IFTTT_ADMIN_TOKEN")
    if not isinstance(token, str) or not token:
        raise ValueError("TG_IFTTT_ADMIN_TOKEN is required for the public web service")
    if database_path is None:
        data_dir = Path(os.environ.get("TG_IFTTT_DATA_DIR", "./data"))
        database_path = data_dir / "state.sqlite3"
    database = Database.connect(Path(database_path), check_same_thread=False)
    database.initialize()

    if adapter is None:
        selected = dict(adapter_config or {})
        selected.setdefault("adapter", os.environ.get("TG_IFTTT_ADAPTER", "fake"))
        try:
            adapter = AdapterFactory.from_config(selected, database=database)
        except AdapterFactoryError as exc:
            database.close()
            raise ValueError(str(exc)) from exc

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app.state.recovery_task = asyncio.create_task(app.state.recovery.run())
        app.state.scheduler_task = asyncio.create_task(app.state.scheduler.run())
        app.state.event_listener_task = asyncio.create_task(app.state.event_listener.run())
        try:
            yield
        finally:
            app.state.recovery.stop()
            app.state.scheduler.stop()
            app.state.event_listener.stop()
            for task in (
                app.state.recovery_task,
                app.state.scheduler_task,
                app.state.event_listener_task,
            ):
                if task is None:
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            app.state.database.close()

    app = FastAPI(title="Telegram IFTTT", version="0.1.0", lifespan=lifespan)
    app.state.database = database
    app.state.adapter = adapter
    app.state.admin_token = token
    app.state.webhook_secret = webhook_secret or os.environ.get("TG_IFTTT_WEBHOOK_SECRET")
    app.state.recovery = RecoveryWorker(database, adapter, recovery_interval)
    default_account = (adapter_config or {}).get("default_account")
    app.state.scheduler = SchedulerWorker(database, adapter, scheduler_interval, default_account)
    app.state.event_listener = EventListenerWorker(database, adapter, event_poll_interval, default_account)
    app.state.recovery_task = None
    app.state.scheduler_task = None
    app.state.event_listener_task = None

    async def require_auth(request: Request) -> None:
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(
            supplied, app.state.admin_token
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")

    async def require_webhook(request: Request) -> None:
        configured = app.state.webhook_secret
        if configured:
            supplied = request.headers.get("x-tg-ifttt-webhook", "")
            if not supplied or not hmac.compare_digest(supplied, configured):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret")
            return
        await require_auth(request)

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "service": "tg-ifttt"}

    @app.get("/api/capabilities", dependencies=[Depends(require_auth)])
    async def capabilities() -> Dict[str, Any]:
        manager = getattr(app.state.adapter, "session_manager", None)
        repository = getattr(manager, "account_repository", None)
        return {
            "adapter": type(app.state.adapter).__name__,
            "ordinary_account_login": manager is not None,
            "session_storage": getattr(repository, "session_storage", None),
            "bot_api": type(app.state.adapter).__name__ == "BotApiAdapter",
            "scheduler": True,
            "event_polling": hasattr(app.state.adapter, "fetch_updates")
            or hasattr(app.state.adapter, "get_updates"),
            "webhook": True,
            "cloudflare_worker": False,
        }

    @app.get("/api/workflows", dependencies=[Depends(require_auth)])
    async def list_workflows() -> Any:
        return app.state.database.workflows.list_workflows()

    def save_workflow_document(payload: Any, expected_id: Optional[str] = None) -> Dict[str, Any]:
        document = payload.get("document", payload) if isinstance(payload, Mapping) else payload
        document = _require_mapping(document, "workflow document")
        try:
            workflow = parse_workflow(document)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if expected_id is not None and workflow.workflow_id != expected_id:
            raise HTTPException(status_code=409, detail="workflow id does not match URL")
        errors = validate_workflow(workflow)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        version_id = _version_id(workflow.to_dict())
        app.state.database.workflows.save_version(workflow, version_id)
        return {
            "workflow_id": workflow.workflow_id,
            "version_id": version_id,
            "document": workflow.to_dict(),
        }

    @app.post("/api/workflows", dependencies=[Depends(require_auth)])
    async def create_workflow(payload: Any = Body(...)) -> Dict[str, Any]:
        return save_workflow_document(payload)

    @app.put("/api/workflows/{workflow_id}", dependencies=[Depends(require_auth)])
    async def update_workflow(workflow_id: str, payload: Any = Body(...)) -> Dict[str, Any]:
        return save_workflow_document(payload, expected_id=workflow_id)

    @app.delete("/api/workflows/{workflow_id}", dependencies=[Depends(require_auth)])
    async def delete_workflow(workflow_id: str) -> Dict[str, Any]:
        if not app.state.database.workflows.delete_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="unknown workflow: %s" % workflow_id)
        return {"workflow_id": workflow_id, "deleted": True}

    @app.get("/api/workflows/{workflow_id}/nodered", dependencies=[Depends(require_auth)])
    async def export_nodered_workflow(workflow_id: str) -> Dict[str, Any]:
        try:
            workflow = app.state.database.workflows.load_current(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"workflow_id": workflow_id, "flow": export_node_red_flow(workflow.to_dict())}

    @app.put("/api/workflows/{workflow_id}/nodered", dependencies=[Depends(require_auth)])
    async def import_nodered_workflow(workflow_id: str, payload: Any = Body(...)) -> Dict[str, Any]:
        try:
            document = compile_node_red_flow(payload, expected_workflow_id=workflow_id)
        except NodeRedFlowError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        saved = save_workflow_document(document, expected_id=workflow_id)
        saved["flow"] = export_node_red_flow(saved["document"])
        return saved

    @app.get("/api/workflows/{workflow_id}", dependencies=[Depends(require_auth)])
    async def get_workflow(workflow_id: str) -> Dict[str, Any]:
        try:
            workflow = app.state.database.workflows.load_current(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return workflow.to_dict()

    @app.get("/api/workflows/{workflow_id}/versions", dependencies=[Depends(require_auth)])
    async def list_workflow_versions(workflow_id: str) -> Any:
        try:
            return app.state.database.workflows.list_versions(workflow_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def execute_workflow(workflow_id: str, body: Any) -> Dict[str, Any]:
        try:
            workflow = app.state.database.workflows.load_current(workflow_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = _require_mapping(body) if body is not None else {}
        account_id = _resolve_execution_account(
            app.state.adapter,
            payload.pop("account_id", None),
            workflow.account,
        )
        trigger_payload = payload.pop("trigger_payload", payload)
        if not isinstance(trigger_payload, Mapping):
            trigger_payload = {"payload": trigger_payload}
        engine = WorkflowEngine(app.state.database, app.state.adapter)
        run_id = engine.start(workflow, str(account_id), dict(trigger_payload))
        result = await engine.resume(run_id)
        return {"run": _run_json(app.state.database.runs.load_run(run_id)), "result": result.status}

    @app.post("/api/workflows/{workflow_id}/run", dependencies=[Depends(require_auth)])
    async def run_workflow(workflow_id: str, payload: Any = Body(default=None)) -> Dict[str, Any]:
        return await execute_workflow(workflow_id, payload)

    @app.get("/api/runs", dependencies=[Depends(require_auth)])
    async def list_runs(limit: int = 100) -> Any:
        try:
            return [_run_json(run) for run in app.state.database.runs.list_runs(limit)]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}", dependencies=[Depends(require_auth)])
    async def get_run(run_id: str) -> Dict[str, Any]:
        try:
            return _run_json(app.state.database.runs.load_run(run_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/webhooks/{workflow_id}")
    async def webhook(
        workflow_id: str,
        request: Request,
        payload: Any = Body(default=None),
    ) -> Dict[str, Any]:
        await require_webhook(request)
        raw = payload if payload is not None else {}
        encoded = json.dumps(raw, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise HTTPException(status_code=413, detail="webhook payload is too large")
        return await execute_workflow(workflow_id, {"trigger_payload": raw})

    def session_manager() -> Any:
        manager = getattr(app.state.adapter, "session_manager", None)
        if manager is None:
            raise HTTPException(status_code=409, detail="ordinary-account login is not configured")
        return manager

    @app.get("/api/accounts", dependencies=[Depends(require_auth)])
    async def list_accounts() -> Any:
        manager = session_manager()
        return [account.__dict__ for account in manager.account_repository.list_accounts()]

    @app.post("/api/accounts/login/qr", dependencies=[Depends(require_auth)])
    async def begin_qr(payload: Any = Body(...)) -> Dict[str, Any]:
        body = _require_mapping(payload)
        manager = session_manager()
        state = await manager.begin_qr_login(str(body.get("account_id", "")), str(body.get("display_name", "")))
        return state.to_dict()

    @app.get("/api/accounts/login/qr/{login_id}", dependencies=[Depends(require_auth)])
    async def poll_qr(login_id: str) -> Dict[str, Any]:
        try:
            return (await session_manager().poll_qr_login(login_id)).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/accounts/login/qr/{login_id}/refresh", dependencies=[Depends(require_auth)])
    async def refresh_qr(login_id: str) -> Dict[str, Any]:
        try:
            return (await session_manager().refresh_qr_login(login_id)).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/accounts/login/phone", dependencies=[Depends(require_auth)])
    async def begin_phone(payload: Any = Body(...)) -> Dict[str, Any]:
        body = _require_mapping(payload)
        try:
            state = await session_manager().begin_phone_login(str(body.get("account_id", "")), str(body.get("phone", "")))
            return state.to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/accounts/login/{login_id}/code", dependencies=[Depends(require_auth)])
    async def submit_code(login_id: str, payload: Any = Body(...)) -> Dict[str, Any]:
        body = _require_mapping(payload)
        try:
            return (await session_manager().submit_phone_code(login_id, str(body.get("code", "")))).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/accounts/login/{login_id}/2fa", dependencies=[Depends(require_auth)])
    async def submit_two_factor(login_id: str, payload: Any = Body(...)) -> Dict[str, Any]:
        body = _require_mapping(payload)
        try:
            return (await session_manager().submit_two_factor(login_id, str(body.get("password", "")))).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/accounts/login/{login_id}", dependencies=[Depends(require_auth)])
    async def disconnect_login(login_id: str) -> Dict[str, Any]:
        await session_manager().disconnect_login(login_id)
        return {"status": "disconnected"}

    @app.post("/api/accounts/{account_id}/disconnect", dependencies=[Depends(require_auth)])
    async def disconnect_account(account_id: str) -> Dict[str, Any]:
        await session_manager().disconnect_account(account_id)
        return {"status": "disconnected"}

    @app.delete("/api/accounts/{account_id}", dependencies=[Depends(require_auth)])
    async def revoke_account(account_id: str) -> Dict[str, Any]:
        await session_manager().revoke_account(account_id)
        return {"status": "revoked"}

    return app
