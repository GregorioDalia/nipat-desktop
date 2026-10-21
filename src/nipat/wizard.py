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
    ("7", "Guida all'uso", "Istruzioni e verifica degli strumenti"),
    ("0", "Esci", ""),
]


def _results_directory(ui: Terminal, layout: ProjectLayout, workflows: Workflows) -> ProjectLayout:
    ui.heading("Cartella risultati / Destinazione delle prossime analisi")
    while True:
        ui.message("Inserire il percorso della cartella oppure premere Invio per mantenere quella indicata.", kind="muted")
        ui.message("Sono accettati percorsi completi o relativi alla cartella corrente, anche tra virgolette.", kind="muted")
        ui.message("La scelta vale per questa sessione; i risultati precedenti restano nella loro cartella.", kind="muted")
        ui.message(":indietro o :annulla torna al menu senza cambiare destinazione.", kind="muted")
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
    while True:
        ui.message("Consultare le istruzioni oppure verificare gli strumenti necessari alle analisi.", kind="muted")
        ui.message("In modalita' simulazione la verifica degli strumenti non viene eseguita. 0 torna al menu principale." if dry_run else
                   "La verifica avvia l'ambiente di analisi senza elaborare campioni. 0 torna al menu principale.", kind="muted")
        action = ui.menu("Guida all'uso", [
            ("1", "Come usare NIPAT", "Input, comandi di navigazione e risultati"),
            ("2", "Verifica strumenti di analisi", "Controlla l'ambiente, R e samtools"),
            ("0", "Torna al menu", ""),
        ], default="0").strip().casefold()
        if action in {"0", ":indietro", ":annulla"}:
            return
        if action == "1":
            ui.heading("Come usare NIPAT")
            for instruction in (
                "Selezionare un'analisi dal menu e seguire le indicazioni mostrate prima di ogni campo.",
                "Per un file, incollare il percorso completo oppure un percorso relativo alla cartella corrente.",
                "In Windows si puo' usare 'Copia come percorso': le virgolette vengono accettate.",
                "Nelle liste di file inserire un percorso alla volta; dopo almeno un file, Invio conclude la lista.",
                "Negli altri campi Invio mantiene il valore tra parentesi oppure lascia vuoto un campo facoltativo.",
                "Un campo obbligatorio senza valore iniziale richiede una risposta prima di proseguire.",
                ":indietro torna al campo precedente; :annulla torna al menu; :vuoto svuota un campo facoltativo.",
                "I percorsi relativi contenuti in una bamlist partono dalla cartella della bamlist.",
                "Il riepilogo permette di correggere gli input. L'analisi parte solo dopo la conferma di avvio.",
                "Con --dry-run vengono preparati i comandi, senza eseguire l'analisi o produrre risultati scientifici.",
                "Ogni esecuzione ha una cartella distinta: output contiene i risultati, work i file intermedi.",
                "run.json registra gli input e lo stato; execution.log conserva i dettagli del processo.",
                "Il punto 6 del menu riapre l'ultima esecuzione della sessione. I risultati precedenti restano su disco.",
                "Per concatenare analisi, utilizzare i file prodotti come input del workflow successivo.",
                "I comandi diretti sono disponibili con nipat.cmd --help.",
                f"Guida completa: {layout.project_dir / 'docs' / 'GUIDA_UTILIZZO.md'}",
            ):
                ui.message(instruction, kind="muted")
        elif action == "2":
            if dry_run:
                ui.message("Modalita' simulazione (--dry-run): la verifica degli strumenti non viene eseguita.", kind="muted")
                ui.message("Per controllarli, avviare NIPAT senza --dry-run e scegliere di nuovo questa voce.", kind="muted")
                continue
            ui.heading("Verifica strumenti di analisi")
            ui.message("Il controllo avvia l'ambiente e verifica gli strumenti; non esegue analisi sui dati.", kind="muted")
            ui.message("Verifica in corso...")
            workflows.runner.doctor(True)
            ui.message("Controllo completato: ambiente di analisi, R e samtools disponibili.", kind="success")
            ui.message("Il controllo riguarda gli strumenti. Gli input saranno verificati quando si prepara un'analisi.", kind="muted")
        else:
            ui.message("Scegliere 1 per le istruzioni, 2 per la verifica oppure 0 per tornare al menu.", kind="muted")


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
        ui.message(":indietro corregge il campo precedente; :annulla torna al menu.", kind="muted")
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
