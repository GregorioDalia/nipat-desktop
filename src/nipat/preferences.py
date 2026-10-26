"""Persistent defaults for the guided interface, independent of runtime ownership.

Preferences never launch tools, move existing data or alter installer metadata.
Direct CLI commands deliberately do not consume these defaults.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping

from nipat.errors import ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.paths import ProjectLayout
from nipat.storage import validate_windows_storage_path as _validate_windows_storage_path


SCHEMA_VERSION = 1
MAX_SETTINGS_BYTES = 1024 * 1024
WORKFLOW_KEYS = {
    "1": frozenset({"mode", "reference", "panel", "parallel"}),
    "2": frozenset({"mode", "reference", "panel"}),
    "3": frozenset({"mode", "panel"}),
    "4": frozenset({"mother_prefix", "father_prefix", "popfreq", "cutoff_mode",
                    "panel", "cutoffs", "cutoff_map", "err_const"}),
}
_PATH_KEYS = frozenset({"reference", "panel", "popfreq"})
_UNSET = object()


def preferences_path() -> Path:
    """Return the per-user path without creating any directory."""
    override = os.environ.get("NIPAT_SETTINGS_FILE")
    if override:
        return Path(override).expanduser().absolute()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise ValidationError("LOCALAPPDATA non disponibile per le impostazioni NIPAT.")
        path = Path(base) / "NIPAT-Desktop" / "preferences.json"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        if not base.is_absolute():
            raise ValidationError("XDG_CONFIG_HOME deve essere un percorso assoluto.")
        path = base / "nipat-desktop" / "preferences.json"
    return path.expanduser().absolute()


def _text(value: Any, label: str, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or (not empty and not value.strip())
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValidationError(f"Impostazione {label} non valida.")
    return value


def _path(value: Any, label: str, *, stored: bool = False) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValidationError(f"Percorso {label} non valido.")
    raw = _text(str(value), label)
    path = Path(raw).expanduser()
    if stored and not path.is_absolute():
        raise ValidationError(f"Il percorso salvato per {label} deve essere assoluto.")
    if label in {"data_dir", "runs_dir"}:
        _validate_windows_storage_path(path)
    resolved = path.resolve()
    if label in {"data_dir", "runs_dir"}:
        # Also check a local path that resolves through a link onto another drive.
        _validate_windows_storage_path(resolved)
    return resolved


def _label(value: Any) -> str:
    label = _text(value, "etichetta cutoff").strip()
    if any(char in label for char in ",="):
        raise ValidationError("Etichetta cutoff non valida: evitare virgole e '='.")
    return label


def _cutoffs(value: Any, *, stored: bool) -> list[tuple[str, Path]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("Indicare almeno un cutoff predefinito.")
    result = []
    labels = set()
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValidationError("Cutoff predefinito non valido: attesi etichetta e percorso.")
        label = _label(item[0])
        if label in labels:
            raise ValidationError(f"Etichetta cutoff duplicata: {label}")
        labels.add(label)
        result.append((label, _path(item[1], "cutoff", stored=stored)))
    return result


def _cutoff_map(value: Any, *, stored: bool) -> str:
    entries = []
    for entry in _text(value, "mappa cutoff").split(","):
        if "=" not in entry:
            raise ValidationError("Mappa cutoff: usare etichetta=percorso.")
        label, filename = (part.strip() for part in entry.split("=", 1))
        entries.append((label, filename))
    return ",".join(f"{label}={path}" for label, path in _cutoffs(entries, stored=stored))


def _workflow_values(choice: str, values: Any, *, stored: bool = False) -> dict[str, Any]:
    if not isinstance(choice, str) or choice not in WORKFLOW_KEYS or not isinstance(values, dict):
        raise ValidationError("Workflow nelle impostazioni non valido.")
    if not all(isinstance(key, str) for key in values):
        raise ValidationError("Nomi delle impostazioni workflow non validi.")
    unknown = values.keys() - WORKFLOW_KEYS[choice]
    if unknown:
        raise ValidationError("Impostazioni workflow non riconosciute: " + ", ".join(sorted(unknown)))
    normalized = {}
    for key, value in values.items():
        if key in _PATH_KEYS:
            normalized[key] = _path(value, key, stored=stored)
        elif key in {"mode", "parallel", "cutoff_mode"}:
            allowed = {"0", "1", "2", "3"} if key == "cutoff_mode" else {"1", "2"}
            if not isinstance(value, str) or value not in allowed:
                raise ValidationError(f"Selezione {key} non valida.")
            normalized[key] = value
        elif key in {"mother_prefix", "father_prefix"}:
            prefix = _text(value, key, empty=True)
            if any(char in prefix for char in "/\\"):
                raise ValidationError("I prefissi non possono contenere separatori di cartella.")
            normalized[key] = prefix
        elif key == "err_const":
            try:
                valid_number = type(value) in {int, float} and math.isfinite(value) and value >= 0
            except OverflowError:
                valid_number = False
            if not valid_number:
                raise ValidationError("La costante di errore deve essere finita e maggiore o uguale a zero.")
            normalized[key] = float(value)
        elif key == "cutoffs":
            normalized[key] = _cutoffs(value, stored=stored)
        elif key == "cutoff_map":
            normalized[key] = _cutoff_map(value, stored=stored)
    return normalized


@dataclass(frozen=True)
class Preferences:
    """Optional overrides only; omitted fields retain their application defaults."""

    data_dir: Path | None = None
    runs_dir: Path | None = None
    workflows: dict[str, dict[str, Any]] = field(default_factory=dict)
    update_channel: str = "testing"
    check_updates_on_startup: bool = False
    execution: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.update_channel, str) or self.update_channel not in {"stable", "testing"}:
            raise ValidationError("Canale aggiornamenti non valido: scegliere stable o testing.")
        if type(self.check_updates_on_startup) is not bool:
            raise ValidationError("Il controllo aggiornamenti all'avvio deve essere attivo o disattivo.")
        if (not isinstance(self.execution, dict)
                or self.execution.keys() - {"input_hashes", "cpus", "memory_mb", "pids_limit"}):
            raise ValidationError("Opzioni di esecuzione non riconosciute.")
        normalized_execution = asdict(ExecutionOptions(**self.execution))
        object.__setattr__(self, "execution", {
            key: normalized_execution[key] for key in self.execution
        })
        for name in ("data_dir", "runs_dir"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _path(value, name))
        if not isinstance(self.workflows, dict):
            raise ValidationError("Impostazioni dei workflow non valide.")
        object.__setattr__(self, "workflows", {
            choice: _workflow_values(choice, values) for choice, values in self.workflows.items()
        })

    def workflow_defaults(self, choice: str) -> dict[str, Any]:
        if choice not in WORKFLOW_KEYS:
            raise ValidationError("Workflow non riconosciuto.")
        return deepcopy(self.workflows.get(choice, {}))

    def execution_options(self, overrides: Mapping[str, Any] | None = None) -> ExecutionOptions:
        """Saved guided defaults, with explicit command-line overrides applied last."""
        values = dict(self.execution)
        values.update(overrides or {})
        if values.keys() - {"input_hashes", "cpus", "memory_mb", "pids_limit"}:
            raise ValidationError("Opzioni di esecuzione non riconosciute.")
        return ExecutionOptions(**values)

    def with_workflow(self, choice: str, values: dict[str, Any]) -> "Preferences":
        workflows = deepcopy(self.workflows)
        normalized = _workflow_values(choice, values)
        if normalized:
            workflows[choice] = normalized
        else:
            workflows.pop(choice, None)
        return replace(self, workflows=workflows)

    def with_directories(self, *, data_dir: Path | str | None | object = _UNSET,
                         runs_dir: Path | str | None | object = _UNSET) -> "Preferences":
        updates = {key: value for key, value in (("data_dir", data_dir), ("runs_dir", runs_dir))
                   if value is not _UNSET}
        return replace(self, **updates)

    def effective_layout(self, base: ProjectLayout,
                         directory_overrides: Mapping[str, Path] | None = None) -> ProjectLayout:
        """Saved directories override installed defaults; explicit CLI flags win."""
        overrides = dict(directory_overrides or {})
        if overrides.keys() - {"data_dir", "runs_dir"}:
            raise ValidationError("Opzioni di cartella non riconosciute.")
        updates = {
            key: _path(overrides.get(key, getattr(self, key) or getattr(base, key)), key)
            for key in ("data_dir", "runs_dir")
        }
        layout = replace(base, **updates)
        layout.validate_storage_roots()
        return layout

    def to_dict(self) -> dict[str, Any]:
        workflows = {}
        for choice, values in self.workflows.items():
            workflows[choice] = {}
            for key, value in _workflow_values(choice, values).items():
                if isinstance(value, Path):
                    value = str(value)
                elif key == "cutoffs":
                    value = [[label, str(path)] for label, path in value]
                workflows[choice][key] = value
        return {"schema_version": SCHEMA_VERSION,
                "data_dir": str(self.data_dir) if self.data_dir is not None else None,
                "runs_dir": str(self.runs_dir) if self.runs_dir is not None else None,
                "workflows": workflows, "update_channel": self.update_channel,
                "check_updates_on_startup": self.check_updates_on_startup,
                "execution": deepcopy(self.execution)}

    @classmethod
    def from_dict(cls, document: Any) -> "Preferences":
        allowed = {"schema_version", "data_dir", "runs_dir", "workflows",
                   "update_channel", "check_updates_on_startup", "execution"}
        if (not isinstance(document, dict) or document.keys() - allowed
                or type(document.get("schema_version")) is not int
                or document["schema_version"] != SCHEMA_VERSION):
            raise ValidationError("Formato o versione delle impostazioni non riconosciuti.")
        workflows = document.get("workflows", {})
        if not isinstance(workflows, dict):
            raise ValidationError("Impostazioni dei workflow non valide.")
        normalized = {choice: _workflow_values(choice, values, stored=True)
                      for choice, values in workflows.items()}
        directories = {key: _path(value, key, stored=True) if value is not None else None
                       for key in ("data_dir", "runs_dir") if (value := document.get(key)) is not None}
        return cls(**directories, workflows=normalized,
                   update_channel=document.get("update_channel", "testing"),
                   check_updates_on_startup=document.get("check_updates_on_startup", False),
                   execution=document.get("execution", {}))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Chiave duplicata nelle impostazioni: {key}")
        result[key] = value
    return result


class PreferencesStore:
    """Read and atomically replace one settings file; reset never touches analysis data."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path).expanduser().absolute() if path is not None else preferences_path()

    def load(self) -> Preferences:
        try:
            if self.path.is_symlink():
                raise ValidationError("Il file delle impostazioni non puo' essere un collegamento.")
            with self.path.open("rb") as stream:
                content = stream.read(MAX_SETTINGS_BYTES + 1)
            if len(content) > MAX_SETTINGS_BYTES:
                raise ValidationError("File delle impostazioni troppo grande.")
            document = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object)
            return Preferences.from_dict(document)
        except FileNotFoundError:
            return Preferences()
        except (OSError, ValueError, UnicodeError, RecursionError, ValidationError) as exc:
            raise ValidationError(f"Impossibile leggere le impostazioni {self.path}: {exc}") from exc

    def save(self, preferences: Preferences) -> None:
        """An unreadable existing file requires explicit reset before replacement."""
        document = preferences.to_dict()
        Preferences.from_dict(document)
        content = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        if len(content) > MAX_SETTINGS_BYTES:
            raise ValidationError("Impostazioni troppo grandi per essere salvate.")
        self.load()  # Never silently replace malformed or inaccessible preferences.
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".preferences-", suffix=".tmp",
                                             dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ValidationError(f"Impossibile salvare le impostazioni {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # A failed best-effort cleanup must not hide the write error.
                    pass

    def reset(self) -> None:
        """Remove only this settings file, even when its content is malformed."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise ValidationError(f"Impossibile ripristinare le impostazioni {self.path}: {exc}") from exc
