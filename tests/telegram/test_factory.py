import pytest

from tg_ifttt.runtime.fake import FakeTelegramAdapter
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.factory import AdapterFactory, AdapterFactoryError
from tg_ifttt.telegram.user_adapter import UserTelegramAdapter


def test_fake_adapter_remains_available_for_offline_runs():
    adapter = AdapterFactory.from_config({"adapter": "fake"})
    assert isinstance(adapter, FakeTelegramAdapter)


def test_unknown_adapter_has_actionable_error():
    with pytest.raises(AdapterFactoryError, match="unsupported adapter"):
        AdapterFactory.from_config({"adapter": "unknown"})


def test_bot_api_requires_token():
    with pytest.raises(AdapterFactoryError, match="BOT_TOKEN"):
        AdapterFactory.from_config({"adapter": "bot_api"})


def test_mtproto_allows_plaintext_sessions_without_master_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TG_IFTTT_MASTER_KEY", raising=False)
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()

    adapter = AdapterFactory.from_config(
        {"adapter": "mtproto", "api_id": 123456, "api_hash": "api-hash"},
        database=database,
    )

    assert isinstance(adapter, UserTelegramAdapter)
    assert adapter.session_manager.account_repository.session_storage == "plaintext"
    database.close()
