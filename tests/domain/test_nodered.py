import pytest

from tg_ifttt.domain.nodered import NodeRedFlowError, compile_node_red_flow, export_node_red_flow


def _flow():
    return [
        {"id": "tab-1", "type": "tab", "label": "每日签到", "disabled": False},
        {
            "id": "meta-1",
            "type": "tg-workflow",
            "z": "tab-1",
            "workflow_id": "daily",
            "workflow_name": "每日签到",
            "enabled": True,
            "account": "account-a",
            "triggers_json": '[{"type":"manual"}]',
            "wires": [],
        },
        {
            "id": "trigger-1",
            "type": "tg-trigger",
            "z": "tab-1",
            "trigger_type": "manual",
            "wires": [["send-1"]],
        },
        {
            "id": "send-1",
            "type": "tg-send-message",
            "z": "tab-1",
            "target": "@example_bot",
            "text": "/start",
            "wires": [["click-1"]],
        },
        {
            "id": "click-1",
            "type": "tg-click-button",
            "z": "tab-1",
            "target": "@example_bot",
            "keyboard": "auto",
            "match_type": "regex",
            "match_value": "每日签到",
            "after_message_id": "{{ steps.send-1.message_id }}",
            "wires": [["end-1"]],
        },
        {"id": "end-1", "type": "tg-end", "z": "tab-1", "wires": [[]]},
    ]


def test_compile_node_red_flow_maps_safe_nodes_and_ignores_editor_metadata_edges():
    document = compile_node_red_flow(_flow())

    assert document == {
        "version": 1,
        "workflow": {"id": "daily", "name": "每日签到", "enabled": True, "account": "account-a"},
        "triggers": [{"type": "manual"}],
        "nodes": [
            {
                "id": "send-1",
                "type": "telegram.send_message",
                "config": {"target": "@example_bot", "text": "/start"},
            },
            {
                "id": "click-1",
                "type": "telegram.click_button",
                "config": {
                    "target": "@example_bot",
                    "keyboard": "auto",
                    "match": {"type": "regex", "value": "每日签到"},
                    "after_message_id": "{{ steps.send-1.message_id }}",
                },
            },
            {"id": "end-1", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "send-1", "to": "click-1"},
            {"from": "click-1", "to": "end-1"},
        ],
    }


def test_compile_node_red_flow_rejects_arbitrary_execution_nodes():
    flow = _flow()
    flow[3] = {"id": "unsafe", "type": "function", "z": "tab-1", "func": "msg.payload = 1", "wires": [[]]}

    with pytest.raises(NodeRedFlowError, match="unsupported Node-RED node type: function"):
        compile_node_red_flow(flow)


def test_compile_node_red_flow_selects_only_the_requested_tab():
    flow = _flow() + [
        {"id": "tab-2", "type": "tab", "label": "Other", "disabled": False},
        {
            "id": "meta-2",
            "type": "tg-workflow",
            "z": "tab-2",
            "workflow_id": "other",
            "workflow_name": "Other",
            "enabled": True,
            "account": "other-account",
            "triggers_json": '[{"type":"cron","expression":"0 1 * * *"}]',
            "wires": [],
        },
        {"id": "trigger-2", "type": "tg-trigger", "z": "tab-2", "trigger_type": "cron", "expression": "0 1 * * *", "wires": [["send-2"]]},
        {"id": "send-2", "type": "tg-send-message", "z": "tab-2", "target": "@other", "text": "hello", "wires": [["end-2"]]},
        {"id": "end-2", "type": "tg-end", "z": "tab-2", "wires": [[]]},
    ]

    document = compile_node_red_flow(flow, expected_workflow_id="daily")

    assert document["workflow"]["id"] == "daily"
    assert document["triggers"] == [{"type": "manual"}]
    assert [node["id"] for node in document["nodes"]] == ["send-1", "click-1", "end-1"]


def test_export_node_red_flow_round_trips_the_canonical_document():
    document = compile_node_red_flow(_flow())

    assert compile_node_red_flow(export_node_red_flow(document)) == document


def test_node_red_bridge_preserves_canvas_node_positions():
    flow = _flow()
    flow[3].update(x=180, y=120)
    flow[4].update(x=520, y=120)
    flow[5].update(x=860, y=120)

    document = compile_node_red_flow(flow)
    assert document["ui"]["nodes"] == {
        "send-1": {"x": 180, "y": 120},
        "click-1": {"x": 520, "y": 120},
        "end-1": {"x": 860, "y": 120},
    }

    exported = export_node_red_flow(document)
    positions = {node["tg_node_id"]: (node["x"], node["y"]) for node in exported if "tg_node_id" in node}
    assert positions == {"send-1": (180, 120), "click-1": (520, 120), "end-1": (860, 120)}


def test_node_red_bridge_preserves_optional_action_names():
    flow = _flow()
    flow[3]["name"] = "启动面板"
    flow[4]["name"] = "点击签到"

    document = compile_node_red_flow(flow)
    assert [node.get("name") for node in document["nodes"]] == ["启动面板", "点击签到", None]

    exported = export_node_red_flow(document)
    names = {node["tg_node_id"]: node["name"] for node in exported if "tg_node_id" in node}
    assert names["send-1"] == "启动面板"
    assert names["click-1"] == "点击签到"


def test_node_red_bridge_round_trips_fixed_time_schedule():
    flow = _flow()
    flow[2].update(
        trigger_type="schedule",
        interval_days=2,
        hour=9,
        minute=30,
        second=45,
        random_seconds=True,
        anchor_date="2026-09-10",
    )

    document = compile_node_red_flow(flow)
    assert document["triggers"] == [
        {
            "type": "schedule",
            "interval_days": 2,
            "hour": 9,
            "minute": 30,
            "second": 45,
            "random_seconds": True,
            "anchor_date": "2026-09-10",
        }
    ]
    assert compile_node_red_flow(export_node_red_flow(document)) == document
