"""Real-image checks for the sequential DNPcall → Contamination plan executor.

Called by the scientific CI package verification. Only synthetic input files and
one output directory are mounted; the image supplies every scientific source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from verify_dnp_engine import check_dnp_outputs, compare_dnp_tables, expected_rows, keyed_rows, table


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(run: Path) -> dict:
    state = json.loads((run / "workflow-state.json").read_text(encoding="utf-8"))
    if (state.get("schema_version") != 1
            or state.get("interface") != "workflow-plan-execution-v1"):
        raise ValueError("Unexpected workflow execution report interface.")
    return state


def _artifact(run: Path, artifact: dict) -> Path:
    relative = Path(artifact["path"])
    path = (run / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError("Workflow artifact is missing or outside its run directory.")
    if artifact["sha256"] != _digest(path):
        raise ValueError("Workflow artifact hash does not identify the produced file.")
    return path


def check_workflow_execution(identifier: str, root: Path, inputs: Path, *, run_image,
                             write_request) -> None:
    """Verify actual chaining, biological table identity, failure, and no reuse."""
    plan = {
        "schema_version": 1,
        "samples": [
            {"id": "research_a", "kind": "bam", "path": "/inputs/bams/sample_0001.bam"},
            {"id": "research_b", "kind": "bam", "path": "/inputs/bams/sample_0002.bam"},
        ],
        # Consumer first and reverse sample order deliberately exercise graph
        # ordering and identity references rather than positional assumptions.
        "steps": [
            {"id": "contamination", "workflow": "contamination", "inputs": {
                "samples": [
                    {"step": "dnp", "output": "dnp-tables", "sample": "research_b"},
                    {"step": "dnp", "output": "dnp-tables", "sample": "research_a"},
                ], "panel": "/inputs/DNP_list.txt",
            }, "parameters": {}},
            {"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["research_a", "research_b"],
                "reference": "/inputs/reference.fa", "panel": "/inputs/DNP_list.txt",
            }, "parameters": {"parallel": False}},
        ],
    }
    results = root / "composed workflow results"
    (results / "work").mkdir(parents=True)
    plan_file = results / "work/plan.json"
    plan_file.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    original_inputs = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    original_plan = plan_file.read_bytes()
    arguments = ["execute-plan", "--plan", "/results/work/plan.json",
                 "--run-dir", "/results/workflow"]
    run_image(identifier, arguments, inputs=inputs, results=results)
    run = results / "workflow"
    state = _state(run)
    if (state.get("status") != "succeeded" or state.get("exit_code") != 0
            or state.get("execution_order") != ["dnp", "contamination"]):
        raise ValueError(f"Unexpected composed workflow status: {state}.")
    if state.get("plan_sha256") != _digest(run / "plan.json"):
        raise ValueError("Workflow report does not identify the exact canonical plan.")
    steps = {step["id"]: step for step in state["steps"]}
    if set(steps) != {"dnp", "contamination"} or any(
        step.get("status") != "succeeded" or step.get("exit_code") != 0
        for step in steps.values()
    ):
        raise ValueError("A composed scientific step did not succeed.")
    for step in steps.values():
        if (not step.get("started_utc") or not step.get("finished_utc")
                or not (run / step["log"]).is_file() or not (run / step["request"]).is_file()):
            raise ValueError("A composed step lacks execution or request evidence.")
    dnp_run = run / "steps/dnp"
    check_dnp_outputs(dnp_run, ("A", "B"))
    compare_dnp_tables(root / "complete DNP results", dnp_run)
    dnp_artifacts = {item["sample"]: item for item in steps["dnp"]["artifacts"]["dnp-tables"]}
    if set(dnp_artifacts) != {"research_a", "research_b"}:
        raise ValueError("DNP output identity mapping lost a plan sample.")
    for sample, alias in (("research_a", "sample_0001"), ("research_b", "sample_0002")):
        path = _artifact(run, dnp_artifacts[sample])
        expected = dnp_run / f"output/individual_outputs/full_output_{alias}.txt"
        if path != expected.resolve():
            raise ValueError("DNP output was assigned to the wrong plan sample.")

    contamination_artifacts = steps["contamination"]["artifacts"]
    summary = table(_artifact(run, contamination_artifacts["summary"]))
    if len(summary) != 2:
        raise ValueError("Expected two Contamination summaries.")
    for row in summary:
        if (int(row["informative_DNPs"]) != 2 or float(row["mean_contamination"]) != 0
                or float(row["sd_contamination"]) != 0):
            raise ValueError(f"Contamination differs from the independent synthetic oracle: {row}.")
    contamination_tables = {
        item["sample"]: _artifact(run, item)
        for item in contamination_artifacts["contamination-tables"]
    }
    if set(contamination_tables) != {"research_a", "research_b"}:
        raise ValueError("Contamination output identity mapping lost a sample.")
    for sample, path in contamination_tables.items():
        rows = keyed_rows(path)
        if set(rows) != {("chrDnpSynthetic", "50", "51"), ("chrDnpSynthetic", "230", "231")}:
            raise ValueError("Unexpected informative loci in chained Contamination.")
        expected = expected_rows("A" if sample == "research_a" else "B")
        for key, row in rows.items():
            if any(row[field] != expected[key][field] for field in ("N_REF", "N_ALT", "N_Other")):
                raise ValueError("Chained Contamination received another sample's DNP table.")
        if any(float(row["contamination"]) != 0 for row in rows.values()):
            raise ValueError("Expected zero unexpected REF/ALT counts at retained synthetic loci.")

    # Execute Contamination separately from the same DNP output tables. Use its
    # native staging names from the recorded request, preserving sample labels.
    step_request = json.loads((run / "steps/contamination/request.json").read_text(encoding="utf-8"))
    separate = root / "separate workflow contamination"
    sources = []
    for item in step_request["samples"]:
        container_path = Path(item["path"])
        relative = container_path.relative_to("/results/workflow")
        sources.append({"path": "/inputs/" + relative.as_posix(), "name": item["name"]})
    write_request(separate, {
        "schema_version": 1, "workflow": "contamination", "samples": sources,
        # The canonical DNP panel is already inside the workflow output mount.
        "panel": "/inputs/steps/dnp/work/DNP_list.txt",
        "work_dir": "/results/work", "out_dir": "/results/output",
    })
    run_image(identifier, ["execute", "contamination", "--request", "/results/work/request.json"],
              inputs=run, results=separate)
    actual_output = run / "steps/contamination/output"
    first = {path.name: table(path) for path in actual_output.glob("*.txt")}
    second = {path.name: table(path) for path in (separate / "output").glob("*.txt")}
    if first != second:
        raise ValueError("Composed Contamination tables differ from the standalone workflow.")

    immutable = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    run_image(identifier, arguments, inputs=inputs, results=results, expected_returncode=2)
    if immutable != {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}:
        raise ValueError("Reusing a workflow run changed its existing results or evidence.")
    if plan_file.read_bytes() != original_plan or any(
        path.read_bytes() != content for path, content in original_inputs.items()
    ):
        raise ValueError("Workflow execution changed an original input or plan.")
    # A corrupt BAM is a runtime failure rather than an unavailable input.
    # DNP's real R/samtools process must fail and its consumer must never run.
    broken_inputs = root / "corrupt workflow inputs"
    shutil.copytree(inputs, broken_inputs)
    (broken_inputs / "bams/sample_0001.bam").write_bytes(b"not a BAM file\n")
    rejected = root / "failed composed workflow"
    (rejected / "work").mkdir(parents=True)
    (rejected / "work/plan.json").write_bytes(original_plan)
    run_image(identifier, arguments, inputs=broken_inputs, results=rejected, expected_returncode=1)
    failed_run = rejected / "workflow"
    failed = _state(failed_run)
    failed_steps = {step["id"]: step for step in failed["steps"]}
    if (failed.get("status") != "failed" or failed.get("exit_code") != 1
            or failed_steps["dnp"].get("status") != "failed"
            or failed_steps["contamination"].get("status") != "blocked"):
        raise ValueError("DNP runtime failure did not block the dependent Contamination step.")
    if (failed_run / "steps/contamination").exists():
        raise ValueError("A blocked downstream analysis created scientific work or results.")
    print("PASS: bundled DNPcall -> Contamination, numeric oracle, separate-call parity, "
          "sample identity, artifact hashes, immutable run reuse rejection, and real R failure isolation.", flush=True)


def _read_request(run: Path, state: dict, step_id: str) -> tuple[dict, dict]:
    record = next(step for step in state["steps"] if step["id"] == step_id)
    request = json.loads((run / record["request"]).read_text(encoding="utf-8"))
    return record, request


def _source_path(container_path: str, mappings: dict[str, Path]) -> Path:
    """Resolve only the declared synthetic mount paths or this workflow's files."""
    for prefix, host in sorted(mappings.items(), key=lambda item: len(item[0]), reverse=True):
        if container_path == prefix:
            return host
        if container_path.startswith(prefix.rstrip("/") + "/") and host.is_dir():
            path = (host / container_path[len(prefix):].lstrip("/")).resolve()
            if path.is_relative_to(host.resolve()) and path.is_file():
                return path
    raise ValueError(f"Unregistered synthetic CPI source: {container_path}.")


