"""Persistent, run-level execution evidence (not scientific validation)."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nipat import __version__
from nipat.errors import ValidationError

HASH_LIMIT_BYTES = 16 * 1024 * 1024
MAX_RUN_METADATA_BYTES = 32 * 1024 * 1024
WORKFLOW_STEPS = {
    "dnp-contamination": {"dnp": "dnp-call", "contamination": "contamination"},
    "dnp-cpi": {"dnp": "dnp-call", "cpi": "cpi"},
    "dnp-contamination-cpi": {"dnp": "dnp-call", "contamination": "contamination", "cpi": "cpi"},
    "snp-batch": {},
    "analysis": {},
}
_RUN_STATUSES = {"preparing", "planned", "running", "succeeded", "failed", "interrupted", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot(stat) -> dict[str, int]:
    return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns, "device": stat.st_dev, "inode": stat.st_ino}


def file_evidence(
    path: Path, *, mode: str = "auto",
    progress: Callable[[Path, int, int], None] | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    evidence: dict[str, Any] = {
        "path": str(path), **_snapshot(stat), "recorded_at": utc_now(),
    }
    if mode not in {"auto", "full"}:
        raise ValidationError("Modalita di checksum degli input non valida.")
    if mode == "full" or stat.st_size <= HASH_LIMIT_BYTES:
        digest = hashlib.sha256()
        completed = 0
        with path.open("rb") as handle:
            if progress:
                progress(path, 0, stat.st_size)
            while block := handle.read(1024 * 1024):
                digest.update(block)
                completed += len(block)
                if progress:
                    progress(path, completed, stat.st_size)
        evidence["sha256"] = digest.hexdigest()
        evidence["hash_method"] = "sha256-full-content"
    else:
        evidence["sha256"] = None
        evidence["hash_note"] = (
            "Not hashed: input exceeds 16 MiB; size/mtime are metadata, not content identity."
        )
    if _snapshot(path.stat()) != _snapshot(stat):
        raise ValidationError(f"Input modificato durante la raccolta della provenienza: {path}")
    return evidence


def verify_input_evidence(
    evidence: dict[str, Any], *, progress: Callable[[Path, int, int], None] | None = None,
) -> None:
    """Re-read hashed inputs; metadata-only records cannot prove content identity."""
    path = Path(evidence["path"])
    try:
        current = _snapshot(path.stat())
        if any(current[key] != evidence.get(key) for key in current):
            raise ValidationError(f"Input modificato dopo la preparazione: {path}")
        if evidence.get("sha256") is not None:
            observed = file_evidence(path, mode="full", progress=progress)
            if observed["sha256"] != evidence["sha256"]:
                raise ValidationError(f"Contenuto dell'input modificato dopo la preparazione: {path}")
    except OSError as exc:
        raise ValidationError(f"Input non piu accessibile dopo la preparazione: {path}") from exc


def project_evidence(project: Path) -> dict[str, Any]:
    files = list((project / "src").rglob("*.py"))
    files += list((project / "scientific").rglob("*.R"))
    files += [project / name for name in (
        "scientific/SHA256SUMS", "compose.yaml", "pyproject.toml",
        "docker/scientific-runtime/Dockerfile",
    )]
    hashes = {}
    for path in sorted(set(files)):
        if path.is_file():
            with path.open("rb") as handle:
                hashes[path.relative_to(project).as_posix()] = hashlib.file_digest(
                    handle, "sha256"
                ).hexdigest()
    result: dict[str, Any] = {
        "nipat_version": __version__, "file_sha256": hashes, "git": None, "release": None,
    }
    # Do not accidentally report a parent workspace's repository as this project.
    if (project / ".git").exists():
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project, check=True,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=project, check=True,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            ).stdout
            result["git"] = {"commit": head, "dirty": bool(status.strip())}
        except (OSError, subprocess.SubprocessError):
            result["git_note"] = "Git metadata unavailable; use file hashes."
    release = project / "release.json"
    if release.is_file():
        try:
            result["release"] = json.loads(release.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result["release_note"] = "release.json could not be read."
    return result


def run_owned_path(run_dir: Path, relative: str) -> Path:
    """Resolve only fixed, run-owned locations; do not follow linked entries."""
    run_dir = run_dir.expanduser().resolve()
    path = run_dir
    for component in Path(relative).parts:
        path = path / component
        if path.is_symlink():
            raise ValueError(f"Percorso collegato non consultabile: {relative}")
    if not path.resolve().is_relative_to(run_dir):
        raise ValueError(f"Percorso esterno alla cartella del run: {relative}")
    return path


def read_run_metadata(run_dir: Path, relative: str = "run.json", *,
                      max_bytes: int = MAX_RUN_METADATA_BYTES) -> dict:
    path = run_owned_path(run_dir, relative)
    if not path.is_file():
        raise ValueError(f"File non disponibile: {relative}")
    # Bound the actual read as well as its reported size, including a file
    # replaced or extended between the size check and open.
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{relative} supera il limite di lettura ({max_bytes // (1024 * 1024)} MiB)")
    with path.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"{relative} supera il limite di lettura ({max_bytes // (1024 * 1024)} MiB)")
    try:
        metadata = json.loads(content.decode("utf-8-sig"))
    except RecursionError as exc:
        raise ValueError(f"Struttura JSON troppo complessa: {relative}") from exc
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 1):
        raise ValueError(f"Formato di {relative} non supportato")
    return metadata


def workflow_steps(metadata: dict) -> list[dict]:
    """Accept only preset-owned IDs and complete, ordered per-sample SNP mappings."""
    workflow = metadata["workflow"]
    expected = [{"id": step_id, "workflow": kind}
                for step_id, kind in WORKFLOW_STEPS[workflow].items()]
    parameters = metadata.get("parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    supplied = parameters.get("expected_steps")
    if workflow == "analysis":
        from nipat_scientific.plan import validate_plan
        from nipat_scientific.errors import ValidationError
        try:
            plan = validate_plan(parameters.get("plan"))["plan"]
        except ValidationError as exc:
            raise ValueError("Piano registrato non valido") from exc
        expected = [{"id": step["id"], "workflow": step["workflow"],
                     **({"sample": step["inputs"]["sample"], "mode": step["parameters"]["mode"]}
                        if step["workflow"] == "snp-call" else {})} for step in plan["steps"]]
        if supplied != expected:
            raise ValueError("Elenco dei passaggi e piano registrato non coerenti")
        mapping = parameters.get("sample_mapping")
        if not isinstance(mapping, list) or any(not isinstance(item, dict) for item in mapping):
            raise ValueError("Associazioni dei campioni non valide")
        sources = {item.get("sample_id"): item for item in mapping if isinstance(item.get("sample_id"), str)}
        if len(sources) != len(mapping) or set(sources) != {item["id"] for item in plan["samples"]}:
            raise ValueError("Campioni registrati non coerenti con il piano")
        for sample in plan["samples"]:
            source = sources[sample["id"]]
            if source.get("container_path") != sample["path"] or not isinstance(source.get("original_path"), str):
                raise ValueError("Percorsi registrati non coerenti con il piano")
        return expected
    has_snp = workflow == "snp-batch" or parameters.get("snp_panel") is not None
    if supplied is None and not has_snp:
        # Runs produced before the per-sample extension had only fixed steps.
        return expected
    if has_snp:
        if workflow != "snp-batch" and (
            not isinstance(parameters.get("snp_panel"), str) or not parameters["snp_panel"]
        ):
            raise ValueError("Pannello SNP registrato non valido")
        mode = parameters.get("mode") if workflow == "snp-batch" else "bam"
        samples = parameters.get("sample_mapping")
        if mode not in ("bam", "pileup") or not isinstance(samples, list) or not samples:
            raise ValueError("Associazioni dei campioni SNP non valide")
        snp_steps = []
        for number, sample in enumerate(samples, 1):
            identifier = f"sample_{number:04d}"
            if (not isinstance(sample, dict) or sample.get("sample_id") != identifier
                    or not isinstance(sample.get("original_path"), str) or not sample["original_path"]
                    or not isinstance(sample.get("container_path"), str) or not sample["container_path"]):
                raise ValueError("Associazioni dei campioni SNP non valide")
            snp_steps.append({"id": f"snp_{number:04d}", "workflow": "snp-call",
                              "sample": identifier, "mode": mode})
        expected.extend(sorted(snp_steps, key=lambda step: step["id"]))
    if supplied != expected:
        raise ValueError("Elenco dei passaggi attesi non valido")
    return expected


def read_workflow_state(run_dir: Path, workflow: str, metadata: dict | None = None) -> dict:
    metadata = read_run_metadata(run_dir) if metadata is None else metadata
    if metadata.get("workflow") != workflow:
        raise ValueError("Workflow e metadati non coerenti")
    state = read_run_metadata(run_dir, "output/workflow/workflow-state.json")
    steps = state.get("steps")
    allowed = {"pending", "running", "succeeded", "failed", "cancelled", "blocked"}
    expected = {step["id"]: step for step in workflow_steps(metadata)}
    if (state.get("interface") != "workflow-plan-execution-v2"
            or not isinstance(state.get("status"), str)
            or state.get("status") not in {"running", "succeeded", "failed", "cancelled"}
            or not isinstance(steps, list) or len(steps) != len(expected)
            or any(not isinstance(step, dict) or not isinstance(step.get("id"), str)
                   or step.get("id") not in expected
                   or step.get("workflow") != expected[step["id"]]["workflow"]
                   or not isinstance(step.get("status"), str) or step["status"] not in allowed
                   for step in steps)
            or {step["id"] for step in steps} != set(expected)):
        raise ValueError("Stato del workflow automatico non valido")
    if state["status"] == "succeeded" and any(step["status"] != "succeeded" for step in steps):
        raise ValueError("Stato complessivo e stati dei passaggi non coerenti")
    parameters = metadata.get("parameters")
    mapping = parameters.get("sample_mapping", []) if isinstance(parameters, dict) else []
    # workflow_steps validates the complete mapping whenever a SNP step is present.
    samples = {row["sample_id"]: row for row in mapping} if any(
        step["workflow"] == "snp-call" for step in steps) else {}
    for step in steps:
        declared = expected[step["id"]]
        if declared["workflow"] != "snp-call":
            continue
        source = samples[declared["sample"]]
        observed = step.get("sample_mapping")
        if (observed is not None or step["status"] == "succeeded") and observed != {
            "sample": declared["sample"], "mode": declared["mode"], "path": source["container_path"],
        }:
            raise ValueError("Passaggio SNP e campione atteso non coerenti")
        if step["status"] != "succeeded":
            continue
        artifacts = step.get("artifacts")
        tables = artifacts.get("snp-tables") if isinstance(artifacts, dict) else None
        if (not isinstance(tables, list) or len(tables) != 1
                or not isinstance(tables[0], dict) or tables[0].get("sample") != declared["sample"]):
            raise ValueError("Risultato SNP e campione atteso non coerenti")
    return state


def read_run_status(run_dir: Path, metadata: dict | None = None) -> str:
    """Read the client outcome and confirm success against the workflow's steps."""
    try:
        metadata = read_run_metadata(run_dir) if metadata is None else metadata
        status = metadata.get("status")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            return "unreadable"
        workflow = metadata.get("workflow")
        if isinstance(workflow, str) and workflow in WORKFLOW_STEPS and status == "succeeded":
            status = read_workflow_state(run_dir, workflow, metadata)["status"]
            if status == "running":
                return "unreadable"
        return status
    except (OSError, ValueError):
        return "unreadable"


@dataclass(frozen=True)
class RunOutcome:
    """Persisted outcome after the command and client-side checks finish."""

    run_dir: Path
    run_id: str
    status: str


class RunRecord:
    def __init__(self, run_dir: Path, workflow: str, parameters: dict[str, Any]):
        self.run_dir = run_dir
        self.path = run_dir / "run.json"
        self.log_path = run_dir / "execution.log"
        if self.path.exists() or self.log_path.exists():
            raise FileExistsError(f"Run evidence already exists: {run_dir}")
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "run_id": uuid.uuid4().hex,
            "run_name": run_dir.name,
            "workflow": workflow,
            "status": "preparing",
            "started_at": utc_now(),
            "finished_at": None,
            "parameters": parameters,
            "inputs": [],
            "input_hash_limit_bytes": HASH_LIMIT_BYTES,
            "host": {"system": platform.platform(), "python": sys.version,
                     "python_executable": sys.executable},
            "source": {}, "runtime": {}, "checks": [], "commands": [],
            "error": None,
        }
        self.save()

    def save(self) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)
