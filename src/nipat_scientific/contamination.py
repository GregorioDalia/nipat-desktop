"""Prepare native Contamination inputs inside the scientific runtime.

The client selects host files and maps them to container paths. This module
validates the scientific inputs, normalizes the panel and stages tables for R.
It has no dependency on desktop paths, Docker, the CLI, or the R algorithms.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.presentation import validate_request_presentation
from nipat_scientific.files import require_count_input, require_file, write_input_report, detect_marker_type
from nipat_scientific.settings import normalize_settings
from nipat_scientific.panels import read_position_panel, write_position_panel


REQUEST_FIELDS = {"schema_version", "workflow", "panel", "samples", "work_dir", "out_dir"}


def _absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        raise ValidationError(f"{label}: percorso non valido.")
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{label}: occorre un percorso assoluto nel container.")
    return path.resolve()


def _sample_name(value: object) -> str:
    if not isinstance(value, str) or not value or not value.endswith(".txt") or any(
        char in "/\\" or unicodedata.category(char) == "Cc" for char in value
    ) or value in {".txt", "..txt"}:
        raise ValidationError("Nome campione non valido: atteso un nome file .txt senza separatori.")
    return value


def prepare_contamination(request: object) -> list[str]:
    """Validate a v1 request, stage fresh artifacts, and return native R argv.

    Existing run directories are allowed, but staging files cannot exist and
    output must be empty. Failed staging is left available for diagnosis;
    a subsequent invocation cannot overwrite it.
    """
    if not isinstance(request, dict) or not REQUEST_FIELDS.issubset(request) or set(request) - REQUEST_FIELDS - {"presentation", "marker_type", "scientific_settings"}:
        raise ValidationError("Richiesta Contamination non valida: campi mancanti o inattesi.")
    validate_request_presentation(request)
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValidationError("Versione della richiesta Contamination non supportata.")
    if request["workflow"] != "contamination":
        raise ValidationError("Workflow della richiesta Contamination non valido.")
    selected = request["samples"]
    if not isinstance(selected, list) or not selected:
        raise ValidationError("Nessuna tabella di input per Contamination.")

    panel = require_file(_absolute_path(request["panel"], "Pannello marcatori"), "Pannello marcatori")
    marker = request.get("marker_type")
    if marker not in (None, "auto", "SNP", "DNP"):
        raise ValidationError("Tipo di marcatore Contamination non valido.")
    if marker == "auto":
        marker = None
    settings = normalize_settings("contamination", request.get("scientific_settings", {}))
    samples: list[tuple[Path, str]] = []
    names: set[str] = set()
    warnings = []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"path", "name"}:
            raise ValidationError("Descrizione campione Contamination non valida.")
        name = _sample_name(item["name"])
        if name.casefold() in names:
            raise ValidationError(f"Nome file duplicato nello staging: {name}")
        names.add(name.casefold())
        source = require_file(_absolute_path(item["path"], "Output del caller"), "Output del caller")
        detected = detect_marker_type(source)
        if marker is None:
            marker = detected
        if marker != detected:
            raise ValidationError("Non mescolare tabelle SNP e DNP nella stessa analisi Contamination.")
        warnings.extend(require_count_input(source, marker_type=marker, cpi=False))
        samples.append((source, name))

    records = read_position_panel(panel, marker_type=marker)

    work_dir = _absolute_path(request["work_dir"], "Cartella di lavoro")
    out_dir = _absolute_path(request["out_dir"], "Cartella risultati")
    if work_dir.is_relative_to(out_dir) or out_dir.is_relative_to(work_dir):
        raise ValidationError("Le cartelle di lavoro e risultati devono essere distinte e non sovrapposte.")
    for source in [panel, *(path for path, _ in samples)]:
        if source.is_relative_to(work_dir) or source.is_relative_to(out_dir):
            raise ValidationError("Gli input non possono trovarsi nelle cartelle di lavoro o risultati.")
    for directory in (work_dir, out_dir):
        if directory.exists() and not directory.is_dir():
            raise ValidationError(f"La destinazione non è una cartella: {directory}")
    if out_dir.is_dir() and any(out_dir.iterdir()):
        raise ValidationError("La cartella risultati deve essere vuota.")
    staged_dir = work_dir / "inputs"
    native_panel = work_dir / f"{marker}panel.txt"
    for destination in (staged_dir, native_panel, work_dir / "input-validation.json"):
        if destination.exists() or destination.is_symlink():
            raise ValidationError(f"Preparazione già presente: {destination}")

    # All validation precedes writes. Inputs are never renamed or modified.
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    staged_dir.mkdir()
    for source, name in samples:
        shutil.copy2(source, staged_dir / name)
    write_position_panel(records, native_panel, marker_type=marker)
    write_input_report(work_dir, "contamination", warnings, normalized=[(panel, native_panel)])
    return [str(native_panel), str(staged_dir), str(out_dir),
            "--include_zero" if settings["include_zero"] else "--exclude_zero"]
