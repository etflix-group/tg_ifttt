"""Convert Telethon and Bot API message objects into runtime snapshots.

The runtime deliberately depends on this small, dependency-light boundary instead
of importing Telegram-specific types.  Both Telethon objects and Bot API JSON are
therefore accepted through conservative attribute/mapping access.
"""

import base64
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from tg_ifttt.runtime.adapters import (
    ButtonSnapshot,
    MessageSnapshot,
)


_MISSING = object()


def _read(value: Any, *names: str, default: Any = None) -> Any:
    if value is None:
        return default
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        try:
            result = getattr(value, name)
        except AttributeError:
            continue
        except Exception:
            continue
        if result is not None:
            return result
    return default


def _decode_callback_data(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "base64:" + base64.urlsafe_b64encode(value).decode("ascii")
    if isinstance(value, bytearray):
        return _decode_callback_data(bytes(value))
    if isinstance(value, memoryview):
        return _decode_callback_data(value.tobytes())
    return str(value)


def _button_kind(raw_button: Any, callback_data: Optional[str], source: Any) -> str:
    if callback_data is not None:
        return "inline"

    if _read(raw_button, "url", "login_url", default=None) is not None:
        return "url"
    unsupported_fields = (
        "callback_game",
        "web_app",
        "switch_inline_query",
        "switch_inline_query_current_chat",
        "request_contact",
        "request_location",
        "request_poll",
        "pay",
    )
    if any(_read(raw_button, field, default=None) is not None for field in unsupported_fields):
        return "unsupported"

    # Telethon's reply keyboard request/game button types do not always expose a
    # distinguishing field on the wrapper returned by Message.buttons.
    class_names = " ".join(
        type(candidate).__name__.lower()
        for candidate in (raw_button, source)
        if candidate is not None
    )
    if any(
        marker in class_names
        for marker in ("requestphone", "requestgeolocation", "keyboardbuttongame", "webview")
    ):
        return "unsupported"
    return "reply"


def normalize_button(raw_button: Any, row: int, column: int) -> ButtonSnapshot:
    """Normalize one raw button while retaining its original keyboard position."""

    source = _read(raw_button, "button", default=None)
    if source is None:
        source = raw_button

    label_value = _read(raw_button, "text", default=_MISSING)
    if label_value is _MISSING:
        label_value = _read(source, "text", default="")
    # Keep the exact label for Reply Keyboard operations. match_button applies
    # whitespace/Unicode normalization only while comparing candidates.
    label = str(label_value or "")

    callback_value = _read(raw_button, "data", "callback_data", default=_MISSING)
    if callback_value is _MISSING:
        callback_value = _read(source, "data", "callback_data", default=None)
    callback_data = _decode_callback_data(callback_value)
    kind = _button_kind(raw_button, callback_data, source)
    return ButtonSnapshot(
        label=label,
        callback_data=callback_data,
        kind=kind,
        row=row,
        column=column,
    )


def _button_rows(raw_message: Any) -> List[List[Any]]:
    raw_buttons = _read(raw_message, "buttons", default=_MISSING)
    if raw_buttons is _MISSING or raw_buttons is None:
        markup = _read(raw_message, "reply_markup", default=None)
        raw_buttons = _read(
            markup,
            "inline_keyboard",
            "keyboard",
            "rows",
            default=[],
        )

    rows: List[List[Any]] = []
    for raw_row in raw_buttons or []:
        row_buttons = _read(raw_row, "buttons", default=_MISSING)
        if row_buttons is _MISSING:
            row_buttons = raw_row
        if row_buttons is None:
            rows.append([])
        else:
            rows.append(list(row_buttons))
    return rows


def normalize_message(
    raw_message: Any,
    peer_id: str,
    sender_id: Optional[str],
) -> MessageSnapshot:
    """Normalize a raw Telethon message or Bot API message JSON object."""

    message_id = _read(raw_message, "id", "message_id", default=None)
    if message_id is None:
        raise ValueError("Telegram message is missing an id")
    try:
        normalized_id = int(message_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Telegram message id must be an integer") from exc

    text = _read(raw_message, "message", "text", default="")
    rows = _button_rows(raw_message)
    buttons: Tuple[Tuple[ButtonSnapshot, ...], ...] = tuple(
        tuple(normalize_button(button, row_index, column_index) for column_index, button in enumerate(row))
        for row_index, row in enumerate(rows)
    )
    return MessageSnapshot(
        message_id=normalized_id,
        peer_id=str(peer_id),
        sender_id=None if sender_id is None else str(sender_id),
        text="" if text is None else str(text),
        buttons=buttons,
    )
