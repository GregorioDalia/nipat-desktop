"""Run the R contamination workflow against synthetic analytical references."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from nipat.errors import NipatError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.integrity import verify_sha256_manifest


EXPECTED_SITES = {
    ("chr1", "100", "101"): (1.0, 0.0),
    ("chr1", "200", "201"): (0.0, 0.0),
    ("chr1", "300", "301"): (0.95, 0.05),
    ("chr1", "400", "401"): (0.05, 0.05),
}
EXPECTED_SD = 0.0288675134594813


def read_tsv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not required.issubset(reader.fieldnames or []):
            raise ValidationError(f"Colonne mancanti nel risultato: {path.name}")
        return list(reader)


def check_number(value: str | None, expected: float, label: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}: valore non numerico {value!r}") from exc
    if not math.isfinite(number) or not math.isclose(
        number, expected, rel_tol=0, abs_tol=1e-12
    ):
        raise ValidationError(f"{label}: ottenuto {value}, atteso {expected}")


def check_outputs(run_dir: Path) -> None:
    output = run_dir / "output"
    summary = read_tsv(
        output / "contamination_summary.txt",
        {"individuo", "informative_DNPs", "mean_contamination", "sd_contamination"},
    )
    if len(summary) != 3 or {row["individuo"] for row in summary} != {
        "NoRatio", "WithRatio", "NoSites"
    }:
        raise ValidationError("Il riepilogo deve contenere esattamente i tre campioni di test.")
    by_sample = {row["individuo"]: row for row in summary}
    for sample in ("NoRatio", "WithRatio"):
        for column, expected in (
            ("informative_DNPs", 4),
            ("mean_contamination", 0.025),
            ("sd_contamination", EXPECTED_SD),
        ):
            check_number(by_sample[sample][column], expected, f"{sample}: {column}")
        sites = read_tsv(
            output / f"contamination_{sample}.txt",
            {"chr", "pos1", "pos2", "ratio_REF_ALT", "contamination"},
        )
        coordinates = [(row["chr"], row["pos1"], row["pos2"]) for row in sites]
        if len(sites) != 4 or set(coordinates) != set(EXPECTED_SITES):
            raise ValidationError(f"{sample}: siti mantenuti diversi da quelli attesi.")
        for row, coordinate in zip(sites, coordinates):
            ratio, contamination = EXPECTED_SITES[coordinate]
            label = f"{sample}: {coordinate}"
            check_number(row["ratio_REF_ALT"], ratio, f"{label} ratio")
            check_number(row["contamination"], contamination, f"{label} contamination")

    empty = by_sample["NoSites"]
    check_number(empty["informative_DNPs"], 0, "NoSites: informative_DNPs")
    for column in ("mean_contamination", "sd_contamination"):
        if empty[column] != "NA":
            raise ValidationError(f"NoSites: {column} deve essere NA.")
    empty_sites = read_tsv(
        output / "contamination_NoSites.txt", {"chr", "pos1", "pos2", "contamination"}
    )
    if empty_sites:
        raise ValidationError("NoSites: atteso file per sito con sola intestazione.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", help="nome opzionale di una nuova esecuzione")
    args = parser.parse_args()
    layout = ProjectLayout.discover()
    try:
        if layout.project_dir != Path(__file__).resolve().parents[1]:
            raise ValidationError(
                "Usare la venv di questa repository e verificare NIPAT_PROJECT_DIR."
            )
        verify_sha256_manifest(layout.project_dir / "scientific" / "SHA256SUMS")
        fixture = layout.project_dir / "tests" / "fixtures" / "contamination"
        inputs = [
            fixture / "samples" / name
            for name in ("NoRatio.tsv", "WithRatio.TXT", "NoSites.txt")
        ]
        originals = {path: path.read_bytes() for path in inputs}
        run_dir = Workflows(layout, DockerComposeRunner(layout)).contamination(
            inputs=inputs, panel=fixture / "DNP_list.txt", run_name=args.run_name
        )
        print(f"Risultati del test: {run_dir}", flush=True)
        for path in inputs:
            if path.read_bytes() != originals[path]:
                raise ValidationError(f"Input originale modificato: {path.name}")
        check_outputs(run_dir)
    except (NipatError, OSError) as exc:
        print(f"Verifica Contamination fallita: {exc}", file=sys.stderr)
        return 1
    print("Verifica Contamination superata: riepilogo e valori per sito attesi.")
    print("Con/senza ratio: 4 siti, media 0.025 (2.5%), SD 0.0288675134594813.")
    print("Campione senza siti informativi: conteggio 0, media e SD NA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
