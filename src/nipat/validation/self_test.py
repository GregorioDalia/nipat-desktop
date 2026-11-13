"""Bundled checks for deployment and numerical regression, not domain validation."""

from __future__ import annotations

import csv
import math
import os
import subprocess
import sys
from pathlib import Path

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


SNP_COLUMNS = {
    "chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count",
    "ratio", "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
    "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts",
}


def compare_snp_outputs(expected_path: Path, actual_path: Path) -> int:
    """Compare every SNPcall 2.0 field, preserving missing and infinite values."""
    def read(path: Path) -> dict[tuple[str, str], dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if set(reader.fieldnames or []) != SNP_COLUMNS or len(reader.fieldnames) != len(SNP_COLUMNS):
                raise ValidationError(f"Colonne SNPcall 2.0 inattese: {path}")
            result = {}
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValidationError(f"Riga SNPcall incompleta: {path}")
                key = (row["chr"], row["pos"])
                if key in result:
                    raise ValidationError(f"Coordinata SNPcall duplicata: {key}")
                result[key] = row
        if not result:
            raise ValidationError(f"Tabella SNPcall vuota: {path}")
        return result

    expected, actual = read(expected_path), read(actual_path)
    if expected.keys() != actual.keys():
        raise ValidationError("Le coordinate SNPcall differiscono dal riferimento.")
    integer_columns = {"N_REF", "N_ALT", "N_Other", "total_count", "reads_discarded_for_indels"}
    numeric_columns = {"ratio", "GL0", "GL1", "GL2", "ratio_reads_discarded_for_indels"}
    for key, row in actual.items():
        for column in SNP_COLUMNS - {"chr", "pos"}:
            observed, reference = row[column], expected[key][column]
            if observed == "NA" or reference == "NA":
                matches = observed == reference
            elif column in integer_columns:
                try:
                    matches = int(observed) == int(reference)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{key}: {column} non intero.") from exc
            elif column in numeric_columns:
                try:
                    observed_number, reference_number = float(observed), float(reference)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{key}: {column} non numerico.") from exc
                matches = (not math.isnan(observed_number) and not math.isnan(reference_number)
                           and math.isclose(observed_number, reference_number,
                                            rel_tol=1e-12, abs_tol=1e-12))
            else:
                matches = observed == reference
            if not matches:
                raise ValidationError(f"{key}: {column} diverso dal riferimento.")
    return len(actual)


def run_snp_example(layout: ProjectLayout, run_name: str | None = None) -> Path:
    source = layout.project_dir / "scientific" / "vendor" / "NEWPAT" / "SNPcall"
    examples = source / "examples"
    inputs = [examples / name for name in ("pileup.txt", "SNPlist.txt", "output.txt")]
    for path in inputs:
        if not path.is_file():
            raise ValidationError(f"File di esempio mancante: {path}")
    run_dir = Workflows(layout, DockerComposeRunner(layout)).snp_call(
        pileup=inputs[0], panel=inputs[1], run_name=run_name,
    )
    output = run_dir / "output" / "SNPcall_output.txt"
    rows = compare_snp_outputs(inputs[2], output)
    print(f"Verifica SNPcall superata: {rows} righe corrispondono al riferimento.")
    print(f"Risultati del test: {run_dir}")
    return run_dir


def run_self_tests(layout: ProjectLayout) -> None:
    """Run every existing reference check in its own fresh run directory."""
    environment = os.environ.copy()
    environment["NIPAT_PROJECT_DIR"] = str(layout.project_dir)
    environment["NIPAT_WORKSPACE_DIR"] = str(layout.workspace_dir)
    environment["NIPAT_DATA_DIR"] = str(layout.data_dir)
    environment["NIPAT_RUNS_DIR"] = str(layout.runs_dir)
    environment["PYTHONPATH"] = str(layout.project_dir / "src") + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    checks = (
        ("SNPcall", "verify_snp_example.py"),
        ("CPI", "verify_cpi_update.py"),
        ("Contamination", "verify_contamination_update.py"),
        ("CPIN", "verify_cpin_update.py"),
        ("percorsi esterni e modalità di input", "verify_input_modes.py"),
    )
    for label, filename in checks:
        script = layout.project_dir / "scripts" / filename
        if not script.is_file():
            raise ValidationError(f"Verifica distribuita mancante: {script}")
        print(f"\nAutotest {label}", flush=True)
        try:
            subprocess.run(
                [sys.executable, "-X", "utf8", "-u", str(script)], cwd=layout.project_dir,
                env=environment, check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeExecutionError(
                f"Autotest {label} non superato. Consultare l'errore e i run appena creati."
            ) from exc
    print("\nAutotest superati: esempi numerici, percorsi esterni e modalità di input.")
    print("Questo autotest non include DNPcall da BAM; le prove su campioni reali restano necessarie.")
