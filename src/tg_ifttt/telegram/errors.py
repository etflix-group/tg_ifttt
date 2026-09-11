"""Typed errors raised at the Telegram integration boundary."""


class TelegramError(RuntimeError):
    """Base error for Telegram connectivity and authorization failures."""


class LoginError(TelegramError):
    """A login flow cannot continue."""


class LoginExpiredError(LoginError):
    """A QR token or one-time login challenge has expired."""


class InvalidSessionError(TelegramError):
    """A stored session is no longer authorized by Telegram."""


class UnsupportedButtonError(TelegramError):
    """The selected button cannot be activated by the current adapter."""


class TelegramFloodWaitError(TelegramError):
    """Telegram requested that the caller wait before retrying."""

    def __init__(self, seconds: int) -> None:
        self.seconds = max(0, int(seconds))
        super().__init__("Telegram requested a flood wait of %d seconds" % self.seconds)


class BotApiError(TelegramError):
    """A Telegram Bot API request returned an error response."""

    def __init__(
        self,
        error_code: int,
        description: str,
        retry_after: int = 0,
    ) -> None:
        self.error_code = int(error_code)
        self.description = str(description)
        self.retry_after = max(0, int(retry_after or 0))
        # Never include the request URL because it contains the Bot Token.
        super().__init__("Bot API error %d: %s" % (self.error_code, self.description))
