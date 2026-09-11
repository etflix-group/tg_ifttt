from .models import AppCredentials, StoredAccount, TelegramAccount, UpdateBatch

__all__ = [
    "AppCredentials",
    "BotApiAdapter",
    "BotApiError",
    "AdapterFactory",
    "AdapterFactoryError",
    "StoredAccount",
    "TelegramAccount",
    "UpdateBatch",
    "InvalidSessionError",
    "LoginError",
    "LoginState",
    "PhoneLoginState",
    "QRLoginState",
    "SessionManager",
    "TelegramError",
    "TelegramFloodWaitError",
    "UnsupportedButtonError",
    "UserTelegramAdapter",
]


def __getattr__(name):
    """Load connector classes lazily to keep storage imports acyclic."""

    if name in {
        "BotApiError",
        "InvalidSessionError",
        "LoginError",
        "TelegramError",
        "TelegramFloodWaitError",
        "UnsupportedButtonError",
    }:
        from . import errors

        return getattr(errors, name)
    if name in {"LoginState", "PhoneLoginState", "QRLoginState", "SessionManager"}:
        from . import session_manager

        return getattr(session_manager, name)
    if name == "UserTelegramAdapter":
        from .user_adapter import UserTelegramAdapter

        return UserTelegramAdapter
    if name == "BotApiAdapter":
        from .bot_adapter import BotApiAdapter

        return BotApiAdapter
    if name in {"AdapterFactory", "AdapterFactoryError"}:
        from .factory import AdapterFactory, AdapterFactoryError

        return AdapterFactory if name == "AdapterFactory" else AdapterFactoryError
    raise AttributeError(name)
