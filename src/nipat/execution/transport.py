"""Native Docker, Windows WSL and macOS Lima Docker bridges.

Only host filesystem paths and a small environment allowlist cross the bridge.
Container paths, scientific arguments and R code remain opaque argv elements.
"""

from __future__ import annotations

import ntpath
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Mapping

from nipat.errors import RuntimeExecutionError, ValidationError


_DISTRO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_DRIVE = re.compile(r"[A-Za-z]:\Z")
_HOST_PATH_VARIABLES = (
    "NIPAT_WORKSPACE_DIR", "NIPAT_PROJECT_DIR", "NIPAT_DATA_DIR", "NIPAT_RUNS_DIR",
)
_LINUX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _resolve_relative_windows_path(value: str) -> str:
    if os.name != "nt":
        raise ValidationError("Il backend WSL richiede percorsi Windows su dischi locali.")
    return str(Path(value).expanduser().resolve())


def _windows_path(path: Path | str) -> PureWindowsPath:
    value = os.fspath(path)
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValidationError("Il percorso contiene caratteri di controllo non supportati.")
    parsed = PureWindowsPath(value)
    # Reject UNC and device paths before any WSL process or network access.
    if value.startswith(("\\\\", "//")) or parsed.drive.startswith("\\\\"):
        raise ValidationError(
            "Il backend WSL non supporta percorsi UNC o di dispositivo. "
            "Usare una cartella su un disco locale fisso, ad esempio C: o D:."
        )
    if not parsed.is_absolute():
        value = _resolve_relative_windows_path(value)
        parsed = PureWindowsPath(value)
    if not _DRIVE.fullmatch(parsed.drive) or not parsed.is_absolute():
        raise ValidationError("Il backend WSL richiede un percorso assoluto su un disco locale fisso.")
    return PureWindowsPath(ntpath.normpath(str(parsed)))


def _drive_type(root: str) -> int:
    if os.name != "nt":
        raise ValidationError("Il backend WSL è disponibile solo su Windows.")
    import ctypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint
    return int(function(root))


class DockerTransport:
    backend = "native"
    executable = "docker"

    def __init__(self, *, dry_run: bool = False):
        self.dry_run = dry_run

    @classmethod
    def from_environment(cls, *, dry_run: bool = False) -> "DockerTransport":
        backend = os.environ.get("NIPAT_BACKEND", "native").strip().lower()
        if backend in ("", "native"):
            if os.name == "nt":
                raise ValidationError(
                    "Su Windows NIPAT richiede il runtime WSL dedicato. "
                    "Avviare NIPAT.exe dall'installazione NIPAT oppure completare "
                    "la configurazione con NIPAT-Setup.exe. Per l'esecuzione dai sorgenti, "
                    "configurare NIPAT_BACKEND=wsl e NIPAT_WSL_DISTRO."
                )
            return cls(dry_run=dry_run)
        if backend == "wsl":
            distro = os.environ.get("NIPAT_WSL_DISTRO", "")
            if not distro:
                raise ValidationError(
                    "NIPAT_WSL_DISTRO deve identificare esplicitamente la distribuzione "
                    "di questa installazione. Ripetere la preparazione NIPAT."
                )
            return WslDockerTransport(distro, dry_run=dry_run)
        if backend == "lima":
            return LimaDockerTransport(dry_run=dry_run)
        raise ValidationError("NIPAT_BACKEND deve essere 'native', 'wsl' oppure 'lima'.")

    @property
    def metadata(self) -> dict[str, str]:
        return {"backend": self.backend}

    @property
    def unavailable_message(self) -> str:
        return (
            "Docker Engine non è disponibile. Verificare che il servizio Docker "
            "sia avviato e accessibile all'utente corrente su Linux."
        )

    def host_path(self, path: Path | str) -> str:
        return str(path)

    def command(self, argv: list[str], environment: Mapping[str, str]) -> list[str]:
        return list(argv)

    def ensure_command(self) -> list[str] | None:
        return None


