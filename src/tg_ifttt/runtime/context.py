from dataclasses import dataclass
from typing import Any, Dict

from tg_ifttt.domain.models import WorkflowSpec
from tg_ifttt.expression.evaluator import render_template
from tg_ifttt.runtime.adapters import TelegramAdapter
from tg_ifttt.storage.repositories import RunRecord


@dataclass
class ExecutionContext:
    workflow: WorkflowSpec
    run: RunRecord
    adapter: TelegramAdapter
    variables: Dict[str, Any]
    outputs: Dict[str, Any]

    @property
    def expression_context(self) -> Dict[str, Any]:
        return {
            "steps": self.outputs,
            "variables": self.variables,
            "trigger": self.run.trigger_payload,
        }

    def render_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return render_template(value, self.expression_context)
        if isinstance(value, dict):
            return {key: self.render_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render_value(item) for item in value]
        return value
