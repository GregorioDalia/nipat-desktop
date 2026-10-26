"""Shared storage policy for direct commands and the guided client.

Installer metadata is read-only here. Data and results must never overlap the
runtime/cache locations, independently of which interface starts a run.
"""
from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
import sys
from typing import TYPE_CHECKING, Any

from nipat.errors import ValidationError

if TYPE_CHECKING:
    from nipat.paths import ProjectLayout

MAX_LAYOUT_BYTES = 1024 * 1024


def validate_windows_storage_path(path: Path) -> None:
    """Validate local fixed drives before following a destination's links."""
    if sys.platform != "win32":
        return
    from nipat.execution.transport import _drive_type, _windows_path

    raw = str(path)
    parsed = PureWindowsPath(raw)
    if not parsed.is_absolute() and not raw.startswith(("\\\\", "//")):
        raw = str(path.absolute())
    parsed = _windows_path(raw)
    if _drive_type(parsed.anchor) != 3:
        raise ValidationError(
            f"La cartella deve trovarsi su un disco locale fisso: {parsed.anchor}. "
            "Le unita' di rete e rimovibili non sono supportate per dati e risultati."
        )


def resolve_storage_path(value: Path | str) -> Path:
    path = Path(value).expanduser()
    validate_windows_storage_path(path)
    resolved = path.resolve()
    validate_windows_storage_path(resolved)
    return resolved


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Chiave duplicata: {key}")
        result[key] = value
    return result


def validate_managed_directories(layout: ProjectLayout) -> None:
    """Reject unsafe destinations before any directory or run is created.

    A checkout and Linux package have no Windows installation record. When a
    record is present, malformed metadata cannot silently waive the policy.
    """
    record = layout.project_dir / ".runtime" / "install-layout.json"
    if not record.exists() and not record.is_symlink():
        return
    try:
        if record.is_symlink():
            raise ValueError("collegamento non consentito")
        with record.open("rb") as stream:
            content = stream.read(MAX_LAYOUT_BYTES + 1)
        if len(content) > MAX_LAYOUT_BYTES:
            raise ValueError("dimensione del record")
        data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        fields = {"app_dir", "runtime_dir", "cache_dir", "data_dir", "runs_dir"}
        if (not isinstance(data, dict)
                or data.keys() != fields | {"schema_version", "installation_channel"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or data["installation_channel"] != "desktop"):
            raise ValueError("formato o identita del record")
        directories = {}
        for key in fields:
            value = data[key]
            if (not isinstance(value, str) or not value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError("percorso non valido")
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError("percorso non assoluto")
            directories[key] = resolve_storage_path(path)
        if directories["app_dir"] != layout.project_dir.resolve():
            raise ValueError("cartella applicazione diversa dal record")
        paths = list(directories.values())
        for index, path in enumerate(paths):
            if path == Path(path.anchor):
                raise ValueError("radice del disco riservata")
            if any(path.is_relative_to(other) or other.is_relative_to(path)
                   for other in paths[index + 1:]):
                raise ValueError("cartelle di installazione sovrapposte")
    except (OSError, ValueError, UnicodeError, RecursionError, ValidationError) as exc:
        raise ValidationError(
            f"Configurazione delle cartelle installate non valida: {record}. "
            "Riaprire il setup NIPAT per ripararla prima di modificare le destinazioni."
        ) from exc
    for name in ("data_dir", "runs_dir"):
        selected = getattr(layout, name).resolve()
        for role in ("runtime_dir", "cache_dir"):
            protected = directories[role]
            if selected.is_relative_to(protected) or protected.is_relative_to(selected):
                raise ValidationError(
                    f"La cartella {name} si sovrappone alla destinazione riservata {role}: "
                    f"{protected}. Scegliere una cartella separata."
                )
