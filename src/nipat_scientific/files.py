from __future__ import annotations

import csv
from pathlib import Path

from nipat_scientific.errors import ValidationError


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


def tabular_header(path: Path, *, whitespace: bool = False) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first_line = handle.readline()
    if not first_line:
        raise ValidationError(f"File vuoto: {path}")
    if whitespace:
        return [part.strip('\"\'') for part in first_line.split()]
    return next(csv.reader([first_line.rstrip("\r\n")], delimiter="\t"))


def require_columns(
    path: Path, required: set[str], context: str, *, whitespace: bool = False
) -> None:
    current = set(tabular_header(path, whitespace=whitespace))
    missing = sorted(required - current)
    if missing:
        raise ValidationError(
            f"{context}: colonne mancanti in {path.name}: {', '.join(missing)}"
        )


def require_contamination_input(path: Path) -> None:
    # Upstream computes ratio_REF_ALT from counts when the column is absent.
    require_columns(path, CONTAMINATION_COLUMNS, "Input contamination non compatibile")


def require_snp_pileup(path: Path) -> None:
    """Check QNAME's required seventh-column position; R ignores later columns."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if not line.strip():
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 7:
                raise ValidationError(
                    "SNPcall richiede un pileup con almeno 7 colonne, con QNAME nella settima "
                    "(--output-QNAME), senza intestazione."
                )
            try:
                if int(fields[1]) < 1 or int(fields[3]) < 0:
                    raise ValueError
            except ValueError as exc:
                raise ValidationError("Pileup SNP: prima riga non valida o intestazione presente.") from exc
            return
    raise ValidationError(f"Pileup SNP vuoto: {path}")
