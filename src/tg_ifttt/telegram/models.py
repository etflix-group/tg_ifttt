from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class AppCredentials:
    api_id: int
    api_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.api_id, int) or isinstance(self.api_id, bool) or self.api_id <= 0:
            raise ValueError("api_id must be a positive integer")
        if not isinstance(self.api_hash, str) or not self.api_hash.strip():
            raise ValueError("api_hash must be a non-empty string")


@dataclass(frozen=True)
class TelegramAccount:
    account_id: str
    display_name: str
    user_id: Optional[int]
    phone: Optional[str]
    status: str


@dataclass(frozen=True)
class StoredAccount:
    account: TelegramAccount
    session: str


@dataclass(frozen=True)
class UpdateBatch:
    updates: Tuple[Dict[str, Any], ...]
    next_cursor: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "updates": [dict(update) for update in self.updates],
            "next_cursor": self.next_cursor,
        }
