"""Validate and prepare CPI inputs inside the scientific image, without R changes."""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import (
    POPFREQ_COLUMNS, require_dnp_input, require_file, require_population_frequencies,
    write_input_report,
)
from nipat_scientific.panels import read_position_panel, write_position_panel


REQUEST_FIELDS = {
    "schema_version", "workflow", "samples", "pairs", "mother_prefix", "father_prefix",
    "popfreq", "cutoff_mode", "cutoffs", "err_const", "work_dir", "out_dir",
}


def _absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        raise ValidationError(f"{label}: percorso non valido.")
    path = Path(value)
    if not path.is_absolute():
        raise ValidationError(f"{label}: occorre un percorso assoluto nel container.")
    return path.resolve()


def _name_component(value: object, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty) or any(
        char in "/\\" or unicodedata.category(char) == "Cc" for char in value
    ):
        raise ValidationError(f"{label} deve essere un nome senza separatori o caratteri di controllo.")
    return value


def normalize_pairs(pairs: object, mother_prefix: object, father_prefix: object) -> tuple[str, list[str]]:
    """Return canonical pair text and unique selected filenames in request order.

    R constructs pair output names independently of file prefixes. Distinct pairs
    that would overwrite a plot, including on Windows, are rejected explicitly.
    """
    mother = _name_component(mother_prefix, "Prefisso madre", empty=True)
    father = _name_component(father_prefix, "Prefisso padre", empty=True)
    if not isinstance(pairs, str) or not pairs:
        raise ValidationError("Coppie CPI mancanti o non valide.")
    normalized: list[str] = []
    selected: list[str] = []
    output_names: set[str] = set()
    sample_names: dict[str, str] = {}
    for pair in pairs.split(","):
        identifiers = [part.strip() for part in pair.split(":")]
        if len(identifiers) != 2 or not all(identifiers):
            raise ValidationError(f"Coppia CPI non valida: {pair}")
        for label, prefix, identifier in (
            ("Madre", mother, identifiers[0]), ("Padre", father, identifiers[1]),
        ):
            _name_component(identifier, f"Identificativo {label}")
            name = f"{prefix}{identifier}.txt"
            folded = name.casefold()
            if folded in sample_names and sample_names[folded] != name:
                raise ValidationError(f"Nomi campione CPI ambigui: {sample_names[folded]} e {name}.")
            if folded not in sample_names:
                sample_names[folded] = name
                selected.append(name)
        normalized_pair = ":".join(identifiers)
        if normalized_pair in normalized:
            raise ValidationError("Coppia CPI duplicata.")
        normalized.append(normalized_pair)
        output = f"Mother{identifiers[0]}-Father{identifiers[1]}_DNPs".casefold()
        if output in output_names:
            raise ValidationError("Coppie CPI distinte produrrebbero lo stesso nome di risultato.")
        output_names.add(output)
    return ",".join(normalized), selected


