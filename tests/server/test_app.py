from types import SimpleNamespace

from fastapi.testclient import TestClient

from tg_ifttt.runtime.fake import FakeTelegramAdapter
from tg_ifttt.server.app import create_app
from tg_ifttt.telegram.models import TelegramAccount


WORKFLOW = {
    "version": 1,
    "workflow": {"id": "daily", "name": "Daily", "enabled": True, "account": "account-a"},
    "triggers": [{"type": "manual"}],
    "nodes": [
        {
            "id": "send",
            "type": "telegram.send_message",
            "config": {"target": "@bot", "text": "/start"},
        },
        {"id": "end", "type": "end"},
    ],
    "edges": [{"from": "send", "to": "end"}],
}

NODE_RED_FLOW = [
    {"id": "tab-1", "type": "tab", "label": "Daily", "disabled": False},
    {
        "id": "meta-1",
        "type": "tg-workflow",
        "z": "tab-1",
        "workflow_id": "daily",
        "workflow_name": "Daily",
        "enabled": True,
        "account": "account-a",
        "triggers_json": '[{"type":"manual"}]',
        "wires": [],
    },
    {"id": "trigger-1", "type": "tg-trigger", "z": "tab-1", "trigger_type": "manual", "wires": [["send-1"]]},
    {
        "id": "send-1",
        "type": "tg-send-message",
        "z": "tab-1",
        "target": "@bot",
        "text": "/start",
        "wires": [["end-1"]],
    },
    {"id": "end-1", "type": "tg-end", "z": "tab-1", "wires": [[]]},
]


class _SingleAccountRepository:
    def list_accounts(self):
        return [TelegramAccount("account-a", "ACCOUNT-A", 123456789, "+10000000000", "ready")]


class _SingleAccountFakeAdapter(FakeTelegramAdapter):
    def __init__(self):
        super().__init__()
        self.session_manager = SimpleNamespace(account_repository=_SingleAccountRepository())


def test_health_is_public_and_management_routes_require_bearer(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/workflows").status_code == 401
        assert client.get("/api/workflows", headers={"Authorization": "Bearer admin-token"}).status_code == 200


def test_workflow_crud_manual_run_and_webhook_are_durable(tmp_path):
    app = create_app(
        tmp_path / "state.sqlite3",
        adapter=FakeTelegramAdapter(),
        admin_token="admin-token",
        webhook_secret="webhook-token",
    )
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        created = client.post("/api/workflows", json=WORKFLOW, headers=headers)
        assert created.status_code == 200
        assert created.json()["version_id"]
        assert client.get("/api/workflows/daily", headers=headers).json()["workflow"]["id"] == "daily"

        run_response = client.post("/api/workflows/daily/run", json={"trigger_payload": {"source": "ui"}}, headers=headers)
        assert run_response.status_code == 200
        run = run_response.json()["run"]
        assert run["status"] == "success"
        assert run["checkpoint_seq"] == 2
        assert client.get("/api/runs/" + run["run_id"], headers=headers).json()["status"] == "success"

        webhook = client.post(
            "/api/webhooks/daily",
            json={"event": "external"},
            headers={"X-TG-IFTTT-Webhook": "webhook-token"},
        )
        assert webhook.status_code == 200
        assert webhook.json()["run"]["trigger_payload"] == {"event": "external"}
        assert client.post("/api/webhooks/daily", json={}, headers={}).status_code == 401


def test_workflow_delete_removes_the_workflow_but_keeps_run_history(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=WORKFLOW, headers=headers).status_code == 200
        run = client.post("/api/workflows/daily/run", json={}, headers=headers).json()["run"]

        deleted = client.delete("/api/workflows/daily", headers=headers)

        assert deleted.status_code == 200
        assert deleted.json() == {"workflow_id": "daily", "deleted": True}
        assert client.get("/api/workflows/daily", headers=headers).status_code == 404
        assert client.get("/api/workflows", headers=headers).json() == []
        assert client.get(f"/api/runs/{run['run_id']}", headers=headers).status_code == 200


def test_workflow_target_is_used_when_telegram_node_does_not_override_it(tmp_path):
    document = {
        **WORKFLOW,
        "workflow": {**WORKFLOW["workflow"], "target": "@shared-chat"},
        "nodes": [
            {"id": "send", "type": "telegram.send_message", "config": {"text": "/start"}},
            {"id": "end", "type": "end"},
        ],
    }
    adapter = FakeTelegramAdapter()
    app = create_app(tmp_path / "state.sqlite3", adapter=adapter, admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=document, headers=headers).status_code == 200
        response = client.post("/api/workflows/daily/run", json={}, headers=headers)

    assert response.status_code == 200
    assert response.json()["result"] == "success"
    assert adapter.sent_texts == [("/start", "@shared-chat")]


def test_invalid_workflow_never_reaches_storage(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    with TestClient(app) as client:
        response = client.post(
            "/api/workflows",
            json={"version": 1, "workflow": {"id": "bad", "name": "Bad"}, "triggers": [], "nodes": []},
            headers={"Authorization": "Bearer admin-token"},
        )
        assert response.status_code == 422
        assert client.get("/api/workflows", headers={"Authorization": "Bearer admin-token"}).json() == []


def test_manual_run_uses_the_only_connected_account_when_workflow_account_is_empty(tmp_path):
    document = dict(WORKFLOW)
    document["workflow"] = {**WORKFLOW["workflow"], "account": ""}
    app = create_app(tmp_path / "state.sqlite3", adapter=_SingleAccountFakeAdapter(), admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=document, headers=headers).status_code == 200
        response = client.post("/api/workflows/daily/run", json={}, headers=headers)

    assert response.status_code == 200
    assert response.json()["run"]["account_id"] == "account-a"


def test_nodered_flow_export_and_import_use_the_workflow_validation_boundary(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=WORKFLOW, headers=headers).status_code == 200

        exported = client.get("/api/workflows/daily/nodered", headers=headers)
        assert exported.status_code == 200
        flow = exported.json()["flow"]
        assert flow[0]["type"] == "tab"
        assert any(node["type"] == "tg-send-message" for node in flow)

        imported = client.put("/api/workflows/daily/nodered", json={"flow": NODE_RED_FLOW}, headers=headers)
        assert imported.status_code == 200
        assert imported.json()["document"]["workflow"]["name"] == "Daily"
        assert client.get("/api/workflows/daily", headers=headers).json()["nodes"][0]["type"] == "telegram.send_message"


def test_nodered_import_rejects_unsafe_nodes_before_saving(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    unsafe = list(NODE_RED_FLOW)
    unsafe[3] = {"id": "unsafe", "type": "function", "z": "tab-1", "func": "return msg", "wires": [[]]}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=WORKFLOW, headers=headers).status_code == 200
        response = client.put("/api/workflows/daily/nodered", json=unsafe, headers=headers)
        assert response.status_code == 422
        assert client.get("/api/workflows/daily", headers=headers).json()["nodes"][0]["id"] == "send"


def test_workflow_canvas_layout_is_persisted_with_the_document(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", adapter=FakeTelegramAdapter(), admin_token="admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    document = {**WORKFLOW, "ui": {"viewport": {"x": -30, "y": 12, "zoom": 0.9}, "nodes": {"send": {"x": 240, "y": 96}}}}
    with TestClient(app) as client:
        assert client.post("/api/workflows", json=document, headers=headers).status_code == 200
        loaded = client.get("/api/workflows/daily", headers=headers)

    assert loaded.status_code == 200
    assert loaded.json()["ui"]["nodes"]["send"] == {"x": 240, "y": 96}
