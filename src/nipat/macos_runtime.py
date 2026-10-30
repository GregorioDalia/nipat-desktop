"""Owned Lima runtime for the experimental macOS distribution.

The host never needs Docker, Homebrew, or a system Python. Lima is bundled with
the application; Docker runs only in the private VM. Scientific code is loaded
from a checksummed archive and checked against the build's complete descriptor.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import unicodedata
import uuid

from nipat.errors import NipatError, RuntimeExecutionError, ValidationError


CHANNEL = "experimental08"
INSTANCE = "nipat08"
LIMA_VERSION = "2.2.1"
WORKSPACE_NAME = "NIPAT-Experimental08"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LINUX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Pinned upstream Lima v2.2.1 ubuntu-24.04 template. No mutable fallback URL.
# https://github.com/lima-vm/lima/blob/v2.2.1/templates/_images/ubuntu-24.04.yaml
_BASE_IMAGES = {
    "x86_64": {
        "location": "https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-amd64.img",
        "arch": "x86_64",
        "digest": "sha256:6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2",
    },
    "arm64": {
        "location": "https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-arm64.img",
        "arch": "aarch64",
        "digest": "sha256:1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55",
    },
}
_PROVISION = """#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    apt-get update
    apt-get install -y --no-install-recommends docker.io docker-compose-v2
