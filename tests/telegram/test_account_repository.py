from tg_ifttt.storage.crypto import SecretBox
from tg_ifttt.storage.database import Database
from tg_ifttt.storage.account_repository import AccountRepository
from tg_ifttt.telegram.models import TelegramAccount


def test_account_session_is_stored_encrypted_and_loaded(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    repository = AccountRepository(database.connection, SecretBox(b"x" * 32))
    account = TelegramAccount("account-a", "A", 1001, "+8613800000000", "ready")

    repository.save_account(account, "session-value")
    loaded = repository.load_account("account-a")

    assert loaded.account.account_id == "account-a"
    assert loaded.account.user_id == 1001
    assert loaded.session == "session-value"
    raw = database.connection.execute(
        "SELECT session_ciphertext FROM telegram_accounts WHERE account_id = ?",
        ("account-a",),
    ).fetchone()[0]
    assert "session-value" not in raw.decode("utf-8", errors="ignore")
    database.close()


def test_list_accounts_hides_session_data(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    repository = AccountRepository(database.connection, SecretBox(b"x" * 32))
    repository.save_account(
        TelegramAccount("account-a", "A", 1001, "+8613800000000", "ready"),
        "session-value",
    )

    summaries = repository.list_accounts()

    assert [item.account_id for item in summaries] == ["account-a"]
    assert not hasattr(summaries[0], "session")
    database.close()


def test_account_session_can_be_stored_plaintext_without_secret_box(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    repository = AccountRepository(database.connection, None)
    account = TelegramAccount("account-plain", "Plain", 1002, "+8613800000001", "ready")

    repository.save_account(account, "session-value")

    assert repository.load_account("account-plain").session == "session-value"
    raw = database.connection.execute(
        "SELECT session_ciphertext FROM telegram_accounts WHERE account_id = ?",
        ("account-plain",),
    ).fetchone()[0]
    assert raw == b"session-value"
    assert repository.session_storage == "plaintext"
    database.close()
