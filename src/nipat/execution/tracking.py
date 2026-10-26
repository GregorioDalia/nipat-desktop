"""Persistent, run-level execution evidence (not scientific validation)."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nipat import __version__
from nipat.errors import ValidationError

HASH_LIMIT_BYTES = 16 * 1024 * 1024


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