def _check_cpi_result(run: Path, state: dict, step_id: str, expected: dict,
                      source_mappings: dict[str, Path]) -> tuple[dict, dict]:
    from verify_cpi_engine import check_summary, summary_rows

    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    step = next(item for item in plan["steps"] if item["id"] == step_id)
    registered = {item["id"]: item for item in plan["samples"]}
    record, request = _read_request(run, state, step_id)
    if record["status"] != "succeeded" or record["exit_code"] != 0:
        raise ValueError("CPI did not complete successfully in the workflow plan.")
    artifacts = record["artifacts"]
    _artifact(run, artifacts["summary"])
    combined = _artifact(run, artifacts["combined-plot"])
    if not combined.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Invalid combined CPI PDF.")
    pairs = {item["pair"]: item for item in artifacts["cpi-pairs"]}
    if set(pairs) != {pair["id"] for pair in step["inputs"]["pairs"]}:
        raise ValueError("CPI artifact mapping lost or duplicated a declared pair.")
    wanted = {}
    single_label = str(Path(request["work_dir"]) / "DNPpanel.txt")
    for (pair_id, label), values in expected.items():
        actual_label = single_label if label == "<single-panel>" else label
        wanted[(pairs[pair_id]["native_pair"], actual_label)] = values
    step_run = run / "steps" / step_id
    check_summary(step_run, wanted)
    _, rows = summary_rows(step_run)
    covered = []
    expected_staged_names = set()
    for declared in step["inputs"]["pairs"]:
        pair = pairs[declared["id"]]
        if pair["mother"] != declared["mother"] or pair["father"] != declared["father"]:
            raise ValueError("CPI manifest changed an explicit maternal or paternal role.")
        plot = _artifact(run, pair["plot"])
        if plot.name != pair["native_pair"] + "_CPIplot.pdf" or not plot.read_bytes().startswith(b"%PDF-"):
            raise ValueError("CPI PDF was associated with a different pair.")
        for selected in pair["summary_rows"]:
            row_index = selected["row"]
            if not 1 <= row_index <= len(rows):
                raise ValueError("CPI manifest references a nonexistent summary row.")
            row = rows[row_index - 1]
            if row["Pair"] != pair["native_pair"] or row.get("Cutoff") != selected["cutoff"]:
                raise ValueError("CPI manifest row does not match its pair and cutoff.")
            covered.append(row_index)
        # R names are presentation aliases. Verify each alias still contains
        # the byte-identical table selected by the explicit biological role.
        mother_id, father_id = pair["native_pair"][len("Mother"):-len("_DNPs")].split("-Father")
        for role, native_id, prefix in (("mother", mother_id, request["mother_prefix"]),
                                        ("father", father_id, request["father_prefix"])):
            name = prefix + native_id + ".txt"
            expected_staged_names.add(name)
            native_sample = next(item for item in request["samples"] if item["name"] == name)
            selected_source = _source_path(native_sample["path"], source_mappings)
            reference = declared[role]
            if "step" in reference:
                producer = next(item for item in state["steps"] if item["id"] == reference["step"])
                source_artifact = next(item for item in producer["artifacts"]["dnp-tables"]
                                       if item["sample"] == reference["sample"])
                declared_source = _artifact(run, source_artifact)
            else:
                declared_source = _source_path(registered[reference["sample"]]["path"], source_mappings)
            if selected_source.resolve() != declared_source.resolve():
                raise ValueError("CPI native staging selected a different sample than the declared role.")
            if (step_run / "work/inputs" / name).read_bytes() != declared_source.read_bytes():
                raise ValueError("CPI staging changed the selected role's table bytes.")
    if sorted(covered) != list(range(1, len(rows) + 1)):
        raise ValueError("CPI manifest does not cover every summary row exactly once.")
    if {p.name for p in (step_run / "work/inputs").iterdir()} != expected_staged_names:
        raise ValueError("CPI staged extra inputs or copied a shared parent more than once.")
    return record, request


