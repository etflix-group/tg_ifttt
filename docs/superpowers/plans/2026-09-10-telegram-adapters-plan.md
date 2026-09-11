# Telegram Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use checkbox syntax for tracking.

**Goal:** Add production Telegram connectors for ordinary user accounts and Bot API while preserving the existing workflow runtime interface and keeping all automated tests offline.

**Architecture:** Store one deployment-level API ID/API Hash and one encrypted session per ordinary account. Build a session manager around Telethon StringSession, expose QR and phone-code login as explicit stateful operations, and translate Telegram messages/buttons into the existing normalized snapshots. Use a small async Bot API client based on standard-library HTTP so Bot Token flows do not require another HTTP dependency.

**Tech Stack:** Python 3.9+, Telethon 1.x, asyncio, urllib, existing sqlite3/cryptography/pytest stack.

## Global Constraints

- Preserve the approved design and the core connector interfaces.
- Use the owner’s own API ID/API Hash; never ship a public sample credential.
- The same API ID/API Hash may be used for multiple ordinary accounts, but every account has its own encrypted session and entity cache.
- Never log API Hash, Bot Token, session strings, phone codes, or 2FA passwords.
- Do not connect to Telegram during automated tests; use fake Telethon clients and mocked HTTP responses.
- Ordinary-account login must support QR first and phone-code plus 2FA fallback.
- Inline buttons must use callback interaction; Reply Keyboard buttons must send their label as a normal message.
- Keep account-specific peer resolution inside the account adapter.
- Respect Telegram rate limits and return typed errors for flood waits, invalid sessions, and unauthorized actions.
- Keep all new code Python 3.9-compatible.
- Do not add a browser automation dependency.

---

## Task 1: Add Telegram dependencies and account persistence

**Files:**
- Modify: pyproject.toml
- Create: src/tg_ifttt/telegram/__init__.py
- Create: src/tg_ifttt/telegram/models.py
- Create: src/tg_ifttt/storage/account_repository.py
- Modify: src/tg_ifttt/storage/database.py
- Create: tests/telegram/test_account_repository.py

**Interfaces:**
- AppCredentials(api_id: int, api_hash: str)
- TelegramAccount(account_id: str, display_name: str, user_id: Optional[int], phone: Optional[str], status: str)
- AccountRepository.save_account(account, encrypted_session: bytes) -> None
- AccountRepository.load_account(account_id) -> StoredAccount
- AccountRepository.list_accounts() -> List[StoredAccount]
- AccountRepository.delete_account(account_id) -> None

- [x] Step 1: Add a failing account repository test

~~~python
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
~~~

- [x] Step 2: Run the test to verify it fails

Run:

~~~bash
python3 -m pytest tests/telegram/test_account_repository.py -q
~~~

Expected: FAIL because the Telegram package, table, and repository do not exist.

- [x] Step 3: Add Telethon as a runtime dependency

Add a bounded Telethon 1.x dependency to pyproject.toml and keep the existing Python 3.9 floor. Do not add an HTTP client dependency for Bot API.

- [x] Step 4: Add account tables and encrypted repository

Create a telegram_accounts table with account ID, display name, user ID, masked phone, encrypted session, status, created/updated timestamps. Encrypt session strings with the existing SecretBox before writing. Return only masked phone and status from ordinary listing methods; expose the decrypted session only to the connector process.

- [x] Step 5: Run the account repository tests

Run:

~~~bash
python3 -m pytest tests/telegram/test_account_repository.py -q
~~~

Expected: PASS and no plaintext session in SQLite.

---

## Task 2: Extend normalized button/message snapshots

**Files:**
- Modify: src/tg_ifttt/runtime/adapters.py
- Create: src/tg_ifttt/telegram/normalize.py
- Modify: tests/runtime/test_fake_adapter.py
- Create: tests/telegram/test_normalize.py

**Interfaces:**
- ButtonSnapshot(..., row: int = 0, column: int = 0)
- normalize_message(raw_message, peer_id: str, sender_id: Optional[str]) -> MessageSnapshot
- normalize_button(raw_button, row: int, column: int) -> ButtonSnapshot
- flatten_buttons(message: MessageSnapshot) -> List[ButtonSnapshot]

- [x] Step 1: Write failing normalization tests

