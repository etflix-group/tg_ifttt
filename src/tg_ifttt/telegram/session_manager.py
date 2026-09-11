"""Durable ordinary-account authorization built around Telethon StringSession."""

import asyncio
import inspect
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Union

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    SessionExpiredError,
    SessionRevokedError,
    UserDeactivatedBanError,
    UserDeactivatedError,
)
from telethon.sessions import StringSession

from tg_ifttt.storage.account_repository import AccountRepository

from .errors import InvalidSessionError, LoginError, TelegramFloodWaitError
from .models import AppCredentials, TelegramAccount


@dataclass(frozen=True)
class LoginState:
    login_id: str
    account_id: str
    status: str
    method: str
    url: Optional[str] = None
    expires_at: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    attempts_remaining: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "login_id": self.login_id,
            "account_id": self.account_id,
            "status": self.status,
            "method": self.method,
            "url": self.url,
            "expires_at": self.expires_at,
            "phone": self.phone,
            "message": self.message,
            "attempts_remaining": self.attempts_remaining,
        }


class QRLoginState(LoginState):
    pass


class PhoneLoginState(LoginState):
    pass


class TelegramClientHandle:
    """A connected client scoped to one ordinary Telegram account."""

    def __init__(self, account_id: str, client: Any) -> None:
        self.account_id = account_id
        self.client = client

    async def disconnect(self) -> None:
        await _maybe_await(self.client.disconnect())


@dataclass
class _PendingLogin:
    login_id: str
    account_id: str
    display_name: str
    method: str
    client: Any
    phone: Optional[str] = None
    phone_code_hash: Optional[str] = None
    qr: Any = None
    state: LoginState = None  # type: ignore[assignment]
    qr_task: Optional[asyncio.Task] = None
    attempts_remaining: int = 3


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _user_value(user: Any, name: str, default: Any = None) -> Any:
    if isinstance(user, dict):
        return user.get(name, default)
    return getattr(user, name, default)


def _exception_name(error: BaseException) -> str:
    return type(error).__name__


