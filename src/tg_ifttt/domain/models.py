from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple


def _copy_mapping(value: Mapping[str, Any]) -> Dict[str, Any]:
    return deepcopy(dict(value))


@dataclass(frozen=True)
class TriggerSpec:
    trigger_type: str
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.trigger_type}
        result.update(_copy_mapping(self.config))
        return result


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    node_type: str
    config: Dict[str, Any]
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.node_id,
            "type": self.node_type,
            "config": _copy_mapping(self.config),
        }
        if self.name is not None:
            result["name"] = self.name
        return result


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    condition: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"from": self.source, "to": self.target}
        if self.condition is not None:
            result["condition"] = self.condition
        return result


@dataclass(frozen=True)
class WorkflowSpec:
    schema_version: int
    workflow_id: str
    name: str
    enabled: bool
    account: Optional[str]
    target: Optional[str]
    triggers: Tuple[TriggerSpec, ...]
    nodes: Tuple[NodeSpec, ...]
    edges: Tuple[EdgeSpec, ...]
    ui: Dict[str, Any]

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "WorkflowSpec":
        root = dict(document)
        metadata = root.get("workflow")
        if not isinstance(metadata, Mapping):
            raise ValueError("workflow metadata must be a mapping")

        version = root.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("version must be an integer")

        raw_triggers = root.get("triggers", [])
        raw_nodes = root.get("nodes", [])
        raw_edges = root.get("edges", [])
        raw_ui = root.get("ui", {})
        if not isinstance(raw_triggers, list):
            raise ValueError("triggers must be a list")
        if not isinstance(raw_nodes, list):
            raise ValueError("nodes must be a list")
        if not isinstance(raw_edges, list):
            raise ValueError("edges must be a list")
        if not isinstance(raw_ui, Mapping):
            raise ValueError("ui must be a mapping")

        triggers: List[TriggerSpec] = []
        for raw in raw_triggers:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("type"), str):
                raise ValueError("each trigger must contain a string type")
            config = {key: deepcopy(value) for key, value in raw.items() if key != "type"}
            triggers.append(TriggerSpec(raw["type"], config))

        nodes: List[NodeSpec] = []
        for raw in raw_nodes:
            if not isinstance(raw, Mapping):
                raise ValueError("each node must be a mapping")
            node_id = raw.get("id")
            node_type = raw.get("type")
            if not isinstance(node_id, str) or not isinstance(node_type, str):
                raise ValueError("each node must contain string id and type")
            node_config = raw.get("config", {})
            if not isinstance(node_config, Mapping):
                raise ValueError("node config must be a mapping")
            node_name = raw.get("name")
            if node_name is not None and not isinstance(node_name, str):
                raise ValueError("node name must be a string or null")
            nodes.append(NodeSpec(node_id, node_type, _copy_mapping(node_config), node_name))

        edges: List[EdgeSpec] = []
        for raw in raw_edges:
            if not isinstance(raw, Mapping):
                raise ValueError("each edge must be a mapping")
            source = raw.get("from")
            target = raw.get("to")
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError("each edge must contain string from and to")
            condition = raw.get("condition")
            if condition is not None and not isinstance(condition, str):
                raise ValueError("edge condition must be a string")
            edges.append(EdgeSpec(source, target, condition))

        workflow_id = metadata.get("id")
        name = metadata.get("name", workflow_id)
        if not isinstance(workflow_id, str) or not isinstance(name, str):
            raise ValueError("workflow id and name must be strings")
        enabled = metadata.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("workflow enabled must be a boolean")
        account = metadata.get("account")
        if account is not None and not isinstance(account, str):
            raise ValueError("workflow account must be a string or null")
        target = metadata.get("target")
        if target is not None and not isinstance(target, str):
            raise ValueError("workflow target must be a string or null")

        return cls(
            schema_version=version,
            workflow_id=workflow_id,
            name=name,
            enabled=enabled,
            account=account,
            target=target,
            triggers=tuple(triggers),
            nodes=tuple(nodes),
            edges=tuple(edges),
            ui=_copy_mapping(raw_ui),
        )

    def to_dict(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "id": self.workflow_id,
            "name": self.name,
            "enabled": self.enabled,
        }
        if self.account is not None:
            metadata["account"] = self.account
        if self.target is not None:
            metadata["target"] = self.target
        result = {
            "version": self.schema_version,
            "workflow": metadata,
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }
        if self.ui:
            result["ui"] = _copy_mapping(self.ui)
        return result
