from __future__ import annotations

import csv
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import shlex

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
POPFREQ_COLUMNS = {"chr", "pos1", "pos2", "Ref_f.pop", "Alt_f.pop"}


@contextmanager
def input_text(path: Path):
    """Translate expected text/parser failures at the shared input boundary."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield handle
    except UnicodeError as exc:
        raise ValidationError(f"{path.name}: codifica non valida; salvare il file come UTF-8.") from exc
    except csv.Error as exc:
        raise ValidationError(f"{path.name}: tabella non valida ({exc}).") from exc


def table_rows(path: Path, required: set[str], context: str, *, whitespace: bool = False,
               delimiter: str = "\t"):
    """Yield complete, uniquely named rows without retaining a whole input table."""
    with input_text(path) as handle:
        if whitespace:
            def split_rows():
                for number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        yield number, shlex.split(line, comments=False)
                    except ValueError as exc:
                        raise ValidationError(f"{path.name}: riga {number}, delimitazione non valida.") from exc
            rows = split_rows()
        else:
            reader = csv.reader(handle, delimiter=delimiter, strict=True)
            rows = ((reader.line_num, row) for row in reader if row)
        first = next(rows, None)
        if first is None:
            raise ValidationError(f"File vuoto: {path}")
        _, names = first
        missing = sorted(required - set(names))
        if missing:
            raise ValidationError(f"{context}: colonne mancanti in {path.name}: {', '.join(missing)}")
        if len(names) != len(set(names)) or any(not name for name in names):
            raise ValidationError(f"{context}: colonne vuote o duplicate in {path.name}.")
        for number, row in rows:
            if len(row) != len(names):
                raise ValidationError(f"{path.name}: riga {number}, attese {len(names)} colonne, trovate {len(row)}.")
            yield number, dict(zip(names, row, strict=True))


def nonnegative_integer(value: str, path: Path, number: int, column: str, *, positive=False) -> int:
    try:
        parsed = Decimal(value)
        if (not parsed.is_finite() or not math.isfinite(float(parsed))
                or parsed != parsed.to_integral_value() or parsed < (1 if positive else 0)):
            raise ValueError
        return int(parsed)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        condition = "positivo" if positive else "non negativo"
        raise ValidationError(f"{path.name}: riga {number}, {column} deve essere un intero {condition}.") from exc


def locus_key(row: dict, path: Path, number: int) -> tuple[str, int, int]:
    chromosome = row["chr"].strip()
    if not chromosome or any(char.isspace() for char in chromosome):
        raise ValidationError(f"{path.name}: riga {number}, cromosoma non valido.")
    positions = tuple(nonnegative_integer(row[name], path, number, name, positive=True)
                      for name in ("pos1", "pos2"))
    if positions[1] <= positions[0]:
        raise ValidationError(f"{path.name}: riga {number}, pos2 deve essere maggiore di pos1.")
    return chromosome, *positions


def _warning(path: Path, number: int, code: str, message: str) -> dict:
    return {"code": code, "path": str(path), "row": number, "message": message}


def _counts(path: Path, *, cpi: bool) -> list[dict]:
    seen = set()
    warnings = []
    required = DNP_OUTPUT_COLUMNS if cpi else CONTAMINATION_COLUMNS
    for number, row in table_rows(path, required, "Input CPI non compatibile" if cpi else
                                  "Input contamination non compatibile", whitespace=cpi):
        key = locus_key(row, path, number)
        if key in seen:
            raise ValidationError(f"{path.name}: riga {number}, coordinate duplicate: {key}.")
        seen.add(key)
        counts = [nonnegative_integer(row[name], path, number, name)
                  for name in ("N_REF", "N_ALT", "N_Other")]
        if "total_count" in row:
            # The relationship to N_Other is scientific provenance, not a
            # repair rule: preserve supplied totals rather than recomputing.
            # Native DNPcall outer-joins every panel locus after filling primary
            # counts: a zero-coverage locus legitimately retains total_count=NA.
            # Preserve this absence; never synthesize a total or missing counts.
            missing_zero_total = row["total_count"].strip() == "NA" and not any(counts)
            total = None if missing_zero_total else nonnegative_integer(row["total_count"], path, number, "total_count")
            if total is not None and total != sum(counts):
                warnings.append(_warning(path, number, "input.total_count_mismatch",
                    "total_count differs from N_REF + N_ALT + N_Other; supplied values are preserved."))
        if cpi:
            for name in ("REF", "ALT"):
                allele = row[name]
                if len(allele) != 2 or set(allele.upper()) - set("ACGT"):
                    raise ValidationError(f"{path.name}: riga {number}, {name} deve essere un dinucleotide A/C/G/T.")
        if "ratio_REF_ALT" in row:
            raw = row["ratio_REF_ALT"].strip()
            if raw in {"NA", "NaN", ""}:
                if counts[0] + counts[1] > 0:
                    warnings.append(_warning(path, number, "input.missing_ratio",
                        "Supplied ratio_REF_ALT is missing despite REF/ALT reads; R may omit this locus."))
                continue
            try:
                ratio = float(raw)
                if not math.isfinite(ratio) or not 0 <= ratio <= 1:
                    raise ValueError
            except ValueError as exc:
                raise ValidationError(f"{path.name}: riga {number}, ratio_REF_ALT deve essere finito tra 0 e 1.") from exc
            if counts[0] + counts[1] and not math.isclose(
                    ratio, counts[0] / (counts[0] + counts[1]), rel_tol=0, abs_tol=1e-6):
                warnings.append(_warning(path, number, "input.ratio_mismatch",
                    "Supplied ratio_REF_ALT differs from counts; it is preserved, not recomputed."))
    return warnings


def require_dnp_input(path: Path) -> list[dict]:
    """Check imported CPI/DNP count tables; never repair or deduplicate data."""
    return _counts(path, cpi=True)


def require_population_frequencies(path: Path) -> list[dict]:
    seen = set()
    warnings = []
    for number, row in table_rows(path, POPFREQ_COLUMNS, "Frequenze di popolazione non compatibili"):
        key = locus_key(row, path, number)
        if key in seen:
            raise ValidationError(f"{path.name}: riga {number}, coordinate duplicate nelle frequenze: {key}.")
        seen.add(key)
        values = []
        for column in ("Ref_f.pop", "Alt_f.pop"):
            try:
                # This decimal-comma mode is part of the native CPI interface.
                value = float(row[column].replace(",", "."))
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError
            except ValueError as exc:
                raise ValidationError(f"{path.name}: riga {number}, {column} deve essere finita tra 0 e 1.") from exc
            values.append(value)
        if 0 in values:
            warnings.append(_warning(path, number, "input.zero_population_frequency",
                "A population frequency is zero; CPI may divide by zero for an informative locus."))
        if not math.isclose(sum(values), 1.0, rel_tol=0, abs_tol=1e-6):
            warnings.append(_warning(path, number, "input.frequency_sum",
                "REF and ALT frequencies do not sum to one; their interpretation requires domain review."))
    if not seen:
        raise ValidationError(f"Frequenze di popolazione senza loci: {path.name}")
    return warnings


def write_input_report(work_dir: Path, workflow: str, warnings: list[dict], *, normalized=None) -> None:
    """Record warnings and normalization provenance without changing source data."""
    copies = []
    for original, prepared in normalized or []:
        values = {"source": str(original), "prepared": str(prepared)}
        for label, path in (("source_sha256", original), ("prepared_sha256", prepared)):
            with path.open("rb") as handle:
                values[label] = hashlib.file_digest(handle, "sha256").hexdigest()
        copies.append(values)
    destination = work_dir / "input-validation.json"
    with destination.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "workflow": workflow, "status": "validated",
                   "warnings": warnings, "normalizations": copies}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    for warning in warnings:
        print(f"NIPAT input warning [{warning['code']}]: {Path(warning['path']).name}, "
              f"row {warning['row']}: {warning['message']}", flush=True)


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
    with input_text(path) as handle:
        first_line = handle.readline()
    if not first_line:
        raise ValidationError(f"File vuoto: {path}")
    if whitespace:
        return [part.strip('\"\'') for part in first_line.split()]
    try:
        return next(csv.reader([first_line.rstrip("\r\n")], delimiter="\t", strict=True))
    except csv.Error as exc:
        raise ValidationError(f"{path.name}: intestazione tabulare non valida ({exc}).") from exc


def require_columns(
    path: Path, required: set[str], context: str, *, whitespace: bool = False
) -> None:
    header = tabular_header(path, whitespace=whitespace)
    current = set(header)
    missing = sorted(required - current)
    if missing:
        raise ValidationError(
            f"{context}: colonne mancanti in {path.name}: {', '.join(missing)}"
        )
    if len(header) != len(current) or any(not name for name in header):
        raise ValidationError(f"{context}: colonne vuote o duplicate in {path.name}.")


def require_contamination_input(path: Path) -> list[dict]:
    # Upstream computes ratio_REF_ALT from counts when the column is absent.
    return _counts(path, cpi=False)


def require_snp_pileup(path: Path) -> None:
    """Check QNAME's required seventh-column position; R ignores later columns."""
    found = False
    with input_text(path) as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 7:
                raise ValidationError(
                    "SNPcall richiede un pileup con almeno 7 colonne, con QNAME nella settima "
                    "(--output-QNAME), senza intestazione."
                )
            try:
                if not fields[0] or int(fields[1]) < 1 or int(fields[3]) < 0:
                    raise ValueError
            except ValueError as exc:
                raise ValidationError(f"Pileup SNP: riga {number} non valida o intestazione presente.") from exc
            found = True
    if not found:
        raise ValidationError(f"Pileup SNP vuoto: {path}")
