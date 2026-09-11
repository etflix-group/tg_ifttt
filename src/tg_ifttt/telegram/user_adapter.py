"""MTProto adapter for ordinary Telegram user accounts."""

import inspect
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from telethon import events
from telethon.errors import FloodWaitError

from tg_ifttt.runtime.adapters import (
    ButtonMatchError,
    ButtonResult,
    ButtonSnapshot,
    MessageSnapshot,
    TelegramAdapter,
    WaitingForMessage,
    match_button,
    matches_action_barrier,
    normalize_button_label,
)

from .errors import TelegramFloodWaitError, TelegramError, UnsupportedButtonError
from .models import UpdateBatch
from .normalize import normalize_message
from .session_manager import SessionManager, TelegramClientHandle


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


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


def _sender_id(raw_message: Any) -> Optional[str]:
    value = _read(raw_message, "sender_id", default=None)
    if value is None:
        sender = _read(raw_message, "from", "sender", default=None)
        value = _read(sender, "id", default=sender)
    return None if value is None else str(value)


def _as_messages(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    # Telethon's TotalList is a list subclass, but keep this branch for fakes
    # and alternate clients returning one message for an ids query.
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        try:
            return list(value)
        except TypeError:
            pass
    return [value]


def _message_id(raw_message: Any) -> Optional[int]:
    value = _read(raw_message, "id", "message_id", default=None)
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _message_matches(message: MessageSnapshot, request: Mapping[str, Any]) -> bool:
    sender = request.get("sender", request.get("sender_id"))
    if sender is not None and str(sender) != str(message.sender_id):
        return False

    if request.get("action_barrier"):
        if not matches_action_barrier(message, request):
            return False
    else:
        exact_id = request.get("message_id")
        if exact_id is not None and message.message_id != int(exact_id):
            return False
        for field, operator in (("after_message_id", lambda actual, expected: actual > expected),
                                ("min_message_id", lambda actual, expected: actual >= expected),
                                ("max_message_id", lambda actual, expected: actual <= expected)):
            value = request.get(field)
            if value is not None and not operator(message.message_id, int(value)):
                return False

    text_match = request.get("text_match")
    if text_match is None and isinstance(request.get("match"), Mapping):
        text_match = request.get("match")
    if text_match is not None:
        if isinstance(text_match, str):
            text_match = {"type": "exact", "value": text_match}
        if not isinstance(text_match, Mapping):
            return False
        match_type = text_match.get("type", "exact")
        value = text_match.get("value", "")
        if not isinstance(value, str):
            return False
        if match_type == "exact" and normalize_button_label(message.text) != normalize_button_label(value):
            return False
        if match_type == "contains" and normalize_button_label(value) not in normalize_button_label(message.text):
            return False
        if match_type == "regex":
            try:
                if re.search(value, message.text) is None:
                    return False
            except re.error as exc:
                raise TelegramError("invalid message regular expression") from exc
        if match_type not in {"exact", "contains", "regex"}:
            raise TelegramError("unsupported message match type: %s" % match_type)

    regex = request.get("regex")
    if regex is not None:
        if not isinstance(regex, str):
            raise TelegramError("message regex must be a string")
        try:
            if re.search(regex, message.text) is None:
                return False
        except re.error as exc:
            raise TelegramError("invalid message regular expression") from exc
    return True


class UserTelegramAdapter(TelegramAdapter):
    """Translate the runtime adapter protocol into account-scoped Telethon calls."""

    def __init__(self, session_manager: SessionManager) -> None:
        self.session_manager = session_manager
        self._event_callback: Optional[Callable[[str, Mapping[str, Any]], Any]] = None
        self._event_handlers: Dict[str, Tuple[Any, List[Tuple[Any, Any]]]] = {}

    async def _handle(self, account_id: str) -> TelegramClientHandle:
        try:
            handle = await self.session_manager.connect_account(account_id)
            if self._event_callback is not None:
                await self._register_event_handlers(account_id, handle)
            return handle
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc

    async def _register_event_handlers(self, account_id: str, handle: TelegramClientHandle) -> None:
        if account_id in self._event_handlers:
            return
        add_handler = getattr(handle.client, "add_event_handler", None)
        if add_handler is None:
            return

        async def forward(event: Any) -> None:
            await self._forward_event(account_id, event)

        registrations = []
        for builder in (events.NewMessage(incoming=True), events.MessageEdited(incoming=True)):
            add_handler(forward, builder)
            registrations.append((forward, builder))
        self._event_handlers[account_id] = (handle.client, registrations)

    async def _forward_event(self, account_id: str, event: Any) -> None:
        callback = self._event_callback
        if callback is None:
            return
        candidate = _read(event, "message", default=None)
        raw_message = candidate if not isinstance(candidate, (str, bytes)) else event
        peer_id = _read(event, "chat_id", default=None)
        if peer_id is None:
            peer_id = _read(raw_message, "peer_id", "chat_id", default="")
        try:
            message = self._normalize(raw_message, peer_id)
        except (TypeError, ValueError):
            return
        update = {
            "type": "message",
            "normalized_type": "message",
            "message": message.to_dict(),
        }
        await _maybe_await(callback(account_id, update))

    async def _watch_account(self, account_id: str) -> None:
        handle = await self.session_manager.connect_account(account_id)
        await self._register_event_handlers(account_id, handle)

    async def listen(
        self,
        callback: Callable[[str, Mapping[str, Any]], Any],
        stop_event: Any,
        account_ids: Optional[Sequence[str]] = None,
    ) -> None:
        self._event_callback = callback
        requested = set(account_ids or ())
        repository = self.session_manager.account_repository
        requested.update(account.account_id for account in repository.list_accounts())
        for account_id in sorted(requested):
            try:
                await self._watch_account(account_id)
            except Exception:
                # A disconnected or expired account is retried when the next
                # workflow action connects it; other accounts keep listening.
                continue
        try:
            await stop_event.wait()
        finally:
            for client, registrations in self._event_handlers.values():
                remove_handler = getattr(client, "remove_event_handler", None)
                if remove_handler is None:
                    continue
                for handler, builder in registrations:
                    remove_handler(handler, builder)
            self._event_handlers.clear()
            self._event_callback = None

    async def _resolve_peer(self, client: Any, target: Any) -> Any:
        if target is None or target == "":
            raise ValueError("Telegram target must not be empty")
        resolver = getattr(client, "get_input_entity", None)
        if resolver is None:
            resolver = getattr(client, "get_entity", None)
        if resolver is None:
            return target
        try:
            resolved = await _maybe_await(resolver(target))
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc
        return target if resolved is None else resolved

    @staticmethod
    def _normalize(raw_message: Any, target: Any) -> MessageSnapshot:
        peer = str(target)
        return normalize_message(raw_message, peer_id=peer, sender_id=_sender_id(raw_message))

    async def _get_messages(
        self,
        client: Any,
        peer: Any,
        *,
        limit: int,
        message_id: Optional[int] = None,
    ) -> List[Any]:
        getter = getattr(client, "get_messages", None)
        if getter is None:
            raise TelegramError("Telegram client does not support reading messages")
        kwargs: Dict[str, Any] = {"limit": limit}
        if message_id is not None:
            kwargs["ids"] = message_id
        try:
            result = await _maybe_await(getter(peer, **kwargs))
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc
        return _as_messages(result)

    async def send_message(self, account_id: str, target: str, text: str) -> MessageSnapshot:
        handle = await self._handle(account_id)
        peer = await self._resolve_peer(handle.client, target)
        try:
            raw_message = await _maybe_await(handle.client.send_message(peer, text))
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc
        return self._normalize(raw_message, target)

    async def read_messages(self, account_id: str, target: str, limit: int = 20) -> List[MessageSnapshot]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("message limit must be an integer from 1 to 100")
        handle = await self._handle(account_id)
        peer = await self._resolve_peer(handle.client, target)
        raw_messages = await self._get_messages(handle.client, peer, limit=limit)
        return [self._normalize(message, target) for message in raw_messages]

    async def wait_message(self, account_id: str, request: Dict[str, Any]) -> MessageSnapshot:
        if not isinstance(request, dict):
            raise ValueError("wait_message request must be a mapping")
        target = request.get("target")
        if target is None:
            raise ValueError("wait_message requires target")
        limit = request.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("message limit must be an integer from 1 to 100")
        handle = await self._handle(account_id)
        peer = await self._resolve_peer(handle.client, target)
        raw_messages = await self._get_messages(handle.client, peer, limit=limit)
        for raw_message in raw_messages:
            message = self._normalize(raw_message, target)
            if _message_matches(message, request):
                return message
        raise WaitingForMessage(dict(request))

    async def _source_message(
        self,
        client: Any,
        target: Any,
        request: Mapping[str, Any],
    ) -> Tuple[Any, MessageSnapshot]:
        peer = await self._resolve_peer(client, target)
        configured_id = request.get("message")
        if configured_id is not None:
            try:
                message_id = int(configured_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("click_button message must be an integer id") from exc
            raw_messages = await self._get_messages(client, peer, limit=1, message_id=message_id)
            if not raw_messages:
                raise WaitingForMessage(dict(request))
            raw_message = raw_messages[0]
            return raw_message, self._normalize(raw_message, target)

        limit = request.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ValueError("click_button limit must be an integer from 1 to 100")
        after_message_id = request.get("after_message_id")
        if after_message_id is not None:
            try:
                after_message_id = int(after_message_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("click_button after_message_id must be an integer") from exc
        raw_messages = await self._get_messages(client, peer, limit=limit)
        fallback: Optional[Any] = None
        for raw_message in raw_messages:
            message = self._normalize(raw_message, target)
            if after_message_id is not None and message.message_id <= after_message_id:
                # When the bot edits a message in place (same message_id as the
                # clicked panel), the desired button lives on the message whose
                # id equals after_message_id.  Remember it as a fallback so we
                # can still match it if no strictly-newer message has the button.
                if message.message_id == after_message_id:
                    try:
                        match_button(message.buttons, request.get("match", {}))
                        fallback = raw_message
                    except ButtonMatchError as exc:
                        if str(exc) not in {"button match produced no candidates", "button position is out of range"}:
                            raise
                continue
            try:
                match_button(message.buttons, request.get("match", {}))
            except ButtonMatchError as exc:
                if str(exc) in {"button match produced no candidates", "button position is out of range"}:
                    continue
                raise
            return raw_message, message
        if fallback is not None:
            return fallback, self._normalize(fallback, target)
        raise WaitingForMessage(dict(request))

    async def click_button(self, account_id: str, request: Dict[str, Any]) -> ButtonResult:
        if not isinstance(request, dict):
            raise ValueError("click_button request must be a mapping")
        target = request.get("target")
        if target is None:
            raise ValueError("click_button requires target")
        handle = await self._handle(account_id)
        raw_message, message = await self._source_message(handle.client, target, request)
        button = match_button(message.buttons, request.get("match", {}))
        keyboard_mode = request.get("keyboard", request.get("mode", "auto"))
        if keyboard_mode not in {"auto", "inline", "reply"}:
            raise ValueError("keyboard mode must be auto, inline, or reply")
        if keyboard_mode != "auto" and button.kind != keyboard_mode:
            raise UnsupportedButtonError(
                "matched button kind %s does not match keyboard mode %s" % (button.kind, keyboard_mode)
            )
        try:
            if button.kind == "inline":
                click = getattr(raw_message, "click", None)
                if click is None:
                    raise TelegramError("Telegram message does not support inline button clicks")
                await _maybe_await(click(button.row, button.column))
                action_message_id = message.message_id
            elif button.kind == "reply":
                sent_raw = await _maybe_await(
                    handle.client.send_message(await self._resolve_peer(handle.client, target), button.label)
                )
                sent_message = self._normalize(sent_raw, target)
                action_message_id = sent_message.message_id
            else:
                raise UnsupportedButtonError("button kind %s cannot be activated safely" % button.kind)
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc
        return ButtonResult(
            message_id=message.message_id,
            label=button.label,
            kind=button.kind,
            callback_data=button.callback_data,
            before_message=message.to_dict(),
            action_message_id=action_message_id,
        )

    async def fetch_updates(self, account_id: str, cursor: Optional[str] = None) -> UpdateBatch:
        handle = await self._handle(account_id)
        fetcher = getattr(handle.client, "get_updates", None)
        if fetcher is None:
            # Telethon normally delivers updates through its event loop. The
            # durable Docker listener can inject a get_updates-compatible
            # source; a plain client has no safe history-wide polling API.
            return UpdateBatch((), cursor)
        try:
            raw_updates = await _maybe_await(fetcher(cursor))
        except TypeError:
            raw_updates = await _maybe_await(fetcher())
        except FloodWaitError as exc:
            raise TelegramFloodWaitError(exc.seconds) from exc
        updates: List[Dict[str, Any]] = []
        next_cursor = cursor
        for raw_update in raw_updates or []:
            raw_message = _read(raw_update, "message", default=None)
            if raw_message is not None:
                target = _read(raw_message, "peer_id", "chat_id", default="")
                normalized = self._normalize(raw_message, target)
                payload = {"type": "message", "message": normalized.to_dict()}
            elif isinstance(raw_update, Mapping):
                payload = dict(raw_update)
            else:
                payload = {"type": type(raw_update).__name__}
            updates.append(payload)
            update_id = _read(raw_update, "update_id", "id", default=None)
            if update_id is not None:
                next_cursor = str(int(update_id) + 1)
        return UpdateBatch(tuple(updates), next_cursor)
