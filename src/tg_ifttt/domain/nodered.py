"""Conversion between the safe Node-RED editor format and WorkflowSpec.

Node-RED is deliberately treated as an authoring format here.  The Python
engine remains the only workflow runtime, and this module is the trust
boundary for anything imported from Node-RED.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .loader import parse_workflow
from .validation import validate_workflow


class NodeRedFlowError(ValueError):
    """Raised when a Node-RED flow is not a safe tg-ifttt flow."""


NODE_RED_TO_WORKFLOW = {
    "tg-send-message": "telegram.send_message",
    "tg-wait-message": "telegram.wait_message",
    "tg-click-button": "telegram.click_button",
    "tg-answer-callback": "telegram.answer_callback",
    "tg-read-messages": "telegram.read_messages",
    "tg-set-variable": "set_variable",
    "tg-condition": "condition",
    "tg-delay": "delay",
    "tg-end": "end",
}
WORKFLOW_TO_NODE_RED = {value: key for key, value in NODE_RED_TO_WORKFLOW.items()}
EDITOR_NODE_TYPES = {"tab", "tg-workflow", "tg-trigger"}


def _error(message: str) -> NodeRedFlowError:
    return NodeRedFlowError(message)


def _as_flow(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("flow")
    if not isinstance(value, list):
        raise _error("Node-RED flow must be a JSON array")
    result: List[Dict[str, Any]] = []
    for index, node in enumerate(value):
        if not isinstance(node, Mapping):
            raise _error("Node-RED node %d must be an object" % index)
        result.append(dict(node))
    return result


def _string(node: Mapping[str, Any], key: str, default: str = "") -> str:
    value = node.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise _error("Node-RED property %s must be a string" % key)
    return value


def _optional(node: Mapping[str, Any], key: str) -> Any:
    value = node.get(key)
    if value is None or value == "":
        return None
    return deepcopy(value)


def _number(value: Any, key: str, integer: bool = False) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _error("Node-RED property %s must be a number" % key)
    if isinstance(value, (int, float)):
        return int(value) if integer else value
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise _error("Node-RED property %s must be a number" % key) from exc
        if integer:
            if not parsed.is_integer():
                raise _error("Node-RED property %s must be an integer" % key)
            return int(parsed)
        return int(parsed) if parsed.is_integer() else parsed
    raise _error("Node-RED property %s must be a number" % key)


def _json_list(value: Any, key: str) -> Optional[List[Any]]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _error("Node-RED property %s must contain valid JSON" % key) from exc
    if not isinstance(value, list):
        raise _error("Node-RED property %s must be a JSON array" % key)
    return deepcopy(value)


def _click_config(node: Mapping[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "target": _string(node, "target"),
        "keyboard": _string(node, "keyboard", "auto") or "auto",
    }
    match_type = _string(node, "match_type", "exact") or "exact"
    match_value = deepcopy(node.get("match_value", ""))
    config["match"] = {"type": match_type, "value": match_value}
    multiple = _optional(node, "match_multiple")
    if multiple is not None:
        config["match"]["multiple"] = multiple
    message = _optional(node, "message")
    if message is not None:
        config["message"] = _number(message, "message", integer=True) if isinstance(message, str) and message.strip().isdigit() else message
    after_message_id = _optional(node, "after_message_id")
    if after_message_id is not None:
        config["after_message_id"] = _number(after_message_id, "after_message_id", integer=True) if isinstance(after_message_id, str) and after_message_id.strip().isdigit() else after_message_id
    limit = _number(node.get("limit"), "limit", integer=True)
    if limit is not None:
        config["limit"] = limit
    return config


def _action_config(node: Mapping[str, Any], node_type: str) -> Dict[str, Any]:
    if node_type == "tg-send-message":
        return {"target": _string(node, "target"), "text": _string(node, "text")}
    if node_type == "tg-click-button":
        return _click_config(node)
    if node_type == "tg-wait-message":
        config: Dict[str, Any] = {
            "target": _string(node, "target"),
            "sender": _string(node, "sender"),
            "text_match": {
                "type": _string(node, "text_match_type", "contains") or "contains",
                "value": deepcopy(node.get("text_match_value", "")),
            },
        }
        for key in ("message_id", "after_message_id"):
            value = _optional(node, key)
            if value is not None:
                config[key] = _number(value, key, integer=True) if isinstance(value, str) and value.strip().isdigit() else value
        for key in ("limit", "timeout"):
            value = _number(node.get(key), key, integer=True)
            if value is not None:
                config[key] = value
        return config
    if node_type == "tg-answer-callback":
        return {"callback_id": _string(node, "callback_id"), "text": _string(node, "text")}
    if node_type == "tg-read-messages":
        config = {"target": _string(node, "target")}
        limit = _number(node.get("limit"), "limit", integer=True)
        if limit is not None:
            config["limit"] = limit
        return config
    if node_type == "tg-set-variable":
        config = {"name": _string(node, "variable_name", _string(node, "name"))}
        if "value" in node:
            config["value"] = deepcopy(node["value"])
        expression = _optional(node, "expression")
        if expression is not None:
            config["expression"] = expression
        return config
    if node_type == "tg-condition":
        return {"expression": _string(node, "expression")}
    if node_type == "tg-delay":
        return {"seconds": _number(node.get("seconds", 0), "seconds") or 0}
    if node_type == "tg-end":
        return {}
    raise _error("unsupported Node-RED node type: %s" % node_type)


def _trigger_from_node(node: Mapping[str, Any]) -> Dict[str, Any]:
    trigger_type = _string(node, "trigger_type", "manual") or "manual"
    result: Dict[str, Any] = {"type": trigger_type}
    expression = _optional(node, "expression")
    if expression is not None:
        result["expression"] = expression
    event_type = _optional(node, "event_type")
    if event_type is not None:
        result["event_type"] = event_type
    target = _optional(node, "target")
    if target is not None:
        result["target"] = target
    sender = _optional(node, "sender")
    if sender is not None:
        result["sender"] = sender
    match_value = _optional(node, "match_value")
    if match_value is not None:
        result["match"] = {
            "type": _string(node, "match_type", "contains") or "contains",
            "value": match_value,
        }
    if trigger_type == "schedule":
        for key in ("interval_days", "hour", "minute", "second"):
            value = _number(node.get(key), key, integer=True)
            if value is not None:
                result[key] = value
        random_seconds = node.get("random_seconds")
        if random_seconds is not None:
            if not isinstance(random_seconds, bool):
                raise _error("Node-RED property random_seconds must be a boolean")
            result["random_seconds"] = random_seconds
        anchor_date = _optional(node, "anchor_date")
        if anchor_date is not None:
            result["anchor_date"] = _string(node, "anchor_date")
    return result


def _metadata(flow: Sequence[Mapping[str, Any]], expected_workflow_id: Optional[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
    tabs = [node for node in flow if node.get("type") == "tab"]
    metadata_nodes = [node for node in flow if node.get("type") == "tg-workflow"]
    metadata_node: Optional[Mapping[str, Any]] = None
    if expected_workflow_id:
        matches = [node for node in metadata_nodes if node.get("workflow_id") == expected_workflow_id]
        if len(matches) == 1:
            metadata_node = matches[0]
    if metadata_node is None:
        if len(metadata_nodes) > 1:
            raise _error("Node-RED flow must contain at most one tg-workflow node")
        metadata_node = metadata_nodes[0] if metadata_nodes else None

    tab_id = metadata_node.get("z") if metadata_node else None
    if tab_id is None and tabs:
        tab_id = tabs[0].get("id")
    tab = next((item for item in tabs if item.get("id") == tab_id), tabs[0] if tabs else {})
    fallback_id = expected_workflow_id or _string(tab, "label")
    if metadata_node is not None:
        workflow_id = _string(metadata_node, "workflow_id", fallback_id) or fallback_id
        name = _string(metadata_node, "workflow_name", _string(tab, "label", workflow_id)) or workflow_id
        enabled_value = metadata_node.get("enabled", not bool(tab.get("disabled", False)))
        account = metadata_node.get("account", "")
        target = metadata_node.get("target", "")
        raw_triggers = metadata_node.get("triggers_json")
    else:
        workflow_id = fallback_id
        name = _string(tab, "label", workflow_id) or workflow_id
        enabled_value = not bool(tab.get("disabled", False))
        account = ""
        target = ""
        raw_triggers = None
    if not workflow_id:
        raise _error("Node-RED flow must define workflow_id in tg-workflow or the API URL")
    if expected_workflow_id and workflow_id != expected_workflow_id:
        raise _error("workflow id does not match the requested workflow")
    if not isinstance(enabled_value, bool):
        raise _error("Node-RED property enabled must be a boolean")
    if account is not None and not isinstance(account, str):
        raise _error("Node-RED property account must be a string or null")
    if target is not None and not isinstance(target, str):
        raise _error("Node-RED property target must be a string or null")
    triggers = _json_list(raw_triggers, "triggers_json") or []
    if not isinstance(triggers, list):
        raise _error("Node-RED triggers must be an array")
    for index, trigger in enumerate(triggers):
        if not isinstance(trigger, Mapping) or not isinstance(trigger.get("type"), str):
            raise _error("Node-RED trigger %d must contain a string type" % index)
    workflow_metadata: Dict[str, Any] = {"id": workflow_id, "name": name, "enabled": enabled_value}
    if account:
        workflow_metadata["account"] = account
    if target:
        workflow_metadata["target"] = target
    return (
        workflow_metadata,
        [dict(trigger) for trigger in triggers if isinstance(trigger, Mapping)],
        str(tab_id) if tab_id is not None else None,
    )


def _condition_for_output(node: Mapping[str, Any], output_index: int) -> Optional[str]:
    conditions = _json_list(node.get("conditions_json"), "conditions_json") or []
    if output_index >= len(conditions):
        return None
    condition = conditions[output_index]
    if condition in (None, ""):
        return None
    if not isinstance(condition, str):
        raise _error("Node-RED condition output must be a string")
    return condition


def compile_node_red_flow(value: Any, expected_workflow_id: Optional[str] = None) -> Dict[str, Any]:
    """Compile a Node-RED flow array into the canonical workflow document."""

    flow = _as_flow(value)
    ids: Dict[str, Mapping[str, Any]] = {}
    for index, node in enumerate(flow):
        node_id = node.get("id")
        node_type = node.get("type")
        if not isinstance(node_id, str) or not node_id.strip():
            raise _error("Node-RED node %d must contain a non-empty string id" % index)
        if node_id in ids:
            raise _error("duplicate Node-RED node id: %s" % node_id)
        if not isinstance(node_type, str) or not node_type:
            raise _error("Node-RED node %s must contain a string type" % node_id)
        ids[node_id] = node

    metadata, metadata_triggers, tab_id = _metadata(flow, expected_workflow_id)
    def is_relevant(node: Mapping[str, Any]) -> bool:
        node_type = node.get("type")
        if node_type == "tab":
            return tab_id is None or node.get("id") == tab_id
        if node_type == "tg-workflow":
            return node.get("workflow_id") == metadata["id"] and (tab_id is None or node.get("z") in {None, tab_id})
        return tab_id is None or node.get("z") in {None, tab_id}

    relevant = [node for node in flow if is_relevant(node)]
    for node in relevant:
        node_type = node.get("type")
        if node_type not in EDITOR_NODE_TYPES and node_type not in NODE_RED_TO_WORKFLOW:
            raise _error("unsupported Node-RED node type: %s" % node_type)

    action_nodes = [node for node in relevant if node.get("type") in NODE_RED_TO_WORKFLOW]
    if not action_nodes:
        raise _error("Node-RED flow must contain at least one tg-ifttt action node")
    trigger_nodes = [node for node in relevant if node.get("type") == "tg-trigger"]
    triggers = [_trigger_from_node(node) for node in trigger_nodes] or metadata_triggers or [{"type": "manual"}]
    canonical_ids: Dict[str, str] = {}
    for node in action_nodes:
        canonical_id = node.get("tg_node_id", node["id"])
        if not isinstance(canonical_id, str) or not canonical_id.strip():
            raise _error("Node-RED property tg_node_id must be a non-empty string")
        canonical_ids[str(node["id"])] = canonical_id

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    ui_nodes: Dict[str, Dict[str, Any]] = {}
    for node in action_nodes:
        node_id = canonical_ids[str(node["id"])]
        node_type = str(node["type"])
        node_document = {"id": node_id, "type": NODE_RED_TO_WORKFLOW[node_type], "config": _action_config(node, node_type)}
        node_name = node.get("name")
        if node_name is not None and not isinstance(node_name, str):
            raise _error("Node-RED property name must be a string")
        if isinstance(node_name, str) and node_name != node_id:
            node_document["name"] = node_name
        nodes.append(node_document)
        x = _number(node.get("x"), "x")
        y = _number(node.get("y"), "y")
        if x is not None and y is not None:
            ui_nodes[node_id] = {"x": x, "y": y}
        wires = node.get("wires", [])
        if not isinstance(wires, list):
            raise _error("Node-RED wires for %s must be an array" % node_id)
        for output_index, targets in enumerate(wires):
            if not isinstance(targets, list):
                raise _error("Node-RED wire output %s[%d] must be an array" % (node_id, output_index))
            condition = _condition_for_output(node, output_index) if node_type == "tg-condition" else None
            for target in targets:
                if not isinstance(target, str) or target not in ids:
                    raise _error("unknown Node-RED wire target: %s -> %s" % (node_id, target))
                target_node = ids[target]
                if target_node.get("type") in EDITOR_NODE_TYPES:
                    continue
                if target_node.get("type") not in NODE_RED_TO_WORKFLOW:
                    raise _error("unsupported Node-RED node type: %s" % target_node.get("type"))
                target_id = canonical_ids.get(target)
                if target_id is None:
                    raise _error("Node-RED wire target is outside the selected workflow: %s" % target)
                edge: Dict[str, Any] = {"from": node_id, "to": target_id}
                if condition is not None:
                    edge["condition"] = condition
                edges.append(edge)

    document = {
        "version": 1,
        "workflow": metadata,
        "triggers": triggers,
        "nodes": nodes,
        "edges": edges,
    }
    if ui_nodes:
        document["ui"] = {"nodes": ui_nodes}
    try:
        parse_workflow(document)
    except ValueError as exc:
        raise _error(str(exc)) from exc
    return document


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:14]
    return "%s-%s" % (prefix, digest)


def _export_config(node: Any, node_type: str) -> Dict[str, Any]:
    if isinstance(node, Mapping):
        node_id = node.get("id", "")
        node_name = node.get("name")
        config = dict(node.get("config") or {})
    else:
        node_id = getattr(node, "node_id", "")
        node_name = getattr(node, "name", None)
        config = dict(getattr(node, "config", {}) or {})
    result: Dict[str, Any] = {"name": node_name if isinstance(node_name, str) else str(node_id)}
    if node_type == "telegram.send_message":
        result.update({"target": config.get("target", ""), "text": config.get("text", "")})
    elif node_type == "telegram.click_button":
        match = config.get("match") if isinstance(config.get("match"), Mapping) else {}
        result.update(
            {
                "target": config.get("target", ""),
                "message": config.get("message", ""),
                "keyboard": config.get("keyboard", "auto"),
                "match_type": match.get("type", "exact"),
                "match_value": match.get("value", ""),
                "match_multiple": match.get("multiple", ""),
                "after_message_id": config.get("after_message_id", ""),
                "limit": config.get("limit", ""),
            }
        )
    elif node_type == "telegram.wait_message":
        match = config.get("text_match") if isinstance(config.get("text_match"), Mapping) else {}
        result.update(
            {
                "target": config.get("target", ""),
                "sender": config.get("sender", ""),
                "text_match_type": match.get("type", "contains"),
                "text_match_value": match.get("value", ""),
                "message_id": config.get("message_id", ""),
                "after_message_id": config.get("after_message_id", ""),
                "limit": config.get("limit", ""),
                "timeout": config.get("timeout", ""),
            }
        )
    elif node_type == "telegram.answer_callback":
        result.update({"callback_id": config.get("callback_id", ""), "text": config.get("text", "")})
    elif node_type == "telegram.read_messages":
        result.update({"target": config.get("target", ""), "limit": config.get("limit", "")})
    elif node_type == "set_variable":
        result.update({"name": config.get("name", "")})
        if "value" in config:
            result["value"] = config["value"]
        if "expression" in config:
            result["expression"] = config["expression"]
    elif node_type == "condition":
        result["expression"] = config.get("expression", "")
    elif node_type == "delay":
        result["seconds"] = config.get("seconds", 0)
    return result


def export_node_red_flow(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Export a canonical workflow document as a safe Node-RED flow array."""

    try:
        workflow = parse_workflow(document)
    except ValueError as exc:
        raise NodeRedFlowError(str(exc)) from exc
    errors = validate_workflow(workflow)
    if errors:
        raise NodeRedFlowError("; ".join(errors))
    canonical = workflow.to_dict()
    workflow_id = workflow.workflow_id
    tab_id = _stable_id("tab", workflow_id)
    first_action_id = _stable_id("node", workflow.nodes[0].node_id)
    result: List[Dict[str, Any]] = [
        {
            "id": tab_id,
            "type": "tab",
            "label": workflow.name,
            "disabled": not workflow.enabled,
            "info": "tg-ifttt safe editor flow",
            "env": [],
        },
        {
            "id": _stable_id("meta", workflow_id),
            "type": "tg-workflow",
            "z": tab_id,
            "name": "流程元数据",
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "enabled": workflow.enabled,
            "account": workflow.account or "",
            "target": workflow.target or "",
            "triggers_json": json.dumps(canonical["triggers"], ensure_ascii=False, separators=(",", ":")),
            "x": 100,
            "y": 70,
            "wires": [],
        },
    ]
    for index, trigger in enumerate(canonical["triggers"]):
        trigger_type = trigger.get("type", "manual")
        trigger_node: Dict[str, Any] = {
            "id": _stable_id("trigger-%d" % index, workflow_id),
            "type": "tg-trigger",
            "z": tab_id,
            "name": "触发器 %d" % (index + 1),
            "trigger_type": trigger_type,
            "expression": trigger.get("expression", trigger.get("cron", "")),
            "event_type": trigger.get("event_type", trigger.get("update_type", "")),
            "target": trigger.get("target", ""),
            "sender": trigger.get("sender", trigger.get("sender_id", "")),
            "match_type": (trigger.get("match") or {}).get("type", "contains") if isinstance(trigger.get("match"), Mapping) else "contains",
            "match_value": (trigger.get("match") or {}).get("value", "") if isinstance(trigger.get("match"), Mapping) else "",
            "x": 100,
            "y": 150 + index * 75,
            "wires": [[first_action_id]],
        }
        if trigger_type == "schedule":
            trigger_node.update(
                {
                    "interval_days": trigger.get("interval_days"),
                    "hour": trigger.get("hour"),
                    "minute": trigger.get("minute"),
                    "second": trigger.get("second"),
                    "random_seconds": trigger.get("random_seconds", False),
                }
            )
            if trigger.get("anchor_date") is not None:
                trigger_node["anchor_date"] = trigger["anchor_date"]
        result.append(trigger_node)

    red_ids = {node.node_id: _stable_id("node", node.node_id) for node in workflow.nodes}
    ui_nodes = canonical.get("ui", {}).get("nodes", {}) if isinstance(canonical.get("ui"), Mapping) else {}
    outgoing: Dict[str, List[Dict[str, Any]]] = {node.node_id: [] for node in workflow.nodes}
    for edge in workflow.edges:
        outgoing.setdefault(edge.source, []).append({"target": red_ids[edge.target], "condition": edge.condition})
    for index, node in enumerate(workflow.nodes):
        node_type = WORKFLOW_TO_NODE_RED.get(node.node_type)
        if node_type is None:
            raise NodeRedFlowError("workflow node type cannot be exported to Node-RED: %s" % node.node_type)
        wires: List[List[str]] = [[]]
        if node.node_type == "condition":
            condition_edges = outgoing[node.node_id]
            wires = [[], []]
            conditions: List[str] = []
            for output_index, edge in enumerate(condition_edges):
                if output_index >= len(wires):
                    wires.append([])
                wires[output_index].append(edge["target"])
                conditions.append(edge["condition"] or "")
            config = _export_config(node, node.node_type)
            config["conditions_json"] = json.dumps(conditions, ensure_ascii=False, separators=(",", ":"))
        else:
            for edge in outgoing[node.node_id]:
                wires[0].append(edge["target"])
            config = _export_config(node, node.node_type)
        position = ui_nodes.get(node.node_id) if isinstance(ui_nodes, Mapping) else None
        x = position.get("x") if isinstance(position, Mapping) else None
        y = position.get("y") if isinstance(position, Mapping) else None
        position_fields = {}
        if ui_nodes:
            position_fields = {
                "x": x if isinstance(x, (int, float)) and not isinstance(x, bool) else 360 + (index % 3) * 240,
                "y": y if isinstance(y, (int, float)) and not isinstance(y, bool) else 150 + (index // 3) * 150,
            }
        result.append(
            {
                "id": red_ids[node.node_id],
                "type": node_type,
                "z": tab_id,
                "tg_node_id": node.node_id,
                **config,
                **position_fields,
                "wires": wires,
            }
        )
    return result


__all__ = ["NodeRedFlowError", "compile_node_red_flow", "export_node_red_flow"]
