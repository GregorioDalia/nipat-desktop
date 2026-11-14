"""Local result navigation for the guided CLI, without interpreting scientific output."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from nipat.execution.tracking import (
    WORKFLOW_STEPS as _WORKFLOW_STEPS,
    read_run_metadata,
    read_run_status,
    read_workflow_state as _workflow_state,
    run_owned_path as _local_descendant,
    workflow_steps as _workflow_steps,
)

if TYPE_CHECKING:
    from nipat.terminal import Terminal


_MAX_METADATA_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_FILES = 12
_MAX_PAIRS = 12
_MAX_STEPS = 24
_MAX_WARNINGS = 12
_STEP_LABELS = {"dnp-call": "DNPcall", "snp-call": "SNPcall", "contamination": "Contamination", "cpi": "CPI", "cpin": "CPIN"}
_STATUS_LABELS = {
    "unreadable": "Non verificabile",
    "preparing": "Preparazione",
    "planned": "Pianificata (dry-run)",
    "running": "In esecuzione",
    "succeeded": "Completata",
    "failed": "Non riuscita",
    "interrupted": "Interrotta",
    "cancelled": "Interrotta",
    "pending": "In attesa",
    "blocked": "Non avviata: workflow arrestato",
}


def open_local_path(path: Path) -> None:
    """Ask the desktop to display a directory, execution log or fixed run report."""
    path = path.expanduser().resolve()
    if not path.is_dir() and not (path.is_file() and path.name in {"execution.log", "run-report.html"}):
        raise OSError(f"Aprire una cartella esistente, execution.log o run-report.html: {path}")
    if sys.platform == "win32":
        os.startfile(str(path), "open")
    else:
        application = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen(
            [application, str(path)], shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def _short_value(value: object) -> str:
    if value is None:
        return "Non registrato"
    if not isinstance(value, (str, int, float)):
        return "Non disponibile"
    text = str(value)
    return text if len(text) <= 240 else text[:237] + "..."


def _output_inventory(directory: Path) -> tuple[list[str], bool]:
    """List at most twelve actual files; do not traverse linked directories."""
    inventory: list[str] = []
    if not directory.is_dir():
        return inventory, False
    def unreadable(error: OSError) -> None:
        raise error

    for current, directories, filenames in os.walk(
        directory, followlinks=False, onerror=unreadable,
    ):
        directories[:] = sorted(
            (name for name in directories if not (Path(current) / name).is_symlink()),
            key=str.casefold,
        )
        for name in sorted(filenames, key=str.casefold):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            if len(inventory) == _MAX_OUTPUT_FILES:
                return inventory, True
            inventory.append(str(path.relative_to(directory)))
    return inventory, False


def _show_workflow_summary(ui: Terminal, run_dir: Path, workflow: str, metadata: dict) -> None:
    ui.message("Passaggi del workflow automatico:")
    try:
        state = _workflow_state(run_dir, workflow, metadata)
        steps = {step["id"]: step for step in state["steps"]}
        declared = _workflow_steps(metadata)
        parameters = metadata.get("parameters")
        samples = parameters.get("sample_mapping", []) if isinstance(parameters, dict) else []
        for specification in declared[:_MAX_STEPS]:
            step_id = specification["id"]
            label = (_STEP_LABELS[specification["workflow"]] if specification["workflow"] != "snp-call" else
                     f"SNPcall {specification['sample']} ({specification['mode']})")
            step = steps[step_id]
            ui.message(f"  {label}: {_STATUS_LABELS[step['status']]}")
            if specification["workflow"] == "snp-call":
                source = next(sample["original_path"] for sample in samples
                              if sample["sample_id"] == specification["sample"])
                ui.message(f"    Input: {_short_value(source)}")
            output = _local_descendant(run_dir, f"output/workflow/steps/{step_id}/output")
            if output.is_dir():
                ui.message(f"    Cartella {label}: {output}")
            elif step["status"] == "succeeded":
                ui.message(f"    Cartella risultati {label} non disponibile.", kind="warning")
        if len(declared) > _MAX_STEPS:
            ui.message(f"Altri {len(declared) - _MAX_STEPS} passaggi disponibili in workflow-state.json.")
        ui.message(f"Stato dei passaggi: {run_dir / 'output/workflow/workflow-state.json'}")
    except (OSError, ValueError) as exc:
        ui.message(f"Stato dei passaggi non consultabile: {exc}", kind="warning")


def _show_pair_mapping(ui: Terminal, metadata: dict) -> None:
    """Describe declared biological roles without opening metadata-supplied paths."""
    parameters = metadata.get("parameters")
    pairs = parameters.get("pair_mapping") if isinstance(parameters, dict) else None
    fields = ("pair_id", "mother_sample_id", "father_sample_id", "mother_bam", "father_bam")
    if (not isinstance(pairs, list) or not pairs
            or any(not isinstance(pair, dict)
                   or any(not isinstance(pair.get(field), str) for field in fields)
                   for pair in pairs)):
        ui.message("Associazioni delle coppie CPI non consultabili in run.json.", kind="warning")
        return
    ui.message(f"Coppie CPI registrate: {len(pairs)}")
    for pair in pairs[:_MAX_PAIRS]:
        ui.message(f"  Coppia {_short_value(pair['pair_id'])}")
        ui.message(f"    cfDNA materno ({_short_value(pair['mother_sample_id'])}): "
                   f"{_short_value(pair['mother_bam'])}")
        ui.message(f"    Campione paterno ({_short_value(pair['father_sample_id'])}): "
                   f"{_short_value(pair['father_bam'])}")
    if len(pairs) > _MAX_PAIRS:
        ui.message("Altre coppie disponibili in run.json.")


def _show_family_mapping(ui: Terminal, metadata: dict) -> None:
    """Show explicit prenatal/postnatal roles from the same validated plan."""
    try:
        _workflow_steps(metadata)
        parameters = metadata["parameters"]
        names = {item["sample_id"]: Path(item["original_path"]).name for item in parameters["sample_mapping"]}
        shown = 0
        for step in parameters["plan"]["steps"]:
            if step["workflow"] not in {"cpi", "cpin"}:
                continue
            role_names = {"mother": "cfDNA materno" if step["workflow"] == "cpi" else "Madre",
                          "father": "Padre", "child": "Figlio"}
            families = step["inputs"].get("pairs", step["inputs"].get("trios", []))
            for family in families:
                if shown == _MAX_PAIRS:
                    ui.message("Altre associazioni familiari disponibili in run.json.")
                    return
                ui.message(f"  {_STEP_LABELS[step['workflow']]} {_short_value(family['id'])} ({step['parameters'].get('marker_type', '')})")
                for role, title in role_names.items():
                    if role in family:
                        sample = family[role]["sample"]
                        ui.message(f"    {title} ({sample}): {_short_value(names[sample])}")
                shown += 1
    except (ValueError, KeyError, TypeError):
        ui.message("Associazioni familiari non consultabili in run.json.", kind="warning")


def _show_quality_warnings(ui: Terminal, run_dir: Path) -> None:
    """Display recorded validator warnings without interpreting scientific values."""
    warnings = []
    reports = [("work/input-validation.json", "warnings"),
               ("work/scientific-validation.json", "quality_warnings")]
    try:
        metadata = read_run_metadata(run_dir)
        workflow = metadata.get("workflow")
        if isinstance(workflow, str) and workflow in _WORKFLOW_STEPS:
            state_path = _local_descendant(run_dir, "output/workflow/workflow-state.json")
            if state_path.is_file():
                state = _workflow_state(run_dir, workflow, metadata)
                for step in state["steps"]:
                    artifacts = step.get("artifacts")
                    recorded = artifacts.get("quality_warnings", []) if isinstance(artifacts, dict) else []
                    if not isinstance(recorded, list) or any(not isinstance(item, dict) for item in recorded):
                        raise ValueError("Avvisi del workflow non validi")
                    warnings.extend((f"output/workflow/steps/{step['id']}", item) for item in recorded)
                    reports.append((f"output/workflow/steps/{step['id']}/work/input-validation.json", "warnings"))
        for relative, key in reports:
            path = _local_descendant(run_dir, relative)
            if not path.is_file():
                continue  # Earlier versions did not produce these reports.
            report = read_run_metadata(run_dir, relative, max_bytes=_MAX_METADATA_BYTES)
            recorded = report.get(key, [])
            if not isinstance(recorded, list) or any(not isinstance(item, dict) for item in recorded):
                raise ValueError(f"Avvisi non validi: {relative}")
            warnings.extend((relative, item) for item in recorded)
        if not warnings:
            return
        ui.message(f"Avvisi sui dati o sui risultati: {len(warnings)}. Il completamento tecnico non risolve questi avvisi.", kind="warning")
        for origin, item in warnings[:_MAX_WARNINGS]:
            code = _short_value(item.get("code"))
            message = _short_value(item.get("message"))
            ui.message(f"  [{code}] {message}", kind="warning")
            details = []
            for key in ("file", "path", "row", "column", "value"):
                if key in item:
                    details.append(f"{key}={_short_value(item[key])}")
            if details:
                ui.message("    " + "; ".join(details), kind="muted")
            ui.message(f"    Report: {origin}", kind="muted")
        if len(warnings) > _MAX_WARNINGS:
            ui.message("Altri avvisi sono conservati nei report di validazione del run.", kind="warning")
    except (OSError, ValueError) as exc:
        ui.message(f"Avvisi di validazione non consultabili: {exc}", kind="warning")


def _show_summary(ui: Terminal, run_dir: Path, *, dry_run: bool) -> None:
    ui.heading("Riepilogo dell'esecuzione")
    ui.message(f"Cartella: {run_dir}")
    try:
        metadata = read_run_metadata(run_dir)
        ui.message(f"Workflow: {_short_value(metadata.get('workflow'))}")
        status = "planned" if dry_run else read_run_status(run_dir, metadata)
        label = (
            _STATUS_LABELS.get(status, "Stato non riconosciuto")
            if isinstance(status, str) else "Non registrato"
        )
        ui.message(f"Stato registrato: {label}")
        ui.message(f"Inizio (UTC): {_short_value(metadata.get('started_at'))}")
        ui.message(f"Fine (UTC): {_short_value(metadata.get('finished_at'))}")
        inputs = metadata.get("inputs")
        if isinstance(inputs, list):
            ui.message(f"File di input registrati: {len(inputs)}")
        source = metadata.get("source")
        if isinstance(source, dict) and source.get("nipat_version"):
            ui.message(f"Versione NIPAT: {_short_value(source['nipat_version'])}")
        _show_samples(ui, metadata)
        workflow = metadata.get("workflow")
        if isinstance(workflow, str) and workflow in _WORKFLOW_STEPS:
            if not dry_run:
                _show_workflow_summary(ui, run_dir, workflow, metadata)
            if workflow == "analysis":
                _show_family_mapping(ui, metadata)
            elif "cpi" in _WORKFLOW_STEPS[workflow]:
                _show_pair_mapping(ui, metadata)
    except (OSError, ValueError) as exc:
        ui.message(f"Metadati non consultabili: {exc}", kind="warning")

    if dry_run:
        ui.message("Dry-run: nessuna analisi eseguita; consultare il piano in run.json e il log.")
        return
    try:
        files, has_more = _output_inventory(run_dir / "output")
        if not files:
            ui.message("Nessun file presente nella cartella output.", kind="warning")
            return
        ui.message("File disponibili in output:")
        for name in files:
            ui.message(f"  {name}")
        if has_more:
            ui.message(
                "Altri file disponibili: aprire la cartella risultati per l'elenco completo."
            )
    except OSError as exc:
        ui.message(f"Impossibile leggere l'elenco dei risultati: {exc}", kind="warning")


def _show_samples(ui: Terminal, metadata: dict) -> None:
    from nipat.run_report import sample_rows

    samples = sample_rows(metadata)
    if not samples:
        return
    ui.message(f"Campioni registrati: {len(samples)}")
    for sample in samples[:12]:
        ui.message(f"  {_short_value(sample['original_name'])}  [{_short_value(sample['sample_id'])}]")
    if len(samples) > 12:
        ui.message(f"Altri {len(samples) - 12} campioni sono elencati nel resoconto e in run.json.")
    ui.message("I nomi originali identificano i campioni; gli ID tra parentesi collegano le fasi. I file di input non vengono rinominati.", kind="muted")


def _presentation_directory(run_dir: Path) -> Path | None:
    """Prefer human-facing exports without accepting paths from arbitrary metadata."""
    for relative in ("output/workflow/presentation", "output/presentation"):
        try:
            directory = _local_descendant(run_dir, relative)
            index = _local_descendant(run_dir, relative + "/index.html")
            if directory.is_dir() and index.is_file():
                return directory
        except (OSError, ValueError):
            continue
    return None


def show_results(
    ui: Terminal,
    run_dir: Path,
    *,
    dry_run: bool = False,
    open_path: Callable[[Path], None] | None = None,
) -> None:
    """Show recorded run status and offer explicit local file actions."""
    run_dir = run_dir.expanduser().resolve()
    opener = open_local_path if open_path is None else open_path
    status = "planned" if dry_run else read_run_status(run_dir)
    titles = {"planned": "Esecuzione pianificata", "succeeded": "Esecuzione completata",
              "failed": "Esecuzione non riuscita", "interrupted": "Esecuzione interrotta",
              "cancelled": "Esecuzione interrotta", "running": "Esecuzione in corso",
              "preparing": "Preparazione dell'esecuzione"}
    ui.heading(titles.get(status, "Risultati dell'esecuzione"))
    ui.message(f"Esecuzione: {run_dir}", kind="success" if status == "succeeded" else "info")
    ui.message(f"Dettagli: {run_dir / 'run.json'}")
    ui.message(f"Log: {run_dir / 'execution.log'}")
    if dry_run:
        ui.message("Dry-run: i comandi sono stati preparati; l'analisi non e' stata eseguita.")
    else:
        presentation = _presentation_directory(run_dir)
        ui.message(f"Risultati: {presentation or run_dir / 'output'}")
        if presentation:
            ui.message("Aprire index.html per tabelle e grafici con i nomi originali. Gli output nativi restano nella cartella del run.", kind="muted")
        try:
            _show_samples(ui, read_run_metadata(run_dir))
        except (OSError, ValueError):
            pass  # Legacy or incomplete records remain accessible through the summary.
        _show_quality_warnings(ui, run_dir)

    while True:
        choices = []
        targets: dict[str, Path] = {}
        output = run_dir / "output"
        log = run_dir / "execution.log"
        if not dry_run and output.is_dir():
            presentation = _presentation_directory(run_dir)
            choices.append(("1", "Apri cartella risultati", "Tabelle e grafici con i nomi originali" if presentation else "File prodotti dall'analisi"))
            targets["1"] = presentation or output
        choices.append(("2", "Riepilogo dell'esecuzione", "Metadati e file disponibili"))
        if log.is_file():
            choices.append(("3", "Apri log", "Dettagli tecnici dell'esecuzione"))
            targets["3"] = log
        if run_dir.is_dir():
            choices.append(("4", "Apri cartella del run", "Input preparati, metadati e output"))
            targets["4"] = run_dir
        try:
            report = _local_descendant(run_dir, "run-report.html")
            if report.is_file():
                choices.append(("5", "Apri resoconto", "Campioni, fasi, impostazioni e risorse registrate"))
                targets["5"] = report
        except (OSError, ValueError):
            pass
        choices.append(("0", "Torna al menu", ""))
        choice = ui.menu("Prossima azione", choices, default="0").strip().casefold()
        if choice in {"0", ":indietro", ":annulla", "\x1b"}:
            return
        if choice == "2":
            _show_summary(ui, run_dir, dry_run=dry_run)
        elif choice in targets:
            target = targets[choice]
            try:
                opener(target)
                ui.message(f"Richiesta di apertura inviata: {target}")
            except OSError as exc:
                ui.message(f"Apertura non riuscita: {exc}. Percorso: {target}", kind="error")
        else:
            ui.message("Scegliere una delle azioni disponibili.", kind="warning")
