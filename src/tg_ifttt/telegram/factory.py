"""Configuration-driven adapter construction for Docker and Qinglong."""

import base64
import binascii
import os
from typing import Any, Mapping, Optional

from tg_ifttt.runtime.fake import FakeTelegramAdapter
from tg_ifttt.storage.database import Database
from tg_ifttt.storage.account_repository import AccountRepository
from tg_ifttt.storage.crypto import SecretBox

from .bot_adapter import BotApiAdapter
from .models import AppCredentials
from .session_manager import SessionManager
from .user_adapter import UserTelegramAdapter


class AdapterFactoryError(ValueError):
    """Raised when an adapter cannot be built from deployment configuration."""


def _nested_or_root(config: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if key in config:
        return config[key]
    nested = config.get("telegram")
    if isinstance(nested, Mapping) and key in nested:
        return nested[key]
    return default


def _secret_key(config: Mapping[str, Any]) -> Optional[bytes]:
    configured = _nested_or_root(config, "master_key")
    value = configured if configured is not None else os.environ.get("TG_IFTTT_MASTER_KEY")
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterFactoryError("master key must be a string")
    value = value.strip()
    if not value:
        return None
    if len(value) == 64:
        try:
            decoded = bytes.fromhex(value)
        except ValueError:
            decoded = b""
        if len(decoded) == 32:
            return decoded
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        decoded = b""
    if len(decoded) == 32:
        return decoded
    raw = value.encode("utf-8")
    if len(raw) == 32:
        return raw
    raise AdapterFactoryError("master key must decode to exactly 32 bytes")


def _secret_box(config: Mapping[str, Any]) -> Optional[SecretBox]:
    key = _secret_key(config)
    return None if key is None else SecretBox(key)


class AdapterFactory:
    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        database: Optional[Database] = None,
    ) -> Any:
        if not isinstance(config, Mapping):
            raise AdapterFactoryError("adapter config must be a mapping")
        adapter_name = _nested_or_root(config, "adapter", "fake")
        if adapter_name == "fake":
            return FakeTelegramAdapter.from_settings(dict(config))
        if adapter_name == "bot_api":
            token = _nested_or_root(config, "bot_token") or os.environ.get("TG_IFTTT_BOT_TOKEN")
            if not isinstance(token, str) or not token.strip():
                raise AdapterFactoryError("bot_api adapter requires TG_IFTTT_BOT_TOKEN or bot_token")
            return BotApiAdapter(token)
        if adapter_name != "mtproto":
            raise AdapterFactoryError("unsupported adapter: %s" % adapter_name)
        if database is None:
            raise AdapterFactoryError("mtproto adapter requires an initialized database")
        raw_api_id = _nested_or_root(config, "api_id") or os.environ.get("TG_IFTTT_API_ID")
        api_hash = _nested_or_root(config, "api_hash") or os.environ.get("TG_IFTTT_API_HASH")
        try:
            api_id = int(raw_api_id)
        except (TypeError, ValueError) as exc:
            raise AdapterFactoryError("mtproto adapter requires a positive api_id") from exc
        if not isinstance(api_hash, str) or not api_hash.strip():
            raise AdapterFactoryError("mtproto adapter requires TG_IFTTT_API_HASH or api_hash")
        repository = AccountRepository(database.connection, _secret_box(config))
        manager = SessionManager(AppCredentials(api_id, api_hash), repository)
        return UserTelegramAdapter(manager)