def _compare_standalone_cpi(identifier: str, root: Path, label: str, run: Path, state: dict,
                            source_mappings: dict[str, Path], *, run_image, write_request) -> None:
    from verify_cpi_engine import summary_rows

    _, request = _read_request(run, state, "cpi")
    inputs = root / f"standalone CPI inputs {label}"
    inputs.mkdir()
    samples = []
    for number, item in enumerate(request["samples"], 1):
        name = f"sample_{number:04d}.txt"
        shutil.copyfile(_source_path(item["path"], source_mappings), inputs / name)
        samples.append({"path": f"/inputs/{name}", "name": item["name"]})
    shutil.copyfile(_source_path(request["popfreq"], source_mappings), inputs / "population.tsv")
    cutoffs = []
    for number, item in enumerate(request["cutoffs"], 1):
        name = f"panel_{number:04d}.tsv"
        shutil.copyfile(_source_path(item["path"], source_mappings), inputs / name)
        cutoffs.append({"path": f"/inputs/{name}", "label": item["label"]})
    separate = root / f"standalone CPI results {label}"
    write_request(separate, {**request, "samples": samples, "popfreq": "/inputs/population.tsv",
                            "cutoffs": cutoffs, "work_dir": "/results/work", "out_dir": "/results/output"})
    run_image(identifier, ["execute", "cpi", "--request", "/results/work/request.json"],
              inputs=inputs, results=separate)
    fields, actual = summary_rows(run / "steps/cpi")
    separate_fields, standalone = summary_rows(separate)
    # A single-panel label is its generated native path. Only that provenance
    # field changes with the run directory; compare every scientific CSV value.
    if request["cutoff_mode"] == "panel":
        for row in actual:
            if row["Cutoff"] != str(Path(request["work_dir"]) / "DNPpanel.txt"):
                raise ValueError("Unexpected native single-panel label in composed CPI.")
            row["Cutoff"] = "<single-panel>"
        for row in standalone:
            if row["Cutoff"] != "/results/work/DNPpanel.txt":
                raise ValueError("Unexpected native single-panel label in standalone CPI.")
            row["Cutoff"] = "<single-panel>"
    if fields != separate_fields or actual != standalone:
        raise ValueError("Composed CPI CSV differs from its standalone execution.")
    composed_pdfs = {path.name for path in (run / "steps/cpi/output/plots").glob("*.pdf")}
    separate_pdfs = {path.name for path in (separate / "output/plots").glob("*.pdf")}
    if composed_pdfs != separate_pdfs or any(not path.read_bytes().startswith(b"%PDF-")
                                           for path in (separate / "output/plots").glob("*.pdf")):
        raise ValueError("Standalone and composed CPI PDF names/signatures differ.")


