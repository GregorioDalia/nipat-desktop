"""Inspect recorded containers and stop only positively identified NIPAT runs.

Inspection never rewrites the original run status. It is not scientific resume.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.tracking import utc_now


CONTAINER_NAME = re.compile(r"nipat-run-[0-9a-f]{32}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")


def ownership_labels(run_dir: Path, run_id: str) -> dict[str, str]:
    return {
        "org.nipat.product": "nipat-desktop",
        "org.nipat.run-id": run_id,
        "org.nipat.run-path-sha256": hashlib.sha256(
            str(run_dir.resolve()).encode("utf-8")
        ).hexdigest(),
    }


def _load_record(runner, run_dir: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.expanduser().resolve()
    runs_root = runner.layout.runs_dir.resolve()
    if run_dir == runs_root or not run_dir.is_relative_to(runs_root):
        raise ValidationError("Scegliere un run all'interno della cartella risultati configurata.")
    record_path = run_dir / "run.json"
    try:
        if record_path.is_symlink() or record_path.stat().st_size > 16 * 1024 * 1024:
            raise ValidationError("Record del run non valido per la verifica delle esecuzioni.")
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise ValidationError(f"Impossibile leggere il record del run: {run_dir}") from exc
    if (not isinstance(record, dict) or type(record.get("schema_version")) is not int
            or record.get("schema_version") != 1
            or not isinstance(record.get("commands"), list)):
        raise ValidationError("Schema del record del run non supportato.")
    return run_dir, record


def _inspect(runner, name: str) -> dict[str, Any]:
    command = ["docker", "container", "inspect", name, "--format",
               '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
               '"labels":{{json .Config.Labels}},"state":{{json .State.Status}}}']
    try:
        # Do not ensure/start a WSL daemon for this read-only observation.
        result = subprocess.run(
            runner._transport.command(command, runner._environment()),
            env=runner._environment(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, check=False,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode:
            missing = any(text in result.stderr.lower()
                          for text in ("no such container", "no such object"))
            return {"state": "absent" if missing else "unavailable",
                    "error": result.stderr.strip()}
        value = json.loads(result.stdout)
        if (not isinstance(value, dict) or not isinstance(value.get("id"), str)
                or not CONTAINER_ID.fullmatch(value["id"])
                or not isinstance(value.get("state"), str)):
            raise ValueError("Risposta del runtime non valida.")
        return value
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError, RuntimeExecutionError,
            ValidationError) as exc:
        return {"state": "unavailable", "error": str(exc)}


def reconcile_run(runner, run_dir: Path, *, stop: bool = False) -> dict[str, Any]:
    run_dir, record = _load_record(runner, run_dir)
    transport = record.get("transport", {})
    current = runner._transport.metadata
    backend_matches = isinstance(transport, dict) and all(
        transport.get(key) == current.get(key) for key in ("backend", "wsl_distro")
    )
    report = {
        "run_dir": str(run_dir), "run_name": record.get("run_name", run_dir.name),
        "recorded_status": record.get("status"), "observed_at": utc_now(),
        "backend_matches": backend_matches, "containers": [], "stop_requested": stop,
    }
    run_id = record.get("run_id")
    valid_id = isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id)
    expected_labels = ownership_labels(run_dir, run_id) if valid_id else {}
    image = record.get("runtime", {}).get("image_id") if isinstance(record.get("runtime"), dict) else None
    seen = set()
    for command in record["commands"]:
        name = command.get("container_name") if isinstance(command, dict) else None
        if not isinstance(name, str) or not CONTAINER_NAME.fullmatch(name) or name in seen:
            continue
        seen.add(name)
        item: dict[str, Any] = {"container_name": name, "owned": False}
        report["containers"].append(item)
        if not backend_matches:
            item.update(state="identity_mismatch", error="Il run appartiene a un altro backend.")
            continue
        observed = _inspect(runner, name)
        item["state"] = observed["state"]
        if observed.get("error"):
            item["error"] = observed["error"]
        if "id" not in observed:
            continue
        item["container_id"] = observed["id"]
        labels = observed.get("labels") or {}
        item["owned"] = bool(
            expected_labels and isinstance(labels, dict)
            and all(labels.get(key) == value for key, value in expected_labels.items())
            and observed.get("name") == "/" + name
            and isinstance(image, str) and IMAGE_ID.fullmatch(image)
            and observed.get("image") == image
        )
        if not item["owned"]:
            item["error"] = (
                "Identita non confermata: i record precedenti alla 0.7.2 sono consultabili "
                "ma non autorizzano l'arresto automatico."
            )
    if not stop:
        return report
    if runner.dry_run:
        raise ValidationError("L'arresto richiede una verifica reale; rimuovere --dry-run.")
    active = [item for item in report["containers"]
              if item["state"] in {"running", "restarting", "paused"}]
    if not active or any(not item["owned"] for item in active):
        raise ValidationError("Nessun container attivo identificato in modo sicuro per questo run.")
    destination = run_dir / "recovery.json"
    if destination.is_symlink():
        raise ValidationError("recovery.json non deve essere un collegamento simbolico.")
    previous_reports = []
    if destination.exists():
        try:
            previous_document = json.loads(destination.read_text(encoding="utf-8"))
            previous_reports = previous_document["observations"]
            if not isinstance(previous_reports, list):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            raise ValidationError("Il precedente recovery.json non e leggibile; arresto non eseguito.") from exc
    previous = runner._bundled_workflow
    try:
        workflow = record.get("bundled_workflow")
        runner._bundled_workflow = workflow if isinstance(workflow, str) else None
        for item in active:
            # Use the immutable container ID verified above, never a reusable name.
            item["cleanup"] = runner._stop_container(item["container_id"])
    finally:
        runner._bundled_workflow = previous
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=run_dir,
                                     prefix=".recovery-", suffix=".json", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump({"schema_version": 1, "observations": [*previous_reports, report]},
                  handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def incomplete_runs(runner) -> list[dict[str, Any]]:
    reports = []
    if not runner.layout.runs_dir.is_dir():
        return reports
    for path in sorted(runner.layout.runs_dir.glob("*/run.json")):
        try:
            run_dir, record = _load_record(runner, path.parent)
            if record.get("status") in {"preparing", "running", "interrupted", "failed"}:
                reports.append(reconcile_run(runner, run_dir))
        except ValidationError as exc:
            reports.append({"run_dir": str(path.parent), "run_name": path.parent.name,
                            "recorded_status": "unreadable", "observed_at": utc_now(),
                            "backend_matches": False, "containers": [], "stop_requested": False,
                            "error": str(exc)})
    return reports
