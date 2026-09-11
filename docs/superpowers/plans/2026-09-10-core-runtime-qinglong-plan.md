# Core Runtime and Qinglong Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use checkbox syntax for tracking.

**Goal:** Build a tested Python foundation that loads the approved workflow model, validates and safely evaluates it, persists durable run state, executes connector-backed nodes with checkpoints, and exposes a one-file Qinglong runner.

**Architecture:** Use a Python 3.9+ package with pure domain models, a SQLite repository, a restricted AST-based expression evaluator, and a connector protocol. The first tranche keeps Telegram networking behind a fake adapter so the runtime can be tested deterministically; the next tranche will add Telethon and Bot API connectors without changing runtime interfaces. The Qinglong artifact is generated from the same package and reads configuration beside its entry file.

**Tech Stack:** Python 3.9+, dataclasses, sqlite3, asyncio, PyYAML, cryptography, pytest, optional mypy/ruff; no web framework or frontend dependency in this tranche.

## Global Constraints

- Preserve the approved design in docs/superpowers/specs/2026-09-10-telegram-ifttt-design.md.
- Support both YAML and JSON workflow documents.
- Store canonical workflow data as normalized JSON-compatible structures.
- Do not use Python eval, exec, imports, filesystem access, or unrestricted calls in expressions.
- Persist a checkpoint after every completed node.
- Keep account-specific Telegram entity data isolated; the fake adapter must expose the same boundary.
- Never log master keys, sessions, Bot Tokens, verification codes, or 2FA passwords.
- Keep the Qinglong entrypoint runnable as one Python file with configuration beside it.
- Use Python 3.9-compatible syntax because the current workspace runtime is Python 3.9.6.
- Keep the first tranche independent of Telegram network access; all runtime tests must run offline.
- The workspace is not currently a Git repository, so commit steps are replaced by file-level verification and must not claim commits.

---

## Task 1: Create the Python package and test harness

**Files:**
- Create: pyproject.toml
- Create: src/tg_ifttt/__init__.py
- Create: src/tg_ifttt/version.py
- Create: tests/conftest.py
- Create: tests/test_smoke.py
- Create: .gitignore
- Modify: README.md

**Interfaces:**
- Produces an installable package named tg-ifttt.
- Exposes tg_ifttt.__version__.
- Provides a pytest command that works from the repository root.

- [x] Step 1: Write the failing smoke test

~~~python
from tg_ifttt.version import __version__


def test_package_version_is_present():
    assert __version__
~~~

- [x] Step 2: Run the test to verify it fails

Run:

~~~bash
python3 -m pytest tests/test_smoke.py -q
~~~

Expected: FAIL because the package and test configuration do not exist.

- [x] Step 3: Add the minimal package configuration

Create a Python 3.9-compatible project with runtime dependencies for YAML and encryption and pytest as a development dependency:

~~~toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tg-ifttt"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
  "PyYAML>=6.0,<7.0",
  "cryptography>=41.0,<46.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0,<9.0",
  "pytest-asyncio>=0.23,<1.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-ra"

[tool.setuptools.packages.find]
where = ["src"]
~~~

- [x] Step 4: Implement the package version

~~~python
# src/tg_ifttt/version.py
__version__ = "0.1.0"
~~~

~~~python
# src/tg_ifttt/__init__.py
from .version import __version__

__all__ = ["__version__"]
~~~

- [x] Step 5: Run the test to verify it passes

Run:

~~~bash
python3 -m pytest tests/test_smoke.py -q
~~~

Expected: PASS.

- [x] Step 6: Add repository hygiene files

Ignore virtual environments, caches, local SQLite files, encrypted account data, and generated Qinglong artifacts. Add a README that states the project is a self-hosted Telegram automation engine and links to the approved design document.

- [x] Step 7: Verify the package metadata

Run:

~~~bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
~~~

Expected: the smoke test passes and the editable package installs without modifying application code.

---

## Task 2: Implement workflow domain models and document loading

**Files:**
- Create: src/tg_ifttt/domain/__init__.py
- Create: src/tg_ifttt/domain/models.py
- Create: src/tg_ifttt/domain/errors.py
- Create: src/tg_ifttt/domain/loader.py
- Create: src/tg_ifttt/domain/validation.py
- Create: tests/domain/test_loader.py
- Create: tests/domain/test_validation.py
- Create: tests/fixtures/workflows/daily_checkin.yaml
- Create: tests/fixtures/workflows/daily_checkin.json