def check_imported_cpi_plans(identifier: str, root: Path, *, run_image, write_request) -> None:
    """Positive numeric oracles, all cutoff modes and shared-parent identity."""
    from verify_cpi_engine import FIXTURE, ERROR_FIXTURE, NO_SITES, mismatch_expected
    from verify_cpi_update import EXPECTED_INFORMATIVE
    from verify_input_modes import EXPECTED_FIRST_TWO

    inputs = root / "workflow CPI original inputs"
    inputs.mkdir()
    sources = {
        "maternal": "MotherInformative.txt", "paternal": "FatherInformative.txt",
        "paternal_two": "FatherInformative.txt", "no_maternal": "MotherNoSites.txt",
        "no_paternal": "FatherNoSites.txt",
    }
    for sample, filename in sources.items():
        shutil.copyfile(FIXTURE / "samples" / filename, inputs / f"{sample}.txt")
    shutil.copyfile(FIXTURE / "pop_allFreq.txt", inputs / "population.tsv")
    shutil.copyfile(FIXTURE / "DNP_list.txt", inputs / "full.txt")
    (inputs / "first-two.tsv").write_text("chr\tpos1\tpos2\nchr1\t100\t101\nchr1\t200\t201\n", encoding="utf-8")
    pairs = [
        {"id": "family_a", "mother": {"sample": "maternal"}, "father": {"sample": "paternal"}},
        {"id": "family_b", "mother": {"sample": "maternal"}, "father": {"sample": "paternal_two"}},
        {"id": "no_sites", "mother": {"sample": "no_maternal"}, "father": {"sample": "no_paternal"}},
    ]
    samples = [{"id": sample, "kind": "dnp-table", "path": f"/inputs/{sample}.txt"} for sample in sources]
    originals = {path: path.read_bytes() for path in inputs.iterdir()}
    for mode, cutoffs, labels in (
        ("all", [], {None: EXPECTED_INFORMATIVE}),
        ("panel", [{"label": "", "path": "/inputs/full.txt"}], {"<single-panel>": EXPECTED_INFORMATIVE}),
        ("named", [{"label": "Full", "path": "/inputs/full.txt"},
                   {"label": "FirstTwo", "path": "/inputs/first-two.tsv"}],
         {"Full": EXPECTED_INFORMATIVE, "FirstTwo": EXPECTED_FIRST_TWO}),
    ):
        plan = {"schema_version": 1, "samples": samples, "steps": [{
            "id": "cpi", "workflow": "cpi", "inputs": {"pairs": pairs,
                "popfreq": "/inputs/population.tsv", "cutoffs": cutoffs},
            "parameters": {"cutoff_mode": mode, "err_const": 0.0000892303778101497},
        }]}
        results = root / f"workflow imported CPI {mode}"
        (results / "work").mkdir(parents=True)
        (results / "work/plan.json").write_text(json.dumps(plan), encoding="utf-8")
        run_image(identifier, ["execute-plan", "--plan", "/results/work/plan.json",
                              "--run-dir", "/results/workflow"], inputs=inputs, results=results)
        run = results / "workflow"
        state = _state(run)
        if state["status"] != "succeeded" or state["execution_order"] != ["cpi"]:
            raise ValueError("Imported CPI plan did not complete its only scientific step.")
        expected = {(pair["id"], label): NO_SITES if pair["id"] == "no_sites" else values
                    for pair in pairs for label, values in labels.items()}
        mappings = {"/inputs": inputs, "/results/workflow": run}
        _check_cpi_result(run, state, "cpi", expected, mappings)
        _compare_standalone_cpi(identifier, root, f"imported-{mode}", run, state, mappings,
                                run_image=run_image, write_request=write_request)
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("CPI workflow modified an original table or panel.")

    # A distinct error-constant fixture exercises the parameter-sensitive PI
    # branch. Expected values are independently derived in its committed README.
    mismatch = root / "workflow CPI mismatch inputs"
    mismatch.mkdir()
    for name, source in (("maternal.txt", "MotherM.txt"), ("paternal.txt", "FatherP.txt"),
                         ("paternal_two.txt", "FatherP.txt"), ("population.tsv", "popfreq.tsv")):
        shutil.copyfile(ERROR_FIXTURE / source, mismatch / name)
    mismatch_pairs = pairs[:2]
    plan = {"schema_version": 1, "samples": samples[:3], "steps": [{
        "id": "cpi", "workflow": "cpi", "inputs": {"pairs": mismatch_pairs,
            "popfreq": "/inputs/population.tsv", "cutoffs": []},
        "parameters": {"cutoff_mode": "all", "err_const": 0.1},
    }]}
    results = root / "workflow CPI error constant"
    (results / "work").mkdir(parents=True)
    (results / "work/plan.json").write_text(json.dumps(plan), encoding="utf-8")
    run_image(identifier, ["execute-plan", "--plan", "/results/work/plan.json",
                          "--run-dir", "/results/workflow"], inputs=mismatch, results=results)
    run = results / "workflow"
    state = _state(run)
    values = next(iter(mismatch_expected("0.1", ("unused",)).values()))
    mappings = {"/inputs": mismatch, "/results/workflow": run}
    _check_cpi_result(run, state, "cpi", {(pair["id"], None): values for pair in mismatch_pairs}, mappings)
    _compare_standalone_cpi(identifier, root, "error-constant", run, state, mappings,
                            run_image=run_image, write_request=write_request)
    print("PASS: bundled CPI plans, positive independent numeric oracles, ALL/single/named panels, "
          "shared maternal input, multiple pair identities, error constant, PDFs and standalone CSV parity.", flush=True)


