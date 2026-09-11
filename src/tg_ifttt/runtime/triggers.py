"""Durable cron scheduling and event-driven Telegram triggers."""

import hashlib
import inspect
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tg_ifttt.cron import CronSchedule, FixedTimeSchedule, scheduled_slot
from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.domain.models import TriggerSpec, WorkflowSpec
from tg_ifttt.runtime.adapters import normalize_button_label
from tg_ifttt.runtime.engine import RunResult, WorkflowEngine
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.models import UpdateBatch


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _workflow_account(workflow: WorkflowSpec, default_account: Optional[str]) -> str:
    return workflow.account or default_account or "default"


class SchedulerWorker:
    """Run cron workflows at minute granularity with SQLite idempotency."""

    def __init__(
        self,
        database: Database,
        adapter: Any,
        interval_seconds: float = 20.0,
        default_account: Optional[str] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("scheduler interval must be positive")
        self.database = database
        self.engine = WorkflowEngine(database, adapter)
        self.interval_seconds = interval_seconds
        self.default_account = default_account
        self._stopped = False

    async def tick(self, now: Optional[datetime] = None) -> List[RunResult]:
        current = now or datetime.now().astimezone()
        results: List[RunResult] = []
        for stored in self.database.workflows.list_workflows():
            workflow = parse_workflow(stored["document"])
            if not workflow.enabled:
                continue
            account_id = _workflow_account(workflow, self.default_account)
            for index, trigger in enumerate(workflow.triggers):
                if trigger.trigger_type == "cron":
                    expression = trigger.config.get("expression", trigger.config.get("cron"))
                    schedule = CronSchedule.parse(expression)
                    if not schedule.matches(current):
                        continue
                    key = "cron:%s:%d:%s:%s" % (
                        workflow.workflow_id,
                        index,
                        account_id,
                        scheduled_slot(expression, current),
                    )
                    trigger_payload = {
                        "type": "cron",
                        "expression": expression,
                        "scheduled_at": current.isoformat(),
                    }
                elif trigger.trigger_type == "schedule":
                    schedule = FixedTimeSchedule.from_config(trigger.config)
                    grace_seconds = max(60.0, self.interval_seconds + 1.0)
                    occurrence = schedule.occurrence_at(workflow.workflow_id, index, current)
                    if occurrence is None or not schedule.is_due(
                        workflow.workflow_id,
                        index,
                        current,
                        grace_seconds,
                    ):
                        continue
                    key = "schedule:%s:%d:%s:%s" % (
                        workflow.workflow_id,
                        index,
                        account_id,
                        occurrence.scheduled_at.isoformat(),
                    )
                    trigger_payload = {
                        "type": "schedule",
                        "interval_days": schedule.interval_days,
                        "hour": schedule.hour,
                        "minute": schedule.minute,
                        "second": schedule.second,
                        "random_seconds": occurrence.random_seconds,
                        "scheduled_at": occurrence.scheduled_at.isoformat(),
                    }
                else:
                    continue
                run_id = self.engine.start(
                    workflow,
                    account_id,
                    trigger_payload,
                    idempotency_key=key,
                )
                results.append(await self.engine.resume(run_id))
        return results

    async def run(self) -> None:
        import asyncio

        await self.tick()
        while not self._stopped:
            await asyncio.sleep(self.interval_seconds)
            if not self._stopped:
                await self.tick()

    def stop(self) -> None:
        self._stopped = True


def _event_message(update: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    message = update.get("message")
    if isinstance(message, Mapping):
        return message
    return None


def _match_event(update: Mapping[str, Any], trigger: TriggerSpec) -> bool:
    config = trigger.config
    configured_type = config.get("event_type", config.get("update_type"))
    if configured_type is not None and update.get("normalized_type") != configured_type:
        return False
    message = _event_message(update)
    if message is None:
        return False
    for key in ("target", "peer_id", "chat_id"):
        expected = config.get(key)
        if expected is not None and str(expected) != str(message.get("peer_id")):
            return False
    sender = config.get("sender", config.get("sender_id"))
    if sender is not None and str(sender) != str(message.get("sender_id")):
        return False

    matcher = config.get("match", config.get("text_match"))
    if matcher is None:
        return True
    if isinstance(matcher, str):
        matcher = {"type": "exact", "value": matcher}
    if not isinstance(matcher, Mapping):
        return False
    value = matcher.get("value", "")
    if not isinstance(value, str):
        return False
    text = str(message.get("text", ""))
    match_type = matcher.get("type", "exact")
    if match_type == "exact":
        return normalize_button_label(text) == normalize_button_label(value)
    if match_type == "contains":
        return normalize_button_label(value) in normalize_button_label(text)
    if match_type == "regex":
        try:
            return re.search(value, text) is not None
        except re.error:
            return False
    return False


def _event_identity(update: Mapping[str, Any]) -> str:
    update_id = update.get("update_id")
    if update_id is not None:
        return str(update_id)
    encoded = json.dumps(update, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


class EventListenerWorker:
    """Dispatch Telegram updates and wake runs waiting for message progress."""

    def __init__(
        self,
        database: Database,
        adapter: Any,
        interval_seconds: float = 5.0,
        default_account: Optional[str] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("event poll interval must be positive")
        self.database = database
        self.adapter = adapter
        self.engine = WorkflowEngine(database, adapter)
        self.interval_seconds = interval_seconds
        self.default_account = default_account
        self._stopped = False
        self._listener_stop = None

    def _subscriptions(self) -> List[Tuple[WorkflowSpec, TriggerSpec, str, int]]:
        subscriptions: List[Tuple[WorkflowSpec, TriggerSpec, str, int]] = []
        for stored in self.database.workflows.list_workflows():
            workflow = parse_workflow(stored["document"])
            if not workflow.enabled:
                continue
            account_id = _workflow_account(workflow, self.default_account)
            for index, trigger in enumerate(workflow.triggers):
                if trigger.trigger_type == "telegram.event":
                    subscriptions.append((workflow, trigger, account_id, index))
        return subscriptions

    def _account_ids(self) -> List[str]:
        account_ids = set()
        for stored in self.database.workflows.list_workflows():
            workflow = parse_workflow(stored["document"])
            if workflow.enabled:
                account_ids.add(_workflow_account(workflow, self.default_account))
        account_ids.update(run.account_id for run in self.database.runs.list_recoverable_runs())
        return sorted(account_ids)

    async def _fetch(self, account_id: str, cursor: Optional[str]) -> Optional[UpdateBatch]:
        fetcher = getattr(self.adapter, "fetch_updates", None)
        if fetcher is not None:
            return await _maybe_await(fetcher(account_id, cursor))
        getter = getattr(self.adapter, "get_updates", None)
        if getter is None:
            return None
        offset = None if cursor is None else int(cursor)
        return await _maybe_await(getter(offset=offset, timeout=0))

    async def _resume_waiting(self, account_id: str) -> List[RunResult]:
        results: List[RunResult] = []
        for run in self.database.runs.list_recoverable_runs():
            if run.status != "waiting" or run.account_id != account_id or not run.waiting:
                continue
            results.append(await self.engine.resume(run.run_id))
        return results

    async def _on_update(
        self,
        account_id: str,
        update: Mapping[str, Any],
        subscriptions: Optional[Sequence[Tuple[WorkflowSpec, TriggerSpec, str, int]]] = None,
    ) -> List[RunResult]:
        results = await self._resume_waiting(account_id)
        active_subscriptions = subscriptions if subscriptions is not None else self._subscriptions()
        for workflow, trigger, workflow_account, trigger_index in active_subscriptions:
            if workflow_account != account_id or not _match_event(update, trigger):
                continue
            key = "event:%s:%s:%d:%s" % (
                account_id,
                _event_identity(update),
                trigger_index,
                workflow.workflow_id,
            )
            run_id = self.engine.start(
                workflow,
                account_id,
                {"type": "telegram.event", "event": dict(update)},
                idempotency_key=key,
            )
            results.append(await self.engine.resume(run_id))
        return results

    async def poll_once(self) -> List[RunResult]:
        subscriptions = self._subscriptions()
        account_ids = self._account_ids()
        if not account_ids:
            return []
        results: List[RunResult] = []
        for account_id in account_ids:
            cursor_key = "%s:%s" % (type(self.adapter).__name__, account_id)
            cursor = self.database.triggers.get_cursor(cursor_key)
            batch = await self._fetch(account_id, cursor)
            if batch is None:
                continue
            for update in batch.updates:
                results.extend(await self._on_update(account_id, update, subscriptions))
            self.database.triggers.save_cursor(cursor_key, batch.next_cursor)
        return results

    async def run(self) -> None:
        import asyncio

        listener = getattr(self.adapter, "listen", None)
        if listener is not None:
            self._listener_stop = asyncio.Event()
            try:
                await _maybe_await(listener(self._on_update, self._listener_stop, self._account_ids()))
            finally:
                self._listener_stop = None
            return
        await self.poll_once()
        while not self._stopped:
            await asyncio.sleep(self.interval_seconds)
            if not self._stopped:
                await self.poll_once()

    def stop(self) -> None:
        self._stopped = True
        if self._listener_stop is not None:
            self._listener_stop.set()
