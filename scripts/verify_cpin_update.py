"""Verify the installed postnatal workflow against independent analytical loci."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

from nipat.errors import NipatError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from verify_contamination_update import check_bundled_run, check_number, read_tsv


def check_outputs(run_dir: Path, marker: str) -> None:
    output = run_dir / "output"
    trio = f"MotherM1-FatherF1-ChildC1_{marker}s"
    epsilon = 0.001 if marker == "SNP" else 0.0000892303778101497
    expected = {"heterozygous_child_sites": (2, 1.25 * epsilon / 0.4),
                "all_compatible_sites": (3, 1.25 * epsilon / 0.4 / 0.6)}
    rows = read_tsv(output / "Summary_Postnatal_CPI.txt",
                    {"Trio", "Analysis", "N_sites", "Log10_CPI", "CPI", "Error_constant"})
    if len(rows) != 2 or {row["Analysis"] for row in rows} != set(expected):
        raise ValidationError("CPIN: attese entrambe le analisi dei siti.")
    for row in rows:
        analysis = row["Analysis"]
        count, cpi = expected[analysis]
        if row["Trio"] != trio:
            raise ValidationError("CPIN: terna inattesa nel riepilogo.")
        for key, value in (("N_sites", count), ("CPI", cpi), ("Log10_CPI", math.log10(cpi)),
                           ("Error_constant", epsilon), ("Matching_sites", count - 1),
                           ("Mismatching_sites", 1)):
            check_number(row[key], value, f"CPIN {marker}/{analysis}: {key}")
        curve = read_tsv(output / "curves" / f"{trio}_{analysis}_curve.tsv",
                         {"Min_child_reads", "Through_min_child_reads", "N_sites", "Log10_CPI"})
        if len(curve) != (1 if count == 2 else 2):
            raise ValidationError("CPIN: intervalli della curva inattesi.")
        for key, value in (("Min_child_reads", 2), ("Through_min_child_reads", 50),
                           ("N_sites", count), ("Log10_CPI", math.log10(cpi)),
                           ("Matching_sites", count - 1), ("Mismatching_sites", 1)):
            check_number(curve[0][key], value, f"CPIN curva {analysis}: {key}")
        if count == 3:
            for key, value in (("Min_child_reads", 51), ("Through_min_child_reads", 100),
                               ("N_sites", 1), ("Log10_CPI", math.log10(1 / 0.6)),
                               ("Matching_sites", 1), ("Mismatching_sites", 0)):
                check_number(curve[1][key], value, f"CPIN curva finale: {key}")
        if not (output / "plots" / f"{trio}_{analysis}_CPIplot.pdf").read_bytes().startswith(b"%PDF-"):
            raise ValidationError("CPIN: PDF individuale mancante o non valido.")
    sites = read_tsv(output / "sites" / f"{trio}_sites.tsv", {"Status", "Paternity_Index"})
    expected_statuses = ["eligible", "eligible", "eligible", "mother_child_incompatible",
                         "quality_filter", "quality_filter", "insufficient_child_support",
                         "father_unassigned", "mother_not_homozygous"]
    position = "pos" if marker == "SNP" else "pos1"
    by_position = {int(row[position]): row["Status"] for row in sites}
    if len(sites) != 9 or by_position != dict(enumerate(expected_statuses, 1)):
        raise ValidationError("CPIN: siti o motivi di esclusione diversi dagli attesi.")
    if not (output / "All_CPIplots.pdf").read_bytes().startswith(b"%PDF-"):
        raise ValidationError("CPIN: PDF aggregato mancante o non valido.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", help="prefisso opzionale delle due nuove esecuzioni")
    args = parser.parse_args()
    layout = ProjectLayout.discover()
    try:
        if layout.project_dir != Path(__file__).resolve().parents[1]:
            raise ValidationError("Usare la venv di questa repository e verificare NIPAT_PROJECT_DIR.")
        fixture = layout.project_dir / "tests/fixtures/cpin"
        workflow = Workflows(layout, DockerComposeRunner(layout))
        for marker in ("SNP", "DNP"):
            directory = fixture / marker
            originals = {path: path.read_bytes() for path in directory.iterdir()}
            run_dir = workflow.cpin(input_dir=directory, trios="M1:F1:C1",
                                    popfreq=directory / "population.txt",
                                    run_name=f"{args.run_name}-{marker.lower()}" if args.run_name else None)
            print(f"Risultati CPIN {marker}: {run_dir}", flush=True)
            if any(path.read_bytes() != data for path, data in originals.items()):
                raise ValidationError("CPIN: un input originale è stato modificato.")
            check_outputs(run_dir, marker)
            check_bundled_run(run_dir, layout, workflow="cpin")
    except (NipatError, OSError) as exc:
        print(f"Verifica CPIN fallita: {exc}", file=sys.stderr)
        return 1
    print("Verifica CPIN superata: SNP/DNP, due selezioni, curve, esclusioni e PDF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
