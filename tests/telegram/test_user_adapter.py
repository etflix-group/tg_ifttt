import asyncio
from types import SimpleNamespace

import pytest

from tg_ifttt.storage.account_repository import AccountRepository
from tg_ifttt.storage.crypto import SecretBox
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.models import AppCredentials, TelegramAccount
from tg_ifttt.telegram.session_manager import SessionManager
from tg_ifttt.telegram.user_adapter import UserTelegramAdapter
from tg_ifttt.runtime.adapters import WaitingForMessage


class RawButton:
    def __init__(self, text, data=None):
        self.text = text
        self.data = data


class RawMessage:
    def __init__(self, message_id, text, buttons=None, sender_id="bot"):
        self.id = message_id
        self.message = text
        self.buttons = buttons or []
        self.sender_id = sender_id
        self.clicks = []

    async def click(self, row, column):
        self.clicks.append((row, column))


class FakeClient:
    def __init__(self):
        self.messages = {}
        self.sent = []
        self.connected = False
        self.event_handlers = []

    def add_event_handler(self, callback, event):
        self.event_handlers.append((callback, event))

    def remove_event_handler(self, callback, event):
        self.event_handlers.remove((callback, event))

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return True

    async def send_message(self, peer, text):
        self.sent.append((peer, text))
        message_id = max(self.messages.keys() or [0]) + 1
        message = RawMessage(message_id, text, sender_id="account-a")
        self.messages[message_id] = message
        return message

    async def get_messages(self, peer, limit=20, ids=None):
        if ids is not None:
            return self.messages.get(ids)
        return list(sorted(self.messages.values(), key=lambda item: item.id, reverse=True))[:limit]


@pytest.fixture
def adapter_and_client(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    repository = AccountRepository(database.connection, SecretBox(b"x" * 32))
    repository.save_account(
        TelegramAccount("account-a", "A", 1001, "+8613800000000", "ready"),
        "session-value",
    )
    client = FakeClient()
    manager = SessionManager(
        AppCredentials(123, "hash"),
        repository,
        client_factory=lambda *args: client,
    )
    yield UserTelegramAdapter(manager), client
    database.close()


def test_send_message_resolves_target_per_account(adapter_and_client):
    adapter, client = adapter_and_client
    result = asyncio.run(adapter.send_message("account-a", "@example_bot", "/start"))

    assert result.peer_id == "@example_bot"
    assert client.sent == [("@example_bot", "/start")]


def test_click_inline_button_uses_callback_coordinates(adapter_and_client):
    adapter, client = adapter_and_client
    message = RawMessage(
        10,
        "菜单",
        [[RawButton("✅ 每日签到", b"checkin")]],
    )
    client.messages[10] = message

    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "message": 10,
                "match": {"type": "regex", "value": r"^✅\s*每日签到$"},
            },
        )
    )

    assert result.kind == "inline"
    assert message.clicks == [(0, 0)]


def test_click_button_searches_recent_messages_for_matching_keyboard(adapter_and_client):
    adapter, client = adapter_and_client
    menu = RawMessage(
        9,
        "请选择你需要的服务：",
        [[RawButton("✅ 每日签到", b"checkin")]],
    )
    client.messages[9] = menu
    client.messages[10] = RawMessage(10, "/start")

    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "match": {"type": "regex", "value": r"^✅\s*每日签到$"},
            },
        )
    )

    assert result.message_id == 9
    assert menu.clicks == [(0, 0)]


def test_click_button_waits_for_a_keyboard_after_the_current_message(adapter_and_client):
    adapter, client = adapter_and_client
    old_menu = RawMessage(
        9,
        "旧菜单",
        [[RawButton("✅ 每日签到", b"checkin")]],
    )
    client.messages[9] = old_menu
    client.messages[10] = RawMessage(10, "/start", sender_id="account-a")

    with pytest.raises(WaitingForMessage):
        asyncio.run(
            adapter.click_button(
                "account-a",
                {
                    "target": "@example_bot",
                    "after_message_id": 10,
                    "match": {"type": "regex", "value": r"^✅\s*每日签到$"},
                },
            )
        )

    new_menu = RawMessage(
        11,
        "新菜单",
        [[RawButton("✅ 每日签到", b"checkin")]],
    )
    client.messages[11] = new_menu
    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "after_message_id": 10,
                "match": {"type": "regex", "value": r"^✅\s*每日签到$"},
            },
        )
    )

    assert result.message_id == 11
    assert old_menu.clicks == []
    assert new_menu.clicks == [(0, 0)]


def test_wait_message_action_barrier_accepts_new_message_or_refreshed_panel(adapter_and_client):
    adapter, client = adapter_and_client
    panel = RawMessage(
        10,
        "菜单",
        [[RawButton("✅ 每日签到", b"checkin")]],
    )
    client.messages[10] = panel
    before_message = adapter._normalize(panel, "@example_bot").to_dict()
    request = {
        "target": "@example_bot",
        "action_barrier": "new_message_or_refresh",
        "message_id": 10,
        "after_message_id": 10,
        "before_message": before_message,
    }

    with pytest.raises(WaitingForMessage):
        asyncio.run(adapter.wait_message("account-a", request))

    panel.message = "签到完成"
    refreshed = asyncio.run(adapter.wait_message("account-a", request))

    assert refreshed.message_id == 10
    assert refreshed.text == "签到完成"


def test_click_reply_button_sends_label(adapter_and_client):
    adapter, client = adapter_and_client
    client.messages[10] = RawMessage(10, "菜单", [[RawButton("每日签到")]])

    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "message": 10,
                "match": {"type": "regex", "value": "每日签到"},
            },
        )
    )

    assert result.kind == "reply"
    assert client.sent[-1] == ("@example_bot", "每日签到")


def test_wait_message_applies_sender_and_text_filters(adapter_and_client):
    adapter, client = adapter_and_client
    client.messages[10] = RawMessage(10, "无关消息", sender_id="other")
    client.messages[11] = RawMessage(11, "签到成功，积分 10", sender_id="bot")

    result = asyncio.run(
        adapter.wait_message(
            "account-a",
            {
                "target": "@example_bot",
                "sender": "bot",
                "text_match": {"type": "contains", "value": "签到成功"},
            },
        )
    )
    assert result.message_id == 11


def test_wait_message_returns_serializable_wait_condition(adapter_and_client):
    adapter, client = adapter_and_client
    client.messages[10] = RawMessage(10, "其他", sender_id="bot")

    with pytest.raises(WaitingForMessage) as error:
        asyncio.run(
            adapter.wait_message(
                "account-a",
                {"target": "@example_bot", "text_match": {"type": "exact", "value": "签到"}},
            )
        )
    assert error.value.condition["target"] == "@example_bot"


def test_event_listener_registers_message_and_edit_handlers(adapter_and_client):
    adapter, client = adapter_and_client

    async def exercise():
        updates = []
        stop = asyncio.Event()
        task = asyncio.create_task(adapter.listen(lambda account, update: updates.append((account, update)), stop, ["account-a"]))
        await asyncio.sleep(0)
        assert len(client.event_handlers) == 2
        await client.event_handlers[0][0](SimpleNamespace(message=RawMessage(11, "菜单"), chat_id="@example_bot"))
        stop.set()
        await task
        return updates

    updates = asyncio.run(exercise())

    assert updates[0][0] == "account-a"
    assert updates[0][1]["normalized_type"] == "message"
    assert updates[0][1]["message"]["peer_id"] == "@example_bot"
    assert client.event_handlers == []
