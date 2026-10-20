"""Text prompts for the same application services exposed by the direct CLI."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Callable

from nipat.errors import NipatError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


class _Cancelled(Exception):
    pass


def run_wizard(
    workflows: Workflows,
    layout: ProjectLayout,
    *,
    err_const: float,
    dry_run: bool = False,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> int:
    """Collect arguments without constructing or evaluating shell commands."""

    def ask(label: str, *, default: str = "", required: bool = True) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            answer = read(f"{label}{suffix}: ").strip()
            if answer.casefold() == ":annulla":
                raise _Cancelled
            if answer:
                return answer
            if default or not required:
                return default
            write("Il valore e' obbligatorio; :annulla torna al menu.")

    def path(label: str, *, required: bool = True, default: str = "") -> Path | None:
        while True:
            answer = ask(label, required=required, default=default)
            if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in "\"'":
                answer = answer[1:-1]
            if answer:
                return Path(answer).expanduser()
            if not required:
                return None
            write("Il percorso non puo' essere vuoto.")

    def run_name() -> str | None:
        return ask("Nome nuova esecuzione (Invio = automatico)", required=False) or None

    def mode(label: str, options: set[str], *, default: str = "1") -> str:
        while True:
            answer = ask(label, default=default)
            if answer in options:
                return answer
            write("Scegliere una delle opzioni indicate.")

    def paths(label: str) -> list[Path]:
        write("Inserire un percorso per riga; Invio termina la lista.")
        selected: list[Path] = []
        while True:
            item = path(label, required=not selected)
            if item is None:
                return selected
            selected.append(item)

    def nonnegative_number(label: str, default: float) -> float:
        while True:
            text = ask(label, default=str(default))
            try:
                number = float(text)
            except ValueError:
                number = float("nan")
            if math.isfinite(number) and number >= 0:
                return number
            write("Inserire un numero finito maggiore o uguale a zero, usando il punto decimale.")

    write("NIPAT - CLI guidata per la validazione")
    write(f"Dati: {layout.data_dir}")
    write(f"Risultati: {layout.runs_dir}")
    write("Gli input possono trovarsi in qualsiasi cartella accessibile a Docker.")
    write("Sono accettati percorsi completi o relativi alla cartella corrente.")
    write("Per cambiare la cartella risultati usare l'opzione 5 del menu.")
    write("Le cartelle dei run esistenti non vengono sovrascritte. :annulla torna al menu.")
    if dry_run:
        write("Modalita' dry-run: convalida e prepara i comandi, senza eseguire Docker.")
    had_failure = False
    try:
        while True:
            write("\n1 DNPcall   2 SNPcall   3 Contamination   4 CPI   5 Cartella risultati   0 Esci")
            choice = read("Scelta: ").strip()
            if choice == "0":
                return 2 if had_failure else 0
            if choice not in {"1", "2", "3", "4", "5"}:
                write("Scegliere un numero da 0 a 5.")
                continue
            try:
                if choice == "5":
                    selected = path("Cartella risultati", default=str(layout.runs_dir))
                    updated_layout = replace(layout, runs_dir=selected.resolve())
                    updated_layout.validate_storage_roots()
                    updated_layout.runs_dir.mkdir(parents=True, exist_ok=True)
                    layout = updated_layout
                    workflows.layout = updated_layout
                    workflows.runner.layout = updated_layout
                    write(f"Cartella risultati per le prossime esecuzioni: {layout.runs_dir}")
                    continue
                if choice == "1":
                    input_mode = mode("Input: 1 uno o piu' BAM, 2 file bamlist", {"1", "2"})
                    bams, bamlist = None, None
                    if input_mode == "1":
                        bams = paths("BAM (eventuale indice accanto al file)")
                    else:
                        bamlist = path("File bamlist (un percorso BAM per riga)")
                        write("I percorsi relativi nella bamlist partono dalla sua cartella.")
                    reference = path("FASTA (con indice .fai; .gzi se compresso)")
                    panel = path("Pannello DNP")
                    parallel = mode("Esecuzione parallela? 1 no, 2 si", {"1", "2"}) == "2"
                    run_dir = workflows.dnp_call(
                        bams=bams, bamlist=bamlist, reference=reference, panel=panel,
                        parallel=parallel, run_name=run_name(),
                    )
                elif choice == "2":
                    input_mode = mode("Input: 1 BAM, 2 pileup esistente", {"1", "2"})
                    bam, pileup, reference = None, None, None
                    if input_mode == "1":
                        bam = path("BAM (eventuale indice accanto al file)")
                        reference = path("FASTA (con indice .fai; .gzi se compresso)")
                    else:
                        pileup = path("Pileup compatibile con SNPcall")
                    panel = path("Lista SNP (pos, ref, alt)")
                    run_dir = workflows.snp_call(
                        bam=bam, pileup=pileup, reference=reference,
                        panel=panel, run_name=run_name(),
                    )
                elif choice == "3":
                    input_mode = mode("Input: 1 tabelle singole, 2 cartella", {"1", "2"})
                    inputs, input_dir = None, None
                    if input_mode == "1":
                        inputs = paths("Tabella campione")
                    else:
                        input_dir = path("Cartella di input (TXT/TSV, anche nelle sottocartelle)")
                    panel = path("Pannello DNP")
                    run_dir = workflows.contamination(
                        inputs=inputs, input_dir=input_dir, panel=panel, run_name=run_name(),
                    )
                else:
                    input_dir = path("Cartella con le tabelle cfDNA materno e presunto padre")
                    write("Le coppie usano gli identificativi nei nomi: A1:A1 oppure A1:A1,A2:A2.")
                    pairs = ask("Coppie")
                    mother_prefix = ask("Prefisso file cfDNA materno", default="Mother")
                    father_prefix = ask("Prefisso file presunto padre", default="Father")
                    popfreq = path("Tabella frequenze di popolazione")
                    cutoff_mode = mode(
                        "Cutoff: 0 tutti i siti, 1 pannello singolo, "
                        "2 etichette e file, 3 mappa nativa",
                        {"0", "1", "2", "3"}, default="0",
                    )
                    panel, cutoffs, cutoff_map = None, None, None
                    if cutoff_mode == "1":
                        panel = path("Pannello di coordinate DNP")
                    elif cutoff_mode == "2":
                        cutoffs = []
                        while True:
                            label = ask("Etichetta cutoff (Invio termina la lista)",
                                        required=not cutoffs)
                            if not label:
                                break
                            cutoffs.append((label, path("File cutoff")))
                    elif cutoff_mode == "3":
                        cutoff_map = ask("Mappa cutoff (etichetta=file,etichetta2=file2)")
                    selected_error = nonnegative_number("Costante di errore", err_const)
                    run_dir = workflows.cpi(
                        input_dir=input_dir, pairs=pairs,
                        mother_prefix=mother_prefix, father_prefix=father_prefix,
                        popfreq=popfreq, panel=panel, cutoffs=cutoffs, cutoff_map=cutoff_map,
                        err_const=selected_error,
                        run_name=run_name(),
                    )
                label = "Esecuzione pianificata" if dry_run else "Esecuzione completata"
                write(f"{label}: {run_dir}")
                write(f"Dettagli: {run_dir / 'run.json'}")
                write(f"Log: {run_dir / 'execution.log'}")
            except _Cancelled:
                write("Operazione annullata prima dell'avvio.")
            except (NipatError, OSError) as exc:
                had_failure = True
                write(f"Operazione non riuscita: {exc}")
    except (EOFError, KeyboardInterrupt):
        write("\nSessione interrotta.")
        return 130
