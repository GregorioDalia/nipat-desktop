"""Real-image SNP plan checks with independent synthetic allele-count oracles.

Called by verify_engine_package.py. Scientific sources stay inside the image;
the public client has only compose.yaml and receives read-only original inputs.
"""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import shutil
from unittest.mock import patch

from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.files import require_snp_pileup
from nipat.validation.self_test import compare_snp_outputs
from verify_dnp_engine import check_dnp_outputs, compare_dnp_tables
from verify_workflow_execution import _artifact, _state


PROJECT = Path(__file__).resolve().parents[1]
SNP_FIELDS = ["chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count",
              "ratio", "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
              "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts"]


def independent_snp_row(row: tuple, *, quality: int = 40, other_base: str | None = None) -> tuple:
    """Analytical 2.0 oracle for declared synthetic, indel-free allele observations.

    This does not call the implementation under test. The SAM fixture declares
    every central base and Phred40 quality; samtools output is checked separately.
    """
    chromosome, position, ref, alt, n_ref, n_alt, n_other, total, ratio = row
    if total != n_ref + n_alt + n_other or (n_other and other_base is None):
        raise ValueError("Independent SNP oracle needs complete declared allele counts")
    error = 10 ** (-quality / 10)
    likelihoods = tuple(
        n_ref * math.log((2 - genotype) / 2 * (1 - error) + genotype / 2 * error)
        + n_alt * math.log((2 - genotype) / 2 * error + genotype / 2 * (1 - error))
        for genotype in range(3)
    )
    genotype = ("0/0", "0/1", "1/1")[max(range(3), key=likelihoods.__getitem__)]
    if not total or n_other / total >= 0.1:
        genotype = "NA"
    observations = {ref: n_ref, alt: n_alt}
    if n_other:
        observations[other_base] = n_other
    observations = {base: count for base, count in sorted(observations.items()) if count}
    return (*row, *likelihoods, genotype, 0, 0,
            "-".join(observations), "-".join(str(value) for value in observations.values()))


