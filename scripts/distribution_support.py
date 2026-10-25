"""Verified distribution inputs shared by NIPAT installer builders."""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path


PYTHON_NAME = "python-3.12.10-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/3.12.10/{PYTHON_NAME}"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
SOURCE_MANIFEST = "distribution-files.txt"
EXCLUDED_PARTS = {
    ".git", ".venv", ".runtime", ".distribution", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "data", "runs", "logs", "dist", "build",
    "secrets", "credentials",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(project: Path) -> list[Path]:
    """Read the explicit source allowlist; unlisted local files are never inspected."""
    project = project.resolve()
    manifest = project / SOURCE_MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError(f"Manifest della distribuzione mancante o non valido: {manifest}")
    selected: list[Path] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(manifest.read_text(encoding="utf-8-sig").splitlines(), start=1):
        relative = raw_line.strip()
        if not relative or relative.startswith("#"):
            continue
        parts = relative.split("/")
        if ("\\" in relative or ":" in relative
                or any(part in {"", ".", ".."} for part in parts)):
            raise ValueError(f"Percorso non valido nel manifest, riga {number}: {relative}")
        key = relative.casefold()
        if key in seen:
            raise ValueError(f"Percorso duplicato nel manifest: {relative}")
        seen.add(key)
        if any(part.lower() in EXCLUDED_PARTS or part.lower().endswith(".egg-info") for part in parts):
            raise ValueError(f"Cartella locale vietata nel manifest: {relative}")
        if any(part.lower() == ".env" for part in parts):
            raise ValueError(f"Configurazione privata vietata nel manifest: {relative}")
        path = project
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Collegamento simbolico vietato nel manifest: {relative}")
        if not path.is_file() or not path.resolve().is_relative_to(project):
            raise ValueError(f"File approvato mancante o non valido: {relative}")
        selected.append(path)
    if SOURCE_MANIFEST not in {path.relative_to(project).as_posix() for path in selected}:
        raise ValueError(f"Il manifest deve includere se stesso: {SOURCE_MANIFEST}")
    return sorted(selected)


def require_python_archive(path: Path) -> Path:
    if not path.is_file() or sha256_file(path) != PYTHON_SHA256:
        raise ValueError(f"Archivio Python non valido o checksum errato: {path}")
    return path


def python_archive(project: Path, requested: Path | None, temporary: Path) -> Path:
    if requested is not None:
        return require_python_archive(requested)
    bundled = project / ".distribution" / PYTHON_NAME
    if bundled.is_file():
        return require_python_archive(bundled)
    destination = temporary / PYTHON_NAME
    print(f"Download di Python portabile da {PYTHON_URL}", flush=True)
    with urllib.request.urlopen(PYTHON_URL, timeout=120) as response, destination.open("xb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    return require_python_archive(destination)


def git_source(project: Path) -> dict:
    # No repository is also valid: the release manifest and source hashes identify a ZIP.
    if not (project / ".git").exists():
        return {"commit": None, "dirty": None, "available": False}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=project,
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout
        return {"commit": commit, "dirty": bool(status), "available": True}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "available": False}
