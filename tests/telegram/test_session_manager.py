import asyncio
from types import SimpleNamespace

import pytest
from telethon.errors import SessionPasswordNeededError

from tg_ifttt.storage.account_repository import AccountRepository
from tg_ifttt.storage.crypto import SecretBox
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.errors import InvalidSessionError
from tg_ifttt.telegram.models import AppCredentials, TelegramAccount
from tg_ifttt.telegram.session_manager import SessionManager


class FakeQrLogin:
    def __init__(self, url="tg://login?token=test"):
        self.url = url
        self.expires = None
        self.result = None

    async def wait(self):
        if self.result is None:
            await asyncio.Future()
        return self.result


class FakeSession:
    def __init__(self, value="session-value"):
        self.value = value

    def save(self):
        return self.value


class FakeClient:
    def __init__(self, qr=None, authorized=True):
        self.qr = qr or FakeQrLogin()
        self.authorized = authorized
        self.connected = False
        self.disconnected = False
        self.session = FakeSession()
        self.password_required = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True
        self.connected = False

    async def qr_login(self):
        return self.qr

    async def send_code_request(self, phone):
        self.phone = phone
        return SimpleNamespace(phone_code_hash="hash-1")

    async def sign_in(self, phone=None, code=None, *, phone_code_hash=None, password=None):
        if password is not None:
            return SimpleNamespace(id=1001, phone=self.phone)
        if self.password_required:
            raise SessionPasswordNeededError(None)
        return SimpleNamespace(id=1001, phone=self.phone)

    async def is_user_authorized(self):
        return self.authorized


@pytest.fixture
def account_repository(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    repository = AccountRepository(database.connection, SecretBox(b"x" * 32))
    yield repository
    database.close()


def test_qr_login_saves_session_after_scan(account_repository):
    fake_qr = FakeQrLogin()
    fake_client = FakeClient(qr=fake_qr)
    manager = SessionManager(
        AppCredentials(123, "hash"),
        account_repository,
        client_factory=lambda *args: fake_client,
    )

    state = asyncio.run(manager.begin_qr_login("account-a", "A"))
    assert state.url == "tg://login?token=test"
    fake_qr.result = SimpleNamespace(id=1001, phone="+8613800000000")
    completed = asyncio.run(manager.poll_qr_login(state.login_id))

    assert completed.status == "ready"
    assert account_repository.load_account("account-a").account.user_id == 1001
    assert fake_client.disconnected is True


def test_phone_login_transitions_to_2fa_without_storing_password(account_repository):
    fake_client = FakeClient()
    fake_client.password_required = True
    manager = SessionManager(
        AppCredentials(123, "hash"),
        account_repository,
        client_factory=lambda *args: fake_client,
    )

    state = asyncio.run(manager.begin_phone_login("account-a", "+8613800000000"))
    assert state.status == "code_required"
    password_state = asyncio.run(manager.submit_phone_code(state.login_id, "12345"))
    assert password_state.status == "password_required"
    completed = asyncio.run(manager.submit_two_factor(state.login_id, "secret-password"))

    assert completed.status == "ready"
    assert account_repository.load_account("account-a").account.phone == "+86***00"


def test_connect_account_rejects_unauthorized_session(account_repository):
    account_repository.save_account(
        TelegramAccount("account-a", "A", 1001, "+8613800000000", "ready"),
        "session-value",
    )
    fake_client = FakeClient(authorized=False)
    manager = SessionManager(
        AppCredentials(123, "hash"),
        account_repository,
        client_factory=lambda *args: fake_client,
    )

    with pytest.raises(InvalidSessionError):
        asyncio.run(manager.connect_account("account-a"))
    assert account_repository.load_account("account-a").account.status == "invalid"
    assert fake_client.disconnected is True
