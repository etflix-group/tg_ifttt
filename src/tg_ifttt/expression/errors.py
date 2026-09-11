class ExpressionError(ValueError):
    """Base error for expression parsing and evaluation."""


class UnsafeExpressionError(ExpressionError):
    """Raised when an expression uses syntax outside the allowlist."""
