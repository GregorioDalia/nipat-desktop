"""Exercise final native CLI precedence and inspect the actual recorded values."""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from nipat_scientific.settings import settings_context

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/five_modules/SNP"
pytestmark = pytest.mark.skipif(shutil.which("Rscript") is None, reason="R runtime is unavailable")


def execute(tmp_path, workflow, settings, flags, inputs=None):
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    with settings_context(workflow, settings, work):
        env = dict(os.environ, NIPAT_EXECUTION_MODE="serial",
                   NIPAT_PARALLEL_HELPER=str(ROOT / "src/nipat_scientific/parallel.R"),
                   NIPAT_PLOTS_HELPER=str(ROOT / "src/nipat_scientific/plots.R"))
        if workflow == "cpi":
            directory = inputs or FIXTURE / "cpi"
            arguments = [str(ROOT / "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R"),
                         "--pileup_dir", str(directory), "--out_dir", str(output),
                         "--pairs=M:F", "--mother_prefix=Mother", "--father_prefix=Father",
                         "--popfreq", str(FIXTURE / "cpi/population.tsv")]
        else:
            arguments = [str(ROOT / "scientific/vendor/NEWPAT/contamination/detect_contamination.R"),
                         str(FIXTURE / "contamination/panel.tsv"),
                         str(FIXTURE / "contamination/Calls.txt"), str(output)]
        result = subprocess.run(["Rscript", *arguments, *flags], env=env, capture_output=True,
                                text=True, timeout=90)
    return result, output


def test_native_cpi_explicit_overrides_are_recorded_after_config(tmp_path):
    result, output = execute(tmp_path, "cpi", {"err_const_snp": 0.02, "min_fetal_reads": 5},
                             ["--err_const_snp", "0.04", "--err_const", "0.06",
                              "--err_const_dnp", "0.03", "--min_fetal_reads", "2"])
    assert result.returncode == 0, result.stderr
    settings = json.loads((output / "scientific-settings.json").read_text())["parameters"]
    assert settings["err_const_snp"] == 0.06
    assert settings["err_const_dnp"] == 0.03
    assert settings["min_fetal_reads"] == 2
    row = next(csv.DictReader((output / "Summary_FetalFraction_CPI.csv").open()))
    assert float(row["Error_constant"]) == settings["err_const_snp"]
    assert int(row["Min_fetal_reads"]) == settings["min_fetal_reads"]


def test_native_contamination_zero_flag_overrides_config_and_is_recorded(tmp_path):
    result, output = execute(tmp_path, "contamination", {"include_zero": False}, ["--include_zero"])
    assert result.returncode == 0, result.stderr
    settings = json.loads((output / "scientific-settings.json").read_text())["parameters"]
    assert settings["include_zero"] is True
    row = next(csv.DictReader((output / "contamination_summary.txt").open(), delimiter="\t"))
    assert row["informative_sites"] == "2"


def test_native_contamination_conflicting_zero_flags_fail(tmp_path):
    result, output = execute(tmp_path, "contamination", {}, ["--include_zero", "--exclude_zero"])
    assert result.returncode != 0
    assert "choose either" in result.stderr
    assert not (output / "contamination_summary.txt").exists()


@pytest.mark.parametrize("row,success", [
    ("", True), ("chr1\t100\tA\tC\t0\t0\t0\tNA\n", True),
    ("chr1\t100\tA\tC\t0\t0\t0\tbad\n", False),
])
def test_native_cpi_empty_and_zero_coverage_are_distinct_from_malformed_total(tmp_path, row, success):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("MotherM.txt", "FatherF.txt"):
        (inputs / name).write_text("chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n" + row)
    result, output = execute(tmp_path, "cpi", {}, [], inputs=inputs)
    assert (result.returncode == 0) is success, result.stderr
    if success:
        curve = output / "curves/MotherM-FatherF_SNPs_panel_1.tsv"
        assert curve.read_text().startswith("Iteration\tInfSites_mother")
