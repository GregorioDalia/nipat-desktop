"""Launch the isolated experimental macOS installation with bundled dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

STATE = Path("/Library/Application Support/NIPAT-Experimental08 Installer")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
CLI_CODE = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "from nipat.cli import main; raise SystemExit(main())")
RUNTIME_CODE = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                "from nipat.macos_runtime import main; raise SystemExit(main())")


def load_manifest(app: Path) -> dict:
    app = app.resolve()
    manifest = json.loads((app / ".distribution/macos-manifest.json").read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("channel") != "experimental08"
            or manifest.get("architecture") not in {"arm64", "x86_64"}
            or not re.fullmatch(r"0\.8\.\d+(?:a|b|rc)\d+", manifest.get("version", ""))
            or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("source_commit", ""))):
        raise ValueError("Manifest macOS sperimentale non valido; reinstallare NIPAT.")
    source_hashes = manifest.get("source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("Inventario sorgenti mancante.")
    for name, expected in source_hashes.items():
        path = Path(name)
        if (path.is_absolute() or path.as_posix() != name or ".." in path.parts
                or "\\" in name or not SHA256.fullmatch(str(expected))):
            raise ValueError("Inventario sorgenti non valido.")
        source = app / path
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(app):
            raise ValueError(f"File installato non valido: {name}")
        with source.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"File installato modificato: {name}; reinstallare NIPAT.")
    return manifest


def environment(app: Path, resources: Path, inherited: dict[str, str]) -> dict[str, str]:
    workspace = Path.home() / "Library/Application Support/NIPAT-Experimental08"
    clean = {key: value for key, value in inherited.items()
             if not key.startswith(("NIPAT_", "PYTHON", "DOCKER", "COMPOSE", "LIMA_"))}
    clean.update({
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "NIPAT_PROJECT_DIR": str(app), "NIPAT_BACKEND": "lima",
        "NIPAT_WORKSPACE_DIR": str(workspace),
        "NIPAT_DATA_DIR": str(workspace / "data"),
        "NIPAT_RUNS_DIR": str(workspace / "runs"),
        "NIPAT_LIMA_EXECUTABLE": str(resources / "lima/bin/limactl"),
        "LIMA_HOME": str(Path.home() / ".nipat08/lima"),
        "NIPAT_LAUNCHER_PID": str(os.getpid()),
    })
    return clean


@contextmanager
def installation_session(state: Path = STATE, *, exclusive: bool = False):
    """A root-owned marker also blocks launches after an interrupted update."""
    import fcntl
    for path in (state, state / "activity.lock"):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Coordinamento installazione non valido; reinstallare NIPAT.")
    with (state / "activity.lock").open("rb") as stream:
        try:
            fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Un'altra sessione NIPAT è attiva; chiuderla prima della manutenzione o attendere la fine dell'aggiornamento.") from exc
        if (state / "update-in-progress").exists():
            raise ValueError("Installazione NIPAT incompleta; rieseguire il pacchetto .pkg.")
        yield


def launch(arguments: list[str], app: Path) -> int:
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise ValueError("Avviare NIPAT su macOS con il proprio utente, senza sudo.")
    if int(platform.mac_ver()[0].split(".")[0]) < 14:
        raise ValueError("NIPAT Experimental08 richiede macOS 14 o successivo.")
    manifest = load_manifest(app)
    if platform.machine() != manifest["architecture"]:
        raise ValueError("Installare il pacchetto NIPAT per l'architettura di questo Mac.")
    resources = app.parent
    env = environment(app, resources, dict(os.environ))
    python = resources / "python/bin/python3.12"
    workspace = Path(env["NIPAT_WORKSPACE_DIR"])
    for path in (workspace, workspace / "data", workspace / "runs"):
        path.mkdir(parents=True, exist_ok=True)
    runtime = [str(python), "-I", "-B", "-c", RUNTIME_CODE, str(app / "src")]
    maintenance = len(arguments) >= 2 and arguments[0] == "--runtime" and arguments[1] in {"stop", "remove-runtime"}
    with installation_session(exclusive=maintenance):
        if arguments and arguments[0] == "--runtime":
            return subprocess.call([*runtime, *arguments[1:]], env=env)
        prepared = subprocess.call([*runtime, "prepare"], env=env)
        if prepared:
            return prepared
        state = json.loads((workspace / ".runtime/macos/runtime.json").read_text())
        identifier = state.get("runtime_image", "")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier):
            raise ValueError("Identita del runtime preparato non valida.")
        env["NIPAT_RUNTIME_IMAGE"] = identifier
        return subprocess.call([str(python), "-I", "-B", "-c", CLI_CODE,
                                str(app / "src"), *(arguments or ["wizard"])],
                               env=env, cwd=workspace / "data")


def main(arguments: list[str] | None = None) -> int:
    try:
        return launch(sys.argv[1:] if arguments is None else arguments,
                      Path(__file__).resolve().parents[2])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"NIPAT: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
