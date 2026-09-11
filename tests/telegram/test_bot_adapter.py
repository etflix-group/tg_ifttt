import asyncio

import pytest

from tg_ifttt.telegram.bot_adapter import BotApiAdapter, HttpResponse
from tg_ifttt.telegram.errors import BotApiError, UnsupportedButtonError
from tg_ifttt.runtime.adapters import WaitingForMessage


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses) if isinstance(responses, list) else [responses]
        self.calls = []

    async def __call__(self, url, payload):
        self.calls.append((url, payload))
        response = self.responses.pop(0)
        return response


def test_bot_send_message_uses_token_and_normalizes_response():
    http = FakeHttp(
        {
            "ok": True,
            "result": {
                "message_id": 7,
                "chat": {"id": 1},
                "from": {"id": 99},
                "text": "hello",
            },
        }
    )
    adapter = BotApiAdapter("123:secret", http_call=http)

    message = asyncio.run(adapter.send_message("bot-a", "1", "hello"))

    assert message.message_id == 7
    assert message.peer_id == "1"
    assert http.calls[0][0].endswith("/sendMessage")
    assert "123:secret" in http.calls[0][0]
    assert http.calls[0][1] == {"chat_id": "1", "text": "hello"}


def test_bot_get_updates_normalizes_inline_keyboard_and_advances_offset():
    http = FakeHttp(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 41,
                    "message": {
                        "message_id": 8,
                        "chat": {"id": 1},
                        "from": {"id": 10},
                        "text": "菜单",
                        "reply_markup": {
                            "inline_keyboard": [[{"text": "签到", "callback_data": "checkin"}]]
                        },
                    },
                }
            ],
        }
    )
    adapter = BotApiAdapter("123:secret", http_call=http)

    batch = asyncio.run(adapter.get_updates(offset=40, timeout=1))

    assert batch.next_cursor == "42"
    assert batch.updates[0]["message"]["buttons"][0][0]["callback_data"] == "checkin"
    assert http.calls[0][1]["offset"] == 40


def test_bot_action_barrier_polls_past_unmatched_updates():
    http = FakeHttp(
        [
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 41,
                        "message": {
                            "message_id": 8,
                            "chat": {"id": 1},
                            "from": {"id": 10},
                            "text": "无关消息",
                        },
                    }
                ],
            },
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 42,
                        "message": {
                            "message_id": 9,
                            "chat": {"id": 1},
                            "from": {"id": 10},
                            "text": "菜单已刷新",
                        },
                    }
                ],
            },
        ]
    )
    adapter = BotApiAdapter("123:secret", http_call=http)

    result = asyncio.run(
        adapter.wait_message(
            "bot-a",
            {"target": "1", "action_barrier": "new_message", "after_message_id": 8},
        )
    )

    assert result.message_id == 9
    assert len(http.calls) == 2
    assert http.calls[1][1]["offset"] == 42


def test_bot_answer_callback_query_uses_callback_endpoint():
    http = FakeHttp({"ok": True, "result": True})
    adapter = BotApiAdapter("123:secret", http_call=http)

    asyncio.run(adapter.answer_callback("callback-1", "已处理"))

    assert http.calls[0][0].endswith("/answerCallbackQuery")
    assert http.calls[0][1] == {"callback_query_id": "callback-1", "text": "已处理"}


def test_bot_api_error_does_not_echo_token():
    http = FakeHttp(
        HttpResponse(
            401,
            {"ok": False, "error_code": 401, "description": "Unauthorized"},
        )
    )
    adapter = BotApiAdapter("123:secret", http_call=http)

    with pytest.raises(BotApiError) as error:
        asyncio.run(adapter.send_message("bot-a", "1", "hello"))
    assert "123:secret" not in str(error.value)


def test_bot_token_cannot_click_as_a_user():
    adapter = BotApiAdapter("123:secret", http_call=FakeHttp({"ok": True, "result": True}))

    with pytest.raises(UnsupportedButtonError):
        asyncio.run(adapter.click_button("bot-a", {"target": "1", "match": {}}))


def test_bot_listener_uses_long_polling_and_forwards_updates():
    http = FakeHttp(
        {
            "ok": True,
            "result": [
                {
                    "update_id": 9,
                    "message": {
                        "message_id": 4,
                        "chat": {"id": 1},
                        "from": {"id": 10},
                        "text": "菜单",
                    },
                }
            ],
        }
    )
    adapter = BotApiAdapter("123:secret", http_call=http)

    async def exercise():
        updates = []
        stop = asyncio.Event()

        async def on_update(account, update):
            updates.append((account, update))
            stop.set()

        await adapter.listen(on_update, stop, ["bot-a"])
        return updates

    updates = asyncio.run(exercise())

    assert updates[0][0] == "bot-a"
    assert updates[0][1]["message"]["message_id"] == 4
    assert http.calls[0][1]["timeout"] == 50
