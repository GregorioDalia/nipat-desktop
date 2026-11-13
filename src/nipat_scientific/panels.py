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
            # The caller builds locus keys as chr:pos1|chr:pos2 and splits
            # them using these delimiters. Reject ambiguous names up front.
            if any(char in chromosome for char in (":", "|", "\0")):
                raise ValidationError(f"DNP_list: cromosoma non rappresentabile alla riga {line_number}.")
            try:
                pos1 = int(pos1_text)
                pos2 = int(pos2_text)
            except ValueError as exc:
                raise ValidationError(
                    f"DNP_list: coordinate non numeriche alla riga {line_number}."
                ) from exc
            # DNPcall includes the base preceding pos1 in its four-base
            # window. Its zero-based BED start is pos1 - 2, so position 1
            # cannot produce a valid interval and must fail before execution.
            if pos1 < 2:
                raise ValidationError(
                    f"DNP_list: pos1 deve essere almeno 2 per includere la base precedente alla riga {line_number}."
                )
            if pos2 != pos1 + 1:
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
            if reference == alternative:
                raise ValidationError(f"DNP_list: REF e ALT devono essere distinti alla riga {line_number}.")
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


def write_position_panel(records: list[DnpRecord | SnpRecord], destination: Path, marker_type: str | None = None) -> None:
    """Normalize positions and retain optional reference/alternative alleles."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    snp = marker_type == "SNP" or (records and isinstance(records[0], SnpRecord))
    alleles = bool(records) and all(record.reference and record.alternative for record in records)
    if any(bool(record.reference or record.alternative) != alleles for record in records):
        raise ValidationError("Il pannello deve contenere REF/ALT per tutti i siti oppure per nessuno.")
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow((["chr", "pos"] if snp else ["chr", "pos1", "pos2"] if alleles else ["n°DNP", "chr", "pos1", "pos2"]) + (["REF", "ALT"] if alleles else []))
        for index, record in enumerate(records, 1):
            values = ([record.chromosome, record.position] if snp else
                      ([record.chromosome, record.pos1, record.pos2] if alleles else
                       [f"DNP{index:03d}", record.chromosome, record.pos1, record.pos2]))
            writer.writerow(values + ([record.reference, record.alternative] if alleles else []))


def read_snp_list(path: Path, *, for_bed: bool = True) -> list[SnpRecord]:
    """Accept SNPcall 2.0 panels and normalize the legacy chr:position format.

    Both interfaces use a three-base window. Coordinates must therefore leave
    room for both neighbours in R's signed 32-bit coordinate representation.
    ``for_bed`` remains a compatibility argument for existing callers.
    """
    records = []
    seen = set()
    for line_number, row in table_rows(path, {"pos", "ref", "alt"}, "Lista SNP"):
        if set(row) not in ({"pos", "ref", "alt"}, {"chr", "pos", "ref", "alt"}):
            raise ValidationError("Lista SNP: attese le colonne chr, pos, ref, alt oppure pos, ref, alt.")
        coordinate = row["pos"].strip()
        try:
            if "chr" in row:
                chromosome, position_text = row["chr"].strip(), coordinate
            else:
                chromosome, position_text = coordinate.rsplit(":", 1)
            position = int(position_text)
        except ValueError as exc:
            raise ValidationError(
                f"Lista SNP: coordinata non valida alla riga {line_number}: {coordinate}"
            ) from exc
        if (not 2 <= position <= 2147483646 or not chromosome or ":" in chromosome
                or any(c.isspace() for c in chromosome)):
            raise ValidationError(
                f"Lista SNP: posizione fuori intervallo 2..2147483646 o cromosoma non valido alla riga {line_number}: {coordinate}"
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
        writer.writerow(["chr", "pos", "ref", "alt"])
        for row in records:
            writer.writerow([row.chromosome, row.position, row.reference, row.alternative])


def read_position_panel(path: Path, marker_type: str = "DNP") -> list[DnpRecord | SnpRecord]:
    """Read typed coordinates, preserving optional alleles for downstream CPI."""
    if marker_type not in {"SNP", "DNP"}:
        raise ValidationError("Tipo marcatore non valido: usare SNP oppure DNP.")
    with input_text(path) as handle:
        rows = [(number, next(csv.reader([line], delimiter="\t", strict=True)))
                for number, line in enumerate(handle, 1) if line.strip()]
    if not rows:
        raise ValidationError(f"Pannello vuoto: {path}")
    if len(rows[0][1]) == 1:
        rows = [(number, row[0].split()) for number, row in rows]
    names = [re.sub(r"[^a-z0-9]", "", name.lower()) for name in rows[0][1]]
    if marker_type == "SNP" and set(names) == {"pos", "ref", "alt"}:
        return read_snp_list(path, for_bed=False)
    coordinates = ["chr", "pos"] if marker_type == "SNP" else ["chr", "pos1", "pos2"]
    if all(name in names for name in coordinates):
        if any(names.count(name) != 1 for name in coordinates + [x for x in ("ref", "alt") if x in names]):
            raise ValidationError(f"Colonne duplicate nel pannello: {path}")
        columns = [names.index(name) for name in coordinates]
        if ("ref" in names) != ("alt" in names):
            raise ValidationError(f"Il pannello richiede entrambe le colonne REF e ALT: {path}")
        allele_columns = [names.index(name) for name in ("ref", "alt")] if "ref" in names else []
        rows = rows[1:]
    else:
        columns = list(range(len(coordinates)))
        allele_columns = [len(coordinates), len(coordinates) + 1] if len(rows[0][1]) == len(coordinates) + 2 else []
    records, seen = [], set()
    for number, row in rows:
        if len(row) <= max(columns + allele_columns):
            raise ValidationError(f"Pannello: mancano campi alla riga {number}.")
        chromosome = row[columns[0]].strip()
        try:
            positions = [int(row[index]) for index in columns[1:]]
        except ValueError as exc:
            raise ValidationError(f"Pannello: coordinate non intere alla riga {number}.") from exc
        if (not chromosome or any(char.isspace() for char in chromosome) or min(positions) < 1
                or (marker_type == "DNP" and positions[1] <= positions[0])):
            raise ValidationError(f"Pannello: coordinate non valide alla riga {number}.")
        key = (chromosome, *positions)
        if key in seen:
            raise ValidationError(f"Pannello: coordinate duplicate alla riga {number}.")
        seen.add(key)
        alleles = [row[index].strip().upper() for index in allele_columns] if allele_columns else ["", ""]
        length = 1 if marker_type == "SNP" else 2
        if allele_columns and (any(len(value) != length or set(value) - set("ACGT") for value in alleles) or alleles[0] == alleles[1]):
            raise ValidationError(f"Pannello: REF/ALT devono essere alleli {marker_type} distinti alla riga {number}.")
        record_class = SnpRecord if marker_type == "SNP" else DnpRecord
        records.append(record_class(chromosome, *positions, *alleles))
    if not records:
        raise ValidationError(f"Pannello senza siti: {path}")
    return records


def write_snp_bed(positions: list[tuple[str, int]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        for chromosome, position in positions:
            writer.writerow([chromosome, position - 2, position + 1])
