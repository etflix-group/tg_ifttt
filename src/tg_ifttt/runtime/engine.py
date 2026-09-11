import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from tg_ifttt.domain.errors import WorkflowValidationError
from tg_ifttt.domain.models import NodeSpec, WorkflowSpec
from tg_ifttt.domain.validation import validate_workflow
from tg_ifttt.expression.evaluator import evaluate
from tg_ifttt.runtime.adapters import TelegramAdapter, WaitingForMessage
from tg_ifttt.runtime.context import ExecutionContext
from tg_ifttt.runtime.nodes import NodeExecutionError, NodeResult, execute_node
from tg_ifttt.storage.database import Database

try:
    from tg_ifttt.telegram.errors import TelegramFloodWaitError
except ImportError:  # pragma: no cover - telegram package may be absent in unit tests
    TelegramFloodWaitError = None  # type: ignore[assignment,misc]


TERMINAL_STATUSES = {"success", "failed", "cancelled", "timeout", "needs_review"}

DEFAULT_WAIT_TIMEOUT_SECONDS = 120
DEFAULT_ACTION_BARRIER_TIMEOUT_SECONDS = 120

FLOOD_WAIT_KIND = "flood_wait"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    current_node_id: Optional[str]


class WorkflowEngine:
    def __init__(self, database: Database, adapter: TelegramAdapter) -> None:
        self.database = database
        self.adapter = adapter

    def start(
        self,
        workflow: WorkflowSpec,
        account_id: str,
        trigger_payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        errors = validate_workflow(workflow)
        if errors:
            raise WorkflowValidationError("; ".join(errors))
        version_id = hashlib.sha256(
            json.dumps(workflow.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        self.database.workflows.save_version(workflow, version_id)
        return self.database.runs.create_run(
            workflow.workflow_id,
            version_id,
            account_id,
            trigger_payload,
            first_node_id=workflow.nodes[0].node_id,
            idempotency_key=idempotency_key,
        )

    async def resume(self, run_id: str) -> RunResult:
        run = self.database.runs.load_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return RunResult(run.run_id, run.status, run.current_node_id)
        workflow = self.database.workflows.load_version(run.workflow_id, run.version_id)
        nodes = {node.node_id: node for node in workflow.nodes}
        if not self.database.runs.acquire_lease(run.account_id, run_id):
            return RunResult(run_id, run.status, run.current_node_id)

        try:
            self.database.runs.set_status(run_id, "running")
            while True:
                run = self.database.runs.load_run(run_id)
                if run.waiting.get("kind") == FLOOD_WAIT_KIND:
                    deadline_str = run.waiting.get("deadline")
                    if isinstance(deadline_str, str):
                        try:
                            deadline = datetime.fromisoformat(deadline_str)
                        except (TypeError, ValueError):
                            deadline = None
                    else:
                        deadline = None
                    if deadline is not None and deadline > datetime.now(timezone.utc):
                        self.database.runs.set_status(run_id, "waiting")
                        return RunResult(run_id, "waiting", run.current_node_id)
                    self.database.runs.clear_waiting(run_id)
                    continue
                if run.waiting.get("kind") == "action_barrier":
                    request = run.waiting.get("request")
                    if not isinstance(request, dict):
                        node_id = str(run.waiting.get("node_id") or run.current_node_id or "unknown")
                        error = NodeExecutionError("action barrier request is invalid")
                        self.database.runs.record_node_failure(run_id, node_id, error)
                        return RunResult(run_id, "failed", run.current_node_id)
                    # Check if the action barrier deadline has expired.
                    barrier_deadline = run.waiting.get("deadline")
                    if barrier_deadline:
                        try:
                            barrier_dt = datetime.fromisoformat(barrier_deadline)
                        except (TypeError, ValueError):
                            barrier_dt = None
                        if barrier_dt is not None and barrier_dt < datetime.now(timezone.utc):
                            node_id = str(run.waiting.get("node_id") or run.current_node_id or "unknown")
                            timeout = run.waiting.get("wait_timeout", DEFAULT_ACTION_BARRIER_TIMEOUT_SECONDS)
                            error = NodeExecutionError(
                                "action barrier timeout: bot did not respond within %s seconds" % timeout
                            )
                            self.database.runs.record_node_failure(run_id, node_id, error)
                            return RunResult(run_id, "failed", node_id)
                    try:
                        await self.adapter.wait_message(run.account_id, request)
                    except WaitingForMessage:
                        self.database.runs.set_status(run_id, "waiting")
                        return RunResult(run_id, "waiting", run.current_node_id)
                    except Exception as exc:
                        flood = self._schedule_flood_wait(run_id, exc, run.waiting.get("node_id") or run.current_node_id or "unknown")
                        if flood is not None:
                            return flood
                        node_id = str(run.waiting.get("node_id") or run.current_node_id or "unknown")
                        self.database.runs.record_node_failure(run_id, node_id, exc)
                        return RunResult(run_id, "failed", run.current_node_id)
                    self.database.runs.clear_waiting(run_id)
                    continue
                if run.current_node_id is None:
                    self.database.runs.set_status(run_id, "success")
                    return RunResult(run_id, "success", None)
                waiting = run.waiting
                if (
                    waiting
                    and waiting.get("kind") not in ("action_barrier", FLOOD_WAIT_KIND)
                    and waiting.get("deadline")
                ):
                    try:
                        deadline = datetime.fromisoformat(waiting["deadline"])
                    except (TypeError, ValueError):
                        deadline = None
                    if deadline is not None and deadline < datetime.now(timezone.utc):
                        node_id = waiting.get("node_id", run.current_node_id or "unknown")
                        timeout = waiting.get("wait_timeout", DEFAULT_WAIT_TIMEOUT_SECONDS)
                        error = NodeExecutionError(
                            "wait timeout: message or button not found within %s seconds" % timeout
                        )
                        self.database.runs.record_node_failure(run_id, str(node_id), error)
                        return RunResult(run_id, "failed", str(node_id))
                node = nodes.get(run.current_node_id)
                if node is None:
                    self.database.runs.set_status(run_id, "failed")
                    return RunResult(run_id, "failed", run.current_node_id)
                context = ExecutionContext(
                    workflow=workflow,
                    run=run,
                    adapter=self.adapter,
                    variables=dict(run.variables),
                    outputs=dict(run.node_outputs),
                )
                try:
                    result = await execute_node(node, context)
                except WaitingForMessage as exc:
                    condition = dict(exc.condition)
                    condition["node_id"] = node.node_id
                    if condition.get("kind") != "action_barrier":
                        previous_deadline = run.waiting.get("deadline")
                        if previous_deadline:
                            condition["deadline"] = previous_deadline
                            condition["wait_timeout"] = run.waiting.get(
                                "wait_timeout", DEFAULT_WAIT_TIMEOUT_SECONDS
                            )
                        else:
                            raw_timeout = node.config.get("wait_timeout", DEFAULT_WAIT_TIMEOUT_SECONDS)
                            try:
                                wait_timeout = float(raw_timeout)
                            except (TypeError, ValueError):
                                wait_timeout = DEFAULT_WAIT_TIMEOUT_SECONDS
                            if wait_timeout > 0:
                                deadline = datetime.now(timezone.utc) + timedelta(seconds=wait_timeout)
                                condition["deadline"] = deadline.isoformat()
                                condition["wait_timeout"] = wait_timeout
                    self.database.runs.set_waiting(run_id, condition)
                    return RunResult(run_id, "waiting", node.node_id)
                except Exception as exc:
                    flood = self._schedule_flood_wait(run_id, exc, node.node_id)
                    if flood is not None:
                        return flood
                    self.database.runs.record_node_failure(run_id, node.node_id, exc)
                    return RunResult(run_id, "failed", node.node_id)

                try:
                    next_node_id = self._select_next_node(workflow, node, result, context)
                except Exception as exc:
                    self.database.runs.record_node_failure(run_id, node.node_id, exc)
                    return RunResult(run_id, "failed", node.node_id)
                variables = dict(run.variables)
                variables.update(result.variable_updates)
                status = "success" if next_node_id is None or node.node_type == "end" else "running"
                action_wait_condition = (
                    result.wait_condition
                    if self._should_wait_after_action(node, nodes.get(next_node_id), next_node_id)
                    else None
                )
                if action_wait_condition is not None:
                    condition = dict(action_wait_condition)
                    condition["kind"] = "action_barrier"
                    condition["node_id"] = node.node_id
                    request = condition.get("request")
                    if not isinstance(request, dict):
                        error = NodeExecutionError("action barrier request is invalid")
                        self.database.runs.record_node_failure(run_id, node.node_id, error)
                        return RunResult(run_id, "failed", node.node_id)
                    # Apply the node's wait_timeout (if any) as a deadline for
                    # the action barrier so runs fail instead of waiting forever
                    # when the bot does not respond to a click/send.
                    raw_timeout = node.config.get("wait_timeout", DEFAULT_ACTION_BARRIER_TIMEOUT_SECONDS)
                    try:
                        barrier_timeout = float(raw_timeout)
                    except (TypeError, ValueError):
                        barrier_timeout = DEFAULT_ACTION_BARRIER_TIMEOUT_SECONDS
                    if barrier_timeout > 0:
                        deadline = datetime.now(timezone.utc) + timedelta(seconds=barrier_timeout)
                        condition["deadline"] = deadline.isoformat()
                        condition["wait_timeout"] = barrier_timeout
                    try:
                        await self.adapter.wait_message(run.account_id, request)
                    except WaitingForMessage:
                        self.database.runs.checkpoint_node(
                            run_id,
                            node.node_id,
                            result.output,
                            next_node_id,
                            status="waiting",
                            variables=variables,
                            waiting_condition=condition,
                        )
                        return RunResult(run_id, "waiting", next_node_id)
                    except Exception as exc:
                        flood = self._schedule_flood_wait(run_id, exc, node.node_id)
                        if flood is not None:
                            return flood
                        self.database.runs.record_node_failure(run_id, node.node_id, exc)
                        return RunResult(run_id, "failed", node.node_id)
                self.database.runs.checkpoint_node(
                    run_id,
                    node.node_id,
                    result.output,
                    next_node_id,
                    status=status,
                    variables=variables,
                )
                if status == "success":
                    return RunResult(run_id, "success", next_node_id)
        finally:
            self.database.runs.release_lease(run.account_id, run_id)

    def _schedule_flood_wait(
        self,
        run_id: str,
        exc: Exception,
        node_id: str,
    ) -> Optional[RunResult]:
        """If *exc* is a TelegramFloodWaitError, schedule a waiting state and return a
        waiting RunResult.  Otherwise return ``None`` so the caller can handle the
        exception as it normally would."""
        if TelegramFloodWaitError is None or not isinstance(exc, TelegramFloodWaitError):
            return None
        wait_seconds = max(1, int(getattr(exc, "seconds", 0)))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        condition = {
            "kind": FLOOD_WAIT_KIND,
            "node_id": node_id,
            "deadline": deadline.isoformat(),
            "flood_wait_seconds": wait_seconds,
        }
        self.database.runs.set_waiting(run_id, condition)
        return RunResult(run_id, "waiting", node_id)

    @staticmethod
    def _should_wait_after_action(node: NodeSpec, next_node: Optional[NodeSpec], next_node_id: Optional[str]) -> bool:
        if next_node_id is None or next_node is None:
            return False
        if node.node_type not in {"telegram.send_message", "telegram.click_button"}:
            return False
        if next_node.node_type in {"telegram.wait_message", "end"}:
            return False
        return True

    def _select_next_node(
        self,
        workflow: WorkflowSpec,
        node: NodeSpec,
        result: NodeResult,
        context: ExecutionContext,
    ) -> Optional[str]:
        edges = [edge for edge in workflow.edges if edge.source == node.node_id]
        if not edges:
            return None

        output_context = dict(context.outputs)
        output_context[node.node_id] = result.output
        expression_context = {
            "steps": output_context,
            "variables": dict(context.variables),
            "trigger": context.run.trigger_payload,
        }
        expression_context["variables"].update(result.variable_updates)
        conditional_edges = [edge for edge in edges if edge.condition]
        if conditional_edges:
            for edge in conditional_edges:
                if bool(evaluate(edge.condition or "False", expression_context)):
                    return edge.target
            return None

        if node.node_type in {"condition", "switch"} and len(edges) > 1:
            return edges[0].target if bool(result.output.get("result")) else edges[1].target
        return edges[0].target
