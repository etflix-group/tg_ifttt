from typing import Any, Iterable, List, Optional

from .adapters import (
    ButtonResult,
    ButtonSnapshot,
    MessageSnapshot,
    TelegramAdapter,
    WaitingForMessage,
    match_button,
)


def _message_from_config(value: Any, default_id: int) -> MessageSnapshot:
    if not isinstance(value, dict):
        raise ValueError("fake message must be a mapping")
    raw_buttons = value.get("buttons", [])
    rows = []
    if not isinstance(raw_buttons, list):
        raise ValueError("fake message buttons must be a list")
    for raw_row in raw_buttons:
        if not isinstance(raw_row, list):
            raise ValueError("fake message button row must be a list")
        row = []
        for raw_button in raw_row:
            if not isinstance(raw_button, dict) or not isinstance(raw_button.get("label"), str):
                raise ValueError("fake button requires a label")
            row.append(
                ButtonSnapshot(
                    label=raw_button["label"],
                    callback_data=raw_button.get("callback_data"),
                    kind=raw_button.get("kind", "inline"),
                )
            )
        rows.append(tuple(row))
    return MessageSnapshot(
        message_id=int(value.get("message_id", default_id)),
        peer_id=str(value.get("peer_id", "@example_bot")),
        sender_id=value.get("sender_id", "bot"),
        text=str(value.get("text", "菜单")),
        buttons=tuple(rows),
    )


class FakeTelegramAdapter(TelegramAdapter):
    """Deterministic connector used by offline examples and runner tests."""

    def __init__(self, incoming: Optional[Iterable[MessageSnapshot]] = None) -> None:
        self.incoming: List[MessageSnapshot] = list(incoming or [])
        self.sent_texts: List[Any] = []
        self.clicked_labels: List[str] = []
        self._next_message_id = 1
        self._last_message: Optional[MessageSnapshot] = None

    @classmethod
    def from_settings(cls, settings: dict) -> "FakeTelegramAdapter":
        fake_settings = settings.get("fake", {})
        configured = fake_settings.get("messages", []) if isinstance(fake_settings, dict) else []
        if configured:
            incoming = [_message_from_config(item, index + 10) for index, item in enumerate(configured)]
        else:
            incoming = [
                MessageSnapshot(
                    message_id=10,
                    peer_id="@example_bot",
                    sender_id="bot",
                    text="菜单",
                    buttons=((
                        ButtonSnapshot(
                            label="✅ 每日签到",
                            callback_data="checkin",
                            kind="inline",
                        ),
                    ),),
                )
            ]
        return cls(incoming)

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