def prepare_cpi(request: object) -> list[str]:
    """Validate a cpi-v1 request before writing byte-preserving staged inputs."""
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValidationError("Richiesta CPI non valida: campi mancanti o inattesi.")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValidationError("Versione della richiesta CPI non supportata.")
    if request["workflow"] != "cpi":
        raise ValidationError("Workflow della richiesta CPI non valido.")
    error = request["err_const"]
    try:
        valid_error = type(error) in (int, float) and math.isfinite(error) and error >= 0
    except OverflowError:
        valid_error = False
    if not valid_error:
        raise ValidationError("La costante di errore deve essere finita e non negativa.")
    pairs, required_names = normalize_pairs(
        request["pairs"], request["mother_prefix"], request["father_prefix"],
    )
    selected = request["samples"]
    if not isinstance(selected, list) or not selected:
        raise ValidationError("Nessuna tabella di input per CPI.")
    samples: dict[str, Path] = {}
    warnings = []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"path", "name"}:
            raise ValidationError("Descrizione campione CPI non valida.")
        name = _name_component(item["name"], "Nome campione")
        if name not in required_names or name in samples:
            raise ValidationError(f"Campione CPI inatteso o duplicato: {name}")
        source = require_file(_absolute_path(item["path"], "Output DNPcall"), "Output DNPcall")
        warnings.extend(require_dnp_input(source))
        samples[name] = source
    if set(samples) != set(required_names):
        raise ValidationError("Mancano campioni richiesti dalle coppie CPI.")
    popfreq = require_file(_absolute_path(request["popfreq"], "Frequenze di popolazione"),
                           "Frequenze di popolazione")
    warnings.extend(require_population_frequencies(popfreq))

    mode = request["cutoff_mode"]
    cutoffs = request["cutoffs"]
    if not isinstance(mode, str) or mode not in {"all", "panel", "named"}:
        raise ValidationError("Modalità cutoff CPI non valida.")
    if not isinstance(cutoffs, list) or (
        (mode == "all" and cutoffs) or (mode == "panel" and len(cutoffs) != 1)
        or (mode == "named" and not cutoffs)
    ):
        raise ValidationError("Pannelli cutoff incoerenti con la modalità CPI.")
    panels = []
    labels: set[str] = set()
    for item in cutoffs:
        if not isinstance(item, dict) or set(item) != {"label", "path"}:
            raise ValidationError("Descrizione cutoff CPI non valida.")
        label = item["label"]
        if not isinstance(label, str):
            raise ValidationError("Etichetta cutoff CPI non valida.")
        label = label.strip()
        if mode == "panel":
            if label:
                raise ValidationError("Il pannello singolo CPI non richiede un'etichetta.")
        elif not label or any(char in ",=" or unicodedata.category(char) == "Cc" for char in label):
            raise ValidationError("Etichetta cutoff non valida: evitare virgole, '=' e caratteri di controllo.")
        if label in labels:
            raise ValidationError(f"Etichetta cutoff duplicata: {label}")
        labels.add(label)
        source = require_file(_absolute_path(item["path"], "Pannello cutoff"), "Pannello cutoff")
        panels.append((label, source, read_position_panel(source)))

    work_dir = _absolute_path(request["work_dir"], "Cartella di lavoro")
    out_dir = _absolute_path(request["out_dir"], "Cartella risultati")
    if work_dir.is_relative_to(out_dir) or out_dir.is_relative_to(work_dir):
        raise ValidationError("Le cartelle di lavoro e risultati devono essere distinte e non sovrapposte.")
    sources = [popfreq, *samples.values(), *(source for _, source, _ in panels)]
    for source in sources:
        if source.is_relative_to(work_dir) or source.is_relative_to(out_dir):
            raise ValidationError("Gli input non possono trovarsi nelle cartelle di lavoro o risultati.")
    for directory in (work_dir, out_dir):
        if directory.exists() and not directory.is_dir():
            raise ValidationError(f"La destinazione non è una cartella: {directory}")
    if out_dir.is_dir() and any(out_dir.iterdir()):
        raise ValidationError("La cartella risultati deve essere vuota.")
    # R parses cutoff_map with unescaped comma/equal separators. Original panel
    # paths are safe because only the normalized staging paths reach that parser.
    if panels and any(char in str(work_dir) for char in ",="):
        raise ValidationError("Il percorso di lavoro CPI per i cutoff non può contenere virgole o '='.")
    staged_dir = work_dir / "inputs"
    native_panels = [work_dir / ("DNPpanel.txt" if mode == "panel" else f"cutoff_{number:03d}.tsv")
                     for number in range(1, len(panels) + 1)]
    for destination in [staged_dir, *native_panels, work_dir / "input-validation.json"]:
        if destination.exists() or destination.is_symlink():
            raise ValidationError(f"Preparazione già presente: {destination}")

    # All validation precedes staging. Reused samples are copied only once.
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    staged_dir.mkdir()
    for name in required_names:
        shutil.copy2(samples[name], staged_dir / name)
    maps = []
    for (label, _, records), destination in zip(panels, native_panels):
        write_position_panel(records, destination)
        maps.append(f"{label}={destination}" if label else str(destination))
    write_input_report(work_dir, "cpi", warnings,
                       normalized=[(source, destination) for (_, source, _), destination
                                   in zip(panels, native_panels)])
    arguments = [
        "--pileup_dir", str(staged_dir), "--out_dir", str(out_dir),
        f"--pairs={pairs}", f"--mother_prefix={request['mother_prefix']}",
        f"--father_prefix={request['father_prefix']}", "--popfreq", str(popfreq),
        "--err_const", str(error),
    ]
    if maps:
        arguments.append("--cutoff_map=" + ",".join(maps))
    return arguments
