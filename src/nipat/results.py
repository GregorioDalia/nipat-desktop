"""Local result navigation for the guided CLI, without interpreting scientific output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from nipat.terminal import Terminal


_MAX_METADATA_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_FILES = 12
_MAX_PAIRS = 12
_MAX_STEPS = 24
_MAX_WARNINGS = 12
_WORKFLOW_STEPS = {
    "dnp-contamination": {"dnp": "dnp-call", "contamination": "contamination"},
    "dnp-cpi": {"dnp": "dnp-call", "cpi": "cpi"},
    "dnp-contamination-cpi": {"dnp": "dnp-call", "contamination": "contamination", "cpi": "cpi"},
    "snp-batch": {},
}
_STEP_LABELS = {"dnp": "DNPcall", "contamination": "Contamination", "cpi": "CPI"}
_STATUS_LABELS = {
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
    """Ask the desktop to display a directory or execution log, never run a command file."""
    path = path.expanduser().resolve()
    if not path.is_dir() and not (path.is_file() and path.name == "execution.log"):
        raise OSError(f"Aprire una cartella esistente o il file execution.log: {path}")
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


def _local_descendant(run_dir: Path, relative: str) -> Path:
    """Resolve only fixed, run-owned locations; do not follow linked entries."""
    path = run_dir
    for component in Path(relative).parts:
        path = path / component
        if path.is_symlink():
            raise ValueError(f"Percorso collegato non consultabile: {relative}")
    if not path.resolve().is_relative_to(run_dir):
        raise ValueError(f"Percorso esterno alla cartella del run: {relative}")
    return path


def _read_metadata(run_dir: Path, relative: str) -> dict:
    path = _local_descendant(run_dir, relative)
    if not path.is_file():
        raise ValueError(f"File non disponibile: {relative}")
    # Bound the actual read as well as its reported size, including a file
    # replaced or extended between the size check and open.
    if path.stat().st_size > _MAX_METADATA_BYTES:
        raise ValueError(f"{relative} supera il limite di lettura del riepilogo (2 MiB)")
    with path.open("rb") as stream:
        content = stream.read(_MAX_METADATA_BYTES + 1)
    if len(content) > _MAX_METADATA_BYTES:
        raise ValueError(f"{relative} supera il limite di lettura del riepilogo (2 MiB)")
    try:
        metadata = json.loads(content.decode("utf-8"))
    except RecursionError as exc:
        raise ValueError(f"Struttura JSON troppo complessa: {relative}") from exc
    if (not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 1):
        raise ValueError(f"Formato di {relative} non supportato")
    return metadata


def _workflow_steps(metadata: dict) -> list[dict]:
    """Accept only preset-owned IDs and complete, ordered per-sample SNP mappings."""
    workflow = metadata["workflow"]
    expected = [{"id": step_id, "workflow": kind}
                for step_id, kind in _WORKFLOW_STEPS[workflow].items()]
    parameters = metadata.get("parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    supplied = parameters.get("expected_steps")
    has_snp = workflow == "snp-batch" or parameters.get("snp_panel") is not None
    if supplied is None and not has_snp:
        # Runs produced before the per-sample extension had only fixed steps.
        return expected
    if has_snp:
        if workflow != "snp-batch" and (
            not isinstance(parameters.get("snp_panel"), str) or not parameters["snp_panel"]
        ):
            raise ValueError("Pannello SNP registrato non valido")
        mode = parameters.get("mode") if workflow == "snp-batch" else "bam"
        samples = parameters.get("sample_mapping")
        if mode not in ("bam", "pileup") or not isinstance(samples, list) or not samples:
            raise ValueError("Associazioni dei campioni SNP non valide")
        snp_steps = []
        for number, sample in enumerate(samples, 1):
            identifier = f"sample_{number:04d}"
            if (not isinstance(sample, dict) or sample.get("sample_id") != identifier
                    or not isinstance(sample.get("original_path"), str) or not sample["original_path"]
                    or not isinstance(sample.get("container_path"), str) or not sample["container_path"]):
                raise ValueError("Associazioni dei campioni SNP non valide")
            snp_steps.append({"id": f"snp_{number:04d}", "workflow": "snp-call",
                              "sample": identifier, "mode": mode})
        expected.extend(sorted(snp_steps, key=lambda step: step["id"]))
    if supplied != expected:
        raise ValueError("Elenco dei passaggi attesi non valido")
    return expected


def _workflow_state(run_dir: Path, workflow: str = "dnp-contamination",
                    metadata: dict | None = None) -> dict:
    metadata = _read_metadata(run_dir, "run.json") if metadata is None else metadata
    if metadata.get("workflow") != workflow:
        raise ValueError("Workflow e metadati non coerenti")
    state = _read_metadata(run_dir, "output/workflow/workflow-state.json")
    steps = state.get("steps")
    allowed = {"pending", "running", "succeeded", "failed", "cancelled", "blocked"}
    expected = {step["id"]: step for step in _workflow_steps(metadata)}
    if (state.get("interface") != "workflow-plan-execution-v1"
            or not isinstance(state.get("status"), str)
            or state.get("status") not in {"running", "succeeded", "failed", "cancelled"}
            or not isinstance(steps, list) or len(steps) != len(expected)
            or any(not isinstance(step, dict) or not isinstance(step.get("id"), str)
                   or step.get("id") not in expected
                   or step.get("workflow") != expected[step["id"]]["workflow"]
                   or not isinstance(step.get("status"), str) or step["status"] not in allowed
                   for step in steps)
            or {step["id"] for step in steps} != set(expected)):
        raise ValueError("Stato del workflow automatico non valido")
    if state["status"] == "succeeded" and any(step["status"] != "succeeded" for step in steps):
        raise ValueError("Stato complessivo e stati dei passaggi non coerenti")
    for step in steps:
        declared = expected[step["id"]]
        if declared["workflow"] != "snp-call":
            continue
        source = next(sample for sample in metadata["parameters"]["sample_mapping"]
                      if sample["sample_id"] == declared["sample"])
        mapping = step.get("sample_mapping")
        if (mapping is not None or step["status"] == "succeeded") and mapping != {
            "sample": declared["sample"], "mode": declared["mode"], "path": source["container_path"],
        }:
            raise ValueError("Passaggio SNP e campione atteso non coerenti")
        if step["status"] != "succeeded":
            continue
        artifacts = step.get("artifacts")
        tables = artifacts.get("snp-tables") if isinstance(artifacts, dict) else None
        if (not isinstance(tables, list) or len(tables) != 1
                or not isinstance(tables[0], dict) or tables[0].get("sample") != declared["sample"]):
            raise ValueError("Risultato SNP e campione atteso non coerenti")
    return state


def _recorded_status(run_dir: Path) -> str | None:
    try:
        metadata = _read_metadata(run_dir, "run.json")
        status = metadata.get("status")
        if not isinstance(status, str):
            return None
        workflow = metadata.get("workflow")
        if isinstance(workflow, str) and workflow in _WORKFLOW_STEPS and status == "succeeded":
            # A completed parent invocation is insufficient if the persisted
            # scientific step report is unavailable or records another outcome.
            return _workflow_state(run_dir, workflow, metadata)["status"]
        return status
    except (OSError, ValueError):
        return None


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
            label = (_STEP_LABELS[step_id] if specification["workflow"] != "snp-call" else
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


def _show_quality_warnings(ui: Terminal, run_dir: Path) -> None:
    """Display recorded validator warnings without interpreting scientific values."""
    warnings = []
    reports = [("work/input-validation.json", "warnings"),
               ("work/scientific-validation.json", "quality_warnings")]
    try:
        metadata = _read_metadata(run_dir, "run.json")
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
            report = _read_metadata(run_dir, relative)
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
        metadata = _read_metadata(run_dir, "run.json")
        ui.message(f"Workflow: {_short_value(metadata.get('workflow'))}")
        status = metadata.get("status")
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
        workflow = metadata.get("workflow")
        if isinstance(workflow, str) and workflow in _WORKFLOW_STEPS:
            if not dry_run:
                _show_workflow_summary(ui, run_dir, workflow, metadata)
            if "cpi" in _WORKFLOW_STEPS[workflow]:
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
    status = "planned" if dry_run else _recorded_status(run_dir)
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
        ui.message(f"Risultati: {run_dir / 'output'}")
        _show_quality_warnings(ui, run_dir)

    while True:
        choices = []
        targets: dict[str, Path] = {}
        output = run_dir / "output"
        log = run_dir / "execution.log"
        if not dry_run and output.is_dir():
            choices.append(("1", "Apri cartella risultati", "File prodotti dall'analisi"))
            targets["1"] = output
        choices.append(("2", "Riepilogo dell'esecuzione", "Metadati e file disponibili"))
        if log.is_file():
            choices.append(("3", "Apri log", "Dettagli tecnici dell'esecuzione"))
            targets["3"] = log
        if run_dir.is_dir():
            choices.append(("4", "Apri cartella del run", "Input preparati, metadati e output"))
            targets["4"] = run_dir
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