**Interfaces:**
- load_workflow(path: Path) -> WorkflowSpec
- parse_workflow(document: Mapping[str, Any]) -> WorkflowSpec
- validate_workflow(workflow: WorkflowSpec) -> list[str]
- WorkflowSpec.to_dict() -> dict[str, Any]
- WorkflowSpec.from_dict(data: Mapping[str, Any]) -> WorkflowSpec

- [x] Step 1: Write failing loader tests

Test both YAML and JSON fixtures and assert that node IDs, edges, trigger values, and button regex configuration are preserved:

~~~python
from pathlib import Path

from tg_ifttt.domain.loader import load_workflow


def test_load_yaml_workflow():
    workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    assert workflow.workflow_id == "daily-checkin"
    assert workflow.nodes[1].node_type == "telegram.click_button"
    assert workflow.nodes[1].config["match"]["type"] == "regex"


def test_yaml_and_json_have_same_canonical_shape():
    yaml_workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    json_workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.json"))
    assert yaml_workflow.to_dict() == json_workflow.to_dict()
~~~

- [x] Step 2: Run the focused tests

Run:

~~~bash
python3 -m pytest tests/domain/test_loader.py -q
~~~

Expected: FAIL because the domain package and fixtures do not exist.

- [x] Step 3: Define dataclasses and enums

Use immutable or controlled dataclasses for trigger, node, edge, and workflow objects. The public shape must include:

~~~python
@dataclass(frozen=True)
class TriggerSpec:
    trigger_type: str
    config: dict[str, Any]

@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    node_type: str
    config: dict[str, Any]

@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    condition: Optional[str] = None

@dataclass(frozen=True)
class WorkflowSpec:
    schema_version: int
    workflow_id: str
    name: str
    enabled: bool
    account: Optional[str]
    triggers: tuple[TriggerSpec, ...]
    nodes: tuple[NodeSpec, ...]
    edges: tuple[EdgeSpec, ...]
~~~

Use Optional[str] instead of the union operator if needed to preserve Python 3.9 compatibility.

- [x] Step 4: Implement YAML/JSON loading and canonical serialization

Detect the suffix, load YAML with safe_load or JSON with json.load, require a mapping at the root, normalize lists to tuples in the dataclasses, and serialize back to stable JSON-compatible dictionaries with deterministic key ordering.

- [x] Step 5: Add validation rules and failing validation tests

Validation must reject:

~~~python
def test_validation_rejects_duplicate_node_ids():
    workflow = make_workflow_with_duplicate_nodes()
    errors = validate_workflow(workflow)
    assert "duplicate node id" in " ".join(errors)


def test_validation_rejects_unknown_edge_endpoint():
    workflow = make_workflow_with_unknown_edge()
    errors = validate_workflow(workflow)
    assert "unknown edge endpoint" in " ".join(errors)


def test_validation_rejects_unreachable_node():
    workflow = make_workflow_with_unreachable_node()
    errors = validate_workflow(workflow)
    assert "unreachable node" in " ".join(errors)
~~~

Implement checks for schema version, required identifiers, duplicate IDs, unknown edge endpoints, at least one trigger, at least one node, unreachable nodes, unsupported node types, and unbounded graph cycles. Allow cycles only through an explicit bounded foreach node.

- [x] Step 6: Add fixtures and run the domain test suite

Run:

~~~bash
python3 -m pytest tests/domain -q
~~~

Expected: PASS for YAML/JSON parity and all validation cases.

---

## Task 3: Implement the safe expression evaluator

**Files:**
- Create: src/tg_ifttt/expression/__init__.py
- Create: src/tg_ifttt/expression/evaluator.py
- Create: src/tg_ifttt/expression/errors.py
- Create: tests/expression/test_evaluator.py

**Interfaces:**
- evaluate(expression: str, context: Mapping[str, Any]) -> Any
- render_template(text: str, context: Mapping[str, Any]) -> str
- regex_match(value: str, pattern: str) -> bool
- contains(value: Any, needle: Any) -> bool

- [x] Step 1: Write passing-shape tests as failing tests

~~~python
import pytest

from tg_ifttt.expression.evaluator import evaluate, render_template
from tg_ifttt.expression.errors import UnsafeExpressionError


def test_evaluate_dotted_context():
    context = {"steps": {"start": {"message_id": 42}}}
    assert evaluate("steps.start.message_id", context) == 42


