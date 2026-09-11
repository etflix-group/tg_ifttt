import asyncio
from pathlib import Path

from tg_ifttt.domain.loader import load_workflow, parse_workflow
from tg_ifttt.runtime.adapters import ButtonResult, ButtonSnapshot, MessageSnapshot, WaitingForMessage, match_button
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.errors import TelegramFloodWaitError

from .test_fake_adapter import FakeTelegramAdapter, message_with_button


def open_test_database(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    return database


def test_start_wait_match_button_and_finish(tmp_path):
    workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    adapter = FakeTelegramAdapter([message_with_button("✅ 每日签到")])
    database = open_test_database(tmp_path)
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    result = asyncio.run(engine.resume(run_id))

    assert result.status == "success"
    assert adapter.sent_texts == [("/start", "@example_bot")]
    assert adapter.clicked_labels == ["✅ 每日签到"]
    stored = database.runs.load_run(run_id)
    assert stored.checkpoint_seq == 2
    database.close()


def test_condition_selects_the_matching_edge(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "condition", "name": "Condition", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "set", "type": "set_variable", "config": {"name": "ok", "value": True}},
                {"id": "branch", "type": "condition", "config": {"expression": "variables.ok == True"}},
                {"id": "success", "type": "set_variable", "config": {"name": "result", "value": "yes"}},
                {"id": "failure", "type": "set_variable", "config": {"name": "result", "value": "no"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "set", "to": "branch"},
                {"from": "branch", "to": "success", "condition": "variables.ok == True"},
                {"from": "branch", "to": "failure", "condition": "variables.ok == False"},
                {"from": "success", "to": "end"},
                {"from": "failure", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    engine = WorkflowEngine(database, FakeTelegramAdapter())
    run_id = engine.start(workflow, "account-a", {})

    result = asyncio.run(engine.resume(run_id))

    assert result.status == "success"
    stored = database.runs.load_run(run_id)
    assert stored.variables["result"] == "yes"
    assert "failure" not in stored.node_outputs
    database.close()


class FailingAdapter:
    async def send_message(self, account_id, target, text):
        raise RuntimeError("account is not connected")


class ActionBarrierAdapter(FakeTelegramAdapter):
    def __init__(self):
        super().__init__()
        self.barrier_messages = []
        self.wait_requests = []

    async def wait_message(self, account_id, request):
        self.wait_requests.append(request)
        if not self.barrier_messages:
            raise WaitingForMessage(request)
        self._last_message = self.barrier_messages.pop(0)
        return self._last_message


class ClickFailsAdapter(ActionBarrierAdapter):
    """Barrier succeeds but click_button always raises WaitingForMessage."""

    async def click_button(self, account_id, request):
        raise WaitingForMessage(request)


def test_send_action_waits_before_next_node_without_resending(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "action-barrier", "name": "Action barrier", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {"id": "mark", "type": "set_variable", "config": {"name": "ready", "value": True}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "send", "to": "mark"},
                {"from": "mark", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = ActionBarrierAdapter()
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))

    assert first.status == "waiting"
    assert adapter.sent_texts == [("/start", "@bot")]
    stored = database.runs.load_run(run_id)
    assert stored.current_node_id == "mark"
    assert stored.waiting["kind"] == "action_barrier"

    adapter.barrier_messages.append(
        MessageSnapshot(message_id=2, peer_id="@bot", sender_id="bot", text="菜单")
    )
    second = asyncio.run(engine.resume(run_id))

    assert second.status == "success"
    assert adapter.sent_texts == [("/start", "@bot")]
    assert database.runs.load_run(run_id).variables["ready"] is True
    assert len(adapter.wait_requests) == 2
    database.close()


def test_click_action_waits_for_refresh_without_reclicking_after_resume(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "click-barrier", "name": "Click barrier", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {
                    "id": "click",
                    "type": "telegram.click_button",
                    "config": {"target": "@bot", "match": {"type": "regex", "value": "签到"}},
                },
                {"id": "mark", "type": "set_variable", "config": {"name": "ready", "value": True}},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "send", "to": "click"},
                {"from": "click", "to": "mark"},
                {"from": "mark", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = ActionBarrierAdapter()
    adapter.barrier_messages.append(message_with_button("每日签到", message_id=2))
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))

    assert first.status == "waiting"
    assert adapter.clicked_labels == ["每日签到"]
    assert database.runs.load_run(run_id).current_node_id == "mark"

    adapter.barrier_messages.append(
        MessageSnapshot(message_id=3, peer_id="@bot", sender_id="bot", text="签到完成")
    )
    second = asyncio.run(engine.resume(run_id))

    assert second.status == "success"
    assert adapter.clicked_labels == ["每日签到"]
    assert database.runs.load_run(run_id).variables["ready"] is True
    database.close()


def test_action_barrier_recovers_without_repeating_action_after_reopen(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "restart-barrier", "name": "Restart barrier", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {"id": "mark", "type": "set_variable", "config": {"name": "ready", "value": True}},
            ],
            "edges": [{"from": "send", "to": "mark"}],
        }
    )
    path = tmp_path / "state.sqlite3"
    first_database = Database.connect(path)
    first_database.initialize()
    first_adapter = ActionBarrierAdapter()
    first_engine = WorkflowEngine(first_database, first_adapter)

    run_id = first_engine.start(workflow, "account-a", {})
    first = asyncio.run(first_engine.resume(run_id))

    assert first.status == "waiting"
    assert first_adapter.sent_texts == [("/start", "@bot")]
    first_database.close()

    second_database = Database.connect(path)
    second_database.initialize()
    second_adapter = ActionBarrierAdapter()
    second_adapter.barrier_messages.append(
        MessageSnapshot(message_id=2, peer_id="@bot", sender_id="bot", text="菜单")
    )
    second_engine = WorkflowEngine(second_database, second_adapter)

    second = asyncio.run(second_engine.resume(run_id))

    assert second.status == "success"
    assert second_adapter.sent_texts == []
    assert second_database.runs.load_run(run_id).variables["ready"] is True
    second_database.close()


