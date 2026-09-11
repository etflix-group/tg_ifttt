import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.domain.models import WorkflowSpec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: Optional[str], default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    workflow_id: str
    version_id: str
    account_id: str
    status: str
    current_node_id: Optional[str]
    variables: Dict[str, Any]
    trigger_payload: Dict[str, Any]
    node_outputs: Dict[str, Any]
    retry_counts: Dict[str, int]
    waiting: Dict[str, Any]
    checkpoint_seq: int
    error: Optional[Dict[str, str]] = None


class WorkflowRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_version(self, workflow: WorkflowSpec, version_id: str) -> None:
        timestamp = _now()
        document = _encode(workflow.to_dict())
        self._connection.execute(
            """
            INSERT INTO workflows (workflow_id, name, enabled, account_id, document_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workflow_id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                account_id = excluded.account_id,
                document_json = excluded.document_json,
                updated_at = excluded.updated_at
            """,
            (
                workflow.workflow_id,
                workflow.name,
                int(workflow.enabled),
                workflow.account,
                document,
                timestamp,
                timestamp,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO workflow_versions (workflow_id, version_id, document_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(workflow_id, version_id) DO UPDATE SET
                document_json = excluded.document_json
            """,
            (workflow.workflow_id, version_id, document, timestamp),
        )
        self._connection.commit()

    def load_version(self, workflow_id: str, version_id: str) -> WorkflowSpec:
        row = self._connection.execute(
            "SELECT document_json FROM workflow_versions WHERE workflow_id = ? AND version_id = ?",
            (workflow_id, version_id),
        ).fetchone()
        if row is None:
            raise KeyError("unknown workflow version: %s/%s" % (workflow_id, version_id))
        return parse_workflow(json.loads(row[0]))

    def load_current(self, workflow_id: str) -> WorkflowSpec:
        row = self._connection.execute(
            "SELECT document_json FROM workflows WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            raise KeyError("unknown workflow: %s" % workflow_id)
        return parse_workflow(json.loads(row[0]))

    def delete_workflow(self, workflow_id: str) -> bool:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT 1 FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            if row is None:
                self._connection.rollback()
                return False
            self._connection.execute(
                "DELETE FROM workflow_versions WHERE workflow_id = ?",
                (workflow_id,),
            )
            self._connection.execute(
                "DELETE FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            )
            self._connection.commit()
            return True
        except Exception:
            self._connection.rollback()
            raise

    def list_workflows(self) -> List[Dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT workflow_id, name, enabled, account_id, document_json, updated_at
            FROM workflows ORDER BY workflow_id
            """
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "workflow_id": row[0],
                    "name": row[1],
                    "enabled": bool(row[2]),
                    "account_id": row[3],
                    "document": json.loads(row[4]),
                    "updated_at": row[5],
                }
            )
        return result

    def list_versions(self, workflow_id: str) -> List[Dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT version_id, document_json, created_at
            FROM workflow_versions WHERE workflow_id = ? ORDER BY created_at DESC
            """,
            (workflow_id,),
        ).fetchall()
        return [
            {
                "version_id": row[0],
                "document": json.loads(row[1]),
                "created_at": row[2],
            }
            for row in rows
        ]


class RunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create_run(
        self,
        workflow_id: str,
        version_id: str,
        account_id: str,
        trigger_payload: Optional[Dict[str, Any]] = None,
        first_node_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        run_id = uuid4().hex
        timestamp = _now()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            if idempotency_key:
                existing = self._connection.execute(
                    "SELECT run_id FROM run_idempotency WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    self._connection.rollback()
                    return str(existing[0])
            self._connection.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, version_id, account_id, status,
                    current_node_id, variables_json, trigger_payload_json,
                    node_outputs_json, retry_counts_json, waiting_json,
                    checkpoint_seq, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    version_id,
                    account_id,
                    first_node_id,
                    _encode({}),
                    _encode(trigger_payload or {}),
                    _encode({}),
                    _encode({}),
                    _encode({}),
                    timestamp,
                    timestamp,
                ),
            )
            if idempotency_key:
                self._connection.execute(
                    "INSERT INTO run_idempotency (idempotency_key, run_id, created_at) VALUES (?, ?, ?)",
                    (idempotency_key, run_id, timestamp),
                )
            self._connection.commit()
            return run_id
        except Exception:
            self._connection.rollback()
            raise

    def checkpoint_node(
        self,
        run_id: str,
        node_id: str,
        output: Dict[str, Any],
        next_node_id: Optional[str],
        status: str = "running",
        variables: Optional[Dict[str, Any]] = None,
        waiting_condition: Optional[Dict[str, Any]] = None,
    ) -> None:
        timestamp = _now()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT node_outputs_json, checkpoint_seq, variables_json FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown run: %s" % run_id)
            outputs = _decode(row[0], {})
            outputs[node_id] = output
            sequence = int(row[1]) + 1
            stored_variables = variables if variables is not None else _decode(row[2], {})
            self._connection.execute(
                """
                INSERT INTO node_runs (run_id, node_id, status, output_json, started_at, finished_at)
                VALUES (?, ?, 'success', ?, ?, ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    status = excluded.status,
                    output_json = excluded.output_json,
                    finished_at = excluded.finished_at
                """,
                (run_id, node_id, _encode(output), timestamp, timestamp),
            )
            self._connection.execute(
                """
                UPDATE workflow_runs
                SET status = ?, current_node_id = ?, node_outputs_json = ?,
                    variables_json = ?, waiting_json = ?, checkpoint_seq = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    next_node_id,
                    _encode(outputs),
                    _encode(stored_variables),
                    _encode(waiting_condition or {}),
                    sequence,
                    timestamp,
                    run_id,
                ),
            )
            if waiting_condition is None:
                self._connection.execute("DELETE FROM waiting_conditions WHERE run_id = ?", (run_id,))
            else:
                self._connection.execute(
                    """
                    INSERT INTO waiting_conditions (run_id, condition_json, deadline, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        condition_json = excluded.condition_json,
                        deadline = excluded.deadline
                    """,
                    (run_id, _encode(waiting_condition), waiting_condition.get("deadline"), timestamp),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def record_node_failure(self, run_id: str, node_id: str, error: BaseException) -> None:
        timestamp = _now()
        error_text = "%s: %s" % (type(error).__name__, str(error))
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT run_id FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown run: %s" % run_id)
            self._connection.execute(
                """
                INSERT INTO node_runs (
                    run_id, node_id, status, output_json, error_text, started_at, finished_at
                ) VALUES (?, ?, 'failed', NULL, ?, ?, ?)
                ON CONFLICT(run_id, node_id) DO UPDATE SET
                    status = excluded.status,
                    output_json = NULL,
                    error_text = excluded.error_text,
                    finished_at = excluded.finished_at
                """,
                (run_id, node_id, error_text, timestamp, timestamp),
            )
            self._connection.execute(
                "UPDATE workflow_runs SET status = 'failed', current_node_id = ?, updated_at = ? WHERE run_id = ?",
                (node_id, timestamp, run_id),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def update_variables(self, run_id: str, variables: Dict[str, Any]) -> None:
        cursor = self._connection.execute(
            "UPDATE workflow_runs SET variables_json = ?, updated_at = ? WHERE run_id = ?",
            (_encode(variables), _now(), run_id),
        )
        self._connection.commit()
        if cursor.rowcount != 1:
            raise KeyError("unknown run: %s" % run_id)

    def set_waiting(self, run_id: str, condition: Dict[str, Any]) -> None:
        timestamp = _now()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE workflow_runs
                SET status = 'waiting', waiting_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (_encode(condition), timestamp, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("unknown run: %s" % run_id)
            self._connection.execute(
                """
                INSERT INTO waiting_conditions (run_id, condition_json, deadline, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    condition_json = excluded.condition_json,
                    deadline = excluded.deadline
                """,
                (run_id, _encode(condition), condition.get("deadline"), timestamp),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def clear_waiting(self, run_id: str) -> None:
        timestamp = _now()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._connection.execute(
                """
                UPDATE workflow_runs
                SET status = 'running', waiting_json = '{}', updated_at = ?
                WHERE run_id = ?
                """,
                (timestamp, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("unknown run: %s" % run_id)
            self._connection.execute("DELETE FROM waiting_conditions WHERE run_id = ?", (run_id,))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def acquire_lease(self, account_id: str, run_id: str, ttl_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT run_id, expires_at FROM account_leases WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is not None:
                current_run_id = row[0]
                current_expiry = datetime.fromisoformat(row[1])
                if current_run_id != run_id and current_expiry > now:
                    self._connection.rollback()
                    return False
            self._connection.execute(
                """
                INSERT INTO account_leases (account_id, run_id, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    expires_at = excluded.expires_at
                """,
                (account_id, run_id, expires.isoformat()),
            )
            self._connection.commit()
            return True
        except Exception:
            self._connection.rollback()
            raise

    def release_lease(self, account_id: str, run_id: str) -> None:
        self._connection.execute(
            "DELETE FROM account_leases WHERE account_id = ? AND run_id = ?",
            (account_id, run_id),
        )
        self._connection.commit()

    def set_status(self, run_id: str, status: str) -> None:
        cursor = self._connection.execute(
            "UPDATE workflow_runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, _now(), run_id),
        )
        self._connection.commit()
        if cursor.rowcount != 1:
            raise KeyError("unknown run: %s" % run_id)

    def load_run(self, run_id: str) -> RunRecord:
        row = self._connection.execute(
            """
            SELECT run_id, workflow_id, version_id, account_id, status,
                   current_node_id, variables_json, trigger_payload_json,
                   node_outputs_json, retry_counts_json, waiting_json, checkpoint_seq
            FROM workflow_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError("unknown run: %s" % run_id)
        error_row = self._connection.execute(
            """
            SELECT node_id, error_text FROM node_runs
            WHERE run_id = ? AND status = 'failed'
            ORDER BY finished_at DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        return RunRecord(
            run_id=row[0],
            workflow_id=row[1],
            version_id=row[2],
            account_id=row[3],
            status=row[4],
            current_node_id=row[5],
            variables=_decode(row[6], {}),
            trigger_payload=_decode(row[7], {}),
            node_outputs=_decode(row[8], {}),
            retry_counts=_decode(row[9], {}),
            waiting=_decode(row[10], {}),
            checkpoint_seq=int(row[11]),
            error=(
                {"node_id": str(error_row[0]), "message": str(error_row[1])}
                if error_row is not None and error_row[1] is not None
                else None
            ),
        )

    def list_recoverable_runs(self) -> List[RunRecord]:
        rows = self._connection.execute(
            "SELECT run_id FROM workflow_runs WHERE status IN ('queued', 'running', 'waiting') ORDER BY created_at"
        ).fetchall()
        return [self.load_run(row[0]) for row in rows]

    def list_runs(self, limit: int = 100) -> List[RunRecord]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("run limit must be an integer from 1 to 500")
        rows = self._connection.execute(
            "SELECT run_id FROM workflow_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self.load_run(row[0]) for row in rows]


class TriggerRepository:
    """Durable cursors for polling-based Telegram trigger adapters."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_cursor(self, trigger_key: str) -> Optional[str]:
        row = self._connection.execute(
            "SELECT cursor FROM trigger_cursors WHERE trigger_key = ?",
            (trigger_key,),
        ).fetchone()
        return None if row is None else row[0]

    def save_cursor(self, trigger_key: str, cursor: Optional[str]) -> None:
        self._connection.execute(
            """
            INSERT INTO trigger_cursors (trigger_key, cursor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(trigger_key) DO UPDATE SET
                cursor = excluded.cursor,
                updated_at = excluded.updated_at
            """,
            (trigger_key, cursor, _now()),
        )
        self._connection.commit()
