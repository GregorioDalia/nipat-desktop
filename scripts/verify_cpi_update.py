"""Run the real CPI workflow and check its synthetic numeric regression cases."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from nipat.cli import DEFAULT_ERR_CONST
from nipat.errors import NipatError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.integrity import verify_sha256_manifest


EXPECTED_INFORMATIVE = {
    "N_sites_mother": 3,
    "N_sites_father": 3,
    "Median_fetal_fraction_raw": 0.06,
    "Median_fetal_fraction_percent": 6,
    "Max_logCPI": 1.301,
    "Min_logCPI": 0.301,
    "Median_logCPI": 0.602,
    "Mean_logCPI": 0.735,
    "CPI_medianFF": 0.602,
}
INFORMATIVE_PAIR = "MotherInformative-FatherInformative_DNPs"
NO_SITES_PAIR = "MotherNoSites-FatherNoSites_DNPs"


def check_number(row: dict[str, str], column: str, expected: float) -> None:
    value = row.get(column)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{row['Pair']}: {column} non numerico: {value!r}") from exc
    if not math.isfinite(number) or not math.isclose(
        number, expected, rel_tol=0, abs_tol=1e-9
    ):
        raise ValidationError(
            f"{row['Pair']}: {column}={value}, atteso {expected}"
        )


def check_outputs(run_dir: Path, expected_cutoff: str) -> None:
    summary = run_dir / "output" / "Summary_FetalFraction_CPI.csv"
    with summary.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_pairs = {INFORMATIVE_PAIR, NO_SITES_PAIR}
    if len(rows) != 2 or {row.get("Pair") for row in rows} != expected_pairs:
        raise ValidationError("Il CSV deve contenere esattamente le due coppie di test.")
    by_pair = {row["Pair"]: row for row in rows}
    for row in rows:
        if row.get("Cutoff") != expected_cutoff:
            raise ValidationError(f"{row['Pair']}: pannello Cutoff inatteso.")

    for column, expected in EXPECTED_INFORMATIVE.items():
        check_number(by_pair[INFORMATIVE_PAIR], column, expected)

    no_sites = by_pair[NO_SITES_PAIR]
    for column in ("N_sites_mother", "N_sites_father"):
        check_number(no_sites, column, 0)
    for column in EXPECTED_INFORMATIVE:
        if column not in ("N_sites_mother", "N_sites_father"):
            if no_sites.get(column) != "NA":
                raise ValidationError(
                    f"{NO_SITES_PAIR}: {column} deve essere NA, "
                    f"ottenuto {no_sites.get(column)!r}"
                )

    for name in (
        f"{INFORMATIVE_PAIR}_CPIplot.pdf",
        f"{NO_SITES_PAIR}_CPIplot.pdf",
        "All_CPIplots.pdf",
    ):
        pdf = run_dir / "output" / "plots" / name
        with pdf.open("rb") as handle:
            if handle.read(5) != b"%PDF-" or pdf.stat().st_size <= 5:
                raise ValidationError(f"PDF mancante o non valido: {pdf}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", help="nome opzionale di una nuova esecuzione")
    args = parser.parse_args()
    layout = ProjectLayout.discover()
    script_project = Path(__file__).resolve().parents[1]
    try:
        if layout.project_dir != script_project:
            raise ValidationError(
                "Il pacchetto nipat o NIPAT_PROJECT_DIR punta a un altro progetto. "
                "Usare la venv di questa repository e verificare l'installazione editable."
            )
        verify_sha256_manifest(layout.project_dir / "scientific" / "SHA256SUMS")
        fixtures = layout.project_dir / "tests" / "fixtures" / "cpi"
        workflow = Workflows(layout, DockerComposeRunner(layout))
        run_dir = workflow.cpi(
            input_dir=fixtures / "samples",
            pairs="Informative:Informative,NoSites:NoSites",
            mother_prefix="Mother",
            father_prefix="Father",
            popfreq=fixtures / "pop_allFreq.txt",
            panel=fixtures / "DNP_list.txt",
            err_const=DEFAULT_ERR_CONST,
            run_name=args.run_name,
        )
        print(f"Risultati del test: {run_dir}", flush=True)
        cutoff = str(layout.container_path(run_dir / "work" / "DNPpanel.txt"))
        check_outputs(run_dir, cutoff)
    except (NipatError, OSError) as exc:
        print(f"Verifica CPI fallita: {exc}", file=sys.stderr)
        return 1
    print("Verifica CPI superata: valori CSV attesi e tre PDF presenti.")
    print("Coppia informativa: 3 siti, frazione fetale 6%, CPI_medianFF (log10) 0.602.")
    print("Coppia senza siti informativi: conteggi 0 e stime NA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