def test_failed_node_records_actionable_error(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "failed", "name": "Failed", "enabled": True, "account": "account-a"},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
            ],
            "edges": [],
        }
    )
    database = open_test_database(tmp_path)
    engine = WorkflowEngine(database, FailingAdapter())

    run_id = engine.start(workflow, "account-a", {})
    result = asyncio.run(engine.resume(run_id))

    assert result.status == "failed"
    assert database.runs.load_run(run_id).error == {
        "node_id": "send",
        "message": "RuntimeError: account is not connected",
    }
    database.close()


def test_click_button_wait_timeout_fails_after_deadline(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "click-timeout", "name": "Click timeout", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {
                    "id": "click",
                    "type": "telegram.click_button",
                    "config": {
                        "target": "@bot",
                        "match": {"type": "regex", "value": "签到"},
                        "wait_timeout": 1,
                    },
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "click"},
                {"from": "click", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = ClickFailsAdapter()
    adapter.barrier_messages.append(message_with_button("每日签到", message_id=2))
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))

    assert first.status == "waiting"
    stored = database.runs.load_run(run_id)
    assert stored.current_node_id == "click"
    waiting = stored.waiting
    assert waiting.get("deadline") is not None
    assert waiting.get("wait_timeout") == 1

    import time
    time.sleep(1.1)

    second = asyncio.run(engine.resume(run_id))
    assert second.status == "failed"
    stored = database.runs.load_run(run_id)
    assert stored.error is not None
    assert "timeout" in stored.error["message"].lower()
    database.close()


def test_click_button_wait_timeout_preserved_across_resumes(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "click-timeout2", "name": "Click timeout2", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {
                    "id": "click",
                    "type": "telegram.click_button",
                    "config": {
                        "target": "@bot",
                        "match": {"type": "regex", "value": "签到"},
                        "wait_timeout": 5,
                    },
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "click"},
                {"from": "click", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = ClickFailsAdapter()
    adapter.barrier_messages.append(message_with_button("每日签到", message_id=2))
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))
    assert first.status == "waiting"
    first_deadline = database.runs.load_run(run_id).waiting.get("deadline")

    second = asyncio.run(engine.resume(run_id))
    assert second.status == "waiting"
    second_deadline = database.runs.load_run(run_id).waiting.get("deadline")

    assert first_deadline == second_deadline
    database.close()


