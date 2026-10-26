from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import sys
from pathlib import Path

from nipat import __version__
from nipat.activity import activity_session
from nipat.errors import NipatError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.preferences import PreferencesStore
from nipat.i18n import translate
from nipat.recovery_ui import recovery_lines
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
    parser.add_argument("--input-hashes", choices=("auto", "full"),
                        help="provenienza: auto calcola SHA-256 fino a 16 MiB; full su tutti gli input")
    parser.add_argument("--cpus", type=float,
                        help="quota CPU del container; non imposta il numero di worker R")
    parser.add_argument("--memory-mb", type=int, help="limite memoria del container in MiB")
    parser.add_argument("--pids-limit", type=int, help="limite dei processi nel container")
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

    runs = subparsers.add_parser("runs", help="controlla le esecuzioni incomplete senza riprenderle")
    run_commands = runs.add_subparsers(dest="run_operation", required=True)
    inspect = run_commands.add_parser("inspect", help="confronta i record con lo stato dei container")
    inspect.add_argument("--run", type=_path, help="singola cartella di esecuzione")
    stop = run_commands.add_parser("stop", help="arresta solo i container identificati e verificati")
    stop.add_argument("--run", type=_path, required=True)
    stop.add_argument("--yes", action="store_true", help="conferma esplicitamente l'arresto")
    for command in (inspect, stop):
        command.add_argument("--json", action="store_true", help="report strutturato con chiavi stabili")
        command.add_argument("--lang", choices=("it", "en"), default="it",
                             help="lingua dei messaggi di questa operazione")

    installation = subparsers.add_parser("installation", help="consulta e gestisce i componenti installati")
    installation_commands = installation.add_subparsers(dest="installation_operation", required=True)
    inventory = installation_commands.add_parser("inspect", help="mostra ambienti, cache e preparazione")
    inventory.add_argument("--json", action="store_true", help="inventario strutturato")
    for operation, help_text in (("cleanup", "rimuove un componente precedente verificato"),
                                 ("recover", "riprende la preparazione della versione installata")):
        command = installation_commands.add_parser(operation, help=help_text)
        command.add_argument("--target", required=True, help="ID ottenuto da installation inspect")
        command.add_argument("--yes", action="store_true", help="conferma e chiude NIPAT per la manutenzione")

    parameters = subparsers.add_parser(
        "parameters", help="consulta opzioni R, regole interne e preparazione degli input",
    )
    parameters.add_argument("workflow", nargs="?", choices=("dnp-call", "snp-call", "contamination", "cpi"))
    parameters.add_argument("--lang", choices=("it", "en"), default="it")
    parameters.add_argument("--section", choices=("all", "parameters", "rules", "preparation"), default="all")
    parameters.add_argument("--json", action="store_true", help="catalogo strutturato bilingue")

    workflow = subparsers.add_parser(
        "workflow", help="esegue automaticamente analisi scientifiche collegate",
    )
    workflow_presets = workflow.add_subparsers(dest="preset", required=True)
    dnp_contamination = workflow_presets.add_parser(
        "dnp-contamination",
        help="esegue DNPcall e passa le tabelle individuali a Contamination",
    )
    workflow_input = dnp_contamination.add_mutually_exclusive_group(required=True)
    workflow_input.add_argument("--bam", type=_path, action="append", help="ripetibile per piu' BAM")
    workflow_input.add_argument("--bamlist", type=_path, help="file con un percorso BAM per riga")
    dnp_contamination.add_argument("--reference", type=_path, required=True)
    dnp_contamination.add_argument("--panel", type=_path, required=True, help="pannello DNPcall")
    dnp_contamination.add_argument(
        "--contamination-panel", type=_path,
        help="pannello Contamination; se omesso usa il pannello DNPcall",
    )
    dnp_contamination.add_argument(
        "--parallel", action="store_true",
        help="parallelismo fra campioni in DNPcall; i due passaggi restano sequenziali",
    )
    dnp_contamination.add_argument("--run-name")
    dnp_contamination.add_argument("--snp-panel", type=_path,
                                    help="aggiunge SNPcall indipendente su ogni BAM, con questo pannello SNP")

    for preset in ("dnp-cpi", "dnp-contamination-cpi"):
        composed_cpi = workflow_presets.add_parser(
            preset, help=("DNPcall e CPI con coppie esplicite" if preset == "dnp-cpi" else
                          "DNPcall, Contamination e CPI con coppie esplicite"),
        )
        composed_cpi.add_argument(
            "--pair", nargs=3, action="append", required=True,
            metavar=("ID", "MATERNAL_BAM", "PATERNAL_BAM"),
            help="ID della coppia, BAM cfDNA materno e BAM paterno; ripetibile",
        )
        composed_cpi.add_argument("--reference", type=_path, required=True)
        composed_cpi.add_argument("--panel", type=_path, required=True, help="pannello DNPcall")
        composed_cpi.add_argument("--popfreq", type=_path, required=True)
        composed_cpi.add_argument("--err-const", type=float, default=DEFAULT_ERR_CONST)
        cutoff = composed_cpi.add_mutually_exclusive_group()
        cutoff.add_argument("--cpi-panel", type=_path, help="singolo pannello cutoff CPI")
        cutoff.add_argument("--cutoff", nargs=2, action="append", metavar=("LABEL", "PATH"),
                            help="pannello cutoff CPI etichettato; ripetibile")
        cutoff.add_argument("--cutoff-map", "--cutoff_map", dest="cutoff_map",
                            help="mappa nativa cutoff CPI; se omessa usa ALL")
        if preset == "dnp-contamination-cpi":
            composed_cpi.add_argument("--contamination-panel", type=_path,
                                      help="pannello Contamination; se omesso usa il pannello DNPcall")
        composed_cpi.add_argument("--parallel", action="store_true",
                                  help="parallelismo fra campioni in DNPcall; i passaggi restano sequenziali")
        composed_cpi.add_argument("--run-name")
        composed_cpi.add_argument("--snp-panel", type=_path,
                                  help="aggiunge SNPcall indipendente su ogni BAM, con questo pannello SNP")

    snp_batch = workflow_presets.add_parser(
        "snp-batch", help="esegue SNPcall in sequenza su piu' BAM o pileup, con risultati separati",
    )
    snp_batch_input = snp_batch.add_mutually_exclusive_group(required=True)
    snp_batch_input.add_argument("--bam", type=_path, action="append", help="ripetibile per piu' BAM")
    snp_batch_input.add_argument("--bamlist", type=_path, help="file con un percorso BAM per riga")
    snp_batch_input.add_argument("--pileup", type=_path, action="append", help="ripetibile per piu' pileup SNP")
    snp_batch.add_argument("--reference", type=_path, help="FASTA obbligatorio soltanto per input BAM")
    snp_batch.add_argument("--panel", type=_path, required=True, help="pannello SNP comune ai campioni")
    snp_batch.add_argument("--run-name")

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
    if args.dry_run and args.command == "runs":
        parser.error("runs interroga il runtime: rimuovere --dry-run; inspect non arresta container")
    if args.dry_run and args.command == "installation":
        parser.error("installation richiede un controllo reale: rimuovere --dry-run; inspect non modifica componenti")
    execution_overrides = {
        name: getattr(args, name) for name in ("input_hashes", "cpus", "memory_mb", "pids_limit")
        if getattr(args, name) is not None
    }
    if execution_overrides and args.command not in {
        "wizard", "workflow", "dnp-call", "snp-call", "contamination", "cpi",
    }:
        parser.error("Le opzioni di provenienza e risorse si applicano alle analisi e al wizard; "
                     "rimuoverle per diagnostica, autotest e manutenzione.")
    completion_label = "Esecuzione pianificata" if args.dry_run else "Esecuzione completata"

    activity = ExitStack()
    try:
        if args.command == "parameters":
            from nipat.catalog_ui import catalog_lines
            from nipat.terminal import Terminal
            from nipat_scientific.catalog import load_catalog

            catalog = load_catalog(args.workflow)
            if args.json:
                # ASCII JSON escapes preserve the bilingual content even when
                # redirected from a Windows console with a legacy encoding.
                print(json.dumps(catalog, ensure_ascii=True, indent=2))
            else:
                with Terminal() as ui:
                    for line in catalog_lines(catalog, language=args.lang, section=args.section):
                        ui.message(line)
            return 0
        layout = ProjectLayout.discover(data_dir=args.data_dir, runs_dir=args.runs_dir)
        activity.enter_context(activity_session(project_dir=layout.project_dir))
        runner = DockerComposeRunner(layout, dry_run=args.dry_run,
                                     options=ExecutionOptions(**execution_overrides))
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
                preferences_store=PreferencesStore(),
                directory_overrides={
                    key: getattr(args, key) for key in ("data_dir", "runs_dir")
                    if getattr(args, key) is not None
                },
                execution_overrides=execution_overrides,
            )
        elif args.command == "runs":
            stop_requested = args.run_operation == "stop"
            if stop_requested and not args.yes:
                from nipat.terminal import Terminal
                with Terminal() as ui:
                    ui.message(translate("recovery_help", args.lang))
                    ui.message(str(args.run))
                    answer = ui.prompt(translate("stop_confirm", args.lang)).strip().casefold()
                if answer not in {"s", "si", "sì", "y", "yes"}:
                    print(translate("stop_cancelled", args.lang))
                    return 0
            reports = ([runner.reconcile_run(args.run, stop=stop_requested)] if args.run is not None
                       else runner.incomplete_runs())
            if args.json:
                print(json.dumps(reports, ensure_ascii=True, indent=2))
            elif not reports:
                print(translate("no_incomplete_runs", args.lang))
            else:
                from nipat.terminal import Terminal
                with Terminal() as ui:
                    for report in reports:
                        for line in recovery_lines(report, language=args.lang):
                            ui.message(line)
                    if stop_requested:
                        ui.message(translate("stop_requested", args.lang))
            if stop_requested and any(
                item.get("cleanup", {}).get("status") == "not_confirmed"
                for report in reports for item in report.get("containers", [])
            ):
                return 2
        elif args.command == "installation":
            from nipat.installation import (
                installation_inventory, inventory_lines, maintenance_selection, start_maintenance,
            )
            from nipat.terminal import Terminal
            from nipat.update_handoff import HANDOFF_EXIT_CODE

            inventory = installation_inventory(layout.project_dir)
            if args.installation_operation == "inspect":
                if args.json:
                    print(json.dumps(inventory, ensure_ascii=True, indent=2))
                else:
                    with Terminal() as ui:
                        for line in inventory_lines(inventory):
                            ui.message(line)
            else:
                selected = maintenance_selection(inventory, args.installation_operation, args.target)
                with Terminal() as ui:
                    ui.message(selected.get("path", selected["id"]))
                    ui.message(selected.get("reason", ""))
                    if not args.yes:
                        answer = ui.prompt("Confermare la manutenzione e chiudere NIPAT? [s/N]").strip().casefold()
                        if answer not in {"s", "si", "sì", "y", "yes"}:
                            ui.message("Manutenzione annullata. Nessuna modifica richiesta.")
                            return 0
                    report = start_maintenance(layout.project_dir, args.installation_operation, args.target)
                    ui.message(f"Passaggio alla manutenzione confermato. Esito finale: {report}")
                return HANDOFF_EXIT_CODE
        elif args.command == "self-test":
            run_self_tests(layout)
        elif args.command == "workflow":
            if args.preset == "dnp-contamination":
                run_dir = workflows.dnp_contamination(
                    bams=args.bam, bamlist=args.bamlist, reference=args.reference,
                    panel=args.panel, contamination_panel=args.contamination_panel,
                    parallel=args.parallel, run_name=args.run_name, snp_panel=args.snp_panel,
                )
            elif args.preset == "snp-batch":
                run_dir = workflows.snp_batch(
                    bams=args.bam, bamlist=args.bamlist, pileups=args.pileup,
                    reference=args.reference, panel=args.panel, run_name=args.run_name,
                )
            else:
                run_dir = workflows.dnp_cpi(
                    pairs=[(pair_id, _path(mother), _path(father))
                           for pair_id, mother, father in args.pair],
                    reference=args.reference, panel=args.panel, popfreq=args.popfreq,
                    err_const=args.err_const, cpi_panel=args.cpi_panel,
                    cutoffs=[(label, _path(path)) for label, path in args.cutoff] if args.cutoff else None,
                    cutoff_map=args.cutoff_map, include_contamination=args.preset == "dnp-contamination-cpi",
                    contamination_panel=getattr(args, "contamination_panel", None),
                    parallel=args.parallel, run_name=args.run_name, snp_panel=args.snp_panel,
                )
            print(f"{completion_label}: {run_dir}")
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
    finally:
        activity.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