class SessionManager:
    """Owns temporary login clients and cached authenticated clients.

    The default factory is production Telethon. Tests can inject a fake factory
    with the same three positional arguments: ``session, api_id, api_hash``.
    """

    def __init__(
        self,
        credentials: AppCredentials,
        account_repository: AccountRepository,
        client_factory: Optional[Callable[[Any, int, str], Any]] = None,
        max_pending_logins: int = 16,
        max_attempts: int = 3,
    ) -> None:
        if max_pending_logins < 1:
            raise ValueError("max_pending_logins must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.credentials = credentials
        self.account_repository = account_repository
        self._client_factory = client_factory or self._default_client_factory
        self._max_pending_logins = max_pending_logins
        self._max_attempts = max_attempts
        self._pending: Dict[str, _PendingLogin] = {}
        self._connected: Dict[str, TelegramClientHandle] = {}

    @staticmethod
    def _default_client_factory(session: Any, api_id: int, api_hash: str) -> TelegramClient:
        return TelegramClient(
            StringSession(session),
            api_id,
            api_hash,
            device_model="tg-ifttt",
            app_version="0.1.0",
        )

    def _new_client(self, session: str = "") -> Any:
        return self._client_factory(session, self.credentials.api_id, self.credentials.api_hash)

    async def _connect(self, client: Any) -> None:
        await _maybe_await(client.connect())

    async def _disconnect_client(self, client: Any) -> None:
        disconnect = getattr(client, "disconnect", None)
        if disconnect is not None:
            await _maybe_await(disconnect())

    async def _enforce_pending_limit(self) -> None:
        while len(self._pending) >= self._max_pending_logins:
            oldest = next(iter(self._pending.values()))
            self._pending.pop(oldest.login_id, None)
            if oldest.qr_task is not None and not oldest.qr_task.done():
                oldest.qr_task.cancel()
            await self._disconnect_client(oldest.client)

    def _initial_state(
        self,
        login_id: str,
        account_id: str,
        method: str,
        status: str,
        **kwargs: Any,
    ) -> LoginState:
        state_type = QRLoginState if method == "qr" else PhoneLoginState
        attempts_remaining = kwargs.pop("attempts_remaining", self._max_attempts)
        return state_type(
            login_id=login_id,
            account_id=account_id,
            status=status,
            method=method,
            attempts_remaining=attempts_remaining,
            **kwargs,
        )

    def _replace_state(self, pending: _PendingLogin, status: str, **kwargs: Any) -> LoginState:
        state = self._initial_state(
            pending.login_id,
            pending.account_id,
            pending.method,
            status,
            phone=pending.phone,
            attempts_remaining=pending.attempts_remaining,
            **kwargs,
        )
        pending.state = state
        return state

    async def begin_qr_login(self, account_id: str, display_name: str) -> QRLoginState:
        await self._enforce_pending_limit()
        login_id = uuid.uuid4().hex
        client = self._new_client("")
        try:
            await self._connect(client)
            qr = await _maybe_await(client.qr_login())
        except Exception:
            await self._disconnect_client(client)
            raise

        pending = _PendingLogin(
            login_id=login_id,
            account_id=account_id,
            display_name=display_name,
            method="qr",
            client=client,
            qr=qr,
            attempts_remaining=self._max_attempts,
        )
        pending.state = self._initial_state(
            login_id,
            account_id,
            "qr",
            "pending_qr",
            url=str(qr.url),
            expires_at=_iso_datetime(getattr(qr, "expires", None)),
        )
        self._pending[login_id] = pending
        # Telethon requires qr.wait() to run while the user scans. The worker
        # keeps that wait alive between HTTP polls; a cancelled worker is retried
        # synchronously by poll_qr_login, which also makes CLI usage deterministic.
        pending.qr_task = asyncio.create_task(self._wait_for_qr(login_id))
        return pending.state  # type: ignore[return-value]

    async def _wait_for_qr(self, login_id: str) -> None:
        pending = self._pending.get(login_id)
        if pending is None:
            return
        try:
            user = await _maybe_await(pending.qr.wait())
            await self._complete_login(pending, user)
        except asyncio.CancelledError:
            raise
        except SessionPasswordNeededError:
            self._replace_state(pending, "password_required", message="Telegram 账号需要二次验证密码")
        except Exception as exc:
            self._replace_state(pending, self._login_failure_status(exc), message=self._safe_error_message(exc))

    async def _poll_cancelled_qr(self, pending: _PendingLogin) -> LoginState:
        try:
            user = await _maybe_await(pending.qr.wait())
            return await self._complete_login(pending, user)
        except SessionPasswordNeededError:
            return self._replace_state(pending, "password_required", message="Telegram 账号需要二次验证密码")
        except asyncio.TimeoutError:
            return self._replace_state(pending, "expired", message="二维码已过期")
        except Exception as exc:
            return self._replace_state(pending, self._login_failure_status(exc), message=self._safe_error_message(exc))

    async def poll_qr_login(self, login_id: str) -> QRLoginState:
        pending = self._get_pending(login_id, "qr")
        if pending.state.status == "expired":
            return await self.refresh_qr_login(login_id)
        if pending.state.status in {"ready", "failed", "password_required"}:
            return pending.state  # type: ignore[return-value]

        if pending.qr_task is None or pending.qr_task.cancelled():
            state = await self._poll_cancelled_qr(pending)
            return state  # type: ignore[return-value]
        if pending.qr_task.done():
            # Retrieving the result prevents an exception from becoming an
            # unobserved asyncio warning. The worker has already updated state.
            try:
                pending.qr_task.result()
            except asyncio.CancelledError:
                state = await self._poll_cancelled_qr(pending)
                return state  # type: ignore[return-value]
            except Exception as exc:
                self._replace_state(pending, self._login_failure_status(exc), message=self._safe_error_message(exc))
        if pending.state.status == "pending_qr":
            expires = getattr(pending.qr, "expires", None)
            if isinstance(expires, datetime) and _now() >= expires:
                self._replace_state(pending, "expired", message="二维码已过期")
                return await self.refresh_qr_login(login_id)
        return pending.state  # type: ignore[return-value]

    async def refresh_qr_login(self, login_id: str) -> QRLoginState:
        pending = self._get_pending(login_id, "qr")
        if pending.state.status in {"ready", "password_required"}:
            return pending.state  # type: ignore[return-value]
        try:
            await _maybe_await(pending.qr.recreate())
            pending.state = self._initial_state(
                pending.login_id,
                pending.account_id,
                "qr",
                "pending_qr",
                url=str(pending.qr.url),
                expires_at=_iso_datetime(getattr(pending.qr, "expires", None)),
                phone=pending.phone,
                attempts_remaining=pending.attempts_remaining,
            )
            pending.qr_task = asyncio.create_task(self._wait_for_qr(login_id))
        except Exception as exc:
            self._replace_state(pending, self._login_failure_status(exc), message=self._safe_error_message(exc))
        return pending.state  # type: ignore[return-value]

    async def begin_phone_login(self, account_id: str, phone: str) -> PhoneLoginState:
        if not isinstance(phone, str) or not phone.strip():
            raise ValueError("phone must be a non-empty string")
        await self._enforce_pending_limit()
        login_id = uuid.uuid4().hex
        client = self._new_client("")
        try:
            await self._connect(client)
            sent_code = await _maybe_await(client.send_code_request(phone.strip()))
        except Exception:
            await self._disconnect_client(client)
            raise

        phone_code_hash = getattr(sent_code, "phone_code_hash", None)
        if isinstance(sent_code, dict):
            phone_code_hash = sent_code.get("phone_code_hash", phone_code_hash)
        pending = _PendingLogin(
            login_id=login_id,
            account_id=account_id,
            display_name=account_id,
            method="phone",
            client=client,
            phone=phone.strip(),
            phone_code_hash=None if phone_code_hash is None else str(phone_code_hash),
            attempts_remaining=self._max_attempts,
        )
        pending.state = self._initial_state(
            login_id,
            account_id,
            "phone",
            "code_required",
            phone=phone.strip(),
        )
        self._pending[login_id] = pending
        return pending.state  # type: ignore[return-value]

    async def submit_phone_code(self, login_id: str, code: str) -> LoginState:
        pending = self._get_pending(login_id, "phone")
        if pending.state.status != "code_required":
            return pending.state
        if not isinstance(code, (str, int)) or not str(code).strip():
            raise ValueError("code must not be empty")
        try:
            user = await _maybe_await(
                pending.client.sign_in(
                    pending.phone,
                    str(code).strip(),
                    phone_code_hash=pending.phone_code_hash,
                )
            )
            return await self._complete_login(pending, user)
        except SessionPasswordNeededError:
            return self._replace_state(pending, "password_required", message="Telegram 账号需要二次验证密码")
        except Exception as exc:
            return self._handle_attempt_failure(pending, exc)

    async def submit_two_factor(self, login_id: str, password: str) -> LoginState:
        pending = self._get_pending(login_id)
        if pending.state.status != "password_required":
            return pending.state
        if not isinstance(password, str) or not password:
            raise ValueError("password must not be empty")
        try:
            user = await _maybe_await(pending.client.sign_in(password=password))
            return await self._complete_login(pending, user)
        except Exception as exc:
            return self._handle_attempt_failure(pending, exc)

    async def _complete_login(self, pending: _PendingLogin, user: Any) -> LoginState:
        session = self._session_string(pending.client)
        account = TelegramAccount(
            account_id=pending.account_id,
            display_name=self._display_name(pending.display_name, user),
            user_id=self._optional_int(_user_value(user, "id")),
            phone=self._optional_str(_user_value(user, "phone")) or pending.phone,
            status="ready",
        )
        self.account_repository.save_account(account, session)
        state = self._replace_state(pending, "ready")
        await self._disconnect_client(pending.client)
        return state

    def _session_string(self, client: Any) -> str:
        session = getattr(client, "session", None)
        save = getattr(session, "save", None)
        if save is not None:
            value = save()
        else:
            value = session
        if not isinstance(value, str) or not value:
            raise LoginError("Telegram client did not return a StringSession")
        return value

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _display_name(fallback: str, user: Any) -> str:
        first = _user_value(user, "first_name", "") or ""
        last = _user_value(user, "last_name", "") or ""
        username = _user_value(user, "username", "") or ""
        value = " ".join(str(part).strip() for part in (first, last) if str(part).strip())
        return value or ("@" + str(username) if username else fallback)

    def _handle_attempt_failure(self, pending: _PendingLogin, error: BaseException) -> LoginState:
        pending.attempts_remaining -= 1
        if pending.attempts_remaining <= 0:
            return self._replace_state(pending, "failed", message=self._safe_error_message(error))
        return self._replace_state(
            pending,
            "password_required" if pending.state.status == "password_required" else "code_required",
            message=self._safe_error_message(error),
        )

    @staticmethod
    def _safe_error_message(error: BaseException) -> str:
        # Telegram RPC messages may contain account metadata. Keep the public
        # state short and never echo credentials or submitted codes/passwords.
        name = _exception_name(error)
        if isinstance(error, PhoneCodeInvalidError):
            return "验证码无效"
        if isinstance(error, PhoneCodeExpiredError):
            return "验证码已过期"
        if isinstance(error, PhoneCodeEmptyError):
            return "验证码不能为空"
        return name

    @staticmethod
    def _login_failure_status(error: BaseException) -> str:
        if isinstance(error, asyncio.TimeoutError) or "Expired" in _exception_name(error):
            return "expired"
        return "failed"

    def _get_pending(self, login_id: str, method: Optional[str] = None) -> _PendingLogin:
        pending = self._pending.get(login_id)
        if pending is None:
            raise KeyError("unknown login id: %s" % login_id)
        if method is not None and pending.method != method:
            raise ValueError("login id belongs to a %s login" % pending.method)
        return pending

    async def disconnect_login(self, login_id: str) -> None:
        pending = self._pending.pop(login_id, None)
        if pending is None:
            return
        if pending.qr_task is not None and not pending.qr_task.done():
            pending.qr_task.cancel()
        await self._disconnect_client(pending.client)

    async def connect_account(self, account_id: str) -> TelegramClientHandle:
        existing = self._connected.get(account_id)
        if existing is not None:
            return existing
        stored = self.account_repository.load_account(account_id)
        client = self._new_client(stored.session)
        try:
            await self._connect(client)
            authorized = await _maybe_await(client.is_user_authorized())
            if not authorized:
                raise InvalidSessionError("Telegram session is not authorized")
        except (
            AuthKeyUnregisteredError,
            SessionExpiredError,
            SessionRevokedError,
            UserDeactivatedError,
            UserDeactivatedBanError,
            InvalidSessionError,
        ) as exc:
            self.account_repository.update_status(account_id, "invalid")
            await self._disconnect_client(client)
            raise InvalidSessionError("Telegram session is invalid") from exc
        except Exception:
            await self._disconnect_client(client)
            raise
        handle = TelegramClientHandle(account_id, client)
        self._connected[account_id] = handle
        return handle

    async def disconnect_account(self, account_id: str) -> None:
        handle = self._connected.pop(account_id, None)
        if handle is not None:
            await handle.disconnect()

    async def revoke_account(self, account_id: str) -> None:
        await self.disconnect_account(account_id)
        self.account_repository.delete_account(account_id)