class FloodWaitAdapter(ActionBarrierAdapter):
    """Adapter that raises TelegramFloodWaitError on first N send_message calls."""

    def __init__(self, flood_seconds: int = 5, flood_count: int = 1):
        super().__init__()
        self._flood_seconds = flood_seconds
        self._flood_remaining = flood_count

    async def send_message(self, account_id, target, text):
        if self._flood_remaining > 0:
            self._flood_remaining -= 1
            raise TelegramFloodWaitError(self._flood_seconds)
        return await super().send_message(account_id, target, text)


def test_flood_wait_on_send_schedules_waiting_then_recovers(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "flood", "name": "Flood", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = FloodWaitAdapter(flood_seconds=2, flood_count=1)
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))

    # Should be waiting (flood wait), not failed
    assert first.status == "waiting"
    stored = database.runs.load_run(run_id)
    assert stored.waiting["kind"] == "flood_wait"
    assert stored.waiting["flood_wait_seconds"] == 2
    assert stored.current_node_id == "send"
    assert adapter.sent_texts == []

    # Wait for flood wait to expire
    import time
    time.sleep(2.1)

    # Recovery should now succeed
    second = asyncio.run(engine.resume(run_id))
    assert second.status == "success"
    assert adapter.sent_texts == [("/start", "@bot")]
    database.close()


def test_flood_wait_on_click_schedules_waiting_then_recovers(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "flood-click", "name": "Flood Click", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {
                    "id": "click",
                    "type": "telegram.click_button",
                    "config": {"target": "@bot", "match": {"type": "regex", "value": "签到"}},
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "click"},
                {"from": "click", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)

    class ClickFloodAdapter(ActionBarrierAdapter):
        def __init__(self):
            super().__init__()
            self._click_flood_remaining = 1

        async def click_button(self, account_id, request):
            if self._click_flood_remaining > 0:
                self._click_flood_remaining -= 1
                raise TelegramFloodWaitError(2)
            # On retry, provide a message to click
            self.barrier_messages.append(message_with_button("每日签到", message_id=2))
            return await super().click_button(account_id, request)

    adapter = ClickFloodAdapter()
    # First barrier message for send_start action_barrier
    adapter.barrier_messages.append(message_with_button("每日签到", message_id=2))
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))

    # send_start succeeds, action_barrier clears, click_button raises FloodWait
    assert first.status == "waiting"
    stored = database.runs.load_run(run_id)
    assert stored.waiting["kind"] == "flood_wait"
    assert stored.current_node_id == "click"
    assert adapter.clicked_labels == []

    # Wait for flood wait to expire
    import time
    time.sleep(2.1)

    # Recovery should retry click and succeed
    second = asyncio.run(engine.resume(run_id))
    assert second.status == "success"
    assert adapter.clicked_labels == ["每日签到"]
    database.close()


def test_flood_wait_not_expired_returns_waiting_without_retry(tmp_path):
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "flood-pending", "name": "Flood Pending", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = FloodWaitAdapter(flood_seconds=10, flood_count=1)
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    first = asyncio.run(engine.resume(run_id))
    assert first.status == "waiting"

    # Resume immediately - should still be waiting (deadline not expired)
    second = asyncio.run(engine.resume(run_id))
    assert second.status == "waiting"
    assert adapter.sent_texts == []  # send_message not retried
    database.close()


