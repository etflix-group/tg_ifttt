import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from tg_ifttt.telegram.models import StoredAccount, TelegramAccount

from .crypto import SecretBox, SecretBoxError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_phone(phone: str) -> str:
    if len(phone) <= 5:
        return "*" * len(phone)
    return phone[:3] + "***" + phone[-2:]


class AccountRepository:
    def __init__(self, connection: sqlite3.Connection, secret_box: Optional[SecretBox] = None) -> None:
        self._connection = connection
        self._secret_box = secret_box

    @property
    def session_storage(self) -> str:
        return "encrypted" if self._secret_box is not None else "plaintext"

    def save_account(self, account: TelegramAccount, session: str) -> None:
        if not isinstance(session, str) or not session:
            raise ValueError("session must be a non-empty string")
        if not account.account_id.strip():
            raise ValueError("account_id must not be empty")
        timestamp = _now()
        session_bytes = session.encode("utf-8")
        stored_session = (
            self._secret_box.encrypt(session_bytes) if self._secret_box is not None else session_bytes
        )
        phone = _mask_phone(account.phone) if account.phone else None
        self._connection.execute(
            """
            INSERT INTO telegram_accounts (
                account_id, display_name, user_id, phone_masked,
                session_ciphertext, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                display_name = excluded.display_name,
                user_id = excluded.user_id,
                phone_masked = excluded.phone_masked,
                session_ciphertext = excluded.session_ciphertext,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                account.account_id,
                account.display_name,
                account.user_id,
                phone,
                stored_session,
                account.status,
                timestamp,
                timestamp,
            ),
        )
        self._connection.commit()

    def load_account(self, account_id: str) -> StoredAccount:
        row = self._connection.execute(
            """
            SELECT account_id, display_name, user_id, phone_masked, session_ciphertext, status
            FROM telegram_accounts WHERE account_id = ?
            """,
            (account_id,),
        ).fetchone()
        if row is None:
            raise KeyError("unknown Telegram account: %s" % account_id)
        stored_session = bytes(row[4])
        if SecretBox.is_encrypted(stored_session):
            if self._secret_box is None:
                raise SecretBoxError(
                    "stored session is encrypted; configure TG_IFTTT_MASTER_KEY to read it"
                )
            session_bytes = self._secret_box.decrypt(stored_session)
        else:
            session_bytes = stored_session
        session = session_bytes.decode("utf-8")
        return StoredAccount(
            account=TelegramAccount(row[0], row[1], row[2], row[3], row[5]),
            session=session,
        )

    def list_accounts(self) -> List[TelegramAccount]:
        rows = self._connection.execute(
            """
            SELECT account_id, display_name, user_id, phone_masked, status
            FROM telegram_accounts ORDER BY account_id
            """
        ).fetchall()
        return [TelegramAccount(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def update_status(self, account_id: str, status: str) -> None:
        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be a non-empty string")
        cursor = self._connection.execute(
            "UPDATE telegram_accounts SET status = ?, updated_at = ? WHERE account_id = ?",
            (status, _now(), account_id),
        )
        if cursor.rowcount != 1:
            raise KeyError("unknown Telegram account: %s" % account_id)
        self._connection.commit()

    def delete_account(self, account_id: str) -> None:
        self._connection.execute(
            "DELETE FROM telegram_accounts WHERE account_id = ?",
            (account_id,),
        )
        self._connection.commit()
