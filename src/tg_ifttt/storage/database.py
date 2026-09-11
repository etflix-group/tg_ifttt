import sqlite3
from pathlib import Path

from .repositories import RunRepository, TriggerRepository, WorkflowRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    account_id TEXT,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_versions (
    workflow_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workflow_id, version_id)
);

CREATE TABLE IF NOT EXISTS telegram_accounts (
    account_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    user_id INTEGER,
    phone_masked TEXT,
    session_ciphertext BLOB NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_node_id TEXT,
    variables_json TEXT NOT NULL,
    trigger_payload_json TEXT NOT NULL,
    node_outputs_json TEXT NOT NULL,
    retry_counts_json TEXT NOT NULL,
    waiting_json TEXT NOT NULL,
    checkpoint_seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_idempotency (
    idempotency_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_runs (
    run_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    output_json TEXT,
    error_text TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (run_id, node_id)
);

CREATE TABLE IF NOT EXISTS waiting_conditions (
    run_id TEXT PRIMARY KEY,
    condition_json TEXT NOT NULL,
    deadline TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inbox_events (
    event_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS trigger_cursors (
    trigger_key TEXT PRIMARY KEY,
    cursor TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_leases (
    account_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.runs = RunRepository(connection)
        self.triggers = TriggerRepository(connection)
        self.workflows = WorkflowRepository(connection)

    @classmethod
    def connect(cls, path: Path, check_same_thread: bool = True) -> "Database":
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=check_same_thread,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return cls(connection)

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
