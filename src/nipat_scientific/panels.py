from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import input_text, table_rows


@dataclass(frozen=True)
class DnpRecord:
    chromosome: str
    pos1: int
    pos2: int
    reference: str
    alternative: str


@dataclass(frozen=True)
class SnpRecord:
    chromosome: str
    position: int
    reference: str
    alternative: str


def read_dnp_list(path: Path) -> list[DnpRecord]:
    records: list[DnpRecord] = []
    seen: set[tuple[str, int, int]] = set()
    with input_text(path) as handle:
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


def read_snp_list(path: Path, *, for_bed: bool = True) -> list[SnpRecord]:
    records = []
    seen = set()
    for line_number, row in table_rows(path, {"pos", "ref", "alt"}, "Lista SNP"):
        coordinate = row["pos"].strip()
        try:
            chromosome, position_text = coordinate.rsplit(":", 1)
            position = int(position_text)
        except ValueError as exc:
            raise ValidationError(
                f"Lista SNP: coordinata non valida alla riga {line_number}: {coordinate}"
            ) from exc
        if position < (2 if for_bed else 1) or not chromosome or any(c.isspace() for c in chromosome):
            raise ValidationError(
                f"Lista SNP: posizione troppo bassa o cromosoma non valido alla riga {line_number}: {coordinate}"
            )
        alleles = [row[name].strip().upper() for name in ("ref", "alt")]
        if any(len(allele) != 1 or allele not in "ACGT" for allele in alleles) or alleles[0] == alleles[1]:
            raise ValidationError(f"{path.name}: riga {line_number}, ref e alt devono essere basi distinte A/C/G/T.")
        key = (chromosome, position)
        if key in seen:
            raise ValidationError(f"{path.name}: riga {line_number}, posizione SNP duplicata: {coordinate}.")
        seen.add(key)
        records.append(SnpRecord(chromosome, position, *alleles))
    if not records:
        raise ValidationError(f"Lista SNP vuota: {path}")
    return records


def read_snp_positions(path: Path, *, for_bed: bool = True) -> list[tuple[str, int]]:
    return [(row.chromosome, row.position) for row in read_snp_list(path, for_bed=for_bed)]


def write_snp_list(records: list[SnpRecord], destination: Path) -> None:
    with destination.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["pos", "ref", "alt"])
        for row in records:
            writer.writerow([f"{row.chromosome}:{row.position}", row.reference, row.alternative])


def read_position_panel(path: Path) -> list[DnpRecord]:
    """Read coordinates without imposing the allele schema used by DNPcall.

    CPI and contamination consume only chr/pos1/pos2. Accept their native
    headered tables, headerless coordinates and the legacy five-column panel.
    The caller writes a normalized tabular copy; originals are never changed.
    """
    with input_text(path) as handle:
        rows = [(number, next(csv.reader([line], delimiter="\t", strict=True)))
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
    seen = set()
    for number, row in rows:
        if len(row) <= max(columns):
            raise ValidationError(f"Pannello: mancano coordinate alla riga {number}.")
        chromosome, pos1, pos2 = (row[index].strip() for index in columns)
        try:
            first_pos, second_pos = int(pos1), int(pos2)
        except ValueError as exc:
            raise ValidationError(f"Pannello: coordinate non intere alla riga {number}.") from exc
        if (not chromosome or any(char.isspace() for char in chromosome)
                or min(first_pos, second_pos) < 1 or second_pos <= first_pos):
            raise ValidationError(f"Pannello: coordinate non valide alla riga {number}.")
        key = chromosome, first_pos, second_pos
        if key in seen:
            raise ValidationError(f"Pannello: coordinate duplicate alla riga {number}.")
        seen.add(key)
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
