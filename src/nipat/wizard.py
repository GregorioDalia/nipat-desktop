"""Text prompts for the same application services exposed by the direct CLI."""

from __future__ import annotations

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

    def path(label: str, *, required: bool = True) -> Path | None:
        while True:
            answer = ask(label, required=required)
            if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in "\"'":
                answer = answer[1:-1]
            if answer:
                return Path(answer).expanduser()
            if not required:
                return None
            write("Il percorso non puo' essere vuoto.")

    def run_name() -> str | None:
        return ask("Nome nuova esecuzione (Invio = automatico)", required=False) or None

    write("NIPAT - CLI guidata per la validazione")
    write(f"Dati: {layout.data_dir}")
    write(f"Risultati: {layout.runs_dir}")
    write("Usare percorsi completi dentro data, runs o la cartella del progetto.")
    write("Le cartelle dei run esistenti non vengono sovrascritte. :annulla torna al menu.")
    if dry_run:
        write("Modalita' dry-run: convalida e prepara i comandi, senza eseguire Docker.")
    had_failure = False
    try:
        while True:
            write("\n1 DNPcall   2 SNPcall   3 Contamination   4 CPI   0 Esci")
            choice = read("Scelta: ").strip()
            if choice == "0":
                return 2 if had_failure else 0
            if choice not in {"1", "2", "3", "4"}:
                write("Scegliere un numero da 0 a 4.")
                continue
            try:
                if choice in {"1", "2"}:
                    bam = path("BAM (con indice .bam.bai)")
                    reference = path("FASTA (con indice .fai)")
                    label = "Pannello DNP" if choice == "1" else "Lista SNP (pos, ref, alt)"
                    panel = path(label)
                    name = run_name()
                    if choice == "1":
                        run_dir = workflows.dnp_call(
                            bam=bam, reference=reference, panel=panel,
                            parallel=False, run_name=name,
                        )
                    else:
                        run_dir = workflows.snp_call(
                            bam=bam, reference=reference, panel=panel, run_name=name,
                        )
                elif choice == "3":
                    write("Inserire un output individuale DNPcall per riga; "
                          "Invio termina la lista.")
                    inputs: list[Path] = []
                    while True:
                        item = path("Tabella campione", required=not inputs)
                        if item is None:
                            break
                        inputs.append(item)
                    panel = path("Pannello DNP")
                    run_dir = workflows.contamination(
                        inputs=inputs, panel=panel, run_name=run_name(),
                    )
                else:
                    input_dir = path("Cartella con le tabelle cfDNA materno e presunto padre")
                    write("Le coppie usano gli identificativi nei nomi: A1:A1 oppure A1:A1,A2:A2.")
                    pairs = ask("Coppie")
                    mother_prefix = ask("Prefisso file cfDNA materno", default="Mother")
                    father_prefix = ask("Prefisso file presunto padre", default="Father")
                    popfreq = path("Tabella frequenze di popolazione")
                    panel = path("Pannello DNP (Invio = nessun cutoff_map)", required=False)
                    write(f"Costante di errore: {err_const}. "
                          "Per modificarla usare cpi --err-const.")
                    run_dir = workflows.cpi(
                        input_dir=input_dir, pairs=pairs,
                        mother_prefix=mother_prefix, father_prefix=father_prefix,
                        popfreq=popfreq, panel=panel, err_const=err_const,
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
