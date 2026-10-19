from __future__ import annotations

import csv
from pathlib import Path

from nipat.errors import ValidationError


DNP_OUTPUT_COLUMNS = {
    "chr",
    "pos1",
    "pos2",
    "REF",
    "ALT",
    "N_REF",
    "N_ALT",
    "N_Other",
    "total_count",
}

CONTAMINATION_COLUMNS = {"chr", "pos1", "pos2", "N_REF", "N_ALT", "N_Other"}


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValidationError(f"{label} non trovato: {resolved}")
    return resolved


def require_directory(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ValidationError(f"{label} non trovata: {resolved}")
    return resolved


def require_sidecar(path: Path, suffix: str, label: str) -> Path:
    sidecar = Path(f"{path}{suffix}")
    if not sidecar.is_file():
        raise ValidationError(f"{label} non trovato: {sidecar}")
    return sidecar


def tabular_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline()
    if not first_line:
        raise ValidationError(f"File vuoto: {path}")
    return next(csv.reader([first_line.rstrip("\r\n")], delimiter="\t"))


def require_columns(path: Path, required: set[str], context: str) -> None:
    current = set(tabular_header(path))
    missing = sorted(required - current)
    if missing:
        raise ValidationError(
            f"{context}: colonne mancanti in {path.name}: {', '.join(missing)}"
        )


def require_contamination_input(path: Path) -> None:
    # Upstream computes ratio_REF_ALT from counts when the column is absent.
    require_columns(path, CONTAMINATION_COLUMNS, "Input contamination non compatibile")
