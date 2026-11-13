"""CPIN input contracts fail before staging; selected samples are copied once."""

from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from nipat_scientific.cpin import normalize_trios, prepare_cpin
from nipat_scientific.errors import ValidationError

FIXTURE = Path(__file__).parent / "fixtures/cpin"


def make_request(tmp_path, marker="SNP"):
    inputs = tmp_path / "inputs"
    shutil.copytree(FIXTURE / marker, inputs)
    return {
        "schema_version": 1, "workflow": "cpin", "trios": " M1 : F1 : C1 ",
        "mother_prefix": "Mother", "father_prefix": "Father", "child_prefix": "Child",
        "samples": [{"path": str(inputs / name), "name": name} for name in
                    ("MotherM1.txt", "FatherF1.txt", "ChildC1.txt")],
        "popfreq": str(inputs / "population.txt"),
        "work_dir": str(tmp_path / "run/work"), "out_dir": str(tmp_path / "run/output"),
    }


@pytest.mark.parametrize("marker", ["SNP", "DNP"])
def test_staging_preserves_counts_and_full_marker_panel(tmp_path, marker):
    request = make_request(tmp_path, marker)
    request["markers"] = str(tmp_path / "inputs/markers.tsv")
    originals = {path: path.read_bytes() for path in (tmp_path / "inputs").iterdir()}
    argv = prepare_cpin(request)
    assert "--trios=M1:F1:C1" in argv
    assert argv[argv.index("--min_child_reads") + 1] == "2"
    assert argv[argv.index("--site_selection") + 1] == "both"
    for sample in request["samples"]:
        assert (tmp_path / "run/work/inputs" / sample["name"]).read_bytes() == originals[Path(sample["path"])]
    assert "\tREF\tALT\n" in (tmp_path / "run/work/markers.tsv").read_text()
    assert {path: path.read_bytes() for path in originals} == originals


def test_shared_parents_are_selected_once():
    canonical, names = normalize_trios("M1:F1:C1, M1:F1:C2", "Mother", "Father", "Child")
    assert canonical == "M1:F1:C1,M1:F1:C2"
    assert names == ["MotherM1.txt", "FatherF1.txt", "ChildC1.txt", "ChildC2.txt"]


@pytest.mark.parametrize("trios", ["M:F:C,M:F:C", "M:F:C,m:f:c",
                                      "M:F", "M:F:C,", "../M:F:C", "M:F:.."])
def test_duplicate_colliding_or_ambiguous_roles_rejected(trios):
    with pytest.raises(ValidationError):
        normalize_trios(trios, "Mother", "Father", "Child")


def test_role_local_identifiers_may_repeat_with_distinct_filenames():
    assert normalize_trios("A:A:A", "Mother", "Father", "Child") == (
        "A:A:A", ["MotherA.txt", "FatherA.txt", "ChildA.txt"])
    with pytest.raises(ValidationError):
        normalize_trios("A:A:A", "", "", "")


def test_role_local_request_stages_distinct_inputs(tmp_path):
    request = make_request(tmp_path)
    request["trios"] = "A:A:A"
    for item, role in zip(request["samples"], ("Mother", "Father", "Child")):
        item["name"] = role + "A.txt"
    argv = prepare_cpin(request)
    assert "--trios=A:A:A" in argv
    assert {path.name for path in (tmp_path / "run/work/inputs").iterdir()} == {
        "MotherA.txt", "FatherA.txt", "ChildA.txt"}


def test_prefix_composition_cannot_alias_distinct_samples():
    with pytest.raises(ValidationError):
        normalize_trios("AB:B:C", "", "A", "Child")


@pytest.mark.parametrize("changes", [
    {"scientific_settings": {"err_const_snp": 0}},
    {"scientific_settings": {"min_child_reads": 1.5}},
    {"scientific_settings": {"unsupported": 42}},
    {"marker_type": "DNP"}, {"schema_version": True}, {"extra": 1},
    {"samples": []}, {"presentation": {}},
])
def test_invalid_request_creates_no_run(tmp_path, changes):
    request = make_request(tmp_path)
    with pytest.raises(ValidationError):
        prepare_cpin({**request, **changes})
    assert not (tmp_path / "run").exists()


def test_same_source_must_not_be_aliased_to_multiple_roles(tmp_path):
    request = make_request(tmp_path)
    request["samples"][1]["path"] = request["samples"][0]["path"]
    with pytest.raises(ValidationError):
        prepare_cpin(request)
    assert not (tmp_path / "run").exists()


def test_inconsistent_totals_and_duplicate_coordinates_reject_without_writes(tmp_path):
    request = make_request(tmp_path)
    sample = Path(request["samples"][0]["path"])
    original = sample.read_text()
    for text in (original.replace("100\t0\t0\t100", "100\t0\t0\t99", 1),
                 original + original.splitlines()[1] + "\n"):
        sample.write_text(text)
        with pytest.raises(ValidationError):
            prepare_cpin(deepcopy(request))
        assert not (tmp_path / "run").exists()


def test_coordinate_only_panel_rejects_before_staging(tmp_path):
    request = make_request(tmp_path)
    panel = tmp_path / "panel.tsv"
    panel.write_text("chr\tpos\n1\t1\n")
    request["markers"] = str(panel)
    with pytest.raises(ValidationError, match="REF e ALT"):
        prepare_cpin(request)
    assert not (tmp_path / "run").exists()
