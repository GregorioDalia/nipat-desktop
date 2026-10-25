from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from nipat_scientific.errors import ValidationError


@dataclass(frozen=True)
class DnpRecord:
    chromosome: str
    pos1: int
    pos2: int
    reference: str
    alternative: str


def read_dnp_list(path: Path) -> list[DnpRecord]:
    records: list[DnpRecord] = []
    seen: set[tuple[str, int, int]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            # DNPcall uses read.table() with its whitespace separator.
            row = line.split()
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != 5:
                raise ValidationError(
                    f"DNP_list: riga {line_number} con {len(row)} colonne, attese 5."
                )
            chromosome, pos1_text, pos2_text, reference, alternative = (
                value.strip() for value in row
            )
            try:
                pos1 = int(pos1_text)
                pos2 = int(pos2_text)
            except ValueError as exc:
                raise ValidationError(
                    f"DNP_list: coordinate non numeriche alla riga {line_number}."
                ) from exc
            if pos1 < 1 or pos2 != pos1 + 1:
                raise ValidationError(
                    f"DNP_list: pos2 deve essere pos1 + 1 alla riga {line_number}."
                )
            reference = reference.upper()
            alternative = alternative.upper()
            if len(reference) != 2 or len(alternative) != 2:
                raise ValidationError(
                    f"DNP_list: REF e ALT devono essere dinucleotidi alla riga {line_number}."
                )
            if set(reference + alternative) - set("ACGT"):
                raise ValidationError(
                    f"DNP_list: allele non valido alla riga {line_number}."
                )
            key = (chromosome, pos1, pos2)
            if key in seen:
                raise ValidationError(f"DNP_list: posizione duplicata alla riga {line_number}.")
            seen.add(key)
            records.append(DnpRecord(chromosome, pos1, pos2, reference, alternative))
    if not records:
        raise ValidationError(f"DNP_list vuoto: {path}")
    return records


def write_dnp_list(records: list[DnpRecord], destination: Path) -> None:
    """Write the validated five-column panel consumed by DNPcall."""
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        for record in records:
            writer.writerow([record.chromosome, record.pos1, record.pos2,
                             record.reference, record.alternative])


def write_position_panel(records: list[DnpRecord], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["n°DNP", "chr", "pos1", "pos2"])
        for index, record in enumerate(records, start=1):
            writer.writerow(
                [f"DNP{index:03d}", record.chromosome, record.pos1, record.pos2]
            )


def read_snp_positions(path: Path, *, for_bed: bool = True) -> list[tuple[str, int]]:
    positions: list[tuple[str, int]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not {"pos", "ref", "alt"}.issubset(reader.fieldnames):
            raise ValidationError("La lista SNP deve avere le colonne: pos, ref, alt.")
        for line_number, row in enumerate(reader, start=2):
            coordinate = (row.get("pos") or "").strip()
            try:
                chromosome, position_text = coordinate.rsplit(":", 1)
                position = int(position_text)
            except (ValueError, AttributeError) as exc:
                raise ValidationError(
                    f"Lista SNP: coordinata non valida alla riga {line_number}: {coordinate}"
                ) from exc
            if position < (2 if for_bed else 1) or not chromosome:
                raise ValidationError(
                    f"Lista SNP: posizione troppo bassa alla riga {line_number}: {coordinate}"
                )
            positions.append((chromosome, position))
    if not positions:
        raise ValidationError(f"Lista SNP vuota: {path}")
    return positions


def read_position_panel(path: Path) -> list[DnpRecord]:
    """Read coordinates without imposing the allele schema used by DNPcall.

    CPI and contamination consume only chr/pos1/pos2. Accept their native
    headered tables, headerless coordinates and the legacy five-column panel.
    The caller writes a normalized tabular copy; originals are never changed.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [(number, next(csv.reader([line], delimiter="\t")))
                for number, line in enumerate(handle, 1) if line.strip()]
    if not rows:
        raise ValidationError(f"Pannello vuoto: {path}")
    first = rows[0][1]
    if len(first) == 1:
        # Legacy DNP lists may also use whitespace like the upstream DNP reader.
        rows = [(number, row[0].split()) for number, row in rows]
        first = rows[0][1]
    names = [re.sub(r"[^a-z0-9]", "", name.lower()) for name in first]
    if all(name in names for name in ("chr", "pos1", "pos2")):
        if any(names.count(name) != 1 for name in ("chr", "pos1", "pos2")):
            raise ValidationError(f"Colonne coordinate duplicate nel pannello: {path}")
        columns = [names.index(name) for name in ("chr", "pos1", "pos2")]
        rows = rows[1:]
    else:
        columns = [0, 1, 2]
    records = []
    for number, row in rows:
        if len(row) <= max(columns):
            raise ValidationError(f"Pannello: mancano coordinate alla riga {number}.")
        chromosome, pos1, pos2 = (row[index].strip() for index in columns)
        try:
            first_pos, second_pos = int(pos1), int(pos2)
        except ValueError as exc:
            raise ValidationError(f"Pannello: coordinate non intere alla riga {number}.") from exc
        if not chromosome or min(first_pos, second_pos) < 1:
            raise ValidationError(f"Pannello: coordinate non valide alla riga {number}.")
        records.append(DnpRecord(chromosome, first_pos, second_pos, "", ""))
    if not records:
        raise ValidationError(f"Pannello senza siti: {path}")
    return records


def write_snp_bed(positions: list[tuple[str, int]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        for chromosome, position in positions:
            writer.writerow([chromosome, position - 2, position + 1])