def _expected(path: Path, rows: list[tuple]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(SNP_FIELDS)
        for row in rows:
            # The committed SAM has T as Other at50 and G as Other at120.
            other = {("chrSynthetic", 50): "T", ("chrSynthetic", 120): "G"}.get(row[:2])
            writer.writerow(independent_snp_row(row, other_base=other))
    return path


def _client_record(parent: Path, layout: ProjectLayout) -> dict:
    record = json.loads((parent / "run.json").read_text(encoding="utf-8"))
    config = json.loads((parent / "work/engine-compose.json").read_text(encoding="utf-8"))
    service = config["services"]["scientific"]
    if (record["status"] != "succeeded" or record["source"].get("role") != "client"
            or len(record["commands"]) != 1
            or "execute-plan" not in record["commands"][0]["argv"]
            or "snp-call" not in record["runtime"]["engine"]["plan_execution"]["workflows"]):
        raise ValueError("SNP batch did not record one complete, image-owned plan invocation.")
    run_target = str(layout.container_path(parent))
    inputs = {item["container_path"] for item in record["input_mounts"]}
    scratch = [item for item in service["volumes"] if item.get("target") == "/scratch"]
    if scratch != [{"type": "volume", "target": "/scratch", "read_only": False}]:
        raise ValueError("SNP plan requires one anonymous scratch volume without a host source.")
    volumes = [item for item in service["volumes"] if item.get("target") != "/scratch"]
    if (set(config["services"]) != {"scientific"} or service.get("read_only") is not True
            or service.get("network_mode") != "none"
            or len(volumes) != len(inputs) + 1
            or {item["target"] for item in volumes} != inputs | {run_target}):
        raise ValueError("SNP plan requires isolated input/current-run mounts and no network.")
    for item in volumes:
        if (item.get("type") != "bind" or item.get("bind", {}).get("create_host_path") is not False
                or item.get("read_only", False) != (item["target"] != run_target)):
            raise ValueError("SNP plan mounted an original input writable or exposed another directory.")
    return record


def _check_snp_summary(run: Path, state: dict, tables: dict[str, Path]) -> None:
    """Require complete, correctly identified multi-sample SNP2 scientific summaries."""
    groups = state.get("snp_summary", [])
    if len(groups) != 1 or set(groups[0]["samples"]) != set(tables):
        raise ValueError("SNP2 aggregate summary lost or duplicated a selected sample")
    group = groups[0]
    with _artifact(run, group["genotypes"]).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        merged = list(reader)
        expected_columns = ["chr", "pos", "REF", "ALT", *(f"GT_{sample}" for sample in group["samples"])]
        if reader.fieldnames != expected_columns:
            raise ValueError("SNP2 merged genotype columns do not identify every original sample")
    coordinate_fields = ("chr", "pos", "REF", "ALT")
    merged_keys = [tuple(row[field] for field in coordinate_fields) for row in merged]
    for sample, source in tables.items():
        with source.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        if ([tuple(row[field] for field in coordinate_fields) for row in rows] != merged_keys
                or [row["GT"] for row in rows] != [row[f"GT_{sample}"] for row in merged]):
            raise ValueError("SNP2 aggregate genotypes changed a scientific value, locus or order")
    with _artifact(run, group["resources"]).open(encoding="utf-8", newline="") as handle:
        resources = list(csv.DictReader(handle, delimiter="\t"))
    if len(resources) != len(tables) or {row["sample"] for row in resources} != set(tables):
        raise ValueError("SNP2 resource summary does not identify every sample exactly once")
    for row in resources:
        for field in ("seconds", "resident_MB_start", "resident_MB_end"):
            if row[field] == "NA" and field != "seconds":
                continue
            value = float(row[field])
            if not math.isfinite(value) or value < 0:
                raise ValueError("SNP2 resource summary contains an invalid observation")
    with _artifact(run, group["sample_labels"]).open(encoding="utf-8", newline="") as handle:
        labels = list(csv.DictReader(handle, delimiter="\t"))
    if ({row["internal_id"] for row in labels} != set(tables)
            or len({row["display_name"] for row in labels}) != len(tables)):
        raise ValueError("SNP2 summary labels are missing or ambiguous")
    plots = [_artifact(run, artifact) for artifact in group["plots"]]
    if {path.name for path in plots} != {"Unassigned_genotypes.pdf", "SNPs_covered_UpSet_plot.pdf"}:
        raise ValueError("SNP2 aggregate summary lacks genotype-NA or UpSet plots")
    if any(not path.read_bytes().startswith(b"%PDF-") for path in plots):
        raise ValueError("SNP2 summary contains an invalid plot")


def _snp_steps(parent: Path, layout: ProjectLayout, expected: list[tuple[Path, Path]],
               *, mode: str) -> list[Path]:
    """Check original-file -> plan sample -> step -> output identity, not order alone."""
    record = _client_record(parent, layout)
    mounts = {item["container_path"]: Path(item["host_path"]).resolve()
              for item in record["input_mounts"]}
    run = parent / "output/workflow"
    state = _state(run)
    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    samples = {item["id"]: item for item in plan["samples"]}
    selected = [item for item in plan["steps"] if item["workflow"] == "snp-call"]
    if state["status"] != "succeeded" or len(selected) != len(expected):
        raise ValueError("SNP plan did not produce the expected number of successful steps.")
    expected_by_source = {source.resolve(): oracle for source, oracle in expected}
    seen = set()
    retained = []
    sample_tables = {}
    for step in selected:
        sample_id = step["inputs"]["sample"]
        source = mounts[samples[sample_id]["path"]]
        if source not in expected_by_source or source in seen:
            raise ValueError("SNP plan lost, repeated or reassigned an original sample.")
        seen.add(source)
        execution = next(item for item in state["steps"] if item["id"] == step["id"])
        if execution["status"] != "succeeded" or execution["exit_code"] != 0:
            raise ValueError("A SNP plan step is incomplete.")
        request = json.loads((run / execution["request"]).read_text(encoding="utf-8"))
        if (request["mode"] != mode or step["parameters"]["mode"] != mode
                or request["bam" if mode == "bam" else "pileup"] != samples[sample_id]["path"]):
            raise ValueError("SNP mode or input changed between plan and scientific request.")
        tables = execution["artifacts"]["snp-tables"]
        if len(tables) != 1 or tables[0]["sample"] != sample_id:
            raise ValueError("SNP output artifact lost its explicit sample identity.")
        actual = _artifact(run, tables[0])
        if actual != (run / "steps" / step["id"] / "output/SNPcall_output.txt").resolve():
            raise ValueError("SNP output is not inside its declared step.")
        compare_snp_outputs(expected_by_source[source], actual)
        sample_tables[sample_id] = actual
        if not (run / execution["log"]).is_file() or not execution.get("finished_utc"):
            raise ValueError("SNP execution evidence is incomplete.")
        preparation = execution["artifacts"]["preparation"]
        if mode == "bam":
            if (execution.get("preparation_exit_code") != 0
                    or execution.get("preparation_command", [None])[0] != "samtools"
                    or not (run / execution["preparation_log"]).is_file()
                    or {item["kind"] for item in preparation} != {"regions-bed", "pileup"}
                    or len(preparation) != 2):
                raise ValueError("SNP BAM preparation lacks its command, log or intermediates.")
            intermediate = {item["kind"]: _artifact(run, item) for item in preparation}
            require_snp_pileup(intermediate["pileup"])
            retained.append(intermediate["pileup"])
        elif preparation or "preparation_command" in execution:
            raise ValueError("An imported pileup triggered unnecessary BAM preparation.")
    if seen != set(expected_by_source):
        raise ValueError("SNP results do not cover the selected original samples.")
    _check_snp_summary(run, state, sample_tables)
    return retained


def _alternate_sample(identifier: str, root: Path, *, run_container, sample: int = 2) -> tuple[Path, Path]:
    """Remove declared REF reads or ALT+Other reads from the committed SAM."""
    if sample not in (2, 3):
        raise ValueError("Unknown independent synthetic SNP sample")
    source = root / f"SNP batch sample {sample} SAM"
    source.mkdir()
    lines = (PROJECT / "tests/fixtures/snp_engine/reads.sam").read_text(encoding="utf-8").splitlines()
    removed = ({"site50_read1", "site120_read1"} if sample == 2
               else {"site50_read5", "site120_read3", "site50_read7", "site120_read6"})
    if {line.split("\t", 1)[0] for line in lines} & removed != removed:
        raise ValueError("Synthetic SNP source does not contain the declared allele reads.")
    (source / "reads.sam").write_text("\n".join(
        line for line in lines if line.split("\t", 1)[0] not in removed
    ) + "\n", encoding="utf-8")
    generated = root / f"SNP batch sample {sample} BAM"
    run_container(identifier, ["samtools", "view", "-b", "-o", "/results/work/sample.bam",
                               "/inputs/reads.sam"], inputs=source, results=generated)
    oracle = _expected(source / "expected.tsv", [
        ("chrSynthetic", 50, "A", "G", 3, 2, 1, 6, 3 / 5),
        ("chrSynthetic", 120, "C", "T", 1, 3, 1, 5, 1 / 4),
    ] if sample == 2 else [
        ("chrSynthetic", 50, "A", "G", 4, 1, 0, 5, 4 / 5),
        ("chrSynthetic", 120, "C", "T", 2, 2, 0, 4, 2 / 4),
    ])
    return generated / "work/sample.bam", oracle


def _deep_sample(identifier: str, root: Path, *, run_container) -> tuple[Path, Path, Path]:
    """Exceed samtools' historical8000-read cap with explicit Phred40 REF reads."""
    source = root / "SNP depth9001 SAM"
    source.mkdir()
    lines = (PROJECT / "tests/fixtures/snp_engine/reads.sam").read_text(encoding="utf-8").splitlines()
    template = next(line.split("\t", 1)[1] for line in lines if line.startswith("site50_read1\t"))
    records = [line for line in lines if line.startswith("@")]
    records.extend(f"deep_{number:05d}\t{template}" for number in range(9001))
    (source / "reads.sam").write_text("\n".join(records) + "\n", encoding="utf-8")
    generated = root / "SNP depth9001 BAM"
    run_container(identifier, ["samtools", "view", "-b", "-o", "/results/work/sample.bam",
                               "/inputs/reads.sam"], inputs=source, results=generated)
    panel = source / "panel.tsv"
    panel.write_text("chr\tpos\tref\talt\nchrSynthetic\t50\tA\tG\n", encoding="utf-8")
    expected = _expected(source / "expected.tsv", [("chrSynthetic", 50, "A", "G", 9001, 0, 0, 9001, 1)])
    return generated / "work/sample.bam", panel, expected


def _failed_snp_plan(identifier: str, root: Path, inputs: Path, *, run_container) -> None:
    """Qualify serial fail-fast and bounded parallel sibling cancellation separately."""
    broken = root / "SNP plan failure inputs"
    shutil.copytree(inputs, broken)
    (broken / "invalid.bam").write_bytes(b"Deliberately invalid BAM\n")
    shutil.copyfile(broken / "sample.bam", broken / "pending.bam")
    for mode in ("serial", "auto"):
        chosen = [("a_failure", "broken", "invalid.bam"), ("b_independent", "valid", "sample.bam")]
        if mode == "auto":
            chosen.append(("z_pending", "pending", "pending.bam"))
        plan = {"schema_version": 1, "samples": [
            {"id": sample, "kind": "bam", "path": f"/inputs/{filename}"}
            for _label, sample, filename in chosen
        ], "steps": [
            {"id": label, "workflow": "snp-call", "inputs": {
                "sample": sample, "reference": "/inputs/reference.fa", "panel": "/inputs/SNPlist.tsv",
            }, "parameters": {"mode": "bam"}}
            for label, sample, _filename in chosen
        ]}
        destination = root / f"failed SNP plan {mode} results"
        (destination / "work").mkdir(parents=True)
        (destination / "work/plan.json").write_text(json.dumps(plan), encoding="utf-8")
        run_container(identifier, ["env", f"NIPAT_EXECUTION_MODE={mode}", "NIPAT_MAX_WORKERS=2",
            "python3", "/opt/nipat/engine/main.py", "execute-plan", "--plan", "/results/work/plan.json",
            "--run-dir", "/results/workflow"], inputs=broken,
            results=destination, expected_returncode=1)
        run = destination / "workflow"
        state = _state(run)
        records = {item["id"]: item for item in state["steps"]}
        failed = records["a_failure"]
        if (state["status"] != "failed" or state["exit_code"] != 1
                or failed["status"] != "failed" or failed.get("preparation_exit_code") != 1):
            raise ValueError(f"samtools failure did not preserve the {mode} SNP failure status.")
        if (run / failed["log"]).exists():
            raise ValueError("R ran after the failing sample's unsuccessful samtools preparation.")
        if not (run / failed["preparation_log"]).is_file():
            raise ValueError("Failed SNP preparation lost its samtools diagnostic log.")
        if mode == "serial":
            if records["b_independent"]["status"] != "blocked" or (run / "steps/b_independent").exists():
                raise ValueError("Serial SNP failure started a later independent sample.")
        else:
            if state.get("snp_parallel", {}).get("workers") != 2:
                raise ValueError("Parallel failure qualification did not exercise two real SNP workers.")
            if records["b_independent"]["status"] not in {"cancelled", "succeeded"}:
                raise ValueError("A started SNP sibling was neither stopped nor already complete.")
            if records["z_pending"]["status"] != "blocked" or (run / "steps/z_pending").exists():
                raise ValueError("Parallel SNP failure started a pending sample.")
            if state.get("snp_summary") or (run / "snp_summary").exists():
                raise ValueError("A failed SNP batch produced an aggregate success summary.")


def check_snp_plans(identifier: str, root: Path, inputs: Path, expected: Path,
                    dnp_inputs: Path, *, run_image, run_container,
                    check_snp_intermediates) -> None:
    project = root / "SNP plan client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "SNP plan data", root / "SNP plan runs",
                           project / "compose.yaml")
    second, second_expected = _alternate_sample(identifier, root, run_container=run_container)
    third, third_expected = _alternate_sample(identifier, root, run_container=run_container, sample=3)
    # Same basenames, reversed selection and distinct numeric results make an
    # accidental positional or basename identity swap observable.
    selected = [(third, third_expected), (second, second_expected), (inputs / "sample.bam", expected)]
    originals = {path: path.read_bytes() for directory in (inputs, dnp_inputs, second.parent, third.parent)
                 for path in directory.rglob("*") if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        workflows = Workflows(layout, DockerComposeRunner(layout))
        batch = workflows.snp_batch(bams=[source for source, _ in selected],
                                    reference=inputs / "reference.fa", panel=inputs / "SNPlist.tsv",
                                    run_name="snp-batch-bams")
        pileups = _snp_steps(batch, layout, selected, mode="bam")
        # The unchanged first sample must retain the exact independently known
        # positions/depths already checked for the standalone interface.
        check_snp_intermediates(pileups[2].parent.parent)
        reference_output = root / "complete SNP BAM results/output/SNPcall_output.txt"
        compare_snp_outputs(reference_output, pileups[2].parent.parent / "output/SNPcall_output.txt")
        old_run = {path: path.read_bytes() for path in batch.rglob("*") if path.is_file()}
        reused = workflows.snp_batch(pileups=list(reversed(pileups)), panel=inputs / "SNPlist.tsv",
                                     run_name="snp-batch-pileups")
        _snp_steps(reused, layout, list(zip(reversed(pileups), (expected, second_expected, third_expected))), mode="pileup")
        lower_panel = root / "lowercase SNP batch panel.tsv"
        with (inputs / "SNPlist.tsv").open(encoding="utf-8", newline="") as handle:
            lower_rows = list(csv.DictReader(handle, delimiter="\t"))
        with lower_panel.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["pos", "ref", "alt"], delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows({"pos": row["pos"], "ref": row["ref"].lower(), "alt": row["alt"].lower()}
                             for row in lower_rows)
        lower_original = lower_panel.read_bytes()
        normalized = workflows.snp_batch(pileups=pileups, panel=lower_panel, run_name="snp-batch-lowercase")
        _snp_steps(normalized, layout, list(zip(pileups, (third_expected, second_expected, expected))), mode="pileup")
        if lower_panel.read_bytes() != lower_original:
            raise ValueError("SNP plan normalization modified the original panel.")
        if any(path.read_bytes() != content for path, content in old_run.items()):
            raise ValueError("Reusing SNP intermediates changed a completed run.")

        deep_bam, deep_panel, deep_expected = _deep_sample(identifier, root, run_container=run_container)
        deep_run = workflows.snp_call(bam=deep_bam, reference=inputs / "reference.fa",
                                      panel=deep_panel, run_name="snp-depth9001")
        compare_snp_outputs(deep_expected, deep_run / "output/SNPcall_output.txt")
        depth_rows = [line.split("\t") for line in (deep_run / "work/pileup.txt").read_text().splitlines()]
        if [int(row[3]) for row in depth_rows] != [9001, 9001, 9001]:
            raise ValueError("SNP2 did not preserve coverage above the historical8000-read cap")

        # The first base of each DNP forms a separate SNP panel. These counts
        # follow directly from the committed artificial dinucleotides: the
        # declared Other dinucleotide has the REF first base at all three loci.
        panel = root / "SNP plan explicit first-base panel.tsv"
        panel.write_text("pos\tref\talt\nchrDnpSynthetic:50\tA\tG\n"
                         "chrDnpSynthetic:140\tT\tC\nchrDnpSynthetic:230\tG\tA\n", encoding="utf-8")
        expected_dnp = []
        for sample, counts in (("A", ((21, 0), (11, 10), (1, 20))),
                               ("B", ((1, 20), (13, 8), (21, 0)))):
            expected_dnp.append(_expected(root / f"SNP plan DNP-{sample} expected.tsv", [
                ("chrDnpSynthetic", pos, ref, alt, ref_count, alt_count, 0, 21, ref_count / 21)
                for (pos, ref, alt), (ref_count, alt_count) in zip(
                    ((50, "A", "G"), (140, "T", "C"), (230, "G", "A")), counts)
            ]))
        bams = [dnp_inputs / f"bams/sample_{number:04d}.bam" for number in (1, 2)]
        combined = workflows.dnp_contamination(bams=bams, reference=dnp_inputs / "reference.fa",
                                               panel=dnp_inputs / "DNP_list.txt", snp_panel=panel,
                                               run_name="dnp-contamination-with-snp")
        _snp_steps(combined, layout, list(zip(bams, expected_dnp)), mode="bam")
        check_dnp_outputs(combined / "output/workflow/steps/dnp", ("A", "B"))
        compare_dnp_tables(root / "complete DNP results", combined / "output/workflow/steps/dnp")
        state = _state(combined / "output/workflow")
        if state["execution_order"] != ["dnp", "contamination", "snp_0001", "snp_0002"]:
            raise ValueError("Adding independent SNP tasks changed deterministic workflow ordering.")
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("A SNP plan changed an original input.")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("SNP plan execution copied scientific sources to the client directory.")
    _failed_snp_plan(identifier, root, inputs, run_container=run_container)
    print("PASS: public SNP BAM/pileup batches and independent SNP tasks beside DNPcall -> Contamination; "
          "three distinct same-name samples, independent counts/likelihoods/genotypes, standalone parity, original sample identity, "
          "retained BED/pileup hashes, isolated single-container execution and real samtools failure isolation.", flush=True)