def _positive_cpi_bams(identifier: str, root: Path, *, run_container) -> Path:
    """Generate independent synthetic read counts, using reviewed sequence contexts.

    The committed fixture recipe documents 96/4 maternal and 50/50 paternal
    dinucleotides, not values extracted from a run of R. The original 62M/Q40
    templates ensure all other sequencing features match the established fixture.
    """
    from verify_dnp_engine import FIXTURE

    source = root / "positive CPI synthetic SAMs"
    source.mkdir()
    headers = []
    templates = {}
    loci = {20: ("AC", "GT"), 110: ("TA", "CG"), 200: ("GC", "AT")}
    for sample in ("A", "B"):
        for line in (FIXTURE / f"reads_{sample}.sam").read_text(encoding="utf-8").splitlines():
            if line.startswith("@"):
                if sample == "A":
                    headers.append(line)
                continue
            fields = line.split("\t")
            position = int(fields[3])
            if position in loci and fields[5] == "62M" and len(fields[9]) == 62:
                allele = fields[9][30:32]
                if allele in loci[position]:
                    templates.setdefault((position, allele), fields)
    if set(templates) != {(position, allele) for position, alleles in loci.items() for allele in alleles}:
        raise ValueError("Missing reviewed synthetic REF/ALT SAM template.")
    for role, counts in (("maternal", (96, 4)), ("paternal", (50, 50))):
        lines = headers.copy()
        for position, alleles in loci.items():
            for allele, count in zip(alleles, counts, strict=True):
                for number in range(count):
                    fields = templates[(position, allele)].copy()
                    fields[0] = f"cpi_{role}_{position}_{allele}_{number:03d}"
                    # Sequence is already in alignment orientation; alternation
                    # exercises both strands without changing the chosen bases.
                    fields[1] = "16" if number % 2 else "0"
                    fields[10] = "I" * 62
                    lines.append("\t".join(fields))
        (source / f"{role}.sam").write_text("\n".join(lines) + "\n", encoding="utf-8")
    generated = root / "positive CPI generated assets"
    inputs = generated / "work"
    inputs.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "reference.fa", inputs / "reference.fa")
    shutil.copyfile(FIXTURE / "DNP_list.txt", inputs / "DNP_list.txt")
    for role in ("maternal", "paternal"):
        run_container(identifier, ["samtools", "view", "-b", "-o", f"/results/work/{role}.bam",
                                   f"/inputs/{role}.sam"], inputs=source, results=generated)
    run_container(identifier, ["samtools", "faidx", "/results/work/reference.fa"], results=generated)
    return inputs


