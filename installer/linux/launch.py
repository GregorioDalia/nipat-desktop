"""User launcher and resumable preparation for the Ubuntu NIPAT Preview package.

The package owns the application and archive; preparation owns only per-user state.
No administrative commands, daemon configuration changes or image deletion occur here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import tempfile
from typing import Mapping


CHANNEL = "preview-0.5"
DIRECTORY = "nipat-05-preview"
SOCKET = "unix:///var/run/docker.sock"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
GUIDE = "docs/INSTALLATORE_LINUX.md"
CLI_CODE = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from nipat.cli import main; raise SystemExit(main())"
)


class SetupError(RuntimeError):
    """A preparation problem that must prevent scientific execution."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_host() -> None:
    if sys.platform != "linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise SetupError("Questo pacchetto richiede Ubuntu 24.04 LTS x86_64.")
    try:
        release = platform.freedesktop_os_release()
    except OSError as exc:
        raise SetupError("Impossibile identificare il sistema operativo Ubuntu.") from exc
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise SetupError("Questo pacchetto richiede Ubuntu 24.04 LTS x86_64.")
    if os.geteuid() == 0:
        raise SetupError(
            "Avviare NIPAT con il proprio utente, senza sudo. "
            "L'accesso a Docker deve essere predisposto dall'amministratore."
        )
    if sys.version_info[:2] != (3, 12):
        raise SetupError("Il pacchetto richiede Python 3.12 fornito da Ubuntu.")


def user_paths(environment: Mapping[str, str]) -> tuple[Path, Path]:
    home = Path.home()
    values = []
    for key, default in (("XDG_DATA_HOME", home / ".local/share"),
                         ("XDG_STATE_HOME", home / ".local/state")):
        base = Path(environment.get(key) or default)
        if not base.is_absolute():
            raise SetupError(f"{key} deve essere un percorso assoluto.")
        values.append(base / DIRECTORY)
    return values[0], values[1]


def clean_environment(app: Path, data: Path, state: Path,
                      inherited: Mapping[str, str]) -> dict[str, str]:
    environment = {
        key: value for key, value in inherited.items()
        if not key.startswith(("NIPAT_", "PYTHON", "DOCKER", "COMPOSE"))
    }
    environment.update({
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NIPAT_BACKEND": "native",
        "NIPAT_PROJECT_DIR": str(app),
        "NIPAT_WORKSPACE_DIR": str(data),
        "NIPAT_DATA_DIR": str(data / "data"),
        "NIPAT_RUNS_DIR": str(data / "runs"),
        "DOCKER_HOST": SOCKET,
        "DOCKER_CONFIG": str(state / "docker-config"),
    })
    return environment


def load_manifest(app: Path) -> tuple[dict, str]:
    path = app / ".distribution/installer-manifest.json"
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
        valid = (
            type(manifest) is dict and manifest.get("schema_version") == 1
            and re.fullmatch(r"0\.5\.\d+(?:(?:a|b|rc)\d+)?", manifest.get("version", ""))
            and manifest.get("release_tag") == "v" + manifest["version"]
            and re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", ""))
            and IMAGE_ID.fullmatch(manifest.get("runtime_image", ""))
            and manifest.get("installation_profile", {}).get("channel") == CHANNEL
        )
        if not valid:
            raise ValueError("identita del pacchetto")
        asset = manifest["assets"]["scientific_image"]
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", asset["file"])
                or not DIGEST.fullmatch(asset["sha256"])
                or type(asset["size"]) is not int or not 0 < asset["size"] < 2**31):
            raise ValueError("archivio scientifico")
        hashes = manifest["source_sha256"]
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("inventario dei sorgenti")
        for name, checksum in hashes.items():
            parsed = PurePosixPath(name)
            if (not name or parsed.is_absolute() or parsed.as_posix() != name
                    or ".." in parsed.parts or "\\" in name
                    or not DIGEST.fullmatch(checksum)):
                raise ValueError("percorso o checksum dei sorgenti")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SetupError("Pacchetto NIPAT incompleto o manifest non valido; reinstallare il pacchetto.") from exc
    return manifest, hashlib.sha256(raw).hexdigest()


