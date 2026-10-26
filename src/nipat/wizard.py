"""Guided, editable CLI over the same services as the direct commands."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from nipat import __version__
from nipat.catalog_ui import show_catalog
from nipat.errors import NipatError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.preferences import PreferencesStore
from nipat.results import show_results
from nipat.terminal import Terminal
from nipat.update_ui import HANDOFF_EXIT_CODE, run_updates
from nipat.wizard_forms import Back, Cancelled, WorkflowForm
from nipat.workflow_forms import DnpContaminationForm, DnpCpiForm, SnpBatchForm
from nipat.wizard_settings import GuidedSettings


MAIN_MENU = [
    ("1", "DNPcall", "Dinucleotidi da uno o piu' BAM"),
    ("2", "SNPcall", "SNP da BAM o pileup esistente"),
    ("3", "Contamination", "Stima da tabelle compatibili"),
    ("4", "CPI", "Frazione fetale e indice di paternita'"),
    ("W", "Workflow automatici", "Analisi collegate e SNPcall su piu' campioni"),
    ("5", "Configura", "Cartelle e parametri predefiniti"),
    ("6", "Ultima esecuzione", "Risultati e log della sessione"),
    ("7", "Guida e informazioni", "Cosa fa NIPAT e come utilizzarlo"),
    ("8", "Verifica ambiente", "Controllo degli strumenti di analisi"),
    ("9", "Verifica aggiornamenti", "Release disponibili, download e installazione"),
    ("0", "Esci", ""),
]


def _select_workflow(ui: Terminal) -> str | None:
    ui.message(
        "Scegliere la sequenza da eseguire. I risultati DNPcall sono forniti automaticamente "
        "alle analisi successive, senza selezionare o copiare file intermedi.", kind="muted",
    )
    ui.message(
        "SNPcall e' un'analisi indipendente: puo' essere aggiunta sui BAM dei workflow DNP "
        "oppure eseguita su una lista di BAM o pileup. Le attivita' vengono eseguite in sequenza.", kind="muted",
    )
    while True:
        selected = ui.menu("Workflow automatici", [
            ("1", "DNPcall -> Contamination", "Conteggi DNP e stima della contaminazione"),
            ("2", "DNPcall -> CPI", "Coppie cfDNA materno / campione paterno"),
            ("3", "DNPcall -> Contamination e CPI", "Entrambe le analisi sulle tabelle DNPcall"),
            ("4", "SNPcall su piu' campioni", "BAM o pileup; risultati separati per campione"),
            ("0", "Torna al menu", ""),
        ], default="0").strip().casefold()
        if selected in {"0", ":annulla", ":indietro"}:
            return None
        if selected in {"1", "2", "3", "4"}:
            return selected
        ui.message("Scegliere un workflow da 1 a 4 oppure 0 per tornare al menu.", kind="muted")


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
            "Ctrl+C annulla l'operazione e torna al menu principale, anche durante il calcolo. Attendere l'arresto: i log e i risultati gia' prodotti vengono conservati.",
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
            "Workflow automatici: la voce W propone DNPcall seguito da Contamination, CPI oppure entrambe le analisi. Una sola conferma avvia la sequenza selezionata.",
            "Dal menu W si puo' anche eseguire SNPcall su piu' BAM o pileup, oppure aggiungerlo ai workflow DNP con una lista SNP specifica. Ogni campione mantiene risultati separati.",
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
            "La voce W, Workflow automatici, esegue DNPcall e poi Contamination, CPI oppure entrambe le analisi: scegliere gli input, controllare il riepilogo e confermare una sola volta.",
            "Le tabelle passano automaticamente alla seconda fase. Se DNPcall fallisce o non produce le tabelle attese, le analisi successive non vengono avviate; ogni errore arresta la sequenza.",
            "Per i workflow CPI, indicare un ID per ogni coppia e assegnare esplicitamente i BAM del cfDNA materno e del campione paterno. Uno stesso campione puo' essere riutilizzato in piu' coppie nello stesso ruolo.",
            "NIPAT prepara automaticamente i nomi e i prefissi dei file CPI. I ruoli derivano dalle coppie dichiarate, senza deduzioni dal nome dei BAM; il riepilogo mostra ID, file e ruoli.",
            "Contamination e CPI usano le tabelle DNPcall: la stima di contaminazione non filtra o modifica gli input CPI. Le fasi sono eseguite in sequenza.",
            "SNPcall analizza ogni BAM o pileup separatamente; i suoi risultati non sono input diretti di Contamination o CPI. Nei workflow DNP usa gli stessi BAM e FASTA, con una lista SNP scelta esplicitamente.",
            "Un errore o un'interruzione arresta l'intero piano, comprese le analisi SNP indipendenti non ancora avviate. I risultati e i log gia' prodotti vengono conservati.",
            "Nel workflow automatico, output/workflow/workflow-state.json registra lo stato delle fasi; output/workflow/steps contiene una cartella per ciascuna fase, con work, output e log.",
            "Le tabelle individuali DNPcall si chiamano full_output_*.txt e si trovano nella sottocartella output/individual_outputs della fase DNPcall.",
            "Ogni fase SNPcall si chiama snp_0001, snp_0002 e cosi' via. La relativa cartella output contiene SNPcall_output.txt; work conserva i file intermedi e command.log i comandi della fase.",
            "Le altre combinazioni richiedono la selezione esplicita dei risultati come input dell'analisi successiva. Verificare campioni, schema delle tabelle e pannelli pertinenti.",
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
            ("6", "Catalogo scientifico", "Opzioni R, regole interne e preparazione; IT / EN"),
            ("0", "Torna al menu", ""),
        ], default="0").strip().casefold()
        if action in {"0", ":indietro", ":annulla"}:
            return
        if action == "6":
            show_catalog(ui)
            continue
        if action not in pages:
            ui.message("Scegliere un argomento da 1 a 6 oppure 0 per tornare al menu.", kind="muted")
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
    ui.message("Ctrl+C interrompe il controllo e torna al menu principale.", kind="muted")
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
    ui = Terminal(read=read, write=write, cancel_to_menu=True)
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
        ui.message("Ctrl+C annulla l'operazione corrente e torna al menu principale. Per uscire scegliere 0 dal menu principale.", kind="muted")
        if not settings.error and settings.preferences.check_updates_on_startup:
            try:
                run_updates(ui, layout, settings.preferences, dry_run=dry_run, startup=True)
            except (Cancelled, KeyboardInterrupt):
                ui.message("Verifica iniziale annullata. Ritorno al menu principale.")
        while True:
            try:
                choice = ui.menu("Menu principale", MAIN_MENU).strip().casefold()
            except (Cancelled, KeyboardInterrupt):
                ui.message("Menu principale. Per uscire scegliere 0.", kind="muted")
                continue
            if choice == "0":
                return 2 if had_failure else 0
            if choice == ":indietro":
                continue
            if choice not in {item[0].casefold() for item in MAIN_MENU}:
                ui.message("Scegliere una delle opzioni indicate (0-9 oppure W).", kind="error")
                continue
            try:
                if choice == "5":
                    try:
                        settings.configure(ui, err_const=err_const)
                    finally:
                        # A prior screen may have been saved before a later
                        # pending edit was cancelled; keep that saved layout.
                        layout = settings.layout
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
                if choice == "w":
                    preset = _select_workflow(ui)
                    if preset is None:
                        continue
                    if preset == "1":
                        form = DnpContaminationForm(
                            "1", ui, layout, err_const,
                            defaults=settings.preferences.workflow_defaults("1"),
                        )
                    elif preset == "4":
                        form = SnpBatchForm(
                            ui, layout, err_const,
                            defaults=settings.preferences.workflow_defaults("2"),
                        )
                    else:
                        form = DnpCpiForm(
                            ui, layout, err_const, include_contamination=preset == "3",
                            defaults=settings.preferences.workflow_defaults("1"),
                            cpi_defaults=settings.preferences.workflow_defaults("4"),
                        )
                else:
                    form = WorkflowForm(choice, ui, layout, err_const,
                                        defaults=settings.preferences.workflow_defaults(choice))
                form.collect()
                while form.review(dry_run=dry_run):
                    ui.heading(f"{form.title} / {'Preparazione dry-run' if dry_run else 'Esecuzione'}")
                    ui.message("I dettagli del processo vengono conservati anche in execution.log.")
                    ui.message("Ctrl+C: interrompi e torna al menu principale. Attendere l'arresto; log e risultati gia' prodotti saranno conservati.", kind="muted")
                    started = time.monotonic()
                    previous_run = workflows.runner.last_run_dir
                    try:
                        method = {
                            "1": workflows.dnp_contamination, "2": workflows.dnp_cpi,
                            "3": workflows.dnp_cpi, "4": workflows.snp_batch,
                        }[preset] if choice == "w" else {
                            "1": workflows.dnp_call, "2": workflows.snp_call,
                            "3": workflows.contamination, "4": workflows.cpi,
                        }[choice]
                        run_dir = method(**form.arguments())
                    except KeyboardInterrupt:
                        interrupted_run = workflows.runner.last_run_dir
                        if isinstance(interrupted_run, Path) and interrupted_run != previous_run:
                            last_run = interrupted_run
                            ui.message(f"Esecuzione interrotta: {last_run}", kind="warning")
                            ui.message("Log e risultati parziali sono conservati; la voce 6 permette di consultarli. Il workflow non viene ripreso automaticamente.", kind="muted")
                        raise
                    except (NipatError, OSError) as exc:
                        had_failure = True
                        ui.message(f"Operazione non riuscita: {exc}", kind="error")
                        ui.message("I valori inseriti sono conservati: modificarli dal riepilogo.")
                        if choice == "w":
                            ui.message("Consultare gli stati delle fasi e i log nella cartella indicata dal processo. Per ripetere il workflow scegliere un nuovo nome: i risultati gia' presenti sono conservati.", kind="muted")
                        continue
                    last_run = run_dir
                    ui.message(f"Tempo trascorso: {time.monotonic() - started:.1f} s")
                    if choice == "w" and not dry_run:
                        workflow_dir = run_dir / "output" / "workflow"
                        ui.message(f"Stati delle fasi: {workflow_dir / 'workflow-state.json'}")
                        steps = [] if preset == "4" else [("dnp", "DNPcall")]
                        if preset in {"1", "3"}:
                            steps.append(("contamination", "Contamination"))
                        if preset in {"2", "3"}:
                            steps.append(("cpi", "CPI"))
                        for step, label in steps:
                            ui.message(f"Risultati {label}: {workflow_dir / 'steps' / step / 'output'}")
                        if preset == "4" or form.values.get("include_snp") == "2":
                            ui.message(f"Risultati SNPcall per campione: {workflow_dir / 'steps'} (cartelle snp_0001, snp_0002, ...)")
                    show_results(ui, run_dir, dry_run=dry_run)
                    break
                else:
                    ui.message("Operazione annullata prima dell'avvio.")
            except (Cancelled, Back, KeyboardInterrupt):
                ui.message("Operazione annullata. Ritorno al menu principale.")
            except (NipatError, OSError) as exc:
                had_failure = True
                ui.message(f"Operazione non riuscita: {exc}", kind="error")
    except (EOFError, KeyboardInterrupt):
        ui.message("\nSessione interrotta.")
        return 130
    finally:
        ui.close()
