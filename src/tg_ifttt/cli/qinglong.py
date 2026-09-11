import argparse
import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from tg_ifttt.domain.loader import load_workflow
from tg_ifttt.runtime.engine import WorkflowEngine
from tg_ifttt.storage.database import Database
from tg_ifttt.telegram.factory import AdapterFactory, AdapterFactoryError


class QinglongError(RuntimeError):
    """Raised for actionable Qinglong runner configuration errors."""


def _load_document(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            if path.suffix.lower() in {".yaml", ".yml"}:
                document = yaml.safe_load(handle)
            elif path.suffix.lower() == ".json":
                document = json.load(handle)
            else:
                raise QinglongError("unsupported config extension: %s" % path.suffix)
    except OSError as exc:
        raise QinglongError("unable to read config %s: %s" % (path, exc)) from exc
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise QinglongError("unable to decode config %s: %s" % (path, exc)) from exc
    if not isinstance(document, dict):
        raise QinglongError("config root must be a mapping")
    return document


def discover_config(script_path: Path, override: Optional[str]) -> Path:
    candidates: List[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    environment_override = os.environ.get("TG_IFTTT_CONFIG")
    if environment_override and not override:
        candidates.append(Path(environment_override).expanduser())
    if not candidates:
        candidates.extend(
            [
                script_path.resolve().parent / "config.yaml",
                script_path.resolve().parent / "config.json",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise QinglongError("config file not found; searched: %s" % searched)


def discover_workflows(config_path: Path) -> List[Path]:
    document = _load_document(config_path)
    raw_workflows = document.get("workflows")
    candidates: List[Path] = []
    if raw_workflows is None:
        workflow_dir = config_path.parent / "workflows"
        candidates.extend(workflow_dir.glob("*.yaml"))
        candidates.extend(workflow_dir.glob("*.yml"))
        candidates.extend(workflow_dir.glob("*.json"))
    elif isinstance(raw_workflows, list):
        for item in raw_workflows:
            if isinstance(item, str):
                candidates.append(config_path.parent / item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                candidates.append(config_path.parent / item["path"])
            else:
                raise QinglongError("each workflow entry must be a path or mapping with path")
    else:
        raise QinglongError("config workflows must be a list")
    unique = {candidate.resolve() for candidate in candidates}
    return sorted(unique, key=lambda item: str(item))


def _make_adapter(config: Dict[str, Any], database: Optional[Database] = None) -> Any:
    try:
        return AdapterFactory.from_config(config, database=database)
    except AdapterFactoryError as exc:
        raise QinglongError(str(exc)) from exc


async def _run_selected_workflows(
    paths: List[Path],
    config: Dict[str, Any],
    database: Database,
    adapter: Any,
) -> int:
    failures = 0
    for path in paths:
        try:
            workflow = load_workflow(path)
            if not workflow.enabled:
                print("[INFO] workflow=%s status=disabled" % workflow.workflow_id)
                continue
            account_id = workflow.account or config.get("default_account") or "default"
            engine = WorkflowEngine(database, adapter)
            run_id = engine.start(workflow, account_id, {})
            result = await engine.resume(run_id)
            print(
                "[INFO] workflow=%s run=%s status=%s"
                % (workflow.workflow_id, run_id, result.status)
            )
            if result.status != "success":
                failures += 1
        except Exception as exc:
            failures += 1
            print("[ERROR] workflow=%s status=failed error=%s" % (path.name, exc))
    return failures


def _persist_workflow_files(paths: List[Path], database: Database) -> None:
    for path in paths:
        workflow = load_workflow(path)
        version_id = hashlib.sha256(
            json.dumps(workflow.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        database.workflows.save_version(workflow, version_id)


def run_selected_workflows(config_path: Path, workflow_id: Optional[str], poll_events: bool = False) -> int:
    config = _load_document(config_path)
    paths = discover_workflows(config_path)
    if workflow_id:
        selected_paths = []
        for path in paths:
            workflow = load_workflow(path)
            if workflow.workflow_id == workflow_id:
                selected_paths.append(path)
        paths = selected_paths
    if not paths:
        print("[INFO] No workflows selected")
        return 0

    data_dir = Path(config.get("data_dir", config_path.parent / "data"))
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir
    database = Database.connect(data_dir / "state.sqlite3")
    database.initialize()
    adapter = _make_adapter(config, database=database)
    try:
        if poll_events:
            _persist_workflow_files(paths, database)
            from tg_ifttt.runtime.triggers import EventListenerWorker

            worker = EventListenerWorker(
                database,
                adapter,
                default_account=config.get("default_account"),
            )
            results = asyncio.run(worker.poll_once())
            for result in results:
                print(
                    "[INFO] event run=%s status=%s" % (result.run_id, result.status)
                )
            return 0 if all(result.status == "success" for result in results) else 1
        failures = asyncio.run(_run_selected_workflows(paths, config, database, adapter))
    finally:
        database.close()
    return 1 if failures else 0


def _package_payload(source_root: Path) -> str:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        package_root = source_root / "src" / "tg_ifttt"
        for path in sorted(package_root.rglob("*.py")):
            archive.write(path, "tg_ifttt/%s" % path.relative_to(package_root).as_posix())
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build_runner(output_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[3]
    payload = _package_payload(source_root)
    digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
    runner = textwrap.dedent(
        """
        #!/usr/bin/env python3
        import base64
        import hashlib
        import importlib
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        PAYLOAD_SHA256 = {digest!r}
        PAYLOAD = {payload!r}
        REQUIREMENTS = ("PyYAML==6.0.1", "cryptography==45.0.7", "Telethon==1.44.0")

        def bootstrap_dependencies():
            dependency_root = Path(tempfile.gettempdir()) / "tg_ifttt_dependencies"
            missing = []
            for module_name in ("yaml", "cryptography", "telethon"):
                try:
                    importlib.import_module(module_name)
                except ImportError:
                    missing.append(module_name)
            if missing:
                dependency_root.mkdir(parents=True, exist_ok=True)
                command = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--target",
                    str(dependency_root),
                ] + list(REQUIREMENTS)
                subprocess.check_call(command)
            sys.path.insert(0, str(dependency_root))

        def install_source_payload():
            cache_root = Path(tempfile.gettempdir()) / "tg_ifttt_source"
            cache_root.mkdir(parents=True, exist_ok=True)
            archive_path = cache_root / (PAYLOAD_SHA256 + ".zip")
            if not archive_path.exists():
                archive_path.write_bytes(base64.b64decode(PAYLOAD))
            sys.path.insert(0, str(archive_path))

        def main():
            bootstrap_dependencies()
            install_source_payload()
            from tg_ifttt.cli.qinglong import main as runner_main
            return runner_main()

        if __name__ == "__main__":
            raise SystemExit(main())
        """
    ).format(digest=digest, payload=payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(runner, encoding="utf-8")
    output_path.chmod(0o755)
    return output_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Telegram IFTTT workflows in Qinglong")
    parser.add_argument("--config", help="YAML or JSON config path")
    parser.add_argument("--workflow-id", help="run only one workflow ID")
    parser.add_argument(
        "--poll-events",
        action="store_true",
        help="poll Telegram event triggers once, then exit",
    )
    args = parser.parse_args(argv)
    try:
        config_path = discover_config(Path(__file__), args.config)
        return run_selected_workflows(config_path, args.workflow_id, args.poll_events)
    except QinglongError as exc:
        print("[ERROR] %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
