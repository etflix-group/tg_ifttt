import json
import subprocess
import sys
from pathlib import Path

from tg_ifttt.cli.qinglong import run_selected_workflows


def test_runner_executes_fake_workflow(tmp_path, capsys):
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    workflow = workflow_dir / "daily.yaml"
    workflow.write_text(
        "version: 1\n"
        "workflow:\n"
        "  id: daily\n"
        "  name: Daily\n"
        "  enabled: true\n"
        "  account: account-a\n"
        "triggers:\n"
        "  - type: manual\n"
        "nodes:\n"
        "  - id: send\n"
        "    type: telegram.send_message\n"
        "    config:\n"
        "      target: '@bot'\n"
        "      text: '/start'\n"
        "  - id: click\n"
        "    type: telegram.click_button\n"
        "    config:\n"
        "      target: '@bot'\n"
        "      match:\n"
        "        type: regex\n"
        "        value: '签到'\n"
        "edges:\n"
        "  - from: send\n"
        "    to: click\n"
    )
    config = tmp_path / "config.yaml"
    config.write_text("adapter: fake\nworkflows:\n  - workflows/daily.yaml\n")

    exit_code = run_selected_workflows(config, None)

    assert exit_code == 0
    assert "status=success" in capsys.readouterr().out


def test_generated_runner_can_run_outside_source_checkout(tmp_path):
    source_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "tg_ifttt_qinglong.py"
    subprocess.run(
        [sys.executable, "scripts/build_qinglong_runner.py", "--output", str(output)],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"adapter": "fake", "workflows": []}))
    result = subprocess.run(
        [sys.executable, str(output), "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "No workflows selected" in result.stdout
