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


def _workflow_state(run_dir: Path) -> dict:
    state = _read_metadata(run_dir, "output/workflow/workflow-state.json")
    steps = state.get("steps")
    allowed = {"pending", "running", "succeeded", "failed", "cancelled", "blocked"}
    expected = {"dnp": "dnp-call", "contamination": "contamination"}
    if (state.get("interface") != "workflow-plan-execution-v1"
            or not isinstance(state.get("status"), str)
            or state.get("status") not in {"running", "succeeded", "failed", "cancelled"}
            or not isinstance(steps, list) or len(steps) != 2
            or any(not isinstance(step, dict) or not isinstance(step.get("id"), str)
                   or step.get("id") not in expected
                   or step.get("workflow") != expected[step["id"]]
                   or not isinstance(step.get("status"), str) or step["status"] not in allowed
                   for step in steps)
            or {step["id"] for step in steps} != set(expected)):
        raise ValueError("Stato del workflow DNPcall → Contamination non valido")
    if state["status"] == "succeeded" and any(step["status"] != "succeeded" for step in steps):
        raise ValueError("Stato complessivo e stati dei passaggi non coerenti")
    return state


def _recorded_status(run_dir: Path) -> str | None:
    try:
        metadata = _read_metadata(run_dir, "run.json")
        status = metadata.get("status")
        if not isinstance(status, str):
            return None
        if metadata.get("workflow") == "dnp-contamination" and status == "succeeded":
            # A completed parent invocation is insufficient if the persisted
            # scientific step report is unavailable or records another outcome.
            return _workflow_state(run_dir)["status"]
        return status
    except (OSError, ValueError):
        return None


def _show_workflow_summary(ui: Terminal, run_dir: Path) -> None:
    ui.message("Passaggi del workflow automatico:")
    try:
        state = _workflow_state(run_dir)
        steps = {step["id"]: step for step in state["steps"]}
        for step_id, label in (("dnp", "DNPcall"), ("contamination", "Contamination")):
            step = steps[step_id]
            ui.message(f"  {label}: {_STATUS_LABELS[step['status']]}")
            output = _local_descendant(run_dir, f"output/workflow/steps/{step_id}/output")
            if output.is_dir():
                ui.message(f"    Cartella {label}: {output}")
            elif step["status"] == "succeeded":
                ui.message(f"    Cartella risultati {label} non disponibile.", kind="warning")
        ui.message(f"Stato dei passaggi: {run_dir / 'output/workflow/workflow-state.json'}")
    except (OSError, ValueError) as exc:
        ui.message(f"Stato dei passaggi non consultabile: {exc}", kind="warning")


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
        if metadata.get("workflow") == "dnp-contamination" and not dry_run:
            _show_workflow_summary(ui, run_dir)
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
