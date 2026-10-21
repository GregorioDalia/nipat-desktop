"""Guided, editable CLI over the same services as the direct commands."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from nipat import __version__
from nipat.errors import NipatError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.results import show_results
from nipat.terminal import Terminal
from nipat.wizard_forms import Back, Cancelled, WorkflowForm, navigation, unquote


MAIN_MENU = [
    ("1", "DNPcall", "Dinucleotidi da uno o piu' BAM"),
    ("2", "SNPcall", "SNP da BAM o pileup esistente"),
    ("3", "Contamination", "Stima da tabelle compatibili"),
    ("4", "CPI", "Frazione fetale e indice di paternita'"),
    ("5", "Cartella risultati", "Destinazione per questa sessione"),
    ("6", "Ultima esecuzione", "Risultati e log della sessione"),
    ("7", "Guida e ambiente", "Uso del menu e verifica del runtime"),
    ("0", "Esci", ""),
]


def _results_directory(ui: Terminal, layout: ProjectLayout, workflows: Workflows) -> ProjectLayout:
    while True:
        answer = navigation(ui.prompt("Cartella risultati", default=str(layout.runs_dir), path=True))
        try:
            path = Path(unquote(answer or str(layout.runs_dir))).expanduser().resolve()
            updated = replace(layout, runs_dir=path)
            updated.validate_storage_roots()
            updated.runs_dir.mkdir(parents=True, exist_ok=True)
        except (NipatError, OSError, ValueError) as exc:
            ui.message(str(exc), kind="error")
            continue
        workflows.layout = updated
        workflows.runner.layout = updated
        ui.message(f"Cartella risultati per questa sessione: {path}", kind="success")
        return updated


def _help(ui: Terminal, workflows: Workflows, layout: ProjectLayout, dry_run: bool) -> None:
    ui.heading("Guida per l'utilizzo")
    ui.message("Selezionare un workflow, compilare gli input e confermare il riepilogo.")
    ui.message("Invio mantiene il valore tra parentesi. :indietro torna al campo precedente.")
    ui.message(":annulla torna al menu. :vuoto svuota un campo facoltativo, anche un prefisso CPI.")
    ui.message("I percorsi relativi partono dalla cartella corrente; quelli nelle bamlist dalla lista.")
    ui.message("Gli elenchi di file terminano con Invio. I risultati esistenti non vengono sovrascritti.")
    ui.message("I comandi diretti restano disponibili: nipat.cmd --help")
    ui.message(f"Guida completa: {layout.project_dir / 'docs' / 'GUIDA_UTILIZZO.md'}")
    action = ui.menu("Verifica dell'ambiente", [
        ("1", "Controlla runtime", "Avvia l'ambiente e controlla R e samtools"),
        ("0", "Torna al menu", ""),
    ], default="0")
    if action == "1":
        if dry_run:
            ui.message("Il controllo reale del runtime non e' disponibile in modalita' dry-run.")
            return
        ui.message("Verifica dell'ambiente in corso...")
        workflows.runner.doctor(True)
        ui.message("Ambiente verificato in questo momento.", kind="success")


def run_wizard(
    workflows: Workflows,
    layout: ProjectLayout,
    *,
    err_const: float,
    dry_run: bool = False,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> int:
    """Collect and review values, then call a workflow only after confirmation."""
    ui = Terminal(read=read, write=write)
    had_failure = False
    last_run: Path | None = None
    try:
        ui.banner(__version__, dry_run)
        ui.message(f"Risultati: {layout.runs_dir}")
        ui.message(f"Cartella corrente: {Path.cwd()}", kind="muted")
        if os.environ.get("NIPAT_BACKEND", "").strip().lower() == "wsl":
            ui.message("Input su dischi locali; le unita' di rete non sono supportate.", kind="muted")
        else:
            ui.message("Input in cartelle accessibili a Docker.", kind="muted")
        ui.message("Ambiente: da verificare all'avvio dell'analisi o dal menu Guida.", kind="muted")
        ui.message(":indietro corregge il campo precedente; :annulla torna al menu.")
        while True:
            choice = ui.menu("Menu principale", MAIN_MENU)
            if choice in {"0", ":annulla", ":indietro"}:
                return 2 if had_failure else 0
            if choice not in {item[0] for item in MAIN_MENU}:
                ui.message("Scegliere una delle opzioni indicate (0-7).", kind="error")
                continue
            try:
                if choice == "5":
                    layout = _results_directory(ui, layout, workflows)
                    continue
                if choice == "6":
                    if last_run is None:
                        ui.message("Nessuna esecuzione completata o pianificata in questa sessione.")
                    else:
                        show_results(ui, last_run, dry_run=dry_run)
                    continue
                if choice == "7":
                    _help(ui, workflows, layout, dry_run)
                    continue
                form = WorkflowForm(choice, ui, layout, err_const)
                form.collect()
                while form.review(dry_run=dry_run):
                    ui.heading(f"{form.title} / {'Preparazione dry-run' if dry_run else 'Esecuzione'}")
                    ui.message("I dettagli del processo vengono conservati anche in execution.log.")
                    started = time.monotonic()
                    try:
                        method = {"1": workflows.dnp_call, "2": workflows.snp_call,
                                  "3": workflows.contamination, "4": workflows.cpi}[choice]
                        run_dir = method(**form.arguments())
                    except (NipatError, OSError) as exc:
                        had_failure = True
                        ui.message(f"Operazione non riuscita: {exc}", kind="error")
                        ui.message("I valori inseriti sono conservati: modificarli dal riepilogo.")
                        continue
                    last_run = run_dir
                    ui.message(f"Tempo trascorso: {time.monotonic() - started:.1f} s")
                    show_results(ui, run_dir, dry_run=dry_run)
                    break
                else:
                    ui.message("Operazione annullata prima dell'avvio.")
            except (Cancelled, Back):
                ui.message("Operazione annullata prima dell'avvio.")
            except (NipatError, OSError) as exc:
                had_failure = True
                ui.message(f"Operazione non riuscita: {exc}", kind="error")
    except (EOFError, KeyboardInterrupt):
        ui.message("\nSessione interrotta.")
        return 130
    finally:
        ui.close()
