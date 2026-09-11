import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple, Union


class WaitingForMessage(Exception):
    def __init__(self, condition: Dict[str, Any]) -> None:
        super().__init__("message is not available yet")
        self.condition = condition


class ButtonMatchError(ValueError):
    """Raised when a button selector is missing or ambiguous."""


@dataclass(frozen=True)
class ButtonSnapshot:
    label: str
    callback_data: Optional[str]
    kind: str
    row: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "callback_data": self.callback_data,
            "kind": self.kind,
            "row": self.row,
            "column": self.column,
        }


@dataclass(frozen=True)
class MessageSnapshot:
    message_id: int
    peer_id: str
    sender_id: Optional[str]
    text: str
    buttons: Tuple[Tuple[ButtonSnapshot, ...], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "peer_id": self.peer_id,
            "sender_id": self.sender_id,
            "text": self.text,
            "buttons": [
                [button.to_dict() for button in row]
                for row in self.buttons
            ],
        }


@dataclass(frozen=True)
class ButtonResult:
    message_id: int
    label: str
    kind: str
    callback_data: Optional[str]
    before_message: Optional[Dict[str, Any]] = None
    action_message_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "label": self.label,
            "kind": self.kind,
            "callback_data": self.callback_data,
        }


def matches_action_barrier(message: MessageSnapshot, request: Mapping[str, Any]) -> bool:
    """Return whether a message represents progress after a Telegram action.

    An action can produce either a new message or an edited keyboard/message in
    place.  The latter keeps the same message id, so callers must provide the
    snapshot captured before the action to distinguish a refresh from the old
    panel that was already present.
    """

    target = request.get("target")
    if target is not None and str(target) != str(message.peer_id):
        return False
    sender = request.get("sender", request.get("sender_id"))
    if sender is not None and str(sender) != str(message.sender_id):
        return False

    after_message_id = request.get("after_message_id")
    if after_message_id is not None:
        try:
            if message.message_id > int(after_message_id):
                return True
        except (TypeError, ValueError):
            return False

    source_message_id = request.get("message_id")
    before_message = request.get("before_message")
    if source_message_id is None or not isinstance(before_message, Mapping):
        return False
    try:
        same_source = message.message_id == int(source_message_id)
    except (TypeError, ValueError):
        return False
    return same_source and message.to_dict() != dict(before_message)


class TelegramAdapter(Protocol):
    async def send_message(self, account_id: str, target: str, text: str) -> MessageSnapshot:
        ...

    async def wait_message(self, account_id: str, request: Dict[str, Any]) -> MessageSnapshot:
        ...

    async def click_button(self, account_id: str, request: Dict[str, Any]) -> ButtonResult:
        ...


def normalize_button_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _flatten_buttons(buttons: Sequence[Sequence[ButtonSnapshot]]) -> List[ButtonSnapshot]:
    return [button for row in buttons for button in row]


def flatten_buttons(
    message_or_buttons: Union[MessageSnapshot, Sequence[Sequence[ButtonSnapshot]]],
) -> List[ButtonSnapshot]:
    """Return buttons in row-major order without exposing raw Telegram objects."""

    if isinstance(message_or_buttons, MessageSnapshot):
        return _flatten_buttons(message_or_buttons.buttons)
    return _flatten_buttons(message_or_buttons)


def match_button(
    buttons: Sequence[Sequence[ButtonSnapshot]],
    match: Dict[str, Any],
) -> ButtonSnapshot:
    if not isinstance(match, dict):
        raise ButtonMatchError("button match must be a mapping")
    match_type = match.get("type", "exact")
    value = match.get("value")
    flattened = flatten_buttons(buttons)

    if match_type == "position":
        position = match.get("position", value)
        if isinstance(position, dict):
            row = position.get("row")
            column = position.get("column")
            if (
                not isinstance(row, int)
                or isinstance(row, bool)
                or not isinstance(column, int)
                or isinstance(column, bool)
            ):
                raise ButtonMatchError("button position row and column must be integers")
            candidates = [
                button
                for button in flattened
                if button.row == row and button.column == column
            ]
        else:
            index = match.get("index", position)
            if not isinstance(index, int) or isinstance(index, bool):
                raise ButtonMatchError("button position must be an integer index")
            if index < 0 or index >= len(flattened):
                raise ButtonMatchError("button position is out of range")
            candidates = [flattened[index]]
    elif match_type == "callback_data":
        candidates = [button for button in flattened if button.callback_data == str(value)]
    elif match_type in {"exact", "contains", "regex"}:
        if not isinstance(value, str):
            raise ButtonMatchError("text button match value must be a string")
        expected = normalize_button_label(value)
        candidates = []
        for button in flattened:
            label = normalize_button_label(button.label)
            if match_type == "exact" and label == expected:
                candidates.append(button)
            elif match_type == "contains" and expected in label:
                candidates.append(button)
            elif match_type == "regex":
                try:
                    matched = re.search(value, label) is not None
                except re.error as exc:
                    raise ButtonMatchError("invalid button regular expression") from exc
                if matched:
                    candidates.append(button)
    else:
        raise ButtonMatchError("unsupported button match type: %s" % match_type)

    if not candidates:
        raise ButtonMatchError("button match produced no candidates")
    if len(candidates) == 1:
        return candidates[0]

    policy = match.get("multiple", match.get("multiple_policy", "fail"))
    if policy == "first":
        return candidates[0]
    if policy == "index":
        index = match.get("index")
        if isinstance(index, int) and 0 <= index < len(candidates):
            return candidates[index]
    raise ButtonMatchError("button match is ambiguous: %d candidates" % len(candidates))
