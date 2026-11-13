"""Validate postnatal trio inputs and stage byte-preserving calling tables."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import (
    detect_marker_type, require_count_input, require_file,
    require_population_frequencies, write_input_report,
)
from nipat_scientific.panels import read_position_panel, write_position_panel
from nipat_scientific.presentation import validate_request_presentation


REQUEST_FIELDS = {
    "schema_version", "workflow", "samples", "trios", "mother_prefix", "father_prefix",
    "child_prefix", "popfreq", "work_dir", "out_dir",
}
OPTIONAL_FIELDS = {"markers", "scientific_settings", "presentation", "marker_type"}
_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")


def _absolute_path(value: object, label: str) -> Path:
    if (not isinstance(value, str) or not value or not Path(value).is_absolute()
            or any(unicodedata.category(char) == "Cc" for char in value)):
        raise ValidationError(f"{label}: occorre un percorso assoluto senza caratteri di controllo.")
    return Path(value).resolve()


def normalize_trios(trios: object, mother_prefix: object, father_prefix: object,
                    child_prefix: object) -> tuple[str, list[str]]:
    """Reject duplicate tuples and file collisions; identifiers are role-local."""
    prefixes = (mother_prefix, father_prefix, child_prefix)
    if any(not isinstance(prefix, str) or (prefix and not _ID.fullmatch(prefix))
           for prefix in prefixes):
        raise ValidationError("Prefissi CPIN non validi: usare lettere, numeri, punti, trattini o underscore.")
    if not isinstance(trios, str) or not trios.strip():
        raise ValidationError("Specificare almeno una terna madre:padre:figlio.")
    normalized, selected = [], []
    tuples, outputs, filenames = set(), set(), {}
    file_owners = {}
    for raw in trios.split(","):
        ids = tuple(part.strip() for part in raw.split(":"))
        if len(ids) != 3 or any(not _ID.fullmatch(part) or part in {".", ".."} for part in ids):
            raise ValidationError(f"Terna CPIN non valida: {raw}")
        folded = tuple(part.casefold() for part in ids)
        if folded in tuples:
            raise ValidationError("Terna CPIN duplicata.")
        tuples.add(folded)
        output = f"Mother{ids[0]}-Father{ids[1]}-Child{ids[2]}".casefold()
        if output in outputs:
            raise ValidationError("Terne CPIN distinte produrrebbero lo stesso nome di risultato.")
        outputs.add(output)
        for role, prefix, identifier in zip(("mother", "father", "child"), prefixes, ids):
            name = f"{prefix}{identifier}.txt"
            key = name.casefold()
            if key in filenames and filenames[key] != name:
                raise ValidationError("Nomi di campione CPIN ambigui per maiuscole/minuscole.")
            if key in file_owners and file_owners[key] != (role, identifier.casefold()):
                raise ValidationError("Prefissi e identificativi CPIN fanno coincidere campioni distinti.")
            file_owners[key] = (role, identifier.casefold())
            if key not in filenames:
                filenames[key] = name
                selected.append(name)
        normalized.append(":".join(ids))
    return ",".join(normalized), selected


def prepare_cpin(request: object) -> list[str]:
    """Prepare the CPIN v1 request after complete structural/input validation."""
    if (not isinstance(request, dict) or not REQUEST_FIELDS <= set(request)
            or set(request) - REQUEST_FIELDS - OPTIONAL_FIELDS):
        raise ValidationError("Richiesta CPIN non valida: campi mancanti o inattesi.")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValidationError("Versione della richiesta CPIN non supportata.")
    if request["workflow"] != "cpin":
        raise ValidationError("Workflow della richiesta CPIN non valido.")
    from nipat_scientific.settings import normalize_settings
    settings = normalize_settings("cpin", request.get("scientific_settings", {}))
    trios, required_names = normalize_trios(request["trios"], request["mother_prefix"],
                                          request["father_prefix"], request["child_prefix"])
    population = require_file(_absolute_path(request["popfreq"], "Frequenze di popolazione"),
                              "Frequenze di popolazione")
    marker_type = detect_marker_type(population)
    if request.get("marker_type") not in (None, marker_type):
        raise ValidationError("Il tipo di marcatori CPIN non corrisponde alle frequenze.")
    warnings = require_population_frequencies(population, marker_type)
    selected = request["samples"]
    if not isinstance(selected, list) or not selected:
        raise ValidationError("Nessuna tabella di input CPIN.")
    samples, source_names = {}, {}
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"path", "name"}:
            raise ValidationError("Descrizione campione CPIN non valida.")
        name = item["name"]
        if not isinstance(name, str) or name not in required_names or name in samples:
            raise ValidationError("Nome di campione CPIN inatteso o duplicato.")
        source = require_file(_absolute_path(item["path"], "Tabella di conteggi"), "Tabella di conteggi")
        if any(source.samefile(previous) for previous in source_names):
            raise ValidationError("La stessa tabella non può identificare due campioni CPIN distinti.")
        source_names[source] = name
        warnings.extend(require_count_input(source, marker_type, cpi=True))
        if any(warning.get("code") == "input.total_count_mismatch" for warning in warnings):
            raise ValidationError("CPIN richiede total_count uguale a N_REF + N_ALT + N_Other.")
        samples[name] = source
    if set(samples) != set(required_names):
        raise ValidationError("Mancano campioni richiesti dalle terne CPIN.")
    validate_request_presentation(request)
    panel = None
    records = None
    if request.get("markers") is not None:
        panel = require_file(_absolute_path(request["markers"], "Pannello CPIN"), "Pannello CPIN")
        records = read_position_panel(panel, marker_type)
        if any(not record.reference or not record.alternative for record in records):
            raise ValidationError("Il pannello CPIN richiede anche gli alleli REF e ALT.")
    work = _absolute_path(request["work_dir"], "Cartella di lavoro")
    output = _absolute_path(request["out_dir"], "Cartella risultati")
    if work.is_relative_to(output) or output.is_relative_to(work):
        raise ValidationError("Le cartelle di lavoro e risultati devono essere distinte e non sovrapposte.")
    for source in [population, *samples.values(), *([panel] if panel else [])]:
        if source.is_relative_to(work) or source.is_relative_to(output):
            raise ValidationError("Gli input CPIN devono trovarsi fuori dalle cartelle di lavoro e risultati.")
    for directory in (work, output):
        if directory.exists() and not directory.is_dir():
            raise ValidationError(f"La destinazione non è una cartella: {directory}")
    if output.is_dir() and any(output.iterdir()):
        raise ValidationError("La cartella risultati CPIN deve essere vuota.")
    staged = work / "inputs"
    native_panel = work / "markers.tsv"
    for target in (staged, native_panel, work / "input-validation.json"):
        if target.exists() or target.is_symlink():
            raise ValidationError(f"Preparazione già presente: {target}")
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    staged.mkdir()
    for name in required_names:
        shutil.copy2(samples[name], staged / name)
    normalized = []
    if panel:
        write_position_panel(records, native_panel, marker_type)
        normalized.append((panel, native_panel))
    write_input_report(work, "cpin", warnings, normalized=normalized)
    arguments = ["--pileup_dir", str(staged), "--out_dir", str(output),
                 f"--trios={trios}", f"--mother_prefix={request['mother_prefix']}",
                 f"--father_prefix={request['father_prefix']}", f"--child_prefix={request['child_prefix']}",
                 "--popfreq", str(population)]
    for key in ("min_child_reads", "site_selection", "err_const_snp", "err_const_dnp"):
        arguments.extend(("--" + key, str(settings[key])))
    if panel:
        arguments.extend(("--markers", str(native_panel)))
    return arguments
