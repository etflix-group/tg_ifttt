"""Small asynchronous Telegram Bot API adapter with no HTTP dependency."""

import asyncio
import inspect
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

from tg_ifttt.runtime.adapters import (
    ButtonResult,
    MessageSnapshot,
    TelegramAdapter,
    WaitingForMessage,
    matches_action_barrier,
)

from .errors import BotApiError, UnsupportedButtonError
from .models import UpdateBatch
from .normalize import normalize_message


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: Any


def _as_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _response_parts(response: Any) -> Tuple[int, Any]:
    if isinstance(response, HttpResponse):
        return response.status_code, response.body
    if isinstance(response, tuple) and len(response) == 2 and isinstance(response[0], int):
        return int(response[0]), response[1]
    if isinstance(response, Mapping):
        return 200, response
    status = getattr(response, "status_code", getattr(response, "status", 200))
    body = getattr(response, "body", None)
    if body is None:
        json_method = getattr(response, "json", None)
        if json_method is not None:
            body = json_method()
        else:
            body = response
    return int(status), body


def _update_message(update: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for field in ("message", "edited_message", "channel_post", "edited_channel_post"):
        value = update.get(field)
        if isinstance(value, Mapping):
            return value
    callback = update.get("callback_query")
    if isinstance(callback, Mapping) and isinstance(callback.get("message"), Mapping):
        return callback["message"]
    return None


class BotApiAdapter(TelegramAdapter):
    """Bot API operations; it cannot impersonate a user to click a keyboard."""

    def __init__(
        self,
        token: str,
        http_call: Optional[Callable[..., Awaitable[Any]]] = None,
        timeout: float = 20.0,
    ) -> None:
        if not isinstance(token, str) or ":" not in token or not token.strip():
            raise ValueError("Bot Token must be a non-empty Telegram token")
        if timeout <= 0:
            raise ValueError("HTTP timeout must be positive")
        self._token = token.strip()
        self._http_call = http_call
        self._timeout = timeout
        self._inbox: Deque[MessageSnapshot] = deque()
        self._next_offset: Optional[int] = None
        self._listener_active = False

    @property
    def base_url(self) -> str:
        return "https://api.telegram.org/bot" + quote(self._token, safe=":")

    async def _default_http_call(self, url: str, payload: Dict[str, Any]) -> HttpResponse:
        def request() -> HttpResponse:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_object = Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request_object, timeout=self._timeout) as response:
                return HttpResponse(int(response.status), response.read())

        return await asyncio.to_thread(request)

    async def _call(self, method: str, payload: Dict[str, Any]) -> Any:
        url = self.base_url + "/" + method
        if self._http_call is None:
            response = await self._default_http_call(url, payload)
        else:
            # The public injection contract is http_call(url, payload). A
            # keyword-json fallback keeps simple test transports convenient.
            try:
                response = await _maybe_await(self._http_call(url, payload))
            except TypeError as first_error:
                try:
                    response = await _maybe_await(self._http_call(url, json=payload))
                except TypeError:
                    raise first_error
        status_code, body = _response_parts(response)
        body = await _maybe_await(body)
        try:
            document = _as_json(body)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BotApiError(status_code, "Telegram returned invalid JSON") from exc
        if not isinstance(document, Mapping) or not document.get("ok", False):
            error_code = document.get("error_code", status_code) if isinstance(document, Mapping) else status_code
            description = document.get("description", "request failed") if isinstance(document, Mapping) else "request failed"
            parameters = document.get("parameters", {}) if isinstance(document, Mapping) else {}
            retry_after = parameters.get("retry_after", 0) if isinstance(parameters, Mapping) else 0
            raise BotApiError(int(error_code), str(description), int(retry_after or 0))
        return document.get("result")

    @staticmethod
    def _message_from_result(result: Any, target: Any) -> MessageSnapshot:
        if not isinstance(result, Mapping):
            raise BotApiError(502, "Telegram returned an invalid message")
        chat = result.get("chat")
        peer_id = chat.get("id") if isinstance(chat, Mapping) else target
        sender = result.get("from")
        sender_id = sender.get("id") if isinstance(sender, Mapping) else None
        return normalize_message(result, peer_id=str(peer_id), sender_id=None if sender_id is None else str(sender_id))

    async def send_message(self, account_id: str, target: str, text: str) -> MessageSnapshot:
        result = await self._call("sendMessage", {"chat_id": target, "text": text})
        return self._message_from_result(result, target)

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 0) -> UpdateBatch:
        if offset is not None and (not isinstance(offset, int) or isinstance(offset, bool)):
            raise ValueError("update offset must be an integer or null")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0 or timeout > 50:
            raise ValueError("update timeout must be an integer from 0 to 50")
        if offset is None:
            offset = self._next_offset
        payload: Dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "edited_message", "channel_post", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise BotApiError(502, "Telegram returned an invalid update list")

        updates: List[Dict[str, Any]] = []
        next_offset = offset
        for raw_update in result:
            if not isinstance(raw_update, Mapping):
                continue
            update = dict(raw_update)
            message = _update_message(update)
            if message is not None:
                chat = message.get("chat")
                peer_id = chat.get("id") if isinstance(chat, Mapping) else ""
                sender = message.get("from")
                sender_id = sender.get("id") if isinstance(sender, Mapping) else None
                normalized = normalize_message(
                    message,
                    peer_id=str(peer_id),
                    sender_id=None if sender_id is None else str(sender_id),
                )
                update["message"] = normalized.to_dict()
                update["normalized_type"] = "message"
                self._inbox.append(normalized)
            updates.append(update)
            update_id = raw_update.get("update_id")
            if update_id is not None:
                next_offset = int(update_id) + 1
        self._next_offset = next_offset
        return UpdateBatch(tuple(updates), None if next_offset is None else str(next_offset))

    async def listen(self, callback: Callable[[str, Mapping[str, Any]], Any], stop_event: Any, account_ids=None) -> None:
        self._listener_active = True
        listeners = list(account_ids or ("default",))
        try:
            while not stop_event.is_set():
                batch = await self.get_updates(timeout=50)
                for update in batch.updates:
                    for account_id in listeners:
                        await _maybe_await(callback(account_id, update))
        finally:
            self._listener_active = False

    async def wait_message(self, account_id: str, request: Dict[str, Any]) -> MessageSnapshot:
        if not isinstance(request, dict):
            raise ValueError("wait_message request must be a mapping")
        def take_matching() -> Optional[MessageSnapshot]:
            target = request.get("target")
            sender = request.get("sender", request.get("sender_id"))
            for message in list(self._inbox):
                if request.get("action_barrier"):
                    if not matches_action_barrier(message, request):
                        continue
                else:
                    if target is not None and str(target) != str(message.peer_id):
                        continue
                    if sender is not None and str(sender) != str(message.sender_id):
                        continue
                    exact_id = request.get("message_id")
                    if exact_id is not None and message.message_id != int(exact_id):
                        continue
                    after_message_id = request.get("after_message_id")
                    if after_message_id is not None and message.message_id <= int(after_message_id):
                        continue
                self._inbox.remove(message)
                return message
            return None

        message = take_matching()
        if message is not None:
            return message
        if self._listener_active:
            raise WaitingForMessage(dict(request))
        await self.get_updates(timeout=0)
        message = take_matching()
        if message is not None:
            return message
        await self.get_updates(timeout=0)
        message = take_matching()
        if message is not None:
            return message
        raise WaitingForMessage(dict(request))

    async def answer_callback(self, callback_id: str, text: Optional[str] = None) -> None:
        if not isinstance(callback_id, str) or not callback_id:
            raise ValueError("callback query id must not be empty")
        payload: Dict[str, Any] = {"callback_query_id": callback_id}
        if text is not None:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def click_button(self, account_id: str, request: Dict[str, Any]) -> ButtonResult:
        raise UnsupportedButtonError(
            "Bot API tokens cannot click Telegram keyboards as a user; use an ordinary MTProto account"
        )
