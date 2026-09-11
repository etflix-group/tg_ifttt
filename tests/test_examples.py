import asyncio
from pathlib import Path

from tg_ifttt.domain.loader import load_workflow
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.runtime.fake import FakeTelegramAdapter
from tg_ifttt.storage.database import Database


def test_example_workflow_is_executable_without_network(tmp_path):
    workflow = load_workflow(Path("examples/workflows/daily_checkin.yaml"))
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    engine = WorkflowEngine(database, FakeTelegramAdapter.from_settings({}))

    run_id = engine.start(workflow, "example-account", {})
    result = asyncio.run(engine.resume(run_id))

    assert result.status == "success"
    database.close()