~~~python
def test_inline_buttons_keep_callback_data_and_coordinates():
    message = normalize_message(
        fake_message(
            text="菜单",
            buttons=[[fake_callback_button("每日签到", b"checkin")]],
        ),
        peer_id="@bot",
        sender_id="bot",
    )
    button = message.buttons[0][0]
    assert button.kind == "inline"
    assert button.callback_data == "checkin"
    assert button.row == 0
    assert button.column == 0


def test_reply_button_has_no_callback_data():
    message = normalize_message(
        fake_message(buttons=[[fake_text_button("每日签到")]]),
        peer_id="@bot",
        sender_id="bot",
    )
    assert message.buttons[0][0].kind == "reply"
    assert message.buttons[0][0].callback_data is None
~~~

- [x] Step 2: Run the tests to verify they fail

Run:

~~~bash
python3 -m pytest tests/telegram/test_normalize.py -q
~~~

Expected: FAIL because coordinates and Telethon-independent normalization do not exist.

- [x] Step 3: Add row/column fields and preserve backward compatibility

Add default row and column values to ButtonSnapshot so existing fixtures remain valid. Include coordinates in serialization. Keep match_button behavior based on normalized labels and use coordinates for production click operations.

- [x] Step 4: Implement duck-typed raw-message normalization

Read only safe message fields: ID, text, peer/sender identifiers, and button rows. Detect callback buttons by available callback data; detect reply text buttons by their text. Represent unsupported URL/game/payment buttons with a distinct kind and let the adapter reject them explicitly.

- [x] Step 5: Add ambiguity and coordinate tests

Test exact, contains, regex, callback-data, position, multiple-match failure, and explicit first/index policies using the shared matcher.

- [x] Step 6: Run runtime and Telegram normalization tests

Run:

~~~bash
python3 -m pytest tests/runtime tests/telegram/test_normalize.py -q
~~~

Expected: PASS for both keyboard families and existing runtime behavior.

---

## Task 3: Implement ordinary-account session manager and login flows

**Files:**
- Create: src/tg_ifttt/telegram/errors.py
- Create: src/tg_ifttt/telegram/session_manager.py
- Create: tests/telegram/test_session_manager.py

**Interfaces:**
- SessionManager(credentials: AppCredentials, account_repository: AccountRepository)
- begin_qr_login(account_id: str, display_name: str) -> QRLoginState
- poll_qr_login(login_id: str) -> QRLoginState
- begin_phone_login(account_id: str, phone: str) -> PhoneLoginState
- submit_phone_code(login_id: str, code: str) -> LoginState
- submit_two_factor(login_id: str, password: str) -> LoginState
- disconnect_login(login_id: str) -> None
- connect_account(account_id: str) -> TelegramClientHandle
- disconnect_account(account_id: str) -> None

- [x] Step 1: Write fake-client login tests

~~~python
def test_qr_login_saves_session_after_scan(monkeypatch, account_repository):
    fake_client = FakeClient(qr_url="tg://login?token=test")
    manager = SessionManager(AppCredentials(123, "hash"), account_repository, client_factory=lambda *args: fake_client)

    state = asyncio.run(manager.begin_qr_login("account-a", "A"))
    assert state.url == "tg://login?token=test"
    fake_client.qr_login_result = FakeUser(id=1001, phone="+8613800000000")
    completed = asyncio.run(manager.poll_qr_login(state.login_id))

    assert completed.status == "ready"
    assert account_repository.load_account("account-a").account.user_id == 1001
~~~

- [x] Step 2: Run the tests to verify they fail

Run:

~~~bash
python3 -m pytest tests/telegram/test_session_manager.py -q
~~~

Expected: FAIL because session manager and login states do not exist.

- [x] Step 3: Implement the Telethon client factory

Construct clients using StringSession, the deployment API ID/API Hash, and a stable application/device label. Keep pending login clients in a bounded in-memory map keyed by login ID. Do not persist an incomplete QR token or login code.

- [x] Step 4: Implement QR login state transitions

Call Telethon QR login, expose the short-lived URL and expiry, refresh expired QR codes, wait for import/scan, obtain the authorized user, save the StringSession encrypted, and disconnect the temporary client. Map QR expiration, invalid token, and 2FA-required states to typed status values.

- [x] Step 5: Implement phone-code and 2FA fallback

Use Telethon send-code and sign-in operations. On SessionPasswordNeededError, transition to a password-required state without storing the password. On success, save a new StringSession and account metadata. Enforce bounded attempts and clear pending state on failure or disconnect.

- [x] Step 6: Implement reconnect and session invalidation