def check_cpi_chains(identifier: str, root: Path, dnp_inputs: Path, *, run_image,
                     run_container, write_request) -> None:
    """Exercise public CLI presets with an installed-client layout and real R."""
    import os
    from unittest.mock import patch
    from nipat.execution.runner import DockerComposeRunner
    from nipat.execution.workflows import Workflows
    from nipat.paths import ProjectLayout
    from verify_cpi_engine import NO_SITES

    project = root / "workflow client without scientific sources"
    project.mkdir()
    checkout = Path(__file__).resolve().parents[1]
    shutil.copyfile(checkout / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "workflow client data", root / "workflow client results",
                           project / "compose.yaml")
    positive = _positive_cpi_bams(identifier, root, run_container=run_container)
    metadata = root / "workflow CPI population and panels"
    metadata.mkdir()
    population = metadata / "population.tsv"
    population.write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" + "".join(
        f"chrDnpSynthetic\t{position}\t{position + 1}\t0.75\t0.25\n" for position in (50, 140, 230)
    ), encoding="utf-8")
    first = metadata / "first.tsv"
    first.write_text("chr\tpos1\tpos2\nchrDnpSynthetic\t50\t51\n", encoding="utf-8")
    originals = {path: path.read_bytes() for directory in (dnp_inputs, positive, metadata)
                 for path in directory.rglob("*") if path.is_file()}
    full_values = {
        "N_sites_mother": 3, "N_sites_father": 3,
        "Median_fetal_fraction_raw": 0.08, "Median_fetal_fraction_percent": 8,
        "Max_logCPI": 0.903, "Min_logCPI": 0.903, "Median_logCPI": 0.903,
        "Mean_logCPI": 0.903, "CPI_medianFF": 0.903,
    }
    one_values = {**full_values, "N_sites_mother": 1, "N_sites_father": 1,
                  **{key: 0.301 for key in ("Max_logCPI", "Min_logCPI", "Median_logCPI", "Mean_logCPI", "CPI_medianFF")}}
    for full_chain in (False, True):
        source = positive if full_chain else dnp_inputs
        maternal = source / "maternal.bam" if full_chain else source / "bams/sample_0001.bam"
        paternal = source / "paternal.bam" if full_chain else source / "bams/sample_0002.bam"
        label = "positive-full-chain" if full_chain else "no-sites-dnp-cpi"
        with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
            parent = Workflows(layout, DockerComposeRunner(layout)).dnp_cpi(
                pairs=[("family_a", maternal, paternal)], reference=source / "reference.fa",
                panel=source / "DNP_list.txt", popfreq=population, include_contamination=full_chain,
                cutoffs=[("Full", source / "DNP_list.txt"), ("First", first)] if full_chain else None,
                run_name=label,
            )
        run = parent / "output/workflow"
        state = _state(run)
        expected_order = ["dnp", "contamination", "cpi"] if full_chain else ["dnp", "cpi"]
        if state["status"] != "succeeded" or state["execution_order"] != expected_order:
            raise ValueError("The public composed workflow did not run its expected steps exactly once.")
        record = json.loads((parent / "run.json").read_text(encoding="utf-8"))
        if (record["status"] != "succeeded" or len(record["commands"]) != 1
                or "execute-plan" not in record["commands"][0]["argv"]
                or "cpi" not in record["runtime"]["engine"]["plan_execution"]["workflows"]):
            raise ValueError("The public client did not record a single bundled workflow plan execution.")
        mappings = {entry["container_path"]: Path(entry["host_path"]) for entry in record["input_mounts"]}
        mappings[str(layout.container_path(run))] = run
        expected = ({("family_a", "Full"): full_values, ("family_a", "First"): one_values}
                    if full_chain else {("family_a", None): NO_SITES})
        _check_cpi_result(run, state, "cpi", expected, mappings)
        _compare_standalone_cpi(identifier, root, label, run, state, mappings,
                                run_image=run_image, write_request=write_request)
        if not full_chain:
            check_dnp_outputs(run / "steps/dnp", ("A", "B"))
            compare_dnp_tables(root / "complete DNP results", run / "steps/dnp")
        else:
            for number, expected_counts in ((1, (96, 4)), (2, (50, 50))):
                rows = keyed_rows(run / f"steps/dnp/output/individual_outputs/full_output_sample_{number:04d}.txt")
                if set(rows) != {("chrDnpSynthetic", str(pos), str(pos + 1)) for pos in (50, 140, 230)}:
                    raise ValueError("Positive CPI BAMs lost an expected DNP locus.")
                for row in rows.values():
                    if (int(row["N_REF"]), int(row["N_ALT"]), int(row["N_Other"]), int(row["total_count"])) != (*expected_counts, 0, 100):
                        raise ValueError("Positive CPI BAM counts differ from the synthetic read design.")
            contamination, _ = _read_request(run, state, "contamination")
            summary = {row["individuo"]: row for row in table(_artifact(run, contamination["artifacts"]["summary"]))}
            mapped = {item["sample"]: item for item in contamination["artifacts"]["contamination-tables"]}
            maternal_row = summary[mapped["sample_0001"]["native_name"]]
            paternal_row = summary[mapped["sample_0002"]["native_name"]]
            if (maternal_row["informative_DNPs"] != "3" or float(maternal_row["mean_contamination"]) != 0.04
                    or float(maternal_row["sd_contamination"]) != 0 or paternal_row["informative_DNPs"] != "0"
                    or paternal_row["mean_contamination"] != "NA" or paternal_row["sd_contamination"] != "NA"):
                raise ValueError("Positive full-chain Contamination differs from the synthetic oracle.")
            # CPI must consume original DNP tables, not Contamination's filtered
            # subset (the heterozygous father has no retained contamination loci).
            cpi_plan = next(step for step in json.loads((run / "plan.json").read_text())["steps"] if step["id"] == "cpi")
            if any(reference["step"] != "dnp" for pair in cpi_plan["inputs"]["pairs"]
                   for reference in (pair["mother"], pair["father"])):
                raise ValueError("CPI inputs were incorrectly routed through Contamination outputs.")
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("A composed workflow changed its original BAM, reference, panel or population table.")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("The source-free client directory was populated with scientific sources.")
    print("PASS: public DNPcall -> CPI and DNPcall -> Contamination + CPI presets; actual BAMs, "
          "positive 8% fetal fraction/log10 CPI 0.903 oracle, no-sites case, named panels, original DNP routing, "
          "one container call, independent step state and standalone CSV parity without host scientific sources.", flush=True)
