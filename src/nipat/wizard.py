"""Guided, editable CLI over the same services as the direct commands."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from nipat import __version__
from nipat.errors import NipatError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.preferences import PreferencesStore
from nipat.results import show_results
from nipat.terminal import Terminal
from nipat.update_ui import HANDOFF_EXIT_CODE, run_updates
from nipat.wizard_forms import Back, Cancelled, WorkflowForm
from nipat.wizard_settings import GuidedSettings


MAIN_MENU = [
    ("1", "DNPcall", "Dinucleotidi da uno o piu' BAM"),
    ("2", "SNPcall", "SNP da BAM o pileup esistente"),
    ("3", "Contamination", "Stima da tabelle compatibili"),
    ("4", "CPI", "Frazione fetale e indice di paternita'"),
    ("5", "Configura", "Cartelle e parametri predefiniti"),
    ("6", "Ultima esecuzione", "Risultati e log della sessione"),
    ("7", "Guida e informazioni", "Cosa fa NIPAT e come utilizzarlo"),
    ("8", "Verifica ambiente", "Controllo degli strumenti di analisi"),
    ("9", "Verifica aggiornamenti", "Release disponibili, download e installazione"),
    ("0", "Esci", ""),
]


def _help(ui: Terminal, layout: ProjectLayout) -> None:
    pages = {
        "1": ("Come usare NIPAT", (
            "Selezionare un'analisi dal menu e seguire le indicazioni mostrate prima di ogni campo.",
            "Per un file, incollare il percorso completo oppure un percorso relativo alla cartella corrente.",
            "In Windows si puo' usare 'Copia come percorso': le virgolette vengono accettate.",
            "Nelle liste di file inserire un percorso alla volta; dopo almeno un file, Invio conclude la lista.",
            "Negli altri campi Invio mantiene il valore tra parentesi oppure lascia vuoto un campo facoltativo.",
            "Un campo obbligatorio senza valore iniziale richiede una risposta prima di proseguire.",
            ":indietro torna al campo precedente; :annulla torna al menu; :vuoto svuota un campo facoltativo.",
            "I percorsi relativi contenuti in una bamlist partono dalla cartella della bamlist.",
            "Il riepilogo permette di correggere gli input. Per eseguire gli script scientifici scegliere esplicitamente Avvia analisi; Invio sul riepilogo annulla.",
            "Con --dry-run vengono preparati i comandi, senza eseguire l'analisi o produrre risultati scientifici.",
        )),
        "2": ("Analisi disponibili", (
            "NIPAT prepara gli input ed esegue quattro workflow scientifici R nell'ambiente distribuito con l'applicazione.",
            "DNPcall: uno o piu' BAM, un FASTA indicizzato e un pannello DNP; produce conteggi, genotipi, riepiloghi e grafici.",
            "SNPcall: un BAM con FASTA oppure un pileup con QNAME, e una lista SNP; produce una tabella di conteggi allelici.",
            "Contamination: tabelle compatibili con l'output DNPcall e coordinate DNP; produce stime per sito e un riepilogo per campione.",
            "CPI: tabelle cfDNA materno e presunto padre, coppie e frequenze di popolazione; produce stime di frazione fetale, CPI e grafici.",
            "I pannelli e i riferimenti devono essere coerenti con i campioni. La verifica degli input non sostituisce la valutazione scientifica dei risultati.",
        )),
        "3": ("Cartelle e parametri", (
            "Configura salva le cartelle e i valori predefiniti per i prossimi avvii della CLI guidata.",
            "Le preferenze vengono proposte nei campi dell'analisi: prima dell'avvio e' sempre possibile correggerle nel riepilogo.",
            "Campioni, coppie CPI e nome dell'esecuzione vengono scelti per ogni analisi; non sono memorizzati come preferenze.",
            "Le preferenze riguardano le opzioni esposte dagli script. Le costanti interne dei codici R non vengono modificate.",
            "Cambiare cartella dati o risultati non sposta i file gia' presenti. App, runtime e cache si configurano attraverso il programma di installazione.",
            "Ripristina impostazioni elimina solo le preferenze: conserva dati, risultati e installazione.",
            "I comandi diretti mantengono le proprie opzioni e i propri valori predefiniti. --data-dir e --runs-dir espliciti prevalgono sulle cartelle salvate nella sessione guidata.",
        )),
        "4": ("Risultati e analisi in sequenza", (
            "Ogni esecuzione ha una cartella distinta: output contiene i risultati, work i file intermedi.",
            "run.json registra gli input, i parametri e lo stato; execution.log conserva i dettagli del processo.",
            "Ultima esecuzione riapre i risultati e i log della sessione. Le esecuzioni precedenti rimangono nelle rispettive cartelle.",
            "Per concatenare analisi, selezionare i file prodotti come input del workflow successivo.",
            "Esempio: dopo DNPcall, aprire Contamination e scegliere le tabelle full_output_*.txt della cartella output/individual_outputs, insieme al pannello DNP pertinente.",
            "La concatenazione non e' automatica: verificare campioni, schema delle tabelle e pannello per ogni passaggio.",
        )),
        "5": ("Informazioni su NIPAT", (
            f"NIPAT {__version__} - piattaforma locale per l'esecuzione e la validazione dei workflow scientifici.",
            "I dati sono elaborati localmente. La distribuzione include gli script scientifici R e le loro dipendenze nell'immagine di analisi.",
            "Windows utilizza il runtime WSL dedicato; Linux utilizza Docker Engine locale.",
            "Verifica ambiente controlla gli strumenti senza analizzare campioni. E' separata dalla guida e non attesta la validita' scientifica di un risultato.",
            "Verifica aggiornamenti consulta GitHub e propone download e installazione con conferme distinte. L'avviso all'avvio, attivabile in Configura, non scarica file.",
            "Per i comandi diretti: NIPAT.exe --help su Windows; nipat --help su Linux.",
            f"Guida completa: {layout.project_dir / 'docs' / 'GUIDA_UTILIZZO.md'}",
        )),
    }
    while True:
        ui.message("Scegliere un argomento. La consultazione della guida non avvia analisi o strumenti scientifici.", kind="muted")
        action = ui.menu("Guida e informazioni", [
            ("1", "Come usare NIPAT", "Selezione dei file, navigazione e avvio"),
            ("2", "Analisi disponibili", "Scopo, input e risultati dei quattro workflow"),
            ("3", "Cartelle e parametri", "Preferenze, modifiche e ripristino"),
            ("4", "Risultati e analisi in sequenza", "File intermedi, log e workflow successivi"),
            ("5", "Informazioni su NIPAT", "Versione, ambiente e documentazione"),
            ("0", "Torna al menu", ""),
        ], default="0").strip().casefold()
        if action in {"0", ":indietro", ":annulla"}:
            return
        if action not in pages:
            ui.message("Scegliere un argomento da 1 a 5 oppure 0 per tornare al menu.", kind="muted")
            continue
        title, paragraphs = pages[action]
        ui.heading(title)
        for paragraph in paragraphs:
            ui.message(paragraph, kind="muted")


def _check_environment(ui: Terminal, workflows: Workflows, dry_run: bool) -> None:
    ui.heading("Verifica ambiente")
    if dry_run:
        ui.message("Modalita' simulazione (--dry-run): la verifica degli strumenti non viene eseguita.", kind="muted")
        ui.message("Per controllarli, avviare NIPAT senza --dry-run e scegliere di nuovo questa voce.", kind="muted")
        return
    ui.message("Il controllo avvia l'ambiente e verifica gli strumenti; non esegue analisi sui dati.", kind="muted")
    ui.message("Verifica in corso...")
    workflows.runner.doctor(True)
    ui.message("Controllo completato: ambiente di analisi, R e samtools disponibili.", kind="success")
    ui.message("Il controllo riguarda gli strumenti. Gli input saranno verificati quando si prepara un'analisi.", kind="muted")


def run_wizard(
    workflows: Workflows,
    layout: ProjectLayout,
    *,
    err_const: float,
    dry_run: bool = False,
    preferences_store: PreferencesStore | None = None,
    directory_overrides: dict[str, Path] | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> int:
    """Collect and review values, then call a workflow only after confirmation."""
    ui = Terminal(read=read, write=write)
    settings = GuidedSettings(layout, preferences_store, directory_overrides)
    layout = settings.layout
    workflows.layout = workflows.runner.layout = layout
    had_failure = False
    last_run: Path | None = None
    try:
        ui.banner(__version__, dry_run)
        ui.message(f"Dati: {layout.data_dir}")
        ui.message(f"Risultati: {layout.runs_dir}")
        settings.explain(ui)
        ui.message(f"Cartella corrente: {Path.cwd()}", kind="muted")
        if os.environ.get("NIPAT_BACKEND", "").strip().lower() == "wsl":
            ui.message("Input su dischi locali; le unita' di rete non sono supportate.", kind="muted")
        else:
            ui.message("Input in cartelle accessibili a Docker.", kind="muted")
        ui.message(":indietro corregge il campo precedente; :annulla torna al menu.", kind="muted")
        if not settings.error and settings.preferences.check_updates_on_startup:
            run_updates(ui, layout, settings.preferences, dry_run=dry_run, startup=True)
        while True:
            choice = ui.menu("Menu principale", MAIN_MENU)
            if choice in {"0", ":annulla", ":indietro"}:
                return 2 if had_failure else 0
            if choice not in {item[0] for item in MAIN_MENU}:
                ui.message("Scegliere una delle opzioni indicate (0-9).", kind="error")
                continue
            try:
                if choice == "5":
                    layout = settings.configure(ui, err_const=err_const)
                    workflows.layout = workflows.runner.layout = layout
                    continue
                if choice == "6":
                    if last_run is None:
                        ui.message("Nessuna esecuzione completata o pianificata in questa sessione.")
                    else:
                        show_results(ui, last_run, dry_run=dry_run)
                    continue
                if choice == "7":
                    _help(ui, layout)
                    continue
                if choice == "8":
                    _check_environment(ui, workflows, dry_run)
                    continue
                if choice == "9":
                    if run_updates(ui, layout, settings.preferences, dry_run=dry_run):
                        return HANDOFF_EXIT_CODE
                    continue
                if settings.error:
                    settings.explain(ui)
                    continue
                form = WorkflowForm(choice, ui, layout, err_const,
                                    defaults=settings.preferences.workflow_defaults(choice))
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
