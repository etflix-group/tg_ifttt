import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import WorkflowLoadError
from .models import WorkflowSpec


def load_workflow(path: Path) -> WorkflowSpec:
    try:
        suffix = path.suffix.lower()
        with path.open("r", encoding="utf-8") as handle:
            if suffix in {".yaml", ".yml"}:
                document = yaml.safe_load(handle)
            elif suffix == ".json":
                document = json.load(handle)
            else:
                raise WorkflowLoadError("unsupported workflow extension: %s" % suffix)
    except OSError as exc:
        raise WorkflowLoadError("unable to read workflow %s: %s" % (path, exc)) from exc
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise WorkflowLoadError("unable to decode workflow %s: %s" % (path, exc)) from exc

    try:
        return parse_workflow(document)
    except (TypeError, ValueError) as exc:
        raise WorkflowLoadError("invalid workflow %s: %s" % (path, exc)) from exc


def parse_workflow(document: Mapping[str, Any]) -> WorkflowSpec:
    if not isinstance(document, Mapping):
        raise WorkflowLoadError("workflow root must be a mapping")
    try:
        return WorkflowSpec.from_dict(document)
    except (TypeError, ValueError) as exc:
        raise WorkflowLoadError(str(exc)) from exc
