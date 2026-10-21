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


def _show_summary(ui: Terminal, run_dir: Path, *, dry_run: bool) -> None:
    ui.heading("Riepilogo dell'esecuzione")
    ui.message(f"Cartella: {run_dir}")
    metadata_path = run_dir / "run.json"
    try:
        if metadata_path.stat().st_size > _MAX_METADATA_BYTES:
            raise ValueError("run.json supera il limite di lettura del riepilogo (2 MiB)")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
            raise ValueError("formato di run.json non supportato")
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
    """Show the result of a successful workflow and offer explicit local file actions."""
    run_dir = run_dir.expanduser().resolve()
    opener = open_local_path if open_path is None else open_path
    ui.heading("Esecuzione pianificata" if dry_run else "Esecuzione completata")
    ui.message(f"Esecuzione: {run_dir}", kind="info" if dry_run else "success")
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
