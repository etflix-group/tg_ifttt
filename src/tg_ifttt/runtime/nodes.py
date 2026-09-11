import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from tg_ifttt.expression.evaluator import evaluate
from tg_ifttt.runtime.context import ExecutionContext


class NodeExecutionError(RuntimeError):
    """Raised when a node cannot execute with its current configuration."""


@dataclass(frozen=True)
class NodeResult:
    output: Dict[str, Any] = field(default_factory=dict)
    variable_updates: Dict[str, Any] = field(default_factory=dict)
    wait_condition: Optional[Dict[str, Any]] = None


def _required_string(config: Dict[str, Any], name: str) -> str:
    value = config.get(name)
    if not isinstance(value, str) or not value:
        raise NodeExecutionError("node config requires a non-empty string: %s" % name)
    return value


def _target(config: Dict[str, Any], workflow_target: Optional[str]) -> str:
    value = config.get("target")
    if value is None or (isinstance(value, str) and not value.strip()):
        value = workflow_target
    return _required_string({"target": value}, "target")


async def execute_node(node: Any, context: ExecutionContext) -> NodeResult:
    config = context.render_value(node.config)
    node_type = node.node_type

    if node_type == "telegram.send_message":
        target = _target(config, context.workflow.target)
        text = _required_string(config, "text")
        message = await context.adapter.send_message(context.run.account_id, target, text)
        return NodeResult(
            message.to_dict(),
            wait_condition={
                "kind": "action_barrier",
                "request": {
                    "action_barrier": "new_message",
                    "target": target,
                    "after_message_id": message.message_id,
                },
            },
        )

    if node_type == "telegram.wait_message":
        config["target"] = _target(config, context.workflow.target)
        message = await context.adapter.wait_message(context.run.account_id, config)
        return NodeResult(message.to_dict())

    if node_type == "telegram.click_button":
        config["target"] = _target(config, context.workflow.target)
        result = await context.adapter.click_button(context.run.account_id, config)
        request: Dict[str, Any] = {
            "action_barrier": "new_message_or_refresh",
            "target": _required_string(config, "target"),
            "after_message_id": result.action_message_id or result.message_id,
        }
        if result.before_message is not None:
            request.update(
                {
                    "message_id": result.message_id,
                    "before_message": result.before_message,
                }
            )
        return NodeResult(
            result.to_dict(),
            wait_condition={"kind": "action_barrier", "request": request},
        )

    if node_type == "telegram.answer_callback":
        callback_id = _required_string(config, "callback_id")
        answer = getattr(context.adapter, "answer_callback", None)
        if answer is None:
            raise NodeExecutionError("configured adapter does not support callback answers")
        await answer(callback_id, config.get("text"))
        return NodeResult({"callback_id": callback_id, "text": config.get("text")})

    if node_type == "telegram.read_messages":
        target = _target(config, context.workflow.target)
        limit = config.get("limit", 20)
        reader = getattr(context.adapter, "read_messages", None)
        if reader is None:
            raise NodeExecutionError("configured adapter does not support telegram.read_messages")
        messages = await reader(context.run.account_id, target, limit)
        return NodeResult({"messages": [message.to_dict() for message in messages]})

    if node_type == "set_variable":
        name = _required_string(config, "name")
        if "expression" in config:
            expression = _required_string(config, "expression")
            value = evaluate(expression, context.expression_context)
        elif "value" in config:
            value = config["value"]
        else:
            raise NodeExecutionError("set_variable requires value or expression")
        return NodeResult({"name": name, "value": value}, {name: value})

    if node_type == "condition":
        expression = _required_string(config, "expression")
        result = bool(evaluate(expression, context.expression_context))
        return NodeResult({"result": result})

    if node_type == "delay":
        seconds = config.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
            raise NodeExecutionError("delay seconds must be a non-negative number")
        await asyncio.sleep(seconds)
        return NodeResult({"seconds": seconds})

    if node_type == "end":
        return NodeResult({"ended": True})

    raise NodeExecutionError("node type is not implemented by the offline runtime: %s" % node_type)
