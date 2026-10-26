"""Real-image CPI regressions called by verify_engine_package.py.

Expected numbers come from the documented synthetic input design. Native R
parity supplements those expectations, and never generates the expected data.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

from nipat.cli import DEFAULT_ERR_CONST
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from verify_contamination_update import check_bundled_run
from verify_cpi_update import EXPECTED_INFORMATIVE, INFORMATIVE_PAIR, NO_SITES_PAIR, check_number
from verify_input_modes import EXPECTED_FIRST_TWO


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests/fixtures/cpi"
ERROR_FIXTURE = PROJECT / "tests/fixtures/cpi_engine"
SAMPLE_NAMES = ("MotherInformative.txt", "FatherInformative.txt",
                "MotherNoSites.txt", "FatherNoSites.txt")
PAIRS = "Informative:Informative,NoSites:NoSites"
NO_SITES = {name: 0 if name in ("N_sites_mother", "N_sites_father") else "NA"
            for name in EXPECTED_INFORMATIVE}


def summary_rows(run: Path) -> tuple[list[str], list[dict[str, str]]]:
    with (run / "output/Summary_FetalFraction_CPI.csv").open(
        encoding="utf-8-sig", newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def check_summary(run: Path, expected: dict[tuple[str, str | None], dict]) -> None:
    fields, rows = summary_rows(run)
    with_cutoff = any(label is not None for _, label in expected)
    expected_fields = {"Pair", *EXPECTED_INFORMATIVE}
    if with_cutoff:
        expected_fields.add("Cutoff")
    keys = [(row.get("Pair"), row.get("Cutoff")) for row in rows]
    if set(fields) != expected_fields or len(rows) != len(expected) or set(keys) != set(expected):
        raise ValueError(f"Unexpected CPI summary columns, pairs or cutoffs in {run}: {rows}.")
    for row, key in zip(rows, keys):
        for field, wanted in expected[key].items():
            if wanted == "NA":
                if row[field] != "NA":
                    raise ValueError(f"{run}/{key}/{field}: expected NA, got {row[field]}.")
            else:
                check_number(row, field, float(wanted))
    expected_pdfs = {"All_CPIplots.pdf", *(f"{pair}_CPIplot.pdf" for pair, _ in expected)}
    plots = run / "output/plots"
    if {path.name for path in plots.iterdir()} != expected_pdfs:
        raise ValueError(f"Unexpected CPI plot filenames in {run}.")
    for name in expected_pdfs:
        if not (plots / name).read_bytes().startswith(b"%PDF-"):
            raise ValueError(f"Missing or invalid PDF: {plots / name}.")


def standard_expected(labels: dict[str | None, dict]) -> dict:
    return {(pair, label): values if pair == INFORMATIVE_PAIR else NO_SITES
            for label, values in labels.items() for pair in (INFORMATIVE_PAIR, NO_SITES_PAIR)}


def normalized_panel(positions: tuple[int, ...]) -> str:
    return "n°DNP\tchr\tpos1\tpos2\n" + "".join(
        f"DNP{number:03d}\tchr1\t{position}\t{position + 1}\n"
        for number, position in enumerate(positions, 1)
    )


def check_staging(run: Path, samples: dict[str, Path], panels: dict[str, tuple[int, ...]]) -> None:
    staged = run / "work/inputs"
    if {path.name for path in staged.iterdir()} != set(samples):
        raise ValueError(f"CPI staged unselected or duplicate input names in {run}.")
    for name, source in samples.items():
        if (staged / name).read_bytes() != source.read_bytes():
            raise ValueError(f"CPI changed staged sample bytes: {name}.")
    actual_panels = {path.name for path in (run / "work").iterdir()
                     if path.name == "DNPpanel.txt" or path.name.startswith("cutoff_")}
    if actual_panels != set(panels):
        raise ValueError(f"Unexpected CPI prepared panels in {run}: {actual_panels}.")
    for name, positions in panels.items():
        if (run / "work" / name).read_text(encoding="utf-8") != normalized_panel(positions):
            raise ValueError(f"CPI panel preparation differs from expected coordinates: {name}.")


def assert_originals(originals: dict[Path, bytes]) -> None:
    if any(not path.is_file() or path.read_bytes() != value for path, value in originals.items()):
        raise ValueError("CPI workflow changed an original input.")


def check_cpi_workflow(identifier: str, root: Path, *, run_image, write_request) -> Path:
    inputs = root / "complete CPI inputs"
    shutil.copytree(FIXTURE / "samples", inputs / "samples")
    shutil.copyfile(FIXTURE / "pop_allFreq.txt", inputs / "population.tsv")
    shutil.copyfile(FIXTURE / "DNP_list.txt", inputs / "full.txt")
    (inputs / "first-two.tsv").write_text(
        "chr\tpos1\tpos2\nchr1\t100\t101\nchr1\t200\t201\n", encoding="utf-8",
    )
    # Not selected: should never appear in engine staging or client mounts.
    (inputs / "samples/ignored.txt").write_text("unselected input\n", encoding="utf-8")
    originals = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    samples = {name: inputs / "samples" / name for name in SAMPLE_NAMES}
    base = {
        "schema_version": 1, "workflow": "cpi",
        "samples": [{"path": f"/inputs/samples/{name}", "name": name} for name in SAMPLE_NAMES],
        "pairs": PAIRS, "mother_prefix": "Mother", "father_prefix": "Father",
        "popfreq": "/inputs/population.tsv", "err_const": DEFAULT_ERR_CONST,
        "work_dir": "/results/work", "out_dir": "/results/output",
    }
    for mode, cutoffs, labels, panels in (
        ("all", [], {None: EXPECTED_INFORMATIVE}, {}),
        ("panel", [{"label": "", "path": "/inputs/full.txt"}],
         {"/results/work/DNPpanel.txt": EXPECTED_INFORMATIVE},
         {"DNPpanel.txt": (100, 200, 300, 400)}),
        ("named", [{"label": "Full", "path": "/inputs/full.txt"},
                   {"label": "FirstTwo", "path": "/inputs/first-two.tsv"}],
         {"Full": EXPECTED_INFORMATIVE, "FirstTwo": EXPECTED_FIRST_TWO},
         {"cutoff_001.tsv": (100, 200, 300, 400), "cutoff_002.tsv": (100, 200)}),
    ):
        run = root / f"complete CPI {mode}"
        write_request(run, {**base, "cutoff_mode": mode, "cutoffs": cutoffs})
        run_image(identifier, ["execute", "cpi", "--request", "/results/work/request.json"],
                  inputs=inputs, results=run)
        check_summary(run, standard_expected(labels))
        check_staging(run, samples, panels)

    native = root / "native CPI ALL"
    run_image(identifier, [
        "run", "cpi", "--", "--pileup_dir", "/inputs/samples", "--out_dir", "/results/output",
        "--pairs", PAIRS, "--mother_prefix", "Mother", "--father_prefix", "Father",
        "--popfreq", "/inputs/population.tsv", "--err_const", str(DEFAULT_ERR_CONST),
    ], inputs=inputs, results=native)
    check_summary(native, standard_expected({None: EXPECTED_INFORMATIVE}))
    if summary_rows(native) != summary_rows(root / "complete CPI all"):
        raise ValueError("Complete CPI ALL summary differs from native R invocation.")

    invalid = root / "invalid CPI selection"
    write_request(invalid, {**base, "cutoff_mode": "all", "cutoffs": [],
                            "samples": base["samples"][:-1]})
    run_image(identifier, ["execute", "cpi", "--request", "/results/work/request.json"],
              inputs=inputs, results=invalid, expected_returncode=2)
    if list((invalid / "output").iterdir()) or {p.name for p in (invalid / "work").iterdir()} != {"request.json"}:
        raise ValueError("Invalid CPI request reached scientific preparation or R.")
    for label, frequencies in (("out of range", "1.1\t0.5"), ("nonfinite", "NaN\t0.5"),
                               ("duplicate loci", "0.5\t0.5\nchr1\t100\t101\t0.5\t0.5")):
        (inputs / "invalid-population.tsv").write_text(
            "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t100\t101\t" + frequencies + "\n",
            encoding="utf-8")
        rejected = root / f"rejected CPI {label}"
        write_request(rejected, {**base, "cutoff_mode": "all", "cutoffs": [],
                                 "popfreq": "/inputs/invalid-population.tsv"})
        run_image(identifier, ["execute", "cpi", "--request", "/results/work/request.json"],
                  inputs=inputs, results=rejected, expected_returncode=2)
        if list((rejected / "output").iterdir()) or {p.name for p in (rejected / "work").iterdir()} != {"request.json"}:
            raise ValueError(f"Invalid CPI {label} reached scientific preparation or R.")
    (inputs / "invalid-population.tsv").unlink()
    assert_originals(originals)
    print("PASS: complete CPI ALL/single/named panels, native R parity, independent numeric values, "
          "no-sites cases, PDFs and invalid-selection/frequency rejection.", flush=True)
    return inputs


def check_cpi_client_without_host_scripts(identifier: str, root: Path, inputs: Path) -> None:
    project = root / "CPI client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "CPI client data", root / "CPI client results",
                           project / "compose.yaml")
    originals_dir = root / "CPI originals with spaces $ ,= è"
    shutil.copytree(inputs, originals_dir)
    custom = originals_dir / "custom prefixes"
    custom.mkdir()
    for name in SAMPLE_NAMES:
        target = name.replace("Mother", "--Maternal ").replace("Father", "Paternal è ")
        shutil.copyfile(originals_dir / "samples" / name, custom / target)
    # Native maps split on commas. A labelled path can contain '=' because the
    # client splits once and remaps it; the bare entry is also used as its label.
    native_panels = root / "native CPI map panels"
    native_panels.mkdir()
    for source, name in (("full.txt", "full.txt"), ("first-two.tsv", "first=two.tsv")):
        shutil.copyfile(inputs / source, native_panels / name)
    originals = {path: path.read_bytes() for directory in (originals_dir, native_panels)
                 for path in directory.rglob("*") if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        workflow = Workflows(layout, DockerComposeRunner(layout))
        arguments = {
            "input_dir": originals_dir / "samples", "pairs": "Informative: Informative, NoSites :NoSites",
            "mother_prefix": "Mother", "father_prefix": "Father",
            "popfreq": originals_dir / "population.tsv", "err_const": DEFAULT_ERR_CONST,
        }
        all_sites = workflow.cpi(**arguments, run_name="complete-cpi-all")
        single = workflow.cpi(**arguments, panel=originals_dir / "full.txt", run_name="complete-cpi-panel")
        named = workflow.cpi(
            **{**arguments, "input_dir": custom, "mother_prefix": "--Maternal ", "father_prefix": "Paternal è "},
            cutoffs=[("Full", originals_dir / "full.txt"), ("FirstTwo", originals_dir / "first-two.tsv")],
            run_name="complete-cpi-named",
        )
        native_map = workflow.cpi(
            **arguments, cutoff_map=f"FirstTwo={native_panels / 'first=two.tsv'},{native_panels / 'full.txt'}",
            run_name="complete-cpi-native-map",
        )
    standard_samples = {name: originals_dir / "samples" / name for name in SAMPLE_NAMES}
    custom_samples = {name.replace("Mother", "--Maternal ").replace("Father", "Paternal è "): path
                      for name, path in standard_samples.items()}
    for run, expected, samples, panels in (
        (all_sites, {None: EXPECTED_INFORMATIVE}, standard_samples, {}),
        (single, {str(layout.container_path(single / "work/DNPpanel.txt")): EXPECTED_INFORMATIVE},
         standard_samples, {"DNPpanel.txt": (100, 200, 300, 400)}),
        (named, {"Full": EXPECTED_INFORMATIVE, "FirstTwo": EXPECTED_FIRST_TWO}, custom_samples,
         {"cutoff_001.tsv": (100, 200, 300, 400), "cutoff_002.tsv": (100, 200)}),
        (native_map, {"FirstTwo": EXPECTED_FIRST_TWO, str(native_panels / "full.txt"): EXPECTED_INFORMATIVE},
         standard_samples, {"cutoff_001.tsv": (100, 200), "cutoff_002.tsv": (100, 200, 300, 400)}),
    ):
        check_summary(run, standard_expected(expected))
        check_staging(run, samples, panels)
        check_bundled_run(run, layout, workflow="cpi")
    assert_originals(originals)
    check_cpi_error_constant(identifier, root, workflow, layout)
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("The CPI source-free application directory was unexpectedly populated.")
    print("PASS: CLI CPI ALL/panel/repeated-cutoff/native-map modes without host scientific sources; "
          "custom/empty prefixes, reused samples, parameter-sensitive results and isolated mounts.", flush=True)


def mismatch_expected(error: str, pairs: tuple[str, ...]) -> dict:
    with (ERROR_FIXTURE / "expected.tsv").open(encoding="utf-8", newline="") as handle:
        matching = [row for row in csv.DictReader(handle, delimiter="\t") if row["err_const"] == error]
    if len(matching) != 1:
        raise ValueError(f"Missing unique mismatch oracle for err_const={error}.")
    values = {key: value for key, value in matching[0].items() if key != "err_const"}
    return {(pair, None): values for pair in pairs}


def check_cpi_error_constant(identifier: str, root: Path, workflow: Workflows, layout: ProjectLayout) -> None:
    inputs = root / "CPI mismatch originals"
    inputs.mkdir()
    for source, name in (("MotherM.txt", "M.txt"), ("FatherP.txt", "P.txt"), ("FatherP.txt", "Q.txt"),
                         ("popfreq.tsv", "population.tsv")):
        shutil.copyfile(ERROR_FIXTURE / source, inputs / name)
    originals = {path: path.read_bytes() for path in inputs.iterdir()}
    expected_pairs = ("MotherM-FatherP_DNPs", "MotherM-FatherQ_DNPs")
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        for error in ("0.01", "0.1", "0"):
            run = workflow.cpi(
                input_dir=inputs, pairs="M:P,M:Q", mother_prefix="", father_prefix="",
                popfreq=inputs / "population.tsv", err_const=float(error),
                run_name="complete-cpi-error-" + error.replace(".", "-"),
            )
            check_summary(run, mismatch_expected(error, expected_pairs))
            check_staging(run, {name: inputs / name for name in ("M.txt", "P.txt", "Q.txt")}, {})
            check_bundled_run(run, layout, workflow="cpi")
            record = json.loads((run / "run.json").read_text(encoding="utf-8"))
            if (record["parameters"]["err_const"] != float(error)
                    or record["parameters"]["mother_prefix"] != ""
                    or record["parameters"]["father_prefix"] != ""):
                raise ValueError("CPI did not record the selected error constant and empty prefixes.")
            selected = [entry for entry in record["input_mounts"]
                        if Path(entry["host_path"]).name in ("M.txt", "P.txt", "Q.txt")]
            if len(selected) != 3:
                raise ValueError("CPI must mount each selected sample once despite reused maternal input.")
    assert_originals(originals)
    print("PASS: CPI err_const 0.01/0.1/0 gives independently predicted log10 summaries and NA handling; "
          "empty prefixes and shared mother preserve both pairs.", flush=True)
