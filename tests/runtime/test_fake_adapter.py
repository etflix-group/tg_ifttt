from typing import Any, Iterable, List, Optional

from tg_ifttt.runtime.adapters import (
    ButtonResult,
    ButtonSnapshot,
    MessageSnapshot,
    TelegramAdapter,
    WaitingForMessage,
    match_button,
)


def message_with_button(label: str, kind: str = "inline", message_id: int = 10) -> MessageSnapshot:
    return MessageSnapshot(
        message_id=message_id,
        peer_id="@example_bot",
        sender_id="bot",
        text="菜单",
        buttons=((ButtonSnapshot(label=label, callback_data="checkin", kind=kind),),),
    )


class FakeTelegramAdapter(TelegramAdapter):
    def __init__(self, incoming: Optional[Iterable[MessageSnapshot]] = None) -> None:
        self.incoming: List[MessageSnapshot] = list(incoming or [])
        self.sent_texts: List[Any] = []
        self.clicked_labels: List[str] = []
        self._next_message_id = 1
        self._last_message: Optional[MessageSnapshot] = None

    async def send_message(self, account_id: str, target: str, text: str) -> MessageSnapshot:
        self.sent_texts.append((text, target))
        message = MessageSnapshot(
            message_id=self._next_message_id,
            peer_id=target,
            sender_id=account_id,
            text=text,
            buttons=(),
        )
        self._next_message_id += 1
        return message

    async def wait_message(self, account_id: str, request: dict) -> MessageSnapshot:
        if not self.incoming:
            raise WaitingForMessage(request)
        self._last_message = self.incoming.pop(0)
        return self._last_message

    async def click_button(self, account_id: str, request: dict) -> ButtonResult:
        candidate = self._last_message
        if candidate is None and self.incoming:
            candidate = self.incoming[0]
        if candidate is None:
            raise WaitingForMessage(request)
        button = match_button(candidate.buttons, request.get("match", {}))
        self.clicked_labels.append(button.label)
        return ButtonResult(
            message_id=candidate.message_id,
            label=button.label,
            kind=button.kind,
            callback_data=button.callback_data,
            before_message=candidate.to_dict(),
            action_message_id=candidate.message_id,
        )


def test_fake_adapter_matches_regex_button():
    adapter = FakeTelegramAdapter([message_with_button("✅ 每日签到")])
    result = __import__("asyncio").run(
        adapter.click_button(
            "account-a",
            {"match": {"type": "regex", "value": r"^✅\s*每日签到$"}},
        )
    )
    assert result.label == "✅ 每日签到"
    assert adapter.clicked_labels == ["✅ 每日签到"]


def test_fake_adapter_can_send_reply_keyboard_button():
    adapter = FakeTelegramAdapter([message_with_button("每日签到", kind="reply")])
    result = __import__("asyncio").run(
        adapter.click_button(
            "account-a",
            {"match": {"type": "regex", "value": "每日签到"}},
        )
    )
    assert result.kind == "reply"
    assert adapter.clicked_labels == ["每日签到"]
