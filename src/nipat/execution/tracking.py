"""Persistent, run-level execution evidence (not scientific validation)."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nipat import __version__

HASH_LIMIT_BYTES = 16 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_evidence(path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    evidence: dict[str, Any] = {
        "path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
    }
    if stat.st_size <= HASH_LIMIT_BYTES:
        with path.open("rb") as handle:
            evidence["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
    else:
        evidence["sha256"] = None
        evidence["hash_note"] = (
            "Not hashed: input exceeds 16 MiB; size/mtime are metadata, not content identity."
        )
    return evidence


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
