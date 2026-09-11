from collections import defaultdict
from typing import Dict, List, Set

from .models import NodeSpec, WorkflowSpec
from tg_ifttt.cron import CronExpressionError, CronSchedule, FixedTimeSchedule, ScheduleConfigError


SUPPORTED_NODE_TYPES = {
    "telegram.send_message",
    "telegram.send_media",
    "telegram.wait_message",
    "telegram.click_button",
    "telegram.answer_callback",
    "telegram.read_messages",
    "delay",
    "condition",
    "switch",
    "set_variable",
    "extract",
    "retry",
    "timeout",
    "foreach",
    "end",
}

SUPPORTED_TRIGGER_TYPES = {"manual", "cron", "schedule", "telegram.event", "webhook"}


def validate_workflow(workflow: WorkflowSpec) -> List[str]:
    errors: List[str] = []
    if workflow.schema_version != 1:
        errors.append("unsupported schema version: %s" % workflow.schema_version)
    if not workflow.workflow_id.strip():
        errors.append("workflow id must not be empty")
    if not workflow.name.strip():
        errors.append("workflow name must not be empty")
    if not workflow.triggers:
        errors.append("workflow must have at least one trigger")
    for trigger in workflow.triggers:
        if trigger.trigger_type not in SUPPORTED_TRIGGER_TYPES:
            errors.append("unsupported trigger type: %s" % trigger.trigger_type)
        elif trigger.trigger_type == "cron":
            expression = trigger.config.get("expression", trigger.config.get("cron"))
            try:
                CronSchedule.parse(expression)
            except CronExpressionError as exc:
                errors.append("invalid cron trigger: %s" % exc)
        elif trigger.trigger_type == "schedule":
            try:
                FixedTimeSchedule.from_config(trigger.config)
            except ScheduleConfigError as exc:
                errors.append("invalid schedule trigger: %s" % exc)
        elif trigger.trigger_type == "telegram.event":
            match = trigger.config.get("match")
            if match is not None and not isinstance(match, dict):
                errors.append("telegram.event match must be a mapping")
    if not workflow.nodes:
        errors.append("workflow must have at least one node")
        return errors

    nodes_by_id: Dict[str, NodeSpec] = {}
    duplicate_ids: Set[str] = set()
    for node in workflow.nodes:
        if not node.node_id.strip():
            errors.append("node id must not be empty")
        if node.node_id in nodes_by_id:
            duplicate_ids.add(node.node_id)
        nodes_by_id[node.node_id] = node
        if node.node_type not in SUPPORTED_NODE_TYPES:
            errors.append("unsupported node type: %s" % node.node_type)
        if node.node_type in {
            "telegram.send_message",
            "telegram.wait_message",
            "telegram.click_button",
            "telegram.read_messages",
        }:
            local_target = node.config.get("target")
            workflow_target = workflow.target
            if not ((isinstance(local_target, str) and local_target.strip()) or (isinstance(workflow_target, str) and workflow_target.strip())):
                errors.append("node %s requires a target session" % node.node_id)
    for node_id in sorted(duplicate_ids):
        errors.append("duplicate node id: %s" % node_id)

    outgoing: Dict[str, List[str]] = defaultdict(list)
    incoming: Dict[str, List[str]] = defaultdict(list)
    for edge in workflow.edges:
        if edge.source not in nodes_by_id or edge.target not in nodes_by_id:
            errors.append("unknown edge endpoint: %s -> %s" % (edge.source, edge.target))
            continue
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)

    entry_id = workflow.nodes[0].node_id
    reachable: Set[str] = set()
    pending = [entry_id]
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(outgoing[node_id])
    for node in workflow.nodes:
        if node.node_id not in reachable:
            errors.append("unreachable node: %s" % node.node_id)

    errors.extend(_cycle_errors(nodes_by_id, outgoing))
    return errors


def _cycle_errors(nodes_by_id: Dict[str, NodeSpec], outgoing: Dict[str, List[str]]) -> List[str]:
    colors: Dict[str, int] = {node_id: 0 for node_id in nodes_by_id}
    stack: List[str] = []
    errors: Set[str] = set()

    def visit(node_id: str) -> None:
        colors[node_id] = 1
        stack.append(node_id)
        for target in outgoing[node_id]:
            if colors[target] == 0:
                visit(target)
            elif colors[target] == 1 and target in stack:
                cycle = stack[stack.index(target) :]
                if not any(nodes_by_id[item].node_type == "foreach" for item in cycle):
                    errors.add("unbounded cycle: %s" % " -> ".join(cycle + [target]))
        stack.pop()
        colors[node_id] = 2

    for node_id in nodes_by_id:
        if colors[node_id] == 0:
            visit(node_id)
    return sorted(errors)