Load and decrypt a stored session, connect, verify authorization, and map invalid-session errors to account status. Provide a revoke operation that disconnects and deletes the stored session only when called by the account-management layer.

- [x] Step 7: Run the session manager tests

Run:

~~~bash
python3 -m pytest tests/telegram/test_session_manager.py -q
~~~

Expected: PASS with fake clients and no network.

---

## Task 4: Implement the MTProto ordinary-account adapter

**Files:**
- Create: src/tg_ifttt/telegram/user_adapter.py
- Modify: src/tg_ifttt/telegram/__init__.py
- Create: tests/telegram/test_user_adapter.py

**Interfaces:**
- UserTelegramAdapter(session_manager: SessionManager)
- send_message(account_id: str, target: str, text: str) -> MessageSnapshot
- wait_message(account_id: str, request: Dict[str, Any]) -> MessageSnapshot
- click_button(account_id: str, request: Dict[str, Any]) -> ButtonResult
- read_messages(account_id: str, target: str, limit: int) -> List[MessageSnapshot]
- fetch_updates(account_id: str, cursor: Optional[str]) -> UpdateBatch

- [x] Step 1: Write fake-client adapter tests

~~~python
def test_send_message_resolves_target_per_account(fake_client, adapter):
    result = asyncio.run(adapter.send_message("account-a", "@example_bot", "/start"))
    assert result.peer_id == "@example_bot"
    assert fake_client.sent == [("@example_bot", "/start")]


def test_click_inline_button_uses_callback_coordinates(fake_client, adapter):
    fake_client.messages[10] = fake_message_with_callback("✅ 每日签到", b"checkin")
    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "message": 10,
                "match": {"type": "regex", "value": "^✅\\\\s*每日签到$"},
            },
        )
    )
    assert result.kind == "inline"
    assert fake_client.clicked == [(10, 0, 0)]


def test_click_reply_button_sends_label(fake_client, adapter):
    fake_client.messages[10] = fake_message_with_text_button("每日签到")
    result = asyncio.run(
        adapter.click_button(
            "account-a",
            {
                "target": "@example_bot",
                "message": 10,
                "match": {"type": "regex", "value": "每日签到"},
            },
        )
    )
    assert result.kind == "reply"
    assert fake_client.sent[-1] == ("@example_bot", "每日签到")
~~~

- [x] Step 2: Run the tests to verify they fail

Run:

~~~bash
python3 -m pytest tests/telegram/test_user_adapter.py -q
~~~

Expected: FAIL because the production MTProto adapter does not exist.

- [x] Step 3: Implement account client acquisition and peer resolution

Get or reconnect the account client through SessionManager. Resolve target entities through that account’s client and never reuse another account’s entity/access hash.

- [x] Step 4: Implement message send/read/wait

Call Telethon send_message and get_messages, normalize returned messages, and apply request filters for target, sender, text, regex, message boundary, and timeout. Return WaitingForMessage with a serializable condition when no message is available.

- [x] Step 5: Implement unified button operation

Fetch the configured source message or the latest target message, normalize markup, call the shared match_button function, and enforce unique-match defaults. For Inline Keyboard call the message click API using row/column; for Reply Keyboard send the normalized original label as a normal message. Reject URL or unsupported button kinds with a typed error.

- [x] Step 6: Implement update polling

Expose a cursor-based fetch_updates method for the Qinglong poller. Store only normalized event payloads and an account-local cursor; do not expose Telethon objects to the workflow runtime.

- [x] Step 7: Run adapter tests

Run:

~~~bash
python3 -m pytest tests/telegram/test_user_adapter.py -q
~~~

Expected: PASS without a Telegram connection.

---

## Task 5: Implement the Bot API adapter

**Files:**
- Create: src/tg_ifttt/telegram/bot_adapter.py
- Create: tests/telegram/test_bot_adapter.py

**Interfaces:**
- BotApiAdapter(token: str, http_call: Callable[..., Awaitable[HttpResponse]])
- send_message(account_id: str, target: str, text: str) -> MessageSnapshot
- get_updates(offset: Optional[int], timeout: int) -> UpdateBatch
- answer_callback(callback_id: str, text: Optional[str]) -> None

- [x] Step 1: Write mocked HTTP tests

