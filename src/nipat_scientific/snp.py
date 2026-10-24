"""Prepare SNPcall inputs inside the scientific image without desktop imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import require_file, require_sidecar, require_snp_pileup
from nipat_scientific.panels import read_snp_positions, write_snp_bed


REQUEST_FIELDS = {
    "schema_version", "workflow", "mode", "panel", "bam", "pileup", "reference",
    "work_dir", "out_dir",
}


@dataclass(frozen=True)
class SnpPreparation:
    preparation_command: list[str] | None
    native_arguments: list[str]
    generated_pileup: Path | None


def _absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        raise ValidationError(f"{label}: percorso non valido.")
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{label}: occorre un percorso assoluto nel container.")
    return path.resolve()


def prepare_snp(request: object) -> SnpPreparation:
    """Validate a request before writes and describe samtools/R execution.

    The existing panel reader, three-base windows and mpileup options are
    preserved. Indexes are supplied as read-only sidecars, never generated next
    to user inputs. Only BAM mode writes the BED and later produces a pileup.
    """
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValidationError("Richiesta SNPcall non valida: campi mancanti o inattesi.")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValidationError("Versione della richiesta SNPcall non supportata.")
    if request["workflow"] != "snp-call":
        raise ValidationError("Workflow della richiesta SNPcall non valido.")
    mode = request["mode"]
    if not isinstance(mode, str) or mode not in {"bam", "pileup"}:
        raise ValidationError("Modalità SNPcall non valida: scegliere bam oppure pileup.")
    if mode == "bam":
        if request["bam"] is None or request["reference"] is None or request["pileup"] is not None:
            raise ValidationError("La modalità BAM richiede BAM e riferimento, senza pileup.")
    elif request["pileup"] is None or request["bam"] is not None or request["reference"] is not None:
        raise ValidationError("La modalità pileup richiede soltanto il pileup, senza BAM o riferimento.")

    panel = require_file(_absolute_path(request["panel"], "Lista SNP"), "Lista SNP")
    positions = read_snp_positions(panel, for_bed=mode == "bam")
    sources = [panel]
    bam = reference = None
    if mode == "bam":
        bam = require_file(_absolute_path(request["bam"], "BAM"), "BAM")
        reference = require_file(_absolute_path(request["reference"], "FASTA"), "FASTA")
        sources.extend([bam, reference, require_sidecar(reference, ".fai", "Indice FASTA").resolve()])
        if reference.suffix.lower() in {".gz", ".bgz", ".bgzf"}:
            sources.append(require_sidecar(reference, ".gzi", "Indice FASTA BGZF").resolve())
        for suffix in (".bai", ".csi"):
            for candidate in (Path(str(bam) + suffix), bam.with_suffix(suffix)):
                if candidate.is_file():
                    sources.append(candidate.resolve())
    else:
        pileup = require_file(_absolute_path(request["pileup"], "Pileup SNP"), "Pileup SNP")
        require_snp_pileup(pileup)
        sources.append(pileup)

    work_dir = _absolute_path(request["work_dir"], "Cartella di lavoro")
    out_dir = _absolute_path(request["out_dir"], "Cartella risultati")
    if work_dir.is_relative_to(out_dir) or out_dir.is_relative_to(work_dir):
        raise ValidationError("Le cartelle di lavoro e risultati devono essere distinte e non sovrapposte.")
    for source in sources:
        if source.is_relative_to(work_dir) or source.is_relative_to(out_dir):
            raise ValidationError("Gli input non possono trovarsi nelle cartelle di lavoro o risultati.")
    for directory in (work_dir, out_dir):
        if directory.exists() and not directory.is_dir():
            raise ValidationError(f"La destinazione non è una cartella: {directory}")
    if out_dir.is_dir() and any(out_dir.iterdir()):
        raise ValidationError("La cartella risultati deve essere vuota.")
    bed_file = work_dir / "snp_regions.bed"
    generated_pileup = work_dir / "pileup.txt"
    for destination in (bed_file, generated_pileup):
        if destination.exists() or destination.is_symlink():
            raise ValidationError(f"Preparazione già presente: {destination}")

    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = None
    if mode == "bam":
        write_snp_bed(positions, bed_file)
        pileup = generated_pileup
        command = [
            "samtools", "mpileup", "-f", str(reference), "-l", str(bed_file),
            "--output-QNAME", "--no-output-ins", "--no-output-del", "--no-output-ends",
            "-o", str(pileup), str(bam),
        ]
    return SnpPreparation(command, [
        "--pileup", str(pileup), "--snplist", str(panel),
        "--out", str(out_dir / "SNPcall_output.txt"),
    ], generated_pileup if mode == "bam" else None)