class EditedMessageAdapter(ActionBarrierAdapter):
    """Adapter that simulates a bot editing a message in place (same message_id)
    when a button is clicked, replacing the keyboard with new buttons.

    This mirrors real-world bot behaviour: clicking a menu button edits the
    same message (same id) to show a new page with different buttons.
    """

    def __init__(self):
        super().__init__()
        self._edited_messages: dict = {}

    async def click_button(self, account_id, request):
        candidate = self._last_message
        if candidate is None and self.incoming:
            candidate = self.incoming[0]
        if candidate is None:
            raise WaitingForMessage(request)
        button = match_button(candidate.buttons, request.get("match", {}))
        self.clicked_labels.append(button.label)
        # Simulate the bot editing the message: same id, new text + buttons
        edited = MessageSnapshot(
            message_id=candidate.message_id,
            peer_id=candidate.peer_id,
            sender_id="bot",
            text="积分商城页面",
            buttons=(
                (
                    ButtonSnapshot(label="🛒 天卡 (100积分)", callback_data="shop_1", kind="inline"),
                    ButtonSnapshot(label="🛒 周卡 (700积分)", callback_data="shop_2", kind="inline"),
                ),
            ),
        )
        self._edited_messages[candidate.message_id] = edited
        self._last_message = edited
        return ButtonResult(
            message_id=candidate.message_id,
            label=button.label,
            kind=button.kind,
            callback_data=button.callback_data,
            before_message=candidate.to_dict(),
            action_message_id=candidate.message_id,
        )

    async def wait_message(self, account_id, request):
        self.wait_requests.append(request)
        if not self.barrier_messages:
            raise WaitingForMessage(request)
        self._last_message = self.barrier_messages.pop(0)
        return self._last_message

    async def read_messages(self, account_id, target, limit=20):
        # Return edited messages if available, otherwise incoming
        result = []
        for msg_id in sorted(self._edited_messages.keys(), reverse=True):
            result.append(self._edited_messages[msg_id])
        return result[:limit]


def test_click_button_finds_button_on_edited_message_with_same_id(tmp_path):
    """When the bot edits a message in place (same message_id as the clicked
    panel), the next click_button node should still find its button on that
    edited message, even though after_message_id equals the message_id."""
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "edit-click", "name": "Edit Click", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [
                {"id": "send", "type": "telegram.send_message", "config": {"target": "@bot", "text": "/start"}},
                {
                    "id": "click_shop",
                    "type": "telegram.click_button",
                    "config": {
                        "target": "@bot",
                        "after_message_id": "{{ steps.send.message_id }}",
                        "match": {"type": "regex", "value": "积分"},
                    },
                },
                {
                    "id": "click_tianka",
                    "type": "telegram.click_button",
                    "config": {
                        "target": "@bot",
                        "after_message_id": "{{ steps.click_shop.message_id }}",
                        "match": {"type": "regex", "value": "天卡"},
                    },
                },
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"from": "send", "to": "click_shop"},
                {"from": "click_shop", "to": "click_tianka"},
                {"from": "click_tianka", "to": "end"},
            ],
        }
    )
    database = open_test_database(tmp_path)
    adapter = EditedMessageAdapter()
    # The bot replies to /start with a menu containing '积分商城'
    adapter.barrier_messages.append(message_with_button("🏪 积分商城", message_id=2))
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    # First resume: send /start, action_barrier waits for bot reply
    first = asyncio.run(engine.resume(run_id))
    assert first.status == "waiting"

    # Second resume: barrier clears (bot replied with menu), click_shop clicks '积分商城'
    # The bot edits the message in place. action_barrier waits for the edit.
    second = asyncio.run(engine.resume(run_id))
    assert adapter.clicked_labels == ["🏪 积分商城"]
    assert second.status == "waiting"

    # Third resume: barrier clears (edited message detected), click_tianka clicks '🛒 天卡'
    # The edited message has same id=2, after_message_id=2, but the fallback logic
    # should find the button on the message with id == after_message_id.
    adapter.barrier_messages.append(
        MessageSnapshot(
            message_id=2, peer_id="@bot", sender_id="bot", text="积分商城页面",
            buttons=(
                (ButtonSnapshot(label="🛒 天卡 (100积分)", callback_data="shop_1", kind="inline"),),
            ),
        )
    )
    third = asyncio.run(engine.resume(run_id))
    assert third.status == "success"
    assert adapter.clicked_labels == ["🏪 积分商城", "🛒 天卡 (100积分)"]
    database.close()
