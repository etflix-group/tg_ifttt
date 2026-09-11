import asyncio

from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.storage.database import Database

from .test_fake_adapter import FakeTelegramAdapter, message_with_button


def waiting_workflow():
    return parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "waiting", "name": "Waiting", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {"id": "wait", "type": "telegram.wait_message", "config": {"target": "@bot", "timeout": 30}},
                {"id": "click", "type": "telegram.click_button", "config": {"target": "@bot", "match": {"type": "regex", "value": "签到"}}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "send", "to": "wait"},
                {"from": "wait", "to": "click"},
                {"from": "click", "to": "end"},
            ],
        }
    )


def test_waiting_run_recovers_after_reopening_database(tmp_path):
    path = tmp_path / "state.sqlite3"
    first_database = Database.connect(path)
    first_database.initialize()
    first_adapter = FakeTelegramAdapter()
    workflow = waiting_workflow()
    first_engine = WorkflowEngine(first_database, first_adapter)

    run_id = first_engine.start(workflow, "account-a", {})
    waiting_result = asyncio.run(first_engine.resume(run_id))

    assert waiting_result.status == "waiting"
    assert first_adapter.sent_texts == [("/start", "@bot")]
    first_database.close()

    second_database = Database.connect(path)
    second_adapter = FakeTelegramAdapter([message_with_button("每日签到")])
    second_engine = WorkflowEngine(second_database, second_adapter)
    result = asyncio.run(second_engine.resume(run_id))

    assert result.status == "success"
    assert second_adapter.sent_texts == []
    assert second_adapter.clicked_labels == ["每日签到"]
    second_database.close()
