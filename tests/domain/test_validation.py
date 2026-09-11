from tg_ifttt.domain.loader import parse_workflow
from tg_ifttt.domain.validation import validate_workflow


def make_workflow(*, nodes, edges=None):
    return parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "test", "name": "Test", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": nodes,
            "edges": edges or [],
        }
    )


def test_validation_rejects_duplicate_node_ids():
    workflow = make_workflow(
        nodes=[
            {"id": "same", "type": "end"},
            {"id": "same", "type": "end"},
        ]
    )
    errors = validate_workflow(workflow)
    assert "duplicate node id" in " ".join(errors)


def test_validation_rejects_unknown_edge_endpoint():
    workflow = make_workflow(
        nodes=[{"id": "start", "type": "end"}],
        edges=[{"from": "start", "to": "missing"}],
    )
    errors = validate_workflow(workflow)
    assert "unknown edge endpoint" in " ".join(errors)


def test_validation_rejects_unreachable_node():
    workflow = make_workflow(
        nodes=[
            {"id": "start", "type": "end"},
            {"id": "orphan", "type": "end"},
        ]
    )
    errors = validate_workflow(workflow)
    assert "unreachable node" in " ".join(errors)


def test_validation_rejects_unbounded_cycle():
    workflow = make_workflow(
        nodes=[
            {"id": "a", "type": "condition"},
            {"id": "b", "type": "condition"},
        ],
        edges=[
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    )
    errors = validate_workflow(workflow)
    assert "unbounded cycle" in " ".join(errors)


def test_validation_accepts_supported_linear_workflow():
    workflow = make_workflow(
        nodes=[
            {"id": "start", "type": "set_variable"},
            {"id": "finish", "type": "end"},
        ],
        edges=[{"from": "start", "to": "finish"}],
    )
    assert validate_workflow(workflow) == []


def test_validation_accepts_fixed_time_schedule_trigger():
    workflow = make_workflow(
        nodes=[
            {"id": "start", "type": "set_variable", "config": {"name": "ran", "value": True}},
            {"id": "finish", "type": "end"},
        ],
        edges=[{"from": "start", "to": "finish"}],
    )
    scheduled = parse_workflow(
        {
            **workflow.to_dict(),
            "triggers": [
                {
                    "type": "schedule",
                    "interval_days": 2,
                    "hour": 9,
                    "minute": 30,
                    "second": 45,
                    "random_seconds": True,
                    "anchor_date": "2026-09-10",
                }
            ],
        }
    )

    assert validate_workflow(scheduled) == []
