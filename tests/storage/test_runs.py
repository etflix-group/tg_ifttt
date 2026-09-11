from tg_ifttt.storage.database import Database


def test_checkpoint_can_be_loaded_after_reopening_database(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = Database.connect(path)
    first.initialize()
    run_id = first.runs.create_run("daily-checkin", "v1", "account-a")
    first.runs.checkpoint_node(run_id, "send_start", {"message_id": 42}, "click_checkin")
    first.close()

    second = Database.connect(path)
    recovered = second.runs.load_run(run_id)
    assert recovered.current_node_id == "click_checkin"
    assert recovered.node_outputs["send_start"]["message_id"] == 42
    second.close()


def test_recoverable_runs_include_running_and_waiting(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    running = database.runs.create_run("one", "v1", "account-a")
    waiting = database.runs.create_run("two", "v1", "account-a")
    database.runs.set_status(waiting, "waiting")
    database.runs.set_status(running, "running")
    assert {item.run_id for item in database.runs.list_recoverable_runs()} == {running, waiting}
    database.close()


def test_account_lease_allows_one_run_at_a_time(tmp_path):
    database = Database.connect(tmp_path / "state.sqlite3")
    database.initialize()
    first = database.runs.create_run("one", "v1", "account-a")
    second = database.runs.create_run("two", "v1", "account-a")

    assert database.runs.acquire_lease("account-a", first, ttl_seconds=60) is True
    assert database.runs.acquire_lease("account-a", second, ttl_seconds=60) is False
    database.runs.release_lease("account-a", first)
    assert database.runs.acquire_lease("account-a", second, ttl_seconds=60) is True
    database.close()
