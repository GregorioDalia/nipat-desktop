"""Inspect and configure host/VM resources without changing scientific settings.

VM changes are separate from the per-container ExecutionOptions. Every write
requires an explicit confirmation, an unchanged preview, and a byte-for-byte
backup. WSL changes affect the user's entire WSL2 VM, not one distribution.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import stat
import sys
import threading
import uuid

from nipat.errors import RuntimeExecutionError, ValidationError


_MIB = 1024 * 1024
_EMPTY = {"memory_mib": None, "cpus": None}
_LOCAL = threading.local()
_MAX_CONFIG_BYTES = 1024 * 1024


def _decode_output(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    if value.startswith((b"\xff\xfe", b"\xfe\xff")):
        return value.decode("utf-16")
    if b"\x00" in value:
        return value.decode("utf-16-le")
    return value.decode("utf-8", errors="replace")


def _run(argv: list[str], *, timeout: int = 20) -> str:
    try:
        completed = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL,
                                   check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeExecutionError(f"Lettura o modifica delle risorse non completata: {exc}") from exc
    stdout, stderr = _decode_output(completed.stdout), _decode_output(completed.stderr)
    if completed.returncode:
        raise RuntimeExecutionError(
            f"Comando risorse terminato con codice {completed.returncode}: {(stderr or stdout).strip()[-1500:]}"
        )
    return stdout.strip()


def host_resources() -> dict:
    """Physical memory, not available/free memory or a predicted run budget."""
    memory = None
    try:
        if os.name == "nt":
            memory = _windows_memory()
        elif sys.platform == "darwin":
            memory = int(_run(["/usr/sbin/sysctl", "-n", "hw.memsize"])) // _MIB
        else:
            memory = int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE")) // _MIB
    except (OSError, ValueError, RuntimeExecutionError):
        memory = None
    return {"memory_mib": memory, "cpus": os.cpu_count()}


def _windows_memory() -> int | None:
    import ctypes
    from ctypes import wintypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                    ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                    ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
                    ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
                    ("extended", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    function.argtypes = [ctypes.POINTER(MemoryStatus)]
    function.restype = wintypes.BOOL
    return int(status.total) // _MIB if function(ctypes.byref(status)) else None


def suggested_resources(host: dict) -> dict:
    """Conservative starting values, never a claim about scientific requirements."""
    memory, cpus = host.get("memory_mib"), host.get("cpus")
    return {"memory_mib": min(8192, max(128, memory // 2)) if type(memory) is int and memory > 0 else None,
            "cpus": max(1, min(4, cpus - 1)) if type(cpus) is int and cpus > 0 else None}


def _backend() -> str:
    value = os.environ.get("NIPAT_BACKEND", "native").strip().lower() or "native"
    if value not in {"native", "wsl", "lima"}:
        raise ValidationError("Backend delle risorse non riconosciuto.")
    return value


@contextmanager
def _resource_lock(home: Path, backend: str, *, exclusive: bool):
    directory = home / ".nipat"
    if directory.is_symlink():
        raise ValidationError("La cartella di coordinamento delle risorse non può essere un collegamento.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"resources-{backend}.lock"
    if path.is_symlink():
        raise ValidationError("File di coordinamento delle risorse non valido.")
    with path.open("a+b") as stream:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            class Overlapped(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.LockFileEx.restype = wintypes.BOOL
            kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.UnlockFileEx.restype = wintypes.BOOL
            handle, overlap = msvcrt.get_osfhandle(stream.fileno()), Overlapped()
            if not kernel.LockFileEx(handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlap)):
                raise RuntimeExecutionError("Un'analisi o una modifica delle risorse è in corso. Riprovare al termine.")
            try:
                yield
            finally:
                kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlap))
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeExecutionError("Un'analisi o una modifica delle risorse è in corso. Riprovare al termine.") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def analysis_session(layout=None):
    """Shared across local NIPAT processes; safe for nested calls in one thread."""
    key = (str(Path.home().resolve()), _backend())
    active = getattr(_LOCAL, "analysis", {})
    if active.get(key, 0):
        active[key] += 1
        try:
            yield
        finally:
            active[key] -= 1
        return
    with _resource_lock(Path(key[0]), key[1], exclusive=False):
        _LOCAL.analysis = active
        active[key] = 1
        try:
            yield
        finally:
            del active[key]


def _config_bytes(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ValidationError(f"La configurazione risorse non può essere un collegamento: {path}")
    if not path.exists():
        return None
    # O_NOFOLLOW closes the symlink race on POSIX. Windows rejects reparse
    # symlinks above; the fstat check also rejects non-regular file handles.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_CONFIG_BYTES:
            raise ValidationError(f"Configurazione risorse non valida: {path}")
        contents = stream.read(_MAX_CONFIG_BYTES + 1)
        if len(contents) > _MAX_CONFIG_BYTES:
            raise ValidationError(f"Configurazione risorse troppo grande: {path}")
        return contents


def _fingerprint(contents: bytes | None) -> str | None:
    return hashlib.sha256(contents).hexdigest() if contents is not None else None


def _text(contents: bytes | None) -> tuple[str, str, bytes]:
    if contents is None:
        return "", "utf-8", b""
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if contents.startswith(bom):
            try:
                return contents[len(bom):].decode(encoding), encoding, bom
            except UnicodeError as exc:
                raise ValidationError("Codifica della configurazione risorse non valida.") from exc
    try:
        return contents.decode("utf-8"), "utf-8", b""
    except UnicodeError as exc:
        raise ValidationError("La configurazione deve essere UTF-8 o UTF-16 con indicatore BOM; nessuna modifica eseguita.") from exc


def _memory_mib(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value // _MIB if value > 0 else None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|KiB|MB|MiB|GB|GiB|TB|TiB)?\s*", str(value), re.I)
    if match is None:
        return None
    power = {None: 0, "b": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2,
             "gb": 3, "gib": 3, "tb": 4, "tib": 4}[match[2].lower() if match[2] else None]
    amount = float(match[1]) * (1024 ** power) / _MIB
    return int(amount) if math.isfinite(amount) and amount > 0 else None


def wsl_configuration(contents: bytes | None, *, memory_mib: int | None = None,
                      cpus: int | None = None) -> tuple[dict, bytes]:
    """Preserve comments, unknown keys, sections, newline style and BOM exactly."""
    text, encoding, bom = _text(contents)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    sections, current, positions, values = [], None, {}, {}
    for index, line in enumerate(lines):
        section = re.fullmatch(r"\s*\[([^\]]+)\]\s*(?:[#;].*)?(?:\r?\n)?", line)
        if section:
            current = section[1].strip().casefold()
            if current == "wsl2":
                sections.append(index)
            continue
        if current != "wsl2" or line.lstrip().startswith(("#", ";")):
            continue
        match = re.match(r"^(\s*)(memory|processors)(\s*=\s*)([^\r\n]*)(\r?\n)?$", line, re.I)
        if match:
            key = match[2].lower()
            if key in positions:
                raise ValidationError(f"La configurazione WSL contiene più valori '{key}'; correggerla prima della modifica guidata.")
            positions[key] = (index, match)
            values[key] = re.split(r"\s*[#;]", match[4], maxsplit=1)[0].strip()
    if len(sections) > 1:
        raise ValidationError("La configurazione WSL contiene più sezioni [wsl2]; nessuna modifica eseguita.")
    configured = {"memory_mib": _memory_mib(values.get("memory")),
                  "cpus": int(values["processors"]) if values.get("processors", "").isdigit() else None}
    if memory_mib is None and cpus is None:
        return configured, contents or b""
    if memory_mib is None or cpus is None:
        raise ValidationError("Indicare sia RAM sia CPU per la modifica della VM.")
    replacements = {"memory": f"{memory_mib}MB", "processors": str(cpus)}
    missing = []
    for key, value in replacements.items():
        if key in positions:
            index, match = positions[key]
            comment = re.search(r"(\s*[#;].*)$", match[4])
            lines[index] = match[1] + match[2] + match[3] + value + (comment[1] if comment else "") + (match[5] or "")
        else:
            missing.append(key + "=" + value + newline)
    if not sections:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend(["[wsl2]" + newline, *missing])
    elif missing:
        insert = sections[0] + 1
        if not lines[sections[0]].endswith(("\n", "\r")):
            lines[sections[0]] += newline
        lines[insert:insert] = missing
    return configured, bom + "".join(lines).encode(encoding)


def _lima_configuration(contents: bytes) -> dict:
    text, _, _ = _text(contents)
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("object required")
        memory, cpus = parsed.get("memory"), parsed.get("cpus")
    except ValueError:
        selected = {}
        for key in ("memory", "cpus"):
            matches = re.findall(r"(?m)^" + key + r":\s*([^\r\n#]+)", text)
            if len(matches) > 1:
                raise ValidationError(f"Configurazione Lima ambigua: {key} ripetuto.")
            selected[key] = matches[0].strip().strip("\"'") if matches else None
        memory, cpus = selected["memory"], selected["cpus"]
    return {"memory_mib": _memory_mib(memory),
            "cpus": int(cpus) if str(cpus).isdigit() else None}


@dataclass(frozen=True)
class ResourceChange:
    backend: str
    config_path: str
    expected_sha256: str | None
    before: dict
    after: dict
    affected_running: tuple[str, ...]
    warnings: tuple[str, ...]
    replacement: bytes | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {"backend": self.backend, "config_path": self.config_path,
                "expected_sha256": self.expected_sha256, "before": dict(self.before),
                "after": dict(self.after), "affected_running": list(self.affected_running),
                "warnings": list(self.warnings), "restart_required": bool(self.affected_running)}


class ResourceManager:
    def __init__(self, transport, *, home: Path | None = None):
        self.transport = transport
        self.backend = transport.backend
        self.home = (home or Path.home()).resolve()

    @classmethod
    def from_environment(cls, layout=None) -> "ResourceManager":
        from nipat.execution.transport import DockerTransport
        return cls(DockerTransport.from_environment())

    def _wsl(self, arguments: list[str]) -> str:
        if os.name != "nt":
            raise ValidationError("La configurazione WSL è disponibile solo da Windows.")
        executable = Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "wsl.exe"
        return _run([str(executable), *arguments], timeout=180 if "--shutdown" in arguments else 30)

    def _running(self) -> tuple[str, ...]:
        if self.backend == "wsl":
            return tuple(sorted(line.strip() for line in self._wsl(["--list", "--running", "--quiet"]).splitlines() if line.strip()))
        if self.backend == "lima":
            runtime = self.transport.runtime
            if not runtime.instance_dir.exists():
                return ()
            runtime._assert_owned()
            from nipat.macos_runtime import INSTANCE
            raw = runtime._run(runtime.host_prefix() + ["list", "--json", INSTANCE], timeout=20)
            try:
                entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
                if len(entries) != 1 or entries[0].get("name") != INSTANCE:
                    raise ValueError("Unexpected Lima instance")
                status = entries[0].get("status")
                if status not in {"Running", "Stopped"}:
                    raise ValueError("Lima instance is transitioning")
                return (INSTANCE,) if status == "Running" else ()
            except (ValueError, AttributeError) as exc:
                raise RuntimeExecutionError("Stato della VM Lima non disponibile o in transizione.") from exc
        return ()

    def _configuration(self) -> tuple[Path | None, bytes | None, dict]:
        if self.backend == "wsl":
            path = self.home / ".wslconfig"
            contents = _config_bytes(path)
            return path, contents, wsl_configuration(contents)[0]
        if self.backend == "lima":
            runtime = self.transport.runtime
            runtime._assert_owned()
            path = runtime.instance_dir / "lima.yaml"
            contents = _config_bytes(path)
            if contents is None:
                raise ValidationError("Preparare il runtime Lima prima di configurarne le risorse.")
            return path, contents, _lima_configuration(contents)
        return None, None, dict(_EMPTY)

    def _docker(self, arguments: list[str]) -> str:
        argv = ["docker", *arguments]
        if self.backend == "native":
            # Match the installed Linux launcher; never probe an inherited remote context.
            argv = ["docker", "--host", "unix:///var/run/docker.sock", *arguments]
        return _run(self.transport.command(argv, {}), timeout=20)

    def _effective(self) -> dict:
        raw = self._docker(["info", "--format", '{"memory":{{.MemTotal}},"cpus":{{.NCPU}}}'])
        try:
            data = json.loads(raw)
            if (type(data["memory"]) is not int or data["memory"] <= 0
                    or type(data["cpus"]) is not int or data["cpus"] <= 0):
                raise ValueError("Invalid Docker resources")
            return {"memory_mib": data["memory"] // _MIB, "cpus": data["cpus"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeExecutionError("Il runtime non ha restituito valori RAM/CPU validi.") from exc

    def snapshot(self, container_options=None) -> dict:
        host, warnings = host_resources(), []
        configured, effective, path, running = dict(_EMPTY), dict(_EMPTY), None, None
        try:
            path, _, configured = self._configuration()
        except (OSError, ValidationError, RuntimeExecutionError) as exc:
            warnings.append(str(exc))
        try:
            instances = self._running()
            running = (self.transport.distro in instances if self.backend == "wsl" else
                       bool(instances) if self.backend == "lima" else True)
            if running:
                effective = self._effective()
        except (OSError, ValidationError, RuntimeExecutionError) as exc:
            warnings.append(str(exc))
            if self.backend == "native":
                running = None
        if self.backend == "wsl":
            warnings.append("RAM e CPU della VM WSL sono condivise da tutte le distribuzioni WSL2 dell'utente.")
        if not running and self.backend != "native":
            warnings.append("Il runtime è arrestato o non verificabile: le risorse effettive non sono state misurate.")
        options = container_options.as_dict() if hasattr(container_options, "as_dict") else container_options or {}
        container = {"memory_mib": options.get("memory_mb"), "cpus": options.get("cpus")}
        if container["memory_mib"] is not None and effective["memory_mib"] is not None and container["memory_mib"] > effective["memory_mib"]:
            warnings.append("Il limite RAM del container supera la memoria del runtime; aumentarlo non aumenta la RAM della VM.")
        return {"schema_version": 1, "backend": self.backend, "host": host,
                "runtime": {"configured": configured, "effective": effective, "running": running,
                            "scope": {"wsl": "all-wsl2-distributions", "lima": "nipat-lima", "native": "host"}[self.backend],
                            "config_path": str(path) if path else None},
                "container": container, "suggested": suggested_resources(host), "warnings": warnings}

    @staticmethod
    def _validate(memory_mib: int, cpus: int, host: dict) -> None:
        if type(memory_mib) is not int or not 128 <= memory_mib <= 1_048_576:
            raise ValidationError("La RAM della VM deve essere un intero tra 128 e 1048576 MiB.")
        if type(cpus) is not int or not 1 <= cpus <= 1024:
            raise ValidationError("Il numero di CPU della VM deve essere un intero tra 1 e 1024.")
        if host.get("memory_mib") is not None and memory_mib >= host["memory_mib"]:
            raise ValidationError("Lasciare memoria al sistema operativo: la RAM della VM deve essere inferiore alla RAM fisica.")
        if host.get("cpus") is not None and cpus > host["cpus"]:
            raise ValidationError("Le CPU della VM non possono superare quelle del computer.")

    def preview(self, memory_mib: int, cpus: int) -> ResourceChange:
        if self.backend not in {"wsl", "lima"}:
            raise ValidationError("Su Ubuntu nativo configurare i limiti dell'analisi; non esiste una VM NIPAT da ridimensionare.")
        self._validate(memory_mib, cpus, host_resources())
        path, contents, before = self._configuration()
        instances = self._running()
        warnings = ["La proposta non prevede il fabbisogno scientifico: verificare l'analisi con i propri dati."]
        if self.backend == "wsl":
            warnings.append("Questa modifica vale per tutte le distribuzioni WSL2 dell'utente. Il riavvio WSL arresta anche quelle elencate nell'anteprima.")
            replacement = wsl_configuration(contents, memory_mib=memory_mib, cpus=cpus)[1]
        else:
            replacement = None
            warnings.append("La modifica riguarda solo la VM Lima dedicata a NIPAT e ne richiede l'arresto se è in esecuzione.")
        return ResourceChange(self.backend, str(path), _fingerprint(contents), before,
                              {"memory_mib": memory_mib, "cpus": cpus}, instances, tuple(warnings), replacement)

    def _assert_idle(self) -> None:
        raw = self._docker(["ps", "--filter", "label=org.nipat.product=nipat-desktop", "--format", "{{.Names}}"])
        if raw.strip():
            raise RuntimeExecutionError("Sono presenti analisi NIPAT attive: attendere il completamento prima di modificare le risorse.")
        # Older packages might not carry ownership labels. Never stop them either.
        raw = self._docker(["ps", "--filter", "name=nipat-run-", "--format", "{{.Names}}"])
        if raw.strip():
            raise RuntimeExecutionError("Sono presenti container NIPAT attivi: modifica delle risorse interrotta.")

    def _assert_other_wsl_idle(self, instances: tuple[str, ...]) -> None:
        """Older NIPAT installs may not participate in the new shared lock."""
        from nipat.execution.transport import WslDockerTransport
        for name in instances:
            if name == self.transport.distro or not name.casefold().startswith("nipat"):
                continue
            other = ResourceManager(WslDockerTransport(name), home=self.home)
            try:
                other._assert_idle()
            except RuntimeExecutionError as exc:
                raise RuntimeExecutionError(
                    f"Impossibile confermare che {name} sia priva di analisi attive. "
                    "Chiudere quella sessione prima del riavvio globale WSL."
                ) from exc

    def _backup(self, path: Path, contents: bytes | None) -> Path:
        directory = self.home / ".nipat" / "resource-backups"
        if directory.is_symlink():
            raise ValidationError("La cartella dei backup risorse non può essere un collegamento.")
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup = directory / f"{self.backend}-{stamp}-{uuid.uuid4().hex}.json"
        import base64
        document = {"schema_version": 1, "path": str(path), "existed": contents is not None,
                    "sha256": _fingerprint(contents),
                    "content_base64": base64.b64encode(contents).decode("ascii") if contents is not None else None}
        with backup.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
        backup.chmod(0o600)
        return backup

    @staticmethod
    def _replace(path: Path, contents: bytes) -> None:
        temporary = path.with_name(path.name + ".nipat-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def apply(self, change: ResourceChange, *, confirmed: bool,
              restart_confirmed: bool = False) -> dict:
        if confirmed is not True:
            raise ValidationError("La modifica delle risorse richiede la conferma dell'anteprima.")
        if not isinstance(change, ResourceChange) or change.backend != self.backend:
            raise ValidationError("Anteprima risorse non valida per questo ambiente.")
        if not isinstance(change.after, dict) or set(change.after) != {"memory_mib", "cpus"}:
            raise ValidationError("Valori dell'anteprima risorse non validi.")
        with _resource_lock(self.home, self.backend, exclusive=True):
            # Recompute the bytes and target; never trust a supplied replacement/path.
            current = self.preview(change.after["memory_mib"], change.after["cpus"])
            if current.config_path != change.config_path or current.expected_sha256 != change.expected_sha256:
                raise ValidationError("La configurazione è cambiata dopo l'anteprima. Richiedere una nuova anteprima.")
            if restart_confirmed and current.affected_running != change.affected_running:
                raise ValidationError("Le VM attive sono cambiate dopo l'anteprima. Richiedere una nuova conferma del riavvio.")
            if self.backend == "lima" and current.affected_running and not restart_confirmed:
                raise ValidationError("Per modificare la VM Lima in esecuzione occorre confermare il suo riavvio.")
            target_running = (self.transport.distro in current.affected_running if self.backend == "wsl" else bool(current.affected_running))
            if target_running:
                self._assert_idle()
            if self.backend == "wsl" and restart_confirmed:
                self._assert_other_wsl_idle(current.affected_running)
            path = Path(current.config_path)
            contents = _config_bytes(path)
            if _fingerprint(contents) != current.expected_sha256:
                raise ValidationError("La configurazione è cambiata durante i controlli. Richiedere una nuova anteprima.")
            backup = self._backup(path, contents)
            result = {"backend": self.backend, "backup": str(backup), "requested": current.after,
                      "status": "saved-restart-required", "effective": dict(_EMPTY), "warnings": []}
            if self.backend == "wsl":
                if _fingerprint(_config_bytes(path)) != current.expected_sha256:
                    raise ValidationError("La configurazione WSL è cambiata prima del salvataggio. Richiedere una nuova anteprima.")
                self._replace(path, current.replacement)
                if restart_confirmed:
                    try:
                        if self._running() != current.affected_running:
                            result["warnings"].append("Configurazione salvata. Le VM attive sono cambiate: riavvio non eseguito, richiedere una nuova anteprima.")
                            return result
                        self._wsl(["--shutdown"])
                        # Start only NIPAT, never another distribution stopped by shutdown.
                        self._wsl(["--distribution", self.transport.distro, "--user", "root", "--exec",
                                   "/usr/local/bin/nipat-engine", "ensure"])
                    except RuntimeExecutionError as exc:
                        result["status"] = "verification-required"
                        result["warnings"].append(f"Configurazione salvata, riavvio non completato: {exc}")
                        return result
            else:
                runtime = self.transport.runtime
                from nipat.macos_runtime import INSTANCE, read_manifest
                with runtime.lock():
                    runtime._assert_owned()
                    runtime._host_check(read_manifest(runtime.project))
                    if _fingerprint(_config_bytes(path)) != current.expected_sha256:
                        raise ValidationError("La configurazione Lima è cambiata: richiedere una nuova anteprima.")
                    if self._running() != current.affected_running:
                        raise ValidationError("Lo stato della VM Lima è cambiato: richiedere una nuova anteprima.")
                    if target_running:
                        self._assert_idle()
                        runtime._run(runtime.host_prefix() + ["stop", INSTANCE], timeout=180)
                    try:
                        runtime._run(runtime.host_prefix() + ["edit", "--tty=false", "--cpus", str(current.after["cpus"]),
                                     "--memory", format(current.after["memory_mib"] / 1024, ".10g"), INSTANCE])
                        runtime._assert_owned()
                        if _lima_configuration(_config_bytes(path)) != current.after:
                            raise RuntimeExecutionError("Lima non ha applicato le risorse richieste.")
                    except (RuntimeExecutionError, ValidationError, OSError) as exc:
                        self._replace(path, contents)
                        raise RuntimeExecutionError(
                            f"Modifica Lima non completata; configurazione precedente ripristinata. "
                            f"La VM può essere arrestata e verrà riavviata alla prossima analisi. Backup: {backup}. {exc}"
                        ) from exc
                    if restart_confirmed:
                        try:
                            runtime._run(runtime.host_prefix() + ["start", "--tty=false", INSTANCE], timeout=180)
                        except RuntimeExecutionError as exc:
                            result["status"] = "verification-required"
                            result["warnings"].append(f"Configurazione salvata, riavvio non completato: {exc}")
                            return result
            if restart_confirmed:
                try:
                    result["effective"] = self._effective()
                    memory = result["effective"]["memory_mib"]
                    expected = current.after["memory_mib"]
                    if (result["effective"]["cpus"] == current.after["cpus"]
                            and expected * 0.85 <= memory <= expected * 1.05):
                        result["status"] = "applied"
                    else:
                        result["status"] = "verification-required"
                        result["warnings"].append("I valori effettivi non corrispondono alla richiesta; controllare configurazione e runtime prima di analizzare.")
                except RuntimeExecutionError as exc:
                    result["status"] = "verification-required"
                    result["warnings"].append(str(exc))
            return result
