"""Explicit handoff from the running CLI to a verified platform installer."""

from __future__ import annotations

import hashlib
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from .activity import _safe_parent
from .errors import NipatError

HANDOFF_EXIT_CODE = 85


def _windows_layout(project_dir: Path) -> dict:
    project = project_dir.resolve()
    try:
        layout = json.loads((project / ".runtime/install-layout.json").read_text(encoding="utf-8-sig"))
        fields = ("app_dir", "runtime_dir", "cache_dir", "data_dir", "runs_dir")
        if (set(layout) != {"schema_version", "installation_channel", *fields}
                or type(layout["schema_version"]) is not int or layout["schema_version"] != 1
                or layout["installation_channel"] != "desktop"):
            raise ValueError("identita installazione non valida")
        roots = []
        for field in fields:
            if not isinstance(layout[field], str):
                raise ValueError("destinazione non valida")
            path = Path(layout[field])
            if not path.is_absolute() or path.parent == path:
                raise ValueError("destinazione non assoluta o radice del disco")
            if os.name == "nt":
                if not re.fullmatch(r"[A-Za-z]:", path.drive):
                    raise ValueError("disco locale richiesto")
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
                kernel.GetDriveTypeW.restype = ctypes.c_uint32
                if kernel.GetDriveTypeW(path.anchor) != 3:
                    raise ValueError("disco fisso locale non disponibile")
            _safe_parent(path)
            roots.append(path.resolve())
        if roots[0] != project:
            raise ValueError("cartella applicativa diversa da quella registrata")
        for i, path in enumerate(roots):
            for other in roots[:i]:
                if path == other or path in other.parents or other in path.parents:
                    raise ValueError("destinazioni sovrapposte")
        return dict(layout, **dict(zip(fields, roots)))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise NipatError("Configurazione installata non valida: riaprire il setup NIPAT Desktop prima di aggiornare.") from exc


def update_cache_directory(project_dir: Path) -> Path:
    if sys.platform == "win32":
        path = _windows_layout(project_dir)["cache_dir"] / "updates"
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        if base and not Path(base).is_absolute():
            raise NipatError("XDG_CACHE_HOME deve essere un percorso assoluto prima di scaricare aggiornamenti.")
        root = Path(base) if base else Path.home() / ".cache"
        path = root / "nipat-desktop" / "updates"
    _safe_parent(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise NipatError("La cache degli aggiornamenti non e scrivibile.") from exc
    _safe_parent(path)
    return path


def _verify_package(package: Path, sha256: str, size: int) -> None:
    _safe_parent(package)
    if (not re.fullmatch(r"[a-f0-9]{64}", sha256) or type(size) is not int or size <= 0
            or not package.is_file() or package.stat().st_size != size):
        raise NipatError("Il pacchetto scaricato non corrisponde all'aggiornamento verificato.")
    digest = hashlib.sha256()
    with package.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        raise NipatError("SHA-256 del pacchetto non valido. Ripetere il download prima di installare.")


def _canonical_package(package: Path) -> Path:
    # Reject links before resolving: resolution must normalize legitimate Windows
    # short-name aliases without concealing a junction or symbolic link.
    package = Path(package).absolute()
    _safe_parent(package)
    try:
        return package.resolve(strict=True)
    except OSError as exc:
        raise NipatError("Il pacchetto scaricato non e piu disponibile.") from exc


def _start_windows_update(offer, package: Path, project_dir: Path) -> bool:
    package = _canonical_package(package)
    layout = _windows_layout(project_dir)
    cache = update_cache_directory(project_dir)
    if cache not in package.parents:
        raise NipatError("Il pacchetto deve trovarsi nella cache aggiornamenti dell'installazione.")
    worker = project_dir / "installer/windows/update-handoff.ps1"
    if not worker.is_file() or worker.is_symlink():
        raise NipatError("Componente di aggiornamento mancante. Riparare NIPAT con il suo installer.")
    directory = cache / ("handoff-" + uuid.uuid4().hex)
    directory.mkdir()
    copied_worker = directory / "update-handoff.ps1"
    shutil.copyfile(worker, copied_worker)
    descriptor = directory / "handoff.json"
    descriptor.write_text(json.dumps({
        "schema_version": 1, "installation_channel": "desktop", "parent_pid": os.getpid(),
        "project_dir": str(layout["app_dir"]), "package": str(package),
        "sha256": offer.asset.sha256, "size": offer.asset.size,
        "version": offer.version, "source_commit": offer.source_commit, "data_dir": str(layout["data_dir"]),
    }, indent=2) + "\n", encoding="utf-8")
    powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    acknowledged = False
    try:
        process = subprocess.Popen(
            [str(powershell), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(copied_worker), "-Descriptor", str(descriptor)],
            cwd=str(directory), close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        ready = directory / "ready.json"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ready.is_file():
                value = json.loads(ready.read_text(encoding="utf-8-sig"))
                if value == {"schema_version": 1, "worker_pid": process.pid, "parent_pid": os.getpid()}:
                    acknowledged = True
                    return True
                raise NipatError("Conferma del componente di aggiornamento non valida.")
            if process.poll() is not None:
                break
            if (directory / "error.txt").is_file():
                break
            time.sleep(0.05)
    except (OSError, ValueError, TypeError) as exc:
        raise NipatError("Windows non ha avviato l'aggiornamento. NIPAT rimane aperto; consultare la cache aggiornamenti.") from exc
    finally:
        if not acknowledged:
            (directory / "cancel").write_text("handoff canceled\n", encoding="ascii")
    error = directory / "error.txt"
    detail = error.read_text(encoding="utf-8-sig").strip() if error.is_file() else "Avvio del componente non confermato."
    raise NipatError(detail + f" Diagnostica: {directory}")


def begin_update(offer, downloaded: Path, project_dir: Path) -> bool:
    """Launch an independent worker only after explicit UI consent; caller then exits 85."""
    package = _canonical_package(downloaded)
    project_dir = Path(project_dir).resolve()
    _verify_package(package, offer.asset.sha256, offer.asset.size)
    if sys.platform == "win32":
        if offer.asset.platform != "windows-x86_64":
            raise NipatError("Il pacchetto selezionato non e destinato a Windows x64.")
        return _start_windows_update(offer, package, project_dir)
    from .linux_update import LinuxUpdateError, start_linux_update
    if offer.asset.platform != "linux-x86_64":
        raise NipatError("Il pacchetto selezionato non e destinato a Linux x86_64.")
    try:
        return start_linux_update(package, offer.asset.sha256, offer.asset.size,
                                  parent_pid=os.getpid(), project_dir=project_dir)
    except LinuxUpdateError as exc:
        raise NipatError(str(exc)) from exc
