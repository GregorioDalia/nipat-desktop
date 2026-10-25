"""Ubuntu package handoff in a separate terminal, outside the application tree.

This file is also a self-contained helper copied into a private cache directory.
It never elevates the NIPAT application: only the standard APT transaction uses
Polkit. Every package transaction is coordinated by root-owned dpkg hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time


HANDOFF_EXIT_CODE = 85
APP = Path("/opt/nipat-desktop")
PKEXEC = Path("/usr/bin/pkexec")
APT = Path("/usr/bin/apt-get")
TERMINAL = Path("/usr/bin/x-terminal-emulator")
PYTHON = Path("/usr/bin/python3.12")
LOCK = Path("/var/lib/nipat-desktop/activity.lock")
MARKER = Path("/var/lib/nipat-desktop/update-in-progress")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PACKAGE = re.compile(r"nipat-desktop_[0-9]+\.[0-9]+\.[0-9]+(?:~(?:a|b|rc)[0-9]+)?_amd64\.deb\Z")
MAX_PACKAGE_SIZE = 2 * 1024**3


class LinuxUpdateError(RuntimeError):
    """A handoff that leaves the downloaded package available for retry."""


def require_supported_host() -> None:
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise LinuxUpdateError("L'aggiornamento richiede Ubuntu 24.04 LTS x86_64.")
    try:
        release = platform.freedesktop_os_release()
    except OSError as exc:
        raise LinuxUpdateError("Impossibile identificare la distribuzione Linux.") from exc
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise LinuxUpdateError("L'aggiornamento richiede Ubuntu 24.04 LTS x86_64.")


def manual_install_command(package: Path) -> str:
    return "sudo apt install -- " + shlex.quote(str(package.absolute()))


def verify_package(package: Path, expected_sha256: str, expected_size: int) -> None:
    if (not SHA256.fullmatch(expected_sha256) or type(expected_size) is not int
            or not 0 < expected_size < MAX_PACKAGE_SIZE or not PACKAGE.fullmatch(package.name)
            or not package.is_absolute()):
        raise LinuxUpdateError("Metadati del pacchetto di aggiornamento non validi.")
    try:
        descriptor = os.open(package, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            information = os.fstat(stream.fileno())
            if (not stat.S_ISREG(information.st_mode) or information.st_size != expected_size
                    or information.st_nlink != 1):
                raise LinuxUpdateError("Il pacchetto scaricato non e' un file regolare integro.")
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected_sha256:
            raise LinuxUpdateError("Il checksum del pacchetto scaricato non corrisponde alla release.")
    except OSError as exc:
        raise LinuxUpdateError("Impossibile verificare il pacchetto scaricato: " + str(exc)) from exc


def _process_identity(pid: int) -> str | None:
    """Linux start time disambiguates a live PID from a reused process number."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        tail = raw[raw.rfind(")") + 2:].split()
        if tail[0] == "Z":
            return None
        return tail[19]
    except (OSError, IndexError):
        return None


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _reject_symlinks(path: Path) -> None:
    if any(entry.is_symlink() for entry in (path, *path.parents)):
        raise LinuxUpdateError("La cache degli aggiornamenti non puo' attraversare collegamenti simbolici.")


def _cache_directory() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    if not base.is_absolute():
        raise LinuxUpdateError("XDG_CACHE_HOME deve essere un percorso assoluto.")
    cache = base / "nipat-desktop" / "updates"
    _reject_symlinks(cache)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlinks(cache)
    if cache.stat().st_uid != os.getuid():
        raise LinuxUpdateError("La cache degli aggiornamenti non appartiene all'utente.")
    cache.chmod(0o700)
    return cache