def test_render_template():
    context = {"variables": {"points": 17}}
    assert render_template("积分={{ variables.points }}", context) == "积分=17"


def test_contains_and_regex_match():
    context = {"message": "签到成功，积分：17"}
    assert evaluate('message contains "签到"', context) is True
    assert evaluate(r'regex_match(message, "积分[:：](\\d+)")', context) is True


@pytest.mark.parametrize("expression", ["__import__('os')", "open('secret')", "1 .__class__"])
def test_unsafe_expression_is_rejected(expression):
    with pytest.raises(UnsafeExpressionError):
        evaluate(expression, {})
~~~

- [x] Step 2: Run the tests

Run:

~~~bash
python3 -m pytest tests/expression/test_evaluator.py -q
~~~

Expected: FAIL because the evaluator does not exist.

- [x] Step 3: Implement an allowlisted AST interpreter

Parse with ast.parse in eval mode. Permit only constants, names, dotted dictionary/list access, boolean operators, comparisons, arithmetic on safe scalar values, unary operators, calls to the explicit helper registry, and the custom contains comparison form. Reject every other AST node, unknown name, private attribute, callable from context, import, lambda, comprehension, subscript escape, and excessively deep expression.

- [x] Step 4: Implement template rendering

Replace only {{ expression }} spans. Evaluate each expression through the same evaluator. Convert None to an empty string and use stable string conversion for scalar values. Do not allow template syntax to execute statements.

- [x] Step 5: Run expression tests and a bounded fuzz regression

Run:

~~~bash
python3 -m pytest tests/expression -q
~~~

Expected: PASS, with unsafe expressions rejected rather than evaluated.

---

## Task 4: Implement encrypted storage and durable run records

**Files:**
- Create: src/tg_ifttt/storage/__init__.py
- Create: src/tg_ifttt/storage/crypto.py
- Create: src/tg_ifttt/storage/database.py
- Create: src/tg_ifttt/storage/repositories.py
- Create: tests/storage/test_crypto.py
- Create: tests/storage/test_database.py
- Create: tests/storage/test_runs.py

**Interfaces:**
- SecretBox(master_key: bytes).encrypt(plaintext: bytes) -> bytes
- SecretBox.decrypt(ciphertext: bytes) -> bytes
- Database.connect(path: Path) -> Database
- Database.initialize() -> None
- RunRepository.create_run(...) -> str
- RunRepository.checkpoint_node(...) -> None
- RunRepository.load_run(run_id: str) -> RunRecord
- RunRepository.list_recoverable_runs() -> List[RunRecord]

- [x] Step 1: Write encryption tests

~~~python
def test_secret_round_trip():
    box = SecretBox(b"x" * 32)
    ciphertext = box.encrypt(b"telegram-session")
    assert ciphertext != b"telegram-session"
    assert box.decrypt(ciphertext) == b"telegram-session"


def test_wrong_key_fails():
    box = SecretBox(b"x" * 32)
    other = SecretBox(b"y" * 32)
    ciphertext = box.encrypt(b"secret")
    with pytest.raises(Exception):
        other.decrypt(ciphertext)
~~~

- [x] Step 2: Implement AES-GCM envelope encryption

Use cryptography AESGCM with a fresh random nonce per encryption. Validate the master key length, prepend a format/version marker and nonce, and raise a project-specific decryption error for malformed or unauthenticated ciphertext. Do not log plaintext or ciphertext.

- [x] Step 3: Write database schema tests

Verify that initialization creates tables for workflows, versions, runs, node runs, waiting conditions, inbox events, account leases, and audit events, and that SQLite WAL mode is active.

- [x] Step 4: Implement SQLite schema and repository methods

Use parameterized SQL only. Store JSON payloads in TEXT columns with stable JSON encoding. Store run state, node state, variables, retry counters, deadlines, and checkpoint sequence numbers. Wrap each checkpoint in a transaction so a node result and next execution position commit atomically.

- [x] Step 5: Write restart-recovery tests

