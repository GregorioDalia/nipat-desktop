"""Prepare DNPcall's native files inside the scientific image.

The unchanged R script parses equals-delimited options and builds an unquoted
samtools shell command. Only safe container aliases reach that interface;
original host paths are retained by the client, not passed to R.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import require_file, require_sidecar
from nipat_scientific.panels import read_dnp_list, write_dnp_list


REQUEST_FIELDS = {
    "schema_version", "workflow", "panel", "samples", "reference", "parallel",
    "work_dir", "out_dir",
}


@dataclass(frozen=True)
class DnpPreparation:
    native_arguments: list[str]
    working_dir: Path


def _absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        raise ValidationError(f"{label}: percorso non valido.")
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{label}: occorre un percorso assoluto nel container.")
    return path.resolve()


def _native_path(path: Path, label: str) -> str:
    # Posix separators also keep preparation tests portable on Windows. In the
    # Linux image these paths are absolute container-side aliases.
    value = path.as_posix()
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", value) is None:
        raise ValidationError(
            f"{label}: DNPcall richiede un alias di input senza spazi o caratteri speciali."
        )
    return value


def prepare_dnp(request: object) -> DnpPreparation:
    """Validate all inputs before writing native panel/list for unchanged R."""
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValidationError("Richiesta DNPcall non valida: campi mancanti o inattesi.")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValidationError("Versione della richiesta DNPcall non supportata.")
    if request["workflow"] != "dnp-call":
        raise ValidationError("Workflow della richiesta DNPcall non valido.")
    if type(request["parallel"]) is not bool:
        raise ValidationError("La modalità parallela DNPcall deve essere booleana.")
    selected = request["samples"]
    if not isinstance(selected, list) or not selected:
        raise ValidationError("Nessun BAM selezionato per DNPcall.")

    panel = require_file(_absolute_path(request["panel"], "Pannello DNP"), "Pannello DNP")
    records = read_dnp_list(panel)
    reference = require_file(_absolute_path(request["reference"], "FASTA"), "FASTA")
    native_reference = _native_path(reference, "FASTA")
    sources = [panel, reference, require_sidecar(reference, ".fai", "Indice FASTA").resolve()]
    if reference.suffix.lower() in {".gz", ".bgz", ".bgzf"}:
        sources.append(require_sidecar(reference, ".gzi", "Indice FASTA BGZF").resolve())

    bams: list[str] = []
    seen: set[Path] = set()
    for number, item in enumerate(selected, start=1):
        if not isinstance(item, dict) or set(item) != {"path", "sample_id"}:
            raise ValidationError("Descrizione campione DNPcall non valida.")
        expected_id = f"sample_{number:04d}"
        if item["sample_id"] != expected_id:
            raise ValidationError(f"Alias campione DNPcall non valido: atteso {expected_id}.")
        bam = require_file(_absolute_path(item["path"], "BAM"), "BAM")
        native_bam = _native_path(bam, "BAM")
        if bam.name != f"{expected_id}.bam":
            raise ValidationError(f"Il BAM deve usare il nome alias {expected_id}.bam.")
        if bam in seen:
            raise ValidationError("Lo stesso BAM compare più volte nella richiesta DNPcall.")
        seen.add(bam)
        bams.append(native_bam)
        sources.append(bam)
        # The native mpileup uses -l: BAM indexes remain optional and are never
        # created next to user data. Include any supplied sidecars in overlap checks.
        for suffix in (".bai", ".csi"):
            for candidate in (Path(str(bam) + suffix), bam.with_suffix(suffix)):
                if candidate.is_file():
                    sources.append(candidate.resolve())

    work_dir = _absolute_path(request["work_dir"], "Cartella di lavoro")
    out_dir = _absolute_path(request["out_dir"], "Cartella risultati")
    if work_dir.name != "work" or out_dir.name != "output" or work_dir.parent != out_dir.parent:
        raise ValidationError("DNPcall richiede cartelle work e output nella stessa radice di esecuzione.")
    run_dir = work_dir.parent
    for source in sources:
        if source.is_relative_to(work_dir) or source.is_relative_to(out_dir):
            raise ValidationError("Gli input non possono trovarsi nelle cartelle di lavoro o risultati.")
    for directory in (run_dir, work_dir, out_dir):
        if directory.exists() and not directory.is_dir():
            raise ValidationError(f"La destinazione non è una cartella: {directory}")
    if out_dir.is_dir() and any(out_dir.iterdir()):
        raise ValidationError("La cartella risultati deve essere vuota.")
    native_panel = work_dir / "DNP_list.txt"
    bamlist = work_dir / "bamlist.txt"
    for destination in (
        native_panel, bamlist, run_dir / "mpileup.txt", run_dir / "bedfile_for_mpileup.bed",
    ):
        if destination.exists() or destination.is_symlink():
            raise ValidationError(f"Preparazione già presente: {destination}")

    # All validation precedes writes; large files are read through their mounts.
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dnp_list(records, native_panel)
    with bamlist.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(path + "\n" for path in bams))
    arguments = [
        "--bamlist=work/bamlist.txt", "--DNPs=work/DNP_list.txt",
        # R searches options with unanchored regular expressions and takes the
        # first match. Keep fixed options before the reference so a safe alias
        # such as /inputs/--output/genome.fa cannot become the output directory.
        "--out=output", f"--reference={native_reference}",
    ]
    if request["parallel"]:
        arguments.append("--parallel")
    return DnpPreparation(arguments, run_dir)
