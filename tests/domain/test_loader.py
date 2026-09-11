from pathlib import Path

from tg_ifttt.domain.loader import load_workflow, parse_workflow


def test_load_yaml_workflow():
    workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    assert workflow.workflow_id == "daily-checkin"
    assert workflow.nodes[1].node_type == "telegram.click_button"
    assert workflow.nodes[1].config["match"]["type"] == "regex"


def test_yaml_and_json_have_same_canonical_shape():
    yaml_workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.yaml"))
    json_workflow = load_workflow(Path("tests/fixtures/workflows/daily_checkin.json"))
    assert yaml_workflow.to_dict() == json_workflow.to_dict()


def test_node_display_name_is_optional_and_round_trips():
    workflow = parse_workflow(
        {
            "version": 1,
            "workflow": {"id": "named", "name": "Named", "enabled": True},
            "triggers": [{"type": "manual"}],
            "nodes": [{"id": "start", "name": "开始", "type": "end", "config": {}}],
            "edges": [],
        }
    )

    assert workflow.nodes[0].name == "开始"
    assert workflow.to_dict()["nodes"][0]["name"] == "开始"