fi
systemctl enable --now docker
printf '%s\\n' "$PARAM_NipatOwner" > /etc/nipat-owner
"""


def absolute_path(value: str | Path) -> Path:
    raw = os.fspath(value)
    if not raw or any(unicodedata.category(c) == "Cc" for c in raw):
        raise ValidationError("Percorso macOS vuoto o con caratteri di controllo.")
    return Path(raw).expanduser().resolve()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Configurazione NIPAT non leggibile: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Configurazione NIPAT non valida: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_manifest(project: Path) -> dict:
    manifest = _read_json(project / ".distribution" / "macos-manifest.json")
    asset = manifest.get("scientific_asset")
    valid = (
        manifest.get("schema_version") == 1
        and manifest.get("channel") == CHANNEL
        and re.fullmatch(r"0\.8\.[0-9]+(?:[ab][0-9]+|rc[0-9]+)?", str(manifest.get("version", "")))
        and re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", "")))
        and manifest.get("architecture") in _BASE_IMAGES
        and manifest.get("lima_version") == LIMA_VERSION
        and _IMAGE.fullmatch(str(manifest.get("runtime_image", "")))
        and isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", asset["name"])
        and _DIGEST.fullmatch(str(asset.get("sha256", "")))
        and isinstance(manifest.get("engine_description"), dict)
    )
    if not valid:
        raise ValidationError("Manifest macOS sperimentale non valido; reinstallare il pacchetto completo.")
    # Reuse the same contract validation as normal workflow execution.
    from nipat.execution.runner import DockerComposeRunner
    DockerComposeRunner._validate_engine_description(manifest["engine_description"])
    return manifest


def loaded_image_id(output: str) -> str:
    """Accept only the receipt for the single tagless, verified build archive."""
    receipts = [line for line in output.splitlines() if line.startswith("Loaded image")]
    if re.search(r"(?m)^Error\b", output) or len(receipts) != 1:
        raise RuntimeExecutionError("Docker non ha restituito una sola immagine verificabile.")
    match = re.fullmatch(r"Loaded image ID: (sha256:[0-9a-f]{64})", receipts[0])
    if match is None:
        raise RuntimeExecutionError("Ricevuta Docker non valida: richiesto un ID immutabile senza tag.")
    return match[1]


class LimaRuntime:
    def __init__(self, project: Path, workspace: Path, executable: Path, *, home: Path | None = None):
        self.project = absolute_path(project)
        self.workspace = absolute_path(workspace)
        self.executable = absolute_path(executable)
        self.home = absolute_path(home or Path.home())
        expected = self.home / "Library" / "Application Support" / WORKSPACE_NAME
        if self.workspace != expected:
            raise ValidationError(f"Il runtime sperimentale macOS richiede la cartella dedicata {expected}.")
        # macOS Unix sockets have a 104-byte pathname limit. Application Support
        # is deliberately reserved for state/data, not Lima's SSH socket paths.
        self.lima_home = self.home / ".nipat08" / "lima"
        if len(os.fsencode(self.lima_home / INSTANCE / "ssh.sock.1234567890123456")) >= 104:
            raise ValidationError("Il percorso della cartella personale è troppo lungo per i socket Lima su macOS.")
        self.directory = self.workspace / ".runtime" / "macos"
        self.state_path = self.directory / "runtime.json"
        self.owner_path = self.directory / "owner.json"
        self.instance_dir = self.lima_home / INSTANCE

    @classmethod
    def from_environment(cls) -> "LimaRuntime":
        required = ("NIPAT_PROJECT_DIR", "NIPAT_WORKSPACE_DIR", "NIPAT_LIMA_EXECUTABLE", "LIMA_HOME")
        if any(not os.environ.get(key) for key in required):
            raise ValidationError("Avviare NIPAT dall'applicazione macOS installata: configurazione Lima incompleta.")
        value = cls(Path(os.environ[required[0]]), Path(os.environ[required[1]]), Path(os.environ[required[2]]))
        if absolute_path(os.environ["LIMA_HOME"]) != value.lima_home:
            raise ValidationError("LIMA_HOME non appartiene a questa installazione sperimentale.")
        return value

    def host_prefix(self) -> list[str]:
        # Prevent inherited SSH aliases, Docker contexts and user Lima overrides
        # from redirecting a command to another VM or Docker daemon.
        values = {
            "HOME": str(self.home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
            "LIMA_HOME": str(self.lima_home), "SSH": "/usr/bin/ssh",
            "TMPDIR": str(absolute_path(os.environ.get("TMPDIR", "/private/tmp"))),
        }
        return ["/usr/bin/env", "-i", *(f"{key}={value}" for key, value in values.items()), str(self.executable)]

    def shell_command(self, argv: list[str]) -> list[str]:
        return self.host_prefix() + ["shell", "--workdir=/", INSTANCE, *argv]

    def docker_command(self, argv: list[str], environment: dict[str, str] | None = None) -> list[str]:
        values = {
            "HOME": "/root", "PATH": _LINUX_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONFIG": "/root/.docker",
            "DOCKER_DEFAULT_PLATFORM": "linux/amd64", "NIPAT_UID": str(os.getuid()),
            "NIPAT_GID": str(os.getgid()),
        }
        for key in ("NIPAT_PROJECT_DIR", "NIPAT_WORKSPACE_DIR", "NIPAT_DATA_DIR", "NIPAT_RUNS_DIR"):
            if environment and key in environment:
                values[key] = self.host_path(environment[key])
        if environment and environment.get("NIPAT_RUNTIME_IMAGE"):
            values["NIPAT_RUNTIME_IMAGE"] = environment["NIPAT_RUNTIME_IMAGE"]
        return self.shell_command([
            "sudo", "-n", "/usr/bin/env", "-i", *(f"{key}={value}" for key, value in values.items()),
            "docker", "--host", "unix:///var/run/docker.sock", *argv,
        ])

    def default_mounts(self) -> list[dict]:
        candidates = [(self.home, True), (Path("/Volumes"), True), (Path("/private/tmp"), True),
                      (absolute_path(os.environ.get("TMPDIR", "/private/tmp")), True),
                      (self.project, False)]
        mounts = []
        for path, writable in candidates:
            path = path.resolve()
            if any(path.is_relative_to(Path(item["location"])) for item in mounts):
                continue
            mounts.append({"location": str(path), "mountPoint": str(path), "writable": writable})
        return mounts

    def host_path(self, path: Path | str) -> str:
        resolved = absolute_path(path)
        mounts = self.default_mounts()
        if self.owner_path.is_file():
            mounts = self._owner()["mounts"]
        if not any(resolved.is_relative_to(Path(item["location"])) for item in mounts):
            raise ValidationError(
                f"Cartella non condivisa con Lima: {resolved}. Usare la cartella personale, un disco "
                "in /Volumes, oppure aggiungere la cartella con 'macos_runtime prepare --mount PERCORSO'."
            )
        return str(resolved)

    def _owner(self) -> dict:
        owner = _read_json(self.owner_path)
        if (owner.get("channel") != CHANNEL or owner.get("instance") != INSTANCE
                or owner.get("lima_home") != str(self.lima_home)
                or not re.fullmatch(r"[0-9a-f]{32}", str(owner.get("token", "")))
                or not isinstance(owner.get("mounts"), list)):
            raise ValidationError("Identità del runtime Lima non valida; nessuna VM è stata modificata.")
        for item in owner["mounts"]:
            if (not isinstance(item, dict) or not isinstance(item.get("location"), str)
                    or not Path(item["location"]).is_absolute() or item.get("mountPoint") != item["location"]
                    or type(item.get("writable")) is not bool):
                raise ValidationError("Elenco delle cartelle Lima non valido.")
        return owner

    def _assert_owned(self) -> dict:
        owner = self._owner()
        config = self.instance_dir / "lima.yaml"
        if self.instance_dir.is_symlink() or config.is_symlink() or not config.is_file():
            raise ValidationError("La VM Lima dedicata non è presente o non appartiene a NIPAT.")
        contents = config.read_text(encoding="utf-8")
        try:
            parsed = json.loads(contents)
            parameters = parsed.get("param") if isinstance(parsed, dict) else None
            matched = isinstance(parameters, dict) and parameters.get("NipatOwner") == owner["token"]
        except ValueError:
            # Lima can preserve the original JSON or rewrite it as YAML.
            matched = re.search(r"(?m)^\s*NipatOwner:\s*['\"]?" + owner["token"] + r"['\"]?\s*$", contents) is not None
        if not matched:
            raise ValidationError("La VM Lima esistente non appartiene a questa installazione; operazione interrotta.")
        return owner

    @contextmanager
    def lock(self, timeout: float = 15):
        import fcntl
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "operation.lock").open("a", encoding="utf-8") as stream:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeExecutionError("Un'altra operazione sul runtime NIPAT è già in corso.")
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _run(self, argv: list[str], *, timeout: int = 180) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    check=False, stdin=subprocess.DEVNULL, timeout=timeout, cwd=str(self.home))
        except (OSError, subprocess.TimeoutExpired) as exc:
            with (self.directory / "setup.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"argv": argv, "error": str(exc)}, ensure_ascii=False) + "\n")
            raise RuntimeExecutionError(f"Il comando Lima non è stato completato: {exc}") from exc
        with (self.directory / "setup.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"argv": argv, "returncode": result.returncode}, ensure_ascii=False) + "\n")
            log.write(result.stdout + result.stderr + "\n")
        if result.returncode:
            message = (result.stderr or result.stdout).strip()[-2000:]
            raise RuntimeExecutionError(f"Runtime macOS non disponibile (codice {result.returncode}): {message}")
        return result.stdout.strip()

    def _host_check(self, manifest: dict) -> None:
        release = platform.mac_ver()[0]
        if sys.platform != "darwin" or not release or int(release.split(".")[0]) < 14:
            raise ValidationError("Il pacchetto sperimentale richiede macOS 14 o successivo.")
        if platform.machine() != manifest["architecture"]:
            raise ValidationError("Usare il pacchetto NIPAT della propria architettura (Intel o Apple Silicon).")
        if not self.executable.is_file():
            raise ValidationError("Lima incluso nel pacchetto non trovato. Reinstallare NIPAT.")
        if self.lima_home.exists() and self.lima_home.is_symlink():
            raise ValidationError("La cartella Lima dedicata non può essere un collegamento simbolico.")
        if any((self.lima_home / "_config" / name).exists() for name in ("default.yaml", "override.yaml", "base.yaml")):
            raise ValidationError("Override Lima esterni non ammessi nel runtime dedicato NIPAT.")
        version = self._run(self.host_prefix() + ["--version"], timeout=15)
        if not re.fullmatch(r"limactl version " + re.escape(LIMA_VERSION), version):
            raise ValidationError("La versione Lima non corrisponde a quella del pacchetto NIPAT.")

    def template(self, manifest: dict, owner: dict) -> dict:
        return {
            "minimumLimaVersion": LIMA_VERSION, "vmType": "vz",
            "arch": _BASE_IMAGES[manifest["architecture"]]["arch"],
            "images": [_BASE_IMAGES[manifest["architecture"]]],
            "cpus": min(4, os.cpu_count() or 2), "memory": "4GiB", "disk": "40GiB",
            "mountType": "virtiofs", "mounts": owner["mounts"],
            "containerd": {"system": False, "user": False},
            "ssh": {"loadDotSSHPubKeys": False, "forwardAgent": False, "forwardX11": False},
            "vmOpts": {"vz": {"rosetta": {"enabled": manifest["architecture"] == "arm64",
                                               "binfmt": manifest["architecture"] == "arm64"}}},
            "provision": [{"mode": "system", "script": _PROVISION}],
            "probes": [{"script": "#!/bin/sh\nset -eu\ntest \"$(cat /etc/nipat-owner)\" = \"$PARAM_NipatOwner\"\nsudo -n docker info >/dev/null\nsudo -n docker compose version\n",
                        "hint": "Consultare /var/log/cloud-init-output.log nella VM NIPAT."}],
            "portForwards": [{"guestIP": "0.0.0.0", "guestPortRange": [1, 65535], "proto": "any", "ignore": True}],
            "param": {"NipatOwner": owner["token"]},
        }

    def _bindings(self, manifest: dict) -> dict:
        return {"schema_version": 1, "channel": CHANNEL, "backend": "lima", "instance": INSTANCE,
                "lima_home": str(self.lima_home), "version": manifest["version"],
                "source_commit": manifest["source_commit"], "architecture": manifest["architecture"],
                "source_runtime_image": manifest["runtime_image"],
                "runtime_archive_sha256": manifest["scientific_asset"]["sha256"]}

    def _state(self, manifest: dict) -> dict:
        state = _read_json(self.state_path)
        if (any(state.get(key) != value for key, value in self._bindings(manifest).items())
                or state.get("phase") != "ready" or not _IMAGE.fullmatch(str(state.get("runtime_image", "")))):
            raise ValidationError("Preparazione macOS incompleta o di un'altra build. Avviare di nuovo l'applicazione.")
        return state

    def _verify_image(self, manifest: dict, image: str) -> None:
        inspected = self._run(self.docker_command([
            "image", "inspect", "--format", "{{.Id}} {{.Os}} {{.Architecture}}", image,
        ]))
        if inspected != f"{image} linux amd64":
            raise RuntimeExecutionError("Identità o architettura dell'immagine scientifica non valida.")
        name = "nipat-verify-" + uuid.uuid4().hex
        try:
            description = json.loads(self._run(self.docker_command([
                "run", "--rm", "--pull=never", "--platform=linux/amd64", "--name", name,
                "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
                "--env", "HOME=/tmp", image, "python3", "/opt/nipat/engine/main.py", "describe", "--json",
            ])))
        except (ValueError, RuntimeExecutionError):
            try:
                self._run(self.docker_command(["rm", "--force", name]), timeout=20)
            except RuntimeExecutionError:
                pass
            raise
        if description != manifest["engine_description"]:
            raise RuntimeExecutionError("Il codice scientifico dell'immagine non corrisponde alla build NIPAT.")

    def prepare(self, extra_mounts: list[Path] | None = None) -> dict:
        manifest = read_manifest(self.project)
        self._host_check(manifest)
        with self.lock():
            if self.instance_dir.exists() and not self.owner_path.exists():
                raise ValidationError("Esiste già una VM nipat08 non gestita da NIPAT: nessuna modifica eseguita.")
            owner = self._owner() if self.owner_path.exists() else {
                "channel": CHANNEL, "instance": INSTANCE, "lima_home": str(self.lima_home),
                "token": uuid.uuid4().hex, "mounts": self.default_mounts(),
            }
            changed = False
            for value in extra_mounts or []:
                path = absolute_path(value)
                if not path.is_dir() or path == Path("/"):
                    raise ValidationError("Condividere una cartella esistente specifica, non la radice del sistema.")
                if not any(path.is_relative_to(Path(item["location"])) for item in owner["mounts"]):
                    owner["mounts"].append({"location": str(path), "mountPoint": str(path), "writable": True})
                    changed = True
            if self.instance_dir.exists():
                self._assert_owned()
                if changed:
                    raise ValidationError("Per aggiungere cartelle personalizzate rimuovere prima il solo runtime e ripetere prepare --mount. Dati e risultati restano conservati.")
                self._run(self.host_prefix() + ["start", "--tty=false", INSTANCE], timeout=180)
                try:
                    state = self._state(manifest)
                    self._verify_image(manifest, state["runtime_image"])
                    return state
                except (ValidationError, RuntimeExecutionError):
                    pass  # A verified archive below repairs an interrupted import.
            else:
                _write_json(self.owner_path, owner)
                self.lima_home.mkdir(parents=True, exist_ok=True)
                config = self.directory / "lima.yaml"
                _write_json(config, self.template(manifest, owner))  # JSON is a YAML subset.
                state = {**self._bindings(manifest), "phase": "preparing_vm", "last_error": None}
                _write_json(self.state_path, state)
                print("Prima preparazione NIPAT: download di Linux e configurazione di Docker nella VM dedicata. Può richiedere diversi minuti.", flush=True)
                if manifest["architecture"] == "arm64":
                    print("Su Apple Silicon Lima prepara anche Rosetta per eseguire il motore scientifico AMD64.", flush=True)
                try:
                    self._run(self.host_prefix() + ["start", "--tty=false", "--name=" + INSTANCE, str(config)], timeout=1800)
                    self._assert_owned()
                except (NipatError, OSError, ValueError) as exc:
                    state.update(phase="failed", last_error=str(exc))
                    _write_json(self.state_path, state)
                    raise
            state = {**self._bindings(manifest), "phase": "loading_image"}
            _write_json(self.state_path, state)
            try:
                asset = manifest["scientific_asset"]
                archive = self.project / ".distribution" / "assets" / asset["name"]
                if not archive.is_file() or file_sha256(archive) != asset["sha256"]:
                    raise ValidationError("Archivio scientifico mancante o checksum non valido. Reinstallare il pacchetto completo.")
                print("Caricamento e verifica del motore scientifico incluso nel pacchetto...", flush=True)
                image = loaded_image_id(self._run(self.docker_command([
                    "image", "load", "--input", self.host_path(archive),
                ]), timeout=3600))
                self._verify_image(manifest, image)
                state.update(phase="ready", runtime_image=image, last_error=None)
                _write_json(self.state_path, state)
                return state
            except (NipatError, OSError, ValueError) as exc:
                state.update(phase="failed", last_error=str(exc))
                _write_json(self.state_path, state)
                raise

    def ensure(self) -> dict:
        manifest = read_manifest(self.project)
        self._host_check(manifest)
        with self.lock():
            self._assert_owned()
            state = self._state(manifest)
            self._run(self.host_prefix() + ["start", "--tty=false", INSTANCE], timeout=180)
            self._verify_image(manifest, state["runtime_image"])
            return state

    def stop(self) -> None:
        with self.lock():
            self._assert_owned()
            self._run(self.host_prefix() + ["stop", INSTANCE], timeout=180)

    def remove_runtime(self) -> None:
        """Explicit maintenance action: remove only our owned VM, never analyses."""
        with self.lock():
            self._assert_owned()
            self._run(self.host_prefix() + ["delete", "--force", INSTANCE], timeout=180)
            self.state_path.unlink(missing_ok=True)
            self.owner_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preparazione e manutenzione del runtime macOS NIPAT.")
    parser.add_argument("action", choices=("prepare", "ensure", "status", "stop", "remove-runtime"))
    parser.add_argument("--mount", type=Path, action="append", default=[], help="Cartella aggiuntiva, durante la prima preparazione.")
    options = parser.parse_args(argv)
    try:
        runtime = LimaRuntime.from_environment()
        if options.mount and options.action != "prepare":
            raise ValidationError("--mount è disponibile solo con prepare.")
        if options.action == "prepare":
            result = runtime.prepare(options.mount)
        elif options.action == "ensure":
            result = runtime.ensure()
        elif options.action == "status":
            runtime._assert_owned()
            result = runtime._state(read_manifest(runtime.project))
        elif options.action == "stop":
            runtime.stop()
            result = {"instance": INSTANCE, "phase": "stopped"}
        else:
            runtime.remove_runtime()
            result = {"instance": INSTANCE, "phase": "removed", "analyses_preserved": True}
        if options.action == "status":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif options.action in ("prepare", "ensure"):
            print("Runtime scientifico NIPAT disponibile.")
        elif options.action == "stop":
            print("Runtime NIPAT arrestato.")
        else:
            print("Runtime NIPAT rimosso. Dati e risultati sono stati conservati.")
        return 0
    except (NipatError, OSError, ValueError) as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