def verify_sources(app: Path, manifest: dict) -> None:
    for name, expected in manifest["source_sha256"].items():
        path = app / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(app.resolve()):
            raise SetupError(f"File del pacchetto mancante o non valido: {name}")
        if digest(path) != expected:
            raise SetupError(f"File del pacchetto modificato: {name}. Reinstallare NIPAT.")


def loaded_image(output: str) -> str:
    if re.search(r"^Error\b", output, re.MULTILINE):
        raise SetupError("Docker ha segnalato un errore durante il caricamento dell'immagine.")
    receipts = [line for line in output.splitlines() if re.match(r"^Loaded image(?: ID)?:", line)]
    if len(receipts) != 1:
        raise SetupError("Il caricamento deve restituire un solo ID immutabile dell'immagine.")
    match = re.fullmatch(r"Loaded image ID: (sha256:[0-9a-f]{64})", receipts[0])
    if not match:
        raise SetupError("Risposta Docker non riconosciuta: atteso un ID immutabile, senza tag.")
    return match[1]


def docker(arguments: list[str], environment: dict[str, str], *, timeout: int = 60,
           allow_failure: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["/usr/bin/docker", "--host", SOCKET, *arguments], env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("Docker Engine non disponibile o comando scaduto. "
                         f"Consultare {GUIDE}.") from exc
    if result.returncode and not allow_failure:
        raise SetupError(
            "Comando Docker non riuscito. Verificare che Docker Engine locale sia avviato "
            "e accessibile al proprio utente. Consultare " + GUIDE + ".\n"
            + result.stderr.strip() + "\n" + result.stdout.strip()
        )
    return result


def verify_daemon(environment: dict[str, str]) -> None:
    result = docker(["info", "--format", "{{json .}}"], environment)
    try:
        info = json.loads(result.stdout)
        options = info.get("SecurityOptions", [])
        if (info.get("OSType") != "linux" or info.get("Architecture") not in ("x86_64", "amd64")
                or not isinstance(options, list)
                or any("rootless" in str(item).lower() or "userns" in str(item).lower()
                       for item in options)):
            raise ValueError("piattaforma o mappatura utenti non supportata")
    except (ValueError, AttributeError) as exc:
        raise SetupError("NIPAT richiede Docker Engine locale Linux amd64, "
                         "senza modalita rootless o rimappatura userns. "
                         f"Consultare {GUIDE}.") from exc
    docker(["compose", "version"], environment)


def image_present(identifier: str, environment: dict[str, str]) -> bool:
    if not isinstance(identifier, str) or not IMAGE_ID.fullmatch(identifier):
        return False
    result = docker(["image", "inspect", "--format", "{{.Id}} {{.Os}} {{.Architecture}}",
                     identifier], environment, allow_failure=True)
    return result.returncode == 0 and result.stdout.strip() == identifier + " linux amd64"


def atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def setup_lock(state: Path):
    # Import is deferred so the portable unit suite can inspect/test pure helpers.
    import fcntl

    descriptor = os.open(state / "setup.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SetupError("La preparazione NIPAT e gia in corso in un'altra finestra.") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def cli_command(app: Path, arguments: list[str]) -> list[str]:
    return [sys.executable, "-I", "-B", "-c", CLI_CODE, str(app / "src"), *arguments]


def run_cli(app: Path, arguments: list[str], environment: dict[str, str], log=None) -> int:
    if log is None:
        return subprocess.run(cli_command(app, arguments), env=environment).returncode
    with subprocess.Popen(cli_command(app, arguments), env=environment, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                          errors="replace", bufsize=1) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        return process.wait()


def binding(manifest: dict, manifest_hash: str) -> dict:
    return {
        "schema_version": 1,
        "channel": CHANNEL,
        "version": manifest["version"],
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": manifest_hash,
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "source_runtime_image": manifest["runtime_image"],
    }


def ensure_ready(app: Path, data: Path, state: Path, environment: dict[str, str],
                 *, force: bool = False) -> str:
    manifest, manifest_hash = load_manifest(app)
    expected = binding(manifest, manifest_hash)
    for directory in (state, data / "data", data / "runs", state / "docker-config"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with setup_lock(state):
        verify_daemon(environment)
        state_path = state / "state.json"
        try:
            record = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if (not force and isinstance(record, dict) and record.get("phase") == "ready"
                and all(record.get(key) == value for key, value in expected.items())
                and image_present(record.get("resolved_runtime_image", ""), environment)):
            return record["resolved_runtime_image"]
        record = dict(expected, phase="preparing", updated_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(state_path, record)
        descriptor = os.open(state / "setup.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as log:
            def message(value: str) -> None:
                print(value, flush=True)
                log.write(datetime.now(timezone.utc).isoformat() + " " + value + "\n")
                log.flush()

            try:
                message("NIPAT: verifica del pacchetto e dell'archivio scientifico...")
                verify_sources(app, manifest)
                asset = manifest["assets"]["scientific_image"]
                archive = app / ".distribution" / asset["file"]
                if (archive.is_symlink() or not archive.is_file()
                        or archive.stat().st_size != asset["size"] or digest(archive) != asset["sha256"]):
                    raise SetupError("Archivio scientifico non integro. Reinstallare il pacchetto NIPAT.")
                message("NIPAT: caricamento dell'immagine scientifica; attendere...")
                loaded = docker(["image", "load", "--input", str(archive)], environment, timeout=3600)
                message(loaded.stdout.strip())
                if loaded.stderr.strip():
                    message(loaded.stderr.strip())
                identifier = loaded_image(loaded.stdout)
                if not image_present(identifier, environment):
                    raise SetupError("L'immagine caricata non corrisponde all'ID o alla piattaforma previsti.")
                runtime_environment = dict(environment, NIPAT_RUNTIME_IMAGE=identifier)
                for arguments in (["doctor", "--runtime"], ["self-test"]):
                    message("NIPAT: " + " ".join(arguments))
                    code = run_cli(app, arguments, runtime_environment, log)
                    if code != 0:
                        raise SetupError("Verifica NIPAT non superata: " + " ".join(arguments)
                                         + f" (codice {code}). Consultare {state / 'setup.log'}.")
                record.update(phase="ready", resolved_runtime_image=identifier,
                              updated_utc=datetime.now(timezone.utc).isoformat())
                atomic_json(state_path, record)
                message("Ambiente NIPAT disponibile.")
                return identifier
            except (Exception, KeyboardInterrupt) as exc:
                record.update(phase="failed", last_error=str(exc) or "Preparazione interrotta",
                              updated_utc=datetime.now(timezone.utc).isoformat())
                atomic_json(state_path, record)
                message("Preparazione non completata: " + record["last_error"])
                raise


def launch(arguments: list[str]) -> int:
    app = Path(__file__).resolve().parents[2]
    try:
        # Help/version are parser-only commands and never require access to Docker.
        if any(argument in ("--help", "-h", "--version") for argument in arguments):
            data, state = user_paths(os.environ)
            return run_cli(app, arguments, clean_environment(app, data, state, os.environ))
        require_host()
        data, state = user_paths(os.environ)
        environment = clean_environment(app, data, state, os.environ)
        if "--dry-run" in arguments:
            manifest, _ = load_manifest(app)
            environment["NIPAT_RUNTIME_IMAGE"] = manifest["runtime_image"]
            return run_cli(app, arguments, environment)
        setup_only = arguments == ["--setup"]
        if "--setup" in arguments and not setup_only:
            raise SetupError("Usare --setup senza altri argomenti per preparare NIPAT.")
        identifier = ensure_ready(app, data, state, environment, force=setup_only)
        if setup_only:
            return 0
        environment["NIPAT_RUNTIME_IMAGE"] = identifier
        return run_cli(app, arguments or ["wizard"], environment)
    except KeyboardInterrupt:
        print("\nOperazione interrotta.", file=sys.stderr)
        return 130
    except (SetupError, OSError) as exc:
        print("ERRORE: " + str(exc), file=sys.stderr)
        print("Guida: " + str(app / GUIDE), file=sys.stderr)
        return 1


def main(arguments: list[str] | None = None) -> int:
    sys.dont_write_bytecode = True
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    desktop = bool(arguments and arguments[0] == "--desktop")
    if desktop:
        arguments.pop(0)
    code = launch(arguments)
    if desktop and sys.stdin.isatty():
        try:
            input("\nPremere Invio per chiudere questa finestra...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
