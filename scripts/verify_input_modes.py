"""Run four Docker integration checks with preserved inputs outside the workspace."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

# Embedded Python's ._pth excludes the script directory from its search path.
# Resolve sibling verification modules from this file, independently of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nipat.cli import DEFAULT_ERR_CONST
from nipat.errors import NipatError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.self_test import compare_snp_outputs
from verify_contamination_update import check_outputs as check_contamination_outputs
from verify_contamination_update import check_bundled_run
from verify_cpi_update import (
    EXPECTED_INFORMATIVE,
    INFORMATIVE_PAIR,
    NO_SITES_PAIR,
    check_number,
)


# FirstTwo keeps the loci with two and three fetal reads. Their PI values are
# 5 and 2: log10(CPI) is 1 at threshold 2 and log10(2) at threshold 3.
# R rounds the median read count, 2.5, to the even integer 2.
EXPECTED_FIRST_TWO = {
    "N_sites_mother": 2,
    "N_sites_father": 2,
    "Median_fetal_fraction_raw": 0.05,
    "Median_fetal_fraction_percent": 5,
    "Max_logCPI": 1,
    "Min_logCPI": 0.301,
    "Median_logCPI": 0.651,
    "Mean_logCPI": 0.651,
    "CPI_medianFF": 1,
}


def make_external_directory(layout: ProjectLayout, parent: Path | None) -> Path:
    parent = (parent or Path(tempfile.gettempdir())).expanduser().resolve()
    if not parent.is_dir():
        raise ValidationError(f"Directory temporanea non trovata: {parent}")
    for root in (layout.project_dir, layout.data_dir, layout.runs_dir):
        if parent.is_relative_to(root.resolve()):
            raise ValidationError(
                "La prova richiede una directory esterna al progetto, a data e a runs. "
                "Indicarla con --fixture-parent."
            )
    return Path(tempfile.mkdtemp(prefix="nipat input modes $ ,= ", dir=parent)).resolve()


def copy_input(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def write_coordinate_panel(source: Path, destination: Path, limit: int | None = None) -> Path:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row[:3] for row in csv.reader(handle, delimiter="\t") if row]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("chr", "pos1", "pos2"))
        writer.writerows(rows if limit is None else rows[:limit])
    return destination


def prepare_inputs(layout: ProjectLayout, external: Path) -> dict[str, Path]:
    snp_examples = layout.project_dir / "scientific/vendor/NEWPAT/SNPcall/examples"
    fixtures = layout.project_dir / "tests/fixtures"
    snp_dir = external / "SNP input $ ,= files"
    inputs = {
        "snp_pileup": copy_input(snp_examples / "pileup.txt", snp_dir / "pileup $ ,=.txt"),
        "snp_panel": copy_input(snp_examples / "SNPlist.txt", snp_dir / "SNP list $ ,=.tsv"),
        "snp_expected": copy_input(
            snp_examples / "output.txt", snp_dir / "expected output $ ,=.txt"
        ),
    }

    contamination = external / "contamination input $ ,= files"
    inputs["contamination_dir"] = contamination
    inputs["contamination_panel"] = write_coordinate_panel(
        fixtures / "contamination/DNP_list.txt", contamination / "DNP coordinates $ ,=.TSV"
    )
    for original, relative in (
        ("NoRatio.tsv", "first nested $ ,=/NoRatio.TsV"),
        ("WithRatio.TXT", "second nested $ ,=/deeper/WithRatio.tXt"),
        ("NoSites.txt", "NoSites.TXT"),
    ):
        copy_input(fixtures / "contamination/samples" / original, contamination / relative)
    (contamination / "ignored.md").write_text(
        "This non-tabular file must not be selected as a contamination input.\n",
        encoding="utf-8",
    )

    cpi_dir = external / "CPI input $ ,= files"
    for name in (
        "MotherInformative.txt", "FatherInformative.txt",
        "MotherNoSites.txt", "FatherNoSites.txt",
    ):
        copy_input(fixtures / "cpi/samples" / name, cpi_dir / name)
    inputs["cpi_dir"] = cpi_dir
    inputs["cpi_popfreq"] = copy_input(
        fixtures / "cpi/pop_allFreq.txt", external / "population frequencies $ ,=.tsv"
    )
    inputs["cpi_full"] = write_coordinate_panel(
        fixtures / "cpi/DNP_list.txt", external / "Full panel $ ,=.tsv"
    )
    inputs["cpi_first_two"] = write_coordinate_panel(
        fixtures / "cpi/DNP_list.txt", external / "FirstTwo panel $ ,=.tsv", limit=2
    )
    return inputs


def check_originals(originals: dict[Path, bytes]) -> None:
    for path, before in originals.items():
        if not path.is_file() or path.read_bytes() != before:
            raise ValidationError(f"Input esterno modificato o rimosso: {path}")


def check_cpi_outputs(run_dir: Path, *, multiple_cutoffs: bool) -> None:
    with (run_dir / "output/Summary_FetalFraction_CPI.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        required = {"Pair", *EXPECTED_INFORMATIVE}
        if not required.issubset(columns):
            raise ValidationError("Colonne mancanti nel riepilogo CPI.")
        if ("Cutoff" in columns) != multiple_cutoffs:
            raise ValidationError("Presenza della colonna Cutoff incoerente con la modalita' CPI.")
        rows = list(reader)

    expected = (
        {"Full": EXPECTED_INFORMATIVE, "FirstTwo": EXPECTED_FIRST_TWO}
        if multiple_cutoffs else {None: EXPECTED_INFORMATIVE}
    )
    keys = [(row.get("Pair"), row.get("Cutoff")) for row in rows]
    expected_keys = {
        (pair, label) for pair in (INFORMATIVE_PAIR, NO_SITES_PAIR) for label in expected
    }
    if len(keys) != len(expected_keys) or set(keys) != expected_keys:
        raise ValidationError("Coppie o pannelli del riepilogo CPI diversi da quelli attesi.")
    for row in rows:
        if row["Pair"] == INFORMATIVE_PAIR:
            for column, value in expected[row.get("Cutoff")].items():
                check_number(row, column, value)
        else:
            for column in ("N_sites_mother", "N_sites_father"):
                check_number(row, column, 0)
            for column in EXPECTED_INFORMATIVE:
                if column not in ("N_sites_mother", "N_sites_father"):
                    if row.get(column) != "NA":
                        raise ValidationError(f"{NO_SITES_PAIR}: {column} deve essere NA.")

    for name in (
        f"{INFORMATIVE_PAIR}_CPIplot.pdf",
        f"{NO_SITES_PAIR}_CPIplot.pdf",
        "All_CPIplots.pdf",
    ):
        pdf = run_dir / "output/plots" / name
        with pdf.open("rb") as handle:
            if handle.read(5) != b"%PDF-" or pdf.stat().st_size <= 5:
                raise ValidationError(f"PDF mancante o non valido: {pdf}")


def run_checks(layout: ProjectLayout, inputs: dict[str, Path]) -> None:
    workflows = Workflows(layout, DockerComposeRunner(layout))
    token = uuid.uuid4().hex[:12]

    print("\n1/4 SNPcall da pileup esterno", flush=True)
    run_dir = workflows.snp_call(
        pileup=inputs["snp_pileup"], panel=inputs["snp_panel"],
        run_name=f"input-modes-snp-{token}",
    )
    print(f"Run: {run_dir}", flush=True)
    rows = compare_snp_outputs(inputs["snp_expected"], run_dir / "output/SNPcall_output.txt")
    check_bundled_run(run_dir, layout, workflow="snp-call")
    print(f"Verifica SNPcall superata: {rows} righe uguali al riferimento.")

    print("\n2/4 Contamination da directory esterna ricorsiva", flush=True)
    run_dir = workflows.contamination(
        input_dir=inputs["contamination_dir"], panel=inputs["contamination_panel"],
        run_name=f"input-modes-contamination-{token}",
    )
    print(f"Run: {run_dir}", flush=True)
    check_contamination_outputs(run_dir)
    check_bundled_run(run_dir, layout, workflow="contamination")
    print("Verifica Contamination superata: tre campioni e valori per sito attesi.")

    cpi_arguments = {
        "input_dir": inputs["cpi_dir"],
        "pairs": "Informative: Informative, NoSites :NoSites",
        "mother_prefix": "Mother", "father_prefix": "Father",
        "popfreq": inputs["cpi_popfreq"], "panel": None,
        "err_const": DEFAULT_ERR_CONST, "cutoff_map": None,
    }
    print("\n3/4 CPI con due pannelli esterni etichettati", flush=True)
    run_dir = workflows.cpi(
        **cpi_arguments,
        cutoffs=[("Full", inputs["cpi_full"]), ("FirstTwo", inputs["cpi_first_two"])],
        run_name=f"input-modes-cpi-panels-{token}",
    )
    print(f"Run: {run_dir}", flush=True)
    check_cpi_outputs(run_dir, multiple_cutoffs=True)
    check_bundled_run(run_dir, layout, workflow="cpi")
    print("Verifica CPI multi-pannello superata: quattro righe attese e tre PDF.")

    print("\n4/4 CPI ALL senza pannello", flush=True)
    run_dir = workflows.cpi(
        **cpi_arguments, run_name=f"input-modes-cpi-all-{token}",
    )
    print(f"Run: {run_dir}", flush=True)
    check_cpi_outputs(run_dir, multiple_cutoffs=False)
    check_bundled_run(run_dir, layout, workflow="cpi")
    print("Verifica CPI ALL superata: due righe attese, senza Cutoff, e tre PDF.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-parent", type=Path,
        help="directory esterna in cui creare e conservare gli input; default: temp di sistema",
    )
    args = parser.parse_args()
    originals: dict[Path, bytes] = {}
    try:
        layout = ProjectLayout.discover()
        if layout.project_dir != Path(__file__).resolve().parents[1]:
            raise ValidationError("Usare il Python del progetto e verificare NIPAT_PROJECT_DIR.")
        external = make_external_directory(layout, args.fixture_parent)
        print(f"Input esterni conservati per provenienza e diagnosi: {external}", flush=True)
        inputs = prepare_inputs(layout, external)
        originals = {path: path.read_bytes() for path in external.rglob("*") if path.is_file()}
        run_checks(layout, inputs)
        check_originals(originals)
    except (NipatError, OSError, ValueError, TypeError) as exc:
        print(f"Verifica modalita' input fallita: {exc}", file=sys.stderr)
        try:
            check_originals(originals)
        except (NipatError, OSError) as input_error:
            print(str(input_error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Verifica modalita' input interrotta; input esterni conservati.", file=sys.stderr)
        return 130
    print("\nQuattro verifiche Docker superate; tutti gli input esterni sono invariati.")
    print("Queste prove non includono DNPcall da BAM o la validazione scientifica su campioni reali.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