class WslDockerTransport(DockerTransport):
    backend = "wsl"
    executable = "wsl.exe"

    def __init__(self, distro: str, *, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        if not _DISTRO_NAME.fullmatch(distro):
            raise ValidationError("Nome della distribuzione WSL NIPAT non valido.")
        self.distro = distro
        self._paths: dict[str, str] = {}
        self._drives: set[str] = set()

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "backend": self.backend, "wsl_distro": self.distro,
            "path_mapping": "planned_default_mnt" if self.dry_run else "wslpath",
        }

    @property
    def unavailable_message(self) -> str:
        return (
            f"Runtime WSL {self.distro} non disponibile. "
            "Eseguire nuovamente la preparazione NIPAT su Windows."
        )

    def _prefix(self) -> list[str]:
        return ["wsl.exe", "--distribution", self.distro, "--user", "root", "--exec"]

    def _linux_environment(self, environment: Mapping[str, str]) -> list[str]:
        values = {
            "PATH": _LINUX_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONFIG": "/root/.docker",
            "NIPAT_UID": "0", "NIPAT_GID": "0",
        }
        for name in _HOST_PATH_VARIABLES:
            if name in environment:
                values[name] = self.host_path(environment[name])
        if environment.get("NIPAT_RUNTIME_IMAGE"):
            values["NIPAT_RUNTIME_IMAGE"] = environment["NIPAT_RUNTIME_IMAGE"]
        return [f"{name}={value}" for name, value in values.items()]

    def host_path(self, path: Path | str) -> str:
        parsed = _windows_path(path)
        key = str(parsed)
        if key in self._paths:
            return self._paths[key]
        drive = parsed.drive.lower()
        if drive not in self._drives:
            # DRIVE_FIXED=3: mapped network and removable drives are not accepted yet.
            if _drive_type(parsed.anchor) != 3:
                raise ValidationError(
                    f"Il backend WSL richiede un disco locale fisso: {parsed.anchor}. "
                    "Usare una cartella locale per applicazione, dati e risultati."
                )
            self._drives.add(drive)
        if self.dry_run:
            translated = "/mnt/" + drive[0] + "/" + "/".join(parsed.parts[1:])
        else:
            command = self._prefix() + ["wslpath", "-a", "-u", str(parsed)]
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30, check=False, stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeExecutionError(self.unavailable_message) from exc
            translated = result.stdout.rstrip("\r\n")
            if result.returncode or not translated.startswith("/") or any(
                unicodedata.category(char) == "Cc" for char in translated
            ):
                raise RuntimeExecutionError(
                    f"Impossibile rendere accessibile in WSL il percorso {parsed}: "
                    f"{result.stderr.strip() or translated}"
                )
        self._paths[key] = translated
        return translated

    def command(self, argv: list[str], environment: Mapping[str, str]) -> list[str]:
        if not argv or argv[0] != "docker":
            raise ValidationError("Il bridge WSL accetta esclusivamente comandi Docker.")
        return self._prefix() + ["env", "-i", *self._linux_environment(environment), *argv]

    def ensure_command(self) -> list[str]:
        return self._prefix() + [
            "env", "-i", *self._linux_environment({}), "/usr/local/bin/nipat-engine", "ensure",
        ]


class LimaDockerTransport(DockerTransport):
    """Arguments cross Lima through its argv API; never interpolate a shell."""

    backend = "lima"

    def __init__(self, *, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        from nipat.macos_runtime import LimaRuntime
        self.runtime = LimaRuntime.from_environment()
        self.executable = str(self.runtime.executable)

    @property
    def metadata(self) -> dict[str, str]:
        from nipat.macos_runtime import INSTANCE
        return {"backend": self.backend, "lima_instance": INSTANCE,
                "lima_home": str(self.runtime.lima_home), "path_mapping": "virtiofs-same-path",
                "scientific_platform": "linux/amd64"}

    @property
    def unavailable_message(self) -> str:
        return "Runtime Lima NIPAT non disponibile. Avviare nuovamente l'applicazione macOS."

    def host_path(self, path: Path | str) -> str:
        return self.runtime.host_path(path)

    def command(self, argv: list[str], environment: Mapping[str, str]) -> list[str]:
        if not argv or argv[0] != "docker":
            raise ValidationError("Il bridge Lima accetta esclusivamente comandi Docker.")
        return self.runtime.docker_command(argv[1:], dict(environment))

    def ensure_command(self) -> list[str]:
        # The bundled interpreter is isolated and the application is not pip
        # installed. An in-process sys.path entry does not reach this child.
        return [sys.executable, "-I", "-c",
                "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                "runpy.run_module('nipat.macos_runtime',run_name='__main__')",
                str(self.runtime.project / "src"), "ensure"]
