from pathlib import Path

from tg_ifttt.cli.qinglong import discover_config, discover_workflows


def test_config_defaults_to_yaml_next_to_entrypoint(tmp_path):
    entrypoint = tmp_path / "tg_ifttt_qinglong.py"
    entrypoint.write_text("")
    config = tmp_path / "config.yaml"
    config.write_text("workflows: []")
    assert discover_config(entrypoint, None) == config


def test_environment_override_wins(monkeypatch, tmp_path):
    override = tmp_path / "override.json"
    override.write_text("{}")
    monkeypatch.setenv("TG_IFTTT_CONFIG", str(override))
    assert discover_config(tmp_path / "entry.py", None) == override


def test_workflows_are_loaded_from_config_and_sorted(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "workflows:\n"
        "  - workflows/z.yaml\n"
        "  - workflows/a.yaml\n"
    )
    paths = discover_workflows(config)
    assert paths == [tmp_path / "workflows/a.yaml", tmp_path / "workflows/z.yaml"]