def start_linux_update(package: Path, expected_sha256: str, expected_size: int,
                       parent_pid: int | None = None, project_dir: Path | None = None) -> bool:
    """Prepare a reviewable handoff and start its terminal; caller then exits 85."""
    require_supported_host()
    package = Path(package).absolute()
    if sys.platform != "linux" or os.geteuid() == 0:
        raise LinuxUpdateError("Avviare l'aggiornamento dall'applicazione Linux con il proprio utente.")
    if project_dir is None or Path(project_dir).resolve() != APP:
        raise LinuxUpdateError("L'aggiornamento guidato richiede il pacchetto installato. "
                               + manual_install_command(package))
    verify_package(package, expected_sha256, expected_size)
    missing = [str(path) for path in (PKEXEC, APT, TERMINAL, PYTHON) if not os.access(path, os.X_OK)]
    if missing:
        raise LinuxUpdateError("Il sistema non dispone del terminale o dell'autorizzazione grafica richiesti. "
                               "Chiudere NIPAT e installare il pacchetto verificato con: "
                               + manual_install_command(package))
    if not LOCK.is_file() or MARKER.exists():
        raise LinuxUpdateError("La configurazione del pacchetto e' incompleta. "
                               "Completare prima la precedente operazione APT.")
    pids = {int(parent_pid or os.getpid())}
    outer = os.environ.get("NIPAT_LAUNCHER_PID", "")
    if outer.isdecimal() and int(outer) > 1:
        pids.add(int(outer))
    parents = [{"pid": pid, "start": _process_identity(pid)} for pid in sorted(pids)]
    if any(parent["pid"] <= 1 or parent["start"] is None for parent in parents):
        raise LinuxUpdateError("Impossibile identificare la sessione da chiudere prima dell'aggiornamento.")
    directory = Path(tempfile.mkdtemp(prefix="handoff-", dir=_cache_directory()))
    helper = directory / "handoff.py"
    shutil.copyfile(Path(__file__), helper)
    helper.chmod(0o600)
    request = {
        "schema_version": 1, "package": str(package), "sha256": expected_sha256,
        "size": expected_size, "parents": parents,
    }
    request_path = directory / "request.json"
    _write_json(request_path, request)
    _write_json(directory / "state.json", {"phase": "waiting_for_application", "package": str(package)})
    try:
        process = subprocess.Popen(
            [str(TERMINAL), "-e", str(PYTHON), "-I", "-B", str(helper), "--request", str(request_path)],
            start_new_session=True, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _write_json(directory / "state.json", {"phase": "failed", "error": str(exc)})
        raise LinuxUpdateError("Impossibile aprire il terminale di aggiornamento. "
                               + manual_install_command(package)) from exc
    try:
        if _wait_for_acknowledgement(directory, parents, process):
            return True
    except BaseException:
        (directory / "cancel").touch(mode=0o600)
        raise
    (directory / "cancel").touch(mode=0o600)
    _write_json(directory / "state.json", {"phase": "failed", "error": "Avvio del terminale non confermato."})
    raise LinuxUpdateError("Avvio del terminale di aggiornamento non confermato. NIPAT rimane aperto. "
                           "Chiudere NIPAT e installare il pacchetto verificato con: "
                           + manual_install_command(package))


def _wait_for_acknowledgement(directory: Path, parents: list[dict], process) -> bool:
    ready = directory / "ready.json"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if ready.is_file():
            try:
                acknowledgement = json.loads(ready.read_text(encoding="utf-8"))
                if (type(acknowledgement) is dict
                        and set(acknowledgement) == {"schema_version", "worker_pid", "parents"}
                        and acknowledgement["schema_version"] == 1
                        and type(acknowledgement["worker_pid"]) is int
                        and acknowledgement["worker_pid"] > 1
                        and acknowledgement["parents"] == parents
                        and _process_identity(acknowledgement["worker_pid"]) is not None):
                    return True
            except (OSError, ValueError):
                pass
            break
        # GNOME Terminal may return 0 before its child writes acknowledgement.
        # Only an explicit launcher error can end the handshake early.
        if process.poll() not in (None, 0):
            break
        try:
            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if type(state) is not dict or state.get("phase") == "failed":
            break
        time.sleep(0.05)
    return False


def _read_request(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024:
        raise LinuxUpdateError("Richiesta di aggiornamento non valida.")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
        if (type(request) is not dict or request.get("schema_version") != 1
                or set(request) != {"schema_version", "package", "sha256", "size", "parents"}
                or type(request["parents"]) is not list or not 1 <= len(request["parents"]) <= 2):
            raise ValueError("schema")
        for parent in request["parents"]:
            if (type(parent) is not dict or set(parent) != {"pid", "start"}
                    or type(parent["pid"]) is not int or parent["pid"] <= 1
                    or not isinstance(parent["start"], str) or not parent["start"].isdecimal()):
                raise ValueError("processo")
        verify_package(Path(request["package"]), request["sha256"], request["size"])
        return request
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise LinuxUpdateError("Richiesta di aggiornamento incompleta o non valida.") from exc


def wait_for_parents(parents: list[dict], *, timeout: float = 120, cancel: Path | None = None) -> None:
    deadline = time.monotonic() + timeout
    while any(_process_identity(item["pid"]) == item["start"] for item in parents):
        if cancel is not None and cancel.exists():
            raise LinuxUpdateError("Avvio dell'aggiornamento annullato dalla sessione NIPAT.")
        if time.monotonic() >= deadline:
            raise LinuxUpdateError("NIPAT non si e' chiuso. Chiudere la sessione e riprovare l'aggiornamento.")
        time.sleep(0.25)


def _other_sessions_running() -> bool:
    import fcntl
    descriptor = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def run_handoff(request_path: Path) -> int:
    state = request_path.parent / "state.json"
    try:
        require_supported_host()
        request = _read_request(request_path)
        cancel = request_path.parent / "cancel"
        if cancel.exists():
            raise LinuxUpdateError("Avvio dell'aggiornamento annullato dalla sessione NIPAT.")
        _write_json(request_path.parent / "ready.json", {
            "schema_version": 1, "worker_pid": os.getpid(), "parents": request["parents"],
        })
        print("NIPAT: attesa della chiusura dell'applicazione...", flush=True)
        wait_for_parents(request["parents"], cancel=cancel)
        if cancel.exists():
            raise LinuxUpdateError("Avvio dell'aggiornamento annullato dalla sessione NIPAT.")
        if _other_sessions_running():
            raise LinuxUpdateError("Altre sessioni NIPAT sono aperte. Attendere la fine delle analisi, "
                                   "chiudere tutte le finestre e riprovare.")
        package = Path(request["package"])
        verify_package(package, request["sha256"], request["size"])
        _write_json(state, {"phase": "installing", "package": str(package)})
        print("NIPAT: autorizzare l'installazione del pacchetto quando richiesto dal sistema.", flush=True)
        completed = subprocess.run([str(PKEXEC), str(APT), "install", "--", str(package)], check=False)
        if completed.returncode != 0:
            raise LinuxUpdateError(f"Installazione non completata (codice {completed.returncode}). "
                                   "Il pacchetto scaricato e' conservato. Riprovare con: "
                                   + manual_install_command(package))
        if MARKER.exists():
            raise LinuxUpdateError("Il gestore dei pacchetti non ha completato la configurazione NIPAT.")
        _write_json(state, {"phase": "preparing_runtime", "package": str(package)})
        # This remains the original unprivileged user; the installed launcher
        # verifies the new manifest/runtime and runs self-test before the menu.
        completed = subprocess.run(["/usr/bin/nipat", "--setup"], check=False)
        if completed.returncode != 0:
            raise LinuxUpdateError("Pacchetto installato; preparazione dell'ambiente non completata. "
                                   "Avviare NIPAT per riprendere la preparazione.")
        _write_json(state, {"phase": "ready", "package": str(package)})
        return subprocess.run(["/usr/bin/nipat"], check=False).returncode
    except (LinuxUpdateError, OSError, KeyboardInterrupt) as exc:
        message = str(exc) or "Aggiornamento interrotto."
        _write_json(state, {"phase": "failed", "error": message})
        print("ERRORE: " + message, file=sys.stderr, flush=True)
        return 1


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    options = parser.parse_args(arguments)
    if sys.platform != "linux" or os.geteuid() == 0:
        print("Avviare questo helper come utente, senza sudo.", file=sys.stderr)
        return 1
    code = run_handoff(options.request)
    if code and sys.stdin.isatty():
        try:
            input("Premere Invio per chiudere questa finestra...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
