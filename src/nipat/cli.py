from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nipat import __version__
from nipat.errors import NipatError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.self_test import run_self_tests
from nipat.wizard import run_wizard


DEFAULT_ERR_CONST = 0.0000892303778101497


def _path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nipat",
        description="Orchestratore locale dei workflow scientifici NIPAT.",
    )
    parser.add_argument("--version", action="version", version=f"NIPAT {__version__}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="valida gli input e mostra i comandi senza eseguire Docker",
    )
    parser.add_argument(
        "--data-dir", type=_path,
        help="cartella dati predefinita (in alternativa: NIPAT_DATA_DIR)",
    )
    parser.add_argument(
        "--runs-dir", type=_path,
        help="cartella dei risultati (in alternativa: NIPAT_RUNS_DIR)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="controlla ambiente e runtime")
    doctor.add_argument(
        "--runtime",
        action="store_true",
        help="verifica R, samtools e i quattro workflow nell'immagine scientifica",
    )

    subparsers.add_parser("build-runtime", help="costruisce l'immagine R/samtools")
    subparsers.add_parser("wizard", help="avvia la CLI guidata per i quattro workflow")
    subparsers.add_parser("self-test", help="esegue le verifiche numeriche distribuite")

    dnp = subparsers.add_parser("dnp-call", help="esegue DNPcall da BAM")
    dnp_input = dnp.add_mutually_exclusive_group(required=True)
    dnp_input.add_argument("--bam", type=_path, action="append", help="ripetibile per piu' BAM")
    dnp_input.add_argument("--bamlist", type=_path, help="file con un percorso BAM per riga")
    dnp.add_argument("--reference", type=_path, required=True)
    dnp.add_argument("--panel", type=_path, required=True)
    dnp.add_argument("--parallel", action="store_true")
    dnp.add_argument("--run-name")

    snp = subparsers.add_parser("snp-call", help="esegue SNPcall da BAM o pileup esistente")
    snp_input = snp.add_mutually_exclusive_group(required=True)
    snp_input.add_argument("--bam", type=_path)
    snp_input.add_argument("--pileup", type=_path)
    snp.add_argument("--reference", type=_path, help="FASTA obbligatorio con --bam")
    snp.add_argument("--panel", type=_path, required=True)
    snp.add_argument("--run-name")

    contamination = subparsers.add_parser(
        "contamination", help="stima la contaminazione da output DNPcall compatibili"
    )
    contamination_input = contamination.add_mutually_exclusive_group(required=True)
    contamination_input.add_argument("--input", type=_path, action="append")
    contamination_input.add_argument(
        "--input-dir", type=_path, help="cartella da cercare ricorsivamente per tabelle TXT/TSV",
    )
    contamination.add_argument("--panel", type=_path, required=True)
    contamination.add_argument("--run-name")

    cpi = subparsers.add_parser("cpi", help="calcola fetal fraction e CPI")
    cpi.add_argument("--input-dir", type=_path, required=True)
    cpi.add_argument("--pairs", required=True, help='esempio: "A1:A1,A2:A2"')
    cpi.add_argument("--mother-prefix", default="Mother")
    cpi.add_argument("--father-prefix", default="Father")
    cpi.add_argument("--popfreq", type=_path, required=True)
    cpi_cutoff = cpi.add_mutually_exclusive_group()
    cpi_cutoff.add_argument("--panel", type=_path, help="singolo pannello di coordinate DNP")
    cpi_cutoff.add_argument(
        "--cutoff", nargs=2, action="append", metavar=("LABEL", "PATH"),
        help="associazione etichetta/file di cutoff; opzione ripetibile",
    )
    cpi_cutoff.add_argument(
        "--cutoff-map", "--cutoff_map", dest="cutoff_map",
        help="mappa nativa CPI separata da virgole, es. label=percorso,label2=percorso2",
    )
    cpi.add_argument("--err-const", type=float, default=DEFAULT_ERR_CONST)
    cpi.add_argument("--run-name")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.command == "self-test":
        parser.error("self-test richiede l'esecuzione reale; rimuovere --dry-run")
    completion_label = "Esecuzione pianificata" if args.dry_run else "Esecuzione completata"

    try:
        layout = ProjectLayout.discover(data_dir=args.data_dir, runs_dir=args.runs_dir)
        runner = DockerComposeRunner(layout, dry_run=args.dry_run)
        workflows = Workflows(layout, runner)
        if args.command == "doctor":
            runner.doctor(args.runtime)
            print("Ambiente NIPAT disponibile.")
        elif args.command == "build-runtime":
            runner.build()
            print("Build pianificata." if args.dry_run else "Runtime scientifico costruito.")
        elif args.command == "wizard":
            return run_wizard(
                workflows, layout, err_const=DEFAULT_ERR_CONST, dry_run=args.dry_run,
            )
        elif args.command == "self-test":
            run_self_tests(layout)
        elif args.command == "dnp-call":
            run_dir = workflows.dnp_call(
                bams=args.bam,
                bamlist=args.bamlist,
                reference=args.reference,
                panel=args.panel,
                parallel=args.parallel,
                run_name=args.run_name,
            )
            print(f"{completion_label}: {run_dir}")
        elif args.command == "snp-call":
            run_dir = workflows.snp_call(
                bam=args.bam,
                pileup=args.pileup,
                reference=args.reference,
                panel=args.panel,
                run_name=args.run_name,
            )
            print(f"{completion_label}: {run_dir}")
        elif args.command == "contamination":
            run_dir = workflows.contamination(
                inputs=args.input,
                input_dir=args.input_dir,
                panel=args.panel,
                run_name=args.run_name,
            )
            print(f"{completion_label}: {run_dir}")
        elif args.command == "cpi":
            run_dir = workflows.cpi(
                input_dir=args.input_dir,
                pairs=args.pairs,
                mother_prefix=args.mother_prefix,
                father_prefix=args.father_prefix,
                popfreq=args.popfreq,
                panel=args.panel,
                cutoffs=[(label, _path(path)) for label, path in args.cutoff]
                if args.cutoff else None,
                cutoff_map=args.cutoff_map,
                err_const=args.err_const,
                run_name=args.run_name,
            )
            print(f"{completion_label}: {run_dir}")
        else:
            parser.error(f"Comando non gestito: {args.command}")
    except (NipatError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nEsecuzione interrotta.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
