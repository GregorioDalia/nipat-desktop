"""Focused native-R CPIN regression checks with independently derived numbers."""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from nipat_scientific.settings import settings_context
from native_r_helpers import NATIVE_R_AVAILABLE, NATIVE_R_REASON

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/cpin"
sys.path.insert(0, str(ROOT / "scripts"))
from verify_cpin_update import check_outputs

pytestmark = pytest.mark.skipif(not NATIVE_R_AVAILABLE, reason=NATIVE_R_REASON)


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def run_native(tmp_path, marker="SNP", settings=None, inputs=None, trios="M1:F1:C1", native_options=()):
    run = tmp_path / "run"
    work = run / "work"
    work.mkdir(parents=True)
    inputs = inputs or FIXTURE / marker
    env = os.environ.copy()
    env.update(NIPAT_EXECUTION_MODE="serial",
               NIPAT_PARALLEL_HELPER=str(ROOT / "src/nipat_scientific/parallel.R"),
               NIPAT_PLOTS_HELPER=str(ROOT / "src/nipat_scientific/plots.R"))
    with settings_context("cpin", settings or {}, work):
        for name in ("NIPAT_SCIENTIFIC_SETTINGS", "NIPAT_SETTINGS_HELPER", "NIPAT_SETTINGS_REGISTRY"):
            env[name] = os.environ[name]
        result = subprocess.run([
            "Rscript", str(ROOT / "scientific/vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R"),
            "--pileup_dir", str(inputs), "--out_dir", str(run / "output"),
            "--trios", trios, "--mother_prefix", "Mother", "--father_prefix", "Father",
            "--child_prefix", "Child", "--popfreq", str(inputs / "population.txt"),
            *native_options,
        ], env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return run


@pytest.mark.parametrize("marker", ["SNP", "DNP"])
def test_analytical_sites_curves_and_outputs(tmp_path, marker):
    check_outputs(run_native(tmp_path, marker), marker)


@pytest.mark.parametrize("settings,counts", [
    ({"min_child_reads": 1}, [3, 4]),
    ({"min_child_reads": 101}, [0, 0]),
    ({"other_fraction_max": 0.11}, [3, 4]),
    ({"heterozygous_max": 0.7}, [3, 4]),
    ({"site_selection": "other_allele"}, [2]),
    ({"site_selection": "all"}, [3]),
])
def test_settings_change_eligibility_and_analysis(tmp_path, settings, counts):
    run = run_native(tmp_path, settings=settings)
    rows = table(run / "output/Summary_Postnatal_CPI.txt")
    assert [int(row["N_sites"]) for row in rows] == counts
    if counts == [0, 0]:
        assert all(row["CPI"] == row["Log10_CPI"] == "NA" for row in rows)
        assert all(table(path) == [] for path in (run / "output/curves").iterdir())


def test_mismatch_constant_reaches_native_formula(tmp_path):
    run = run_native(tmp_path, settings={"err_const_snp": 0.02})
    rows = table(run / "output/Summary_Postnatal_CPI.txt")
    assert float(rows[0]["CPI"]) == pytest.approx(1.25 * 0.02 / 0.4, rel=1e-12)
    assert float(rows[1]["CPI"]) == pytest.approx(1.25 * 0.02 / 0.4 / 0.6, rel=1e-12)


def test_large_support_exports_intervals_without_depth_sized_allocation(tmp_path):
    inputs = tmp_path / "inputs"
    shutil.copytree(FIXTURE / "SNP", inputs)
    child = inputs / "ChildC1.txt"
    data = child.read_text().replace("100\t0\t0\t100", "1000000000\t0\t0\t1000000000")
    child.write_text(data)
    run = run_native(tmp_path, inputs=inputs)
    curve = table(next((run / "output/curves").glob("*all_compatible*")))
    assert len(curve) == 2
    assert float(curve[-1]["Through_min_child_reads"]) == 1_000_000_000


def test_native_role_local_ids_use_distinct_prefixed_files(tmp_path):
    inputs = tmp_path / "inputs"
    shutil.copytree(FIXTURE / "SNP", inputs)
    for role, identifier in (("Mother", "M1"), ("Father", "F1"), ("Child", "C1")):
        (inputs / f"{role}{identifier}.txt").rename(inputs / f"{role}A.txt")
    run = run_native(tmp_path, inputs=inputs, trios="A:A:A")
    rows = table(run / "output/Summary_Postnatal_CPI.txt")
    assert {row["Trio"] for row in rows} == {"MotherA-FatherA-ChildA_SNPs"}
    assert float(rows[0]["CPI"]) == pytest.approx(0.003125)


def test_native_sidecar_records_explicit_cli_overrides(tmp_path):
    run = run_native(tmp_path, native_options=("--min_child_reads", "3", "--err_const_snp", "0.02"))
    document = json.loads((run / "output/scientific-settings.json").read_text())
    assert document["parameters"]["min_child_reads"] == 3
    assert document["parameters"]["err_const_snp"] == 0.02
    assert document["workflow"] == "cpin"
    assert document["constants"]["ploidy"]["value"] == 2
