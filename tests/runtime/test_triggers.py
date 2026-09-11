import asyncio
from datetime import datetime, timezone

from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.runtime.adapters import MessageSnapshot, WaitingForMessage
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.runtime.fake import FakeTelegramAdapter
from tg_ifttt.runtime.triggers import EventListenerWorker, SchedulerWorker
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.models import UpdateBatch


def open_database(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    return database


def workflow_with_trigger(trigger):
    return parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "triggered", "name": "Triggered", "enabled": True, "account": "a"},
            "triggers": [trigger],
            "nodes": [
                {"id": "set", "type": "set_variable", "config": {"name": "ran", "value": True}},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"from": "set", "to": "end"}],
        }
    )


def test_scheduler_is_minute_idempotent(tmp_path):
    database = open_database(tmp_path)
    workflow = workflow_with_trigger({"type": "cron", "expression": "5 9 * * *"})
    database.workflows.save_version(workflow, "v1")
    worker = SchedulerWorker(database, FakeTelegramAdapter())
    moment = datetime(2026, 9, 10, 9, 5, tzinfo=timezone.utc)

    first = asyncio.run(worker.tick(moment))
    second = asyncio.run(worker.tick(moment))

    assert [result.status for result in first] == ["success"]
    assert [result.status for result in second] == ["success"]
    assert len(database.runs.list_runs()) == 1
    database.close()


def test_scheduler_runs_fixed_time_every_n_days_and_adds_bounded_random_seconds(tmp_path):
    database = open_database(tmp_path)
    workflow = workflow_with_trigger(
        {
            "type": "schedule",
            "interval_days": 2,
            "hour": 9,
            "minute": 30,
            "second": 58,
            "random_seconds": True,
            "anchor_date": "2026-09-10",
        }
    )
    database.workflows.save_version(workflow, "v1")
    worker = SchedulerWorker(database, FakeTelegramAdapter())

    on_anchor_day = asyncio.run(worker.tick(datetime(2026, 9, 10, 9, 30, 59, tzinfo=timezone.utc)))
    on_off_day = asyncio.run(worker.tick(datetime(2026, 9, 11, 9, 30, 59, tzinfo=timezone.utc)))
    on_next_day = asyncio.run(worker.tick(datetime(2026, 9, 12, 9, 30, 59, tzinfo=timezone.utc)))
    duplicate = asyncio.run(worker.tick(datetime(2026, 9, 10, 9, 30, 59, tzinfo=timezone.utc)))

    assert [result.status for result in on_anchor_day] == ["success"]
    assert on_off_day == []
    assert [result.status for result in on_next_day] == ["success"]
    assert [result.status for result in duplicate] == ["success"]
    assert len(database.runs.list_runs()) == 2
    for run in database.runs.list_runs():
        assert 0 <= run.trigger_payload["random_seconds"] <= 1
        assert run.trigger_payload["scheduled_at"].endswith((":58+00:00", ":59+00:00"))
    database.close()


class PollingFakeAdapter(FakeTelegramAdapter):
    def __init__(self):
        super().__init__()
        self.batches = [
            UpdateBatch(
                (
                    {
                        "update_id": 7,
                        "normalized_type": "message",
                        "message": {"peer_id": "room", "sender_id": "user", "text": "go"},
                    },
                ),
                "8",
            )
        ]

    async def fetch_updates(self, account_id, cursor=None):
        return self.batches[0]


class PushFakeAdapter(FakeTelegramAdapter):
    async def listen(self, callback, stop_event, account_ids=None):
        await callback(
            "a",
            {
                "update_id": 8,
                "normalized_type": "message",
                "message": {"peer_id": "room", "sender_id": "user", "text": "go"},
            },
        )
        stop_event.set()


def test_event_listener_persists_cursor_and_deduplicates_updates(tmp_path):
    database = open_database(tmp_path)
    workflow = workflow_with_trigger(
        {
            "type": "telegram.event",
            "target": "room",
            "match": {"type": "regex", "value": "^go$"},
        }
    )
    database.workflows.save_version(workflow, "v1")
    worker = EventListenerWorker(database, PollingFakeAdapter())

    first = asyncio.run(worker.poll_once())
    second = asyncio.run(worker.poll_once())

    assert [result.status for result in first] == ["success"]
    assert [result.status for result in second] == ["success"]
    assert database.triggers.get_cursor("PollingFakeAdapter:a") == "8"
    assert len(database.runs.list_runs()) == 1
    database.close()


def test_event_listener_prefers_push_stream_when_adapter_supports_it(tmp_path):
    database = open_database(tmp_path)
    workflow = workflow_with_trigger(
        {
            "type": "telegram.event",
            "target": "room",
            "match": {"type": "regex", "value": "^go$"},
        }
    )
    database.workflows.save_version(workflow, "v1")
    worker = EventListenerWorker(database, PushFakeAdapter())

    asyncio.run(worker.run())

    assert len(database.runs.list_runs()) == 1
    assert database.runs.list_runs()[0].status == "success"
    database.close()


def test_event_listener_wakes_waiting_run_from_message_update(tmp_path):
    database = open_database(tmp_path)
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "push-wakeup", "name": "Push wakeup", "enabled": True, "account": "a"},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "room", "text": "/start"}},
                {"id": "mark", "type": "set_variable", "config": {"name": "ready", "value": True}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "send", "to": "mark"},
                {"from": "mark", "to": "end"},
            ],
        }
    )
    adapter = FakeTelegramAdapter()
    database.workflows.save_version(workflow, "v1")
    engine = WorkflowEngine(database, adapter)
    run_id = engine.start(workflow, "a")
    first = asyncio.run(engine.resume(run_id))
    assert first.status == "waiting"
    assert database.runs.load_run(run_id).status == "waiting"

    adapter.incoming.append(MessageSnapshot(2, "room", "bot", "菜单"))
    worker = EventListenerWorker(database, adapter)
    result = asyncio.run(
        worker._on_update(
            "a",
            {"normalized_type": "message", "message": {"peer_id": "room", "sender_id": "bot", "text": "菜单"}},
        )
    )

    assert [item.status for item in result] == ["success"]
    assert database.runs.load_run(run_id).variables["ready"] is True
    database.close()