~~~python
def test_bot_send_message_uses_token_and_normalizes_response():
    response = fake_http_response(
        {"ok": True, "result": {"message_id": 7, "chat": {"id": 1}, "text": "hello"}}
    )
    adapter = BotApiAdapter("123:secret", http_call=FakeHttp(response))
    message = asyncio.run(adapter.send_message("bot-a", "1", "hello"))
    assert message.message_id == 7
    assert FakeHttp.last_path.endswith("/sendMessage")
    assert "123:secret" in FakeHttp.last_path
~~~

- [x] **Step 2: Run the tests to verify they fail**

Run:

~~~bash
python3 -m pytest tests/telegram/test_bot_adapter.py -q
~~~

Expected: FAIL because the Bot API client does not exist.

- [x] **Step 3: Implement bounded JSON HTTP calls**

Use urllib.request inside asyncio.to_thread with connect/read timeouts. Parse Telegram’s ok/result/error_code/description fields, raise typed BotApiError on failures, and never include the token in error text.

- [x] **Step 4: Implement send and update methods**

Support sendMessage, getUpdates, and answerCallbackQuery. Normalize Bot API messages and inline markup into MessageSnapshot. Keep Bot API operations separate from ordinary-user actions; the adapter cannot impersonate an ordinary user in another chat.

- [x] **Step 5: Run Bot API tests**

Run:

~~~bash
python3 -m pytest tests/telegram/test_bot_adapter.py -q
~~~

Expected: PASS with mocked HTTP only.

---

## Task 6: Integrate real adapters with the runtime and Qinglong packaging

**Files:**
- Modify: src/tg_ifttt/runtime/nodes.py
- Create: src/tg_ifttt/telegram/factory.py
- Modify: src/tg_ifttt/cli/qinglong.py
- Modify: scripts/build_qinglong_runner.py
- Modify: tests/cli/test_qinglong_runner.py
- Modify: README.md

**Interfaces:**
- AdapterFactory.from_config(config: Mapping[str, Any]) -> TelegramAdapter
- Qinglong config supports adapter: mtproto, adapter: bot_api, and adapter: fake for offline tests.
- Credentials are loaded from environment and encrypted account storage, never from workflow files.

- [x] Step 1: Write adapter-factory tests

~~~python
def test_fake_adapter_remains_available_for_offline_runs():
    adapter = AdapterFactory.from_config({"adapter": "fake"})
    assert isinstance(adapter, FakeTelegramAdapter)


def test_unknown_adapter_has_actionable_error():
    with pytest.raises(QinglongError, match="unsupported adapter"):
        AdapterFactory.from_config({"adapter": "unknown"})
~~~

- [x] Step 2: Implement factory and configuration validation

Select a Bot API adapter by Bot Token or an MTProto adapter by global API credentials plus account repository. Refuse to start when required credentials are absent. Keep fake adapter explicitly opt-in.

- [x] Step 3: Add dependency bootstrap entries to the generated runner

Include the selected Telethon version in the private dependency bootstrap list and update the source payload digest whenever source changes. Preserve offline mode and avoid global site-package writes.

- [x] Step 4: Add a real-adapter smoke test with a fake client factory

Start a workflow through WorkflowEngine with the MTProto adapter wired to fake clients and assert the existing send/wait/click runtime path remains unchanged.

- [x] Step 5: Run the integrated tests

Run:

~~~bash
python3 -m pytest tests/telegram tests/runtime tests/cli -q
python3 scripts/build_qinglong_runner.py --output tg_ifttt_qinglong.py
python3 tg_ifttt_qinglong.py --help
~~~

Expected: all tests pass offline and the generated runner exposes the adapter configuration without a traceback.

---

## Completion evidence for this plan

This adapter tranche is complete only when:

- multiple ordinary accounts can be represented with one shared API ID/API Hash and independent encrypted sessions;
- Docker-facing login states support QR, phone code, and 2FA fallback without persisting transient secrets;
- MTProto messages and both keyboard types normalize into the existing snapshots;
- regex button matching selects the correct button and preserves row/column for Inline callbacks;
- Reply Keyboard actions send the original label;
- Bot API send/update/callback methods work against mocked HTTP;
- invalid sessions, flood waits, ambiguous buttons, and missing credentials produce typed actionable errors;
- Qinglong’s generated single file includes the adapter source and dependency bootstrap;
- all tests run without network access and no secret appears in logs or test artifacts.

## Follow-up plans

After this tranche passes, create separate plans for:

1. FastAPI authentication, account/login APIs, Webhook API, event listener, scheduler, and Docker Compose runtime.
2. React visual editor, account UI, run timeline, import/export, and frontend verification.