~~~python
def test_checkpoint_can_be_loaded_after_reopening_database(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = Database.connect(path)
    first.initialize()
    run_id = first.runs.create_run("daily-checkin", "v1", "account-a")
    first.runs.checkpoint_node(run_id, "send_start", {"message_id": 42}, "click_checkin")
    first.close()

    second = Database.connect(path)
    recovered = second.runs.load_run(run_id)
    assert recovered.current_node_id == "click_checkin"
    assert recovered.node_outputs["send_start"]["message_id"] == 42
~~~

- [x] Step 6: Run storage tests

Run:

~~~bash
python3 -m pytest tests/storage -q
~~~

Expected: PASS, including encryption, schema, transaction, and reopen recovery tests.

---

## Task 5: Implement connector protocol and graph runtime

**Files:**
- Create: src/tg_ifttt/runtime/__init__.py
- Create: src/tg_ifttt/runtime/adapters.py
- Create: src/tg_ifttt/runtime/context.py
- Create: src/tg_ifttt/runtime/engine.py
- Create: src/tg_ifttt/runtime/nodes.py
- Create: tests/runtime/test_fake_adapter.py
- Create: tests/runtime/test_engine.py
- Create: tests/runtime/test_recovery.py

**Interfaces:**
- TelegramAdapter.send_message(account_id, target, text) -> MessageSnapshot
- TelegramAdapter.wait_message(account_id, request) -> MessageSnapshot
- TelegramAdapter.click_button(account_id, request) -> ButtonResult
- NodeExecutor.execute(node, context) -> NodeResult
- WorkflowEngine.start(workflow, account_id, trigger_payload) -> str
- WorkflowEngine.resume(run_id) -> RunResult

- [x] Step 1: Define normalized snapshots and fake adapter

Use serializable dataclasses:

~~~python
@dataclass(frozen=True)
class MessageSnapshot:
    message_id: int
    peer_id: str
    sender_id: Optional[str]
    text: str
    buttons: tuple[tuple[ButtonSnapshot, ...], ...]


@dataclass(frozen=True)
class ButtonSnapshot:
    label: str
    callback_data: Optional[str]
    kind: str
~~~

The fake adapter must record sent actions, return deterministic message IDs, expose a queued incoming message, and implement regex-based button matching using the same normalized rule as production.

- [x] Step 2: Write a failing end-to-end runtime test

~~~python
def test_start_wait_match_button_and_finish(tmp_path):
    workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    adapter = FakeTelegramAdapter(
        incoming=[message_with_button("✅ 每日签到", kind="inline")]
    )
    database = open_test_database(tmp_path)
    engine = WorkflowEngine(database, adapter)

    run_id = engine.start(workflow, "account-a", {})
    result = engine.resume(run_id)

    assert result.status == "success"
    assert adapter.sent_texts == [("/start", "@example_bot")]
    assert adapter.clicked_labels == ["✅ 每日签到"]
~~~

- [x] Step 3: Implement graph traversal and node registry

Build a registry keyed by node type. Resolve outgoing edges after each node. Record node output and next position through RunRepository before continuing. Implement the first offline node set: send_message, wait_message, click_button, set_variable, condition, delay with a test clock, and end.

- [x] Step 4: Implement waiting and recovery states

When the fake adapter cannot satisfy wait_message immediately, checkpoint the run as waiting with a deadline. When resume is called after a matching event is available, continue from the wait node. When a run has an executing node without a committed result, mark it needs_review rather than repeating an ambiguous side effect automatically.

- [x] Step 5: Implement retries, timeout, cancellation, and account leases

Use a lease row keyed by account ID with an expiry. Reject a second active Telegram action for the same account unless the workflow concurrency policy allows it. Retry only nodes marked safe for retry. Persist every transition.

- [x] Step 6: Run runtime tests

Run:

~~~bash
python3 -m pytest tests/runtime -q
~~~

Expected: PASS for successful graph execution, button matching, waiting, restart recovery, lease behavior, and ambiguous side-effect handling.

---

## Task 6: Implement configuration selection and Qinglong runner

**Files:**
- Create: src/tg_ifttt/cli/__init__.py
- Create: src/tg_ifttt/cli/qinglong.py
- Create: scripts/build_qinglong_runner.py
- Create: tests/cli/test_config_discovery.py
- Create: tests/cli/test_qinglong_runner.py
- Create: tests/fixtures/qinglong/config.yaml
- Create: tg_ifttt_qinglong.py

**Interfaces:**
- discover_config(script_path: Path, override: Optional[str]) -> Path
- discover_workflows(config_path: Path) -> List[Path]
- run_selected_workflows(config_path: Path, workflow_id: Optional[str]) -> int
- build_runner(output_path: Path) -> Path

- [x] Step 1: Write failing discovery tests

~~~python
def test_config_defaults_to_yaml_next_to_entrypoint(tmp_path):
    entrypoint = tmp_path / "tg_ifttt_qinglong.py"
    entrypoint.write_text("")
    config = tmp_path / "config.yaml"
    config.write_text("workflows: []")
    assert discover_config(entrypoint, None) == config


def test_environment_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "override.json"
    override.write_text("{}")
    monkeypatch.setenv("TG_IFTTT_CONFIG", str(override))
    assert discover_config(tmp_path / "entry.py", None) == override
~~~

- [x] Step 2: Implement configuration discovery

Resolve paths relative to the entrypoint, not the current working directory. Prefer an explicit function argument, then TG_IFTTT_CONFIG, then config.yaml, then config.json. Reject missing or ambiguous files with a user-facing error.

- [x] Step 3: Implement workflow selection

Load workflow paths from the config document and the sibling workflows directory. Filter disabled workflows and TG_IFTTT_WORKFLOW_ID. Preserve deterministic lexical ordering. Return a non-zero exit code when any selected workflow fails and zero only when all selected workflows succeed.

- [x] Step 4: Write an integration test for the generated single file

Build the runner into a temporary directory, copy the fixture config beside it, invoke it with Python, and assert that it can load the config and execute a fake-adapter workflow without importing from the source checkout.

- [x] Step 5: Implement the runner builder

Create a single Python file containing the package source payload and a bootstrap that extracts or imports it from a private temporary cache. The generated runner must load PyYAML/cryptography/Telethon dependencies from a private dependency directory when absent, use pinned versions, and provide a clear offline error if installation is impossible. It must never modify the global Python environment.

- [x] Step 6: Add the repository entry script

The checked-in entry script invokes the generated runtime path and accepts no required command-line arguments. It supports optional environment overrides, writes state beside itself under data, and emits structured stdout logs.

- [x] Step 7: Run Qinglong tests

Run:

~~~bash
python3 -m pytest tests/cli -q
python3 scripts/build_qinglong_runner.py --output /tmp/tg_ifttt_qinglong.py
python3 /tmp/tg_ifttt_qinglong.py --help
~~~

Expected: discovery tests pass, the generated file is self-contained with respect to project source, and help output is available without a traceback.

---

## Task 7: Add offline fixture workflow and developer documentation

**Files:**
- Create: examples/workflows/daily_checkin.yaml
- Create: examples/config.yaml
- Create: tests/fixtures/fake_messages.py
- Modify: README.md
- Modify: docs/superpowers/specs/2026-09-10-telegram-ifttt-design.md only if implementation constraints require a precise correction

**Interfaces:**
- A new developer can install the package, run the offline example, and understand where real Telegram adapters will plug in.
- The example contains no real account identifiers, Token, session, or public credential.

- [x] Step 1: Write the offline example test

~~~python
def test_example_workflow_is_executable_without_network():
    workflow = load_workflow(Path("examples/workflows/daily_checkin.yaml"))
    result = run_with_fake_adapter(workflow)
    assert result.status == "success"
~~~

- [x] Step 2: Add the example and fake message fixtures

Use a deterministic bot response containing an Inline Keyboard with a regex-matchable label. Add a Reply Keyboard fixture and test both paths.

- [x] Step 3: Document developer commands

Document:

~~~bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
python3 -m tg_ifttt.cli.qinglong --config examples/config.yaml
~~~

Explain that Telegram networking is intentionally not enabled by the offline example and will be added behind the connector protocol.

- [x] Step 4: Run the complete foundation suite

Run:

~~~bash
python3 -m pytest -q
~~~

Expected: all tests pass without a network connection and without requiring Telegram credentials.

---

## Completion evidence for this plan

The foundation tranche is complete only when:

- the package installs on Python 3.9;
- YAML and JSON produce equal canonical workflow data;
- invalid graphs fail before execution;
- unsafe expressions are rejected;
- encrypted secrets round-trip and wrong keys fail;
- a fake Telegram workflow checkpoints every node and resumes after reopening SQLite;
- same-account leases prevent conflicting actions;
- a single generated Qinglong Python file discovers sibling config/workflows and returns meaningful exit codes;
- the full test suite passes offline;
- no test or log contains a real credential.

## Follow-up plans

After this plan passes, create separate implementation plans for:

1. Telegram MTProto and Bot API adapters, including QR login and real button/message operations.
2. FastAPI authentication, Webhook API, event listener, scheduler, and Docker Compose runtime.
3. React visual editor, account UI, run timeline, import/export, and frontend verification.
