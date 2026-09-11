import sqlite3

from tg_ifttt.storage.database import Database


def test_database_initializes_expected_tables(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    names = {
        row[0]
        for row in database.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "workflows",
        "workflow_versions",
        "workflow_runs",
        "node_runs",
        "waiting_conditions",
        "inbox_events",
        "account_leases",
        "audit_logs",
    }.issubset(names)
    journal_mode = database.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"
    database.close()


def test_database_enables_foreign_keys(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    database.close()
