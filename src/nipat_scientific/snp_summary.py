"""Aggregate compatible SNPcall 2.0 samples without mixing scientific panels."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Callable

from nipat_scientific.errors import PlanExecutionError
from nipat_scientific.outputs import _artifact
from nipat_scientific.presentation import _unique_labels


RESOURCE_COLUMNS = ("sample", "seconds", "resident_MB_start", "resident_MB_end")


def _read_table(path: Path, required: set[str]) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", strict=True)
        columns = reader.fieldnames or []
        rows = list(reader)
    if (not required.issubset(columns) or len(columns) != len(set(columns))
            or any(None in row or any(value is None for value in row.values()) for row in rows)):
        raise PlanExecutionError("execution.output", f"Malformed SNP summary input: {path.name}")
    return columns, rows


def _write_table(path: Path, columns: list[str] | tuple[str, ...], rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def finalize_snp_summaries(
    plan: dict, state: dict, root: Path,
    run_process: Callable[[list[str], Path, Path], int],
) -> list[dict]:
    """Merge distinct samples only when panel, reference and input mode agree.

    Single-sample steps already contain the native SNPcall 2.0 summary. Repeated
    analyses of the same sample are partitioned instead of becoming fictitious
    additional individuals. Original tables and their order remain unchanged.
    """
    groups: list[dict] = []
    records = {record["id"]: record for record in state["steps"]}
    for step in plan["steps"]:
        if step["workflow"] != "snp-call" or records[step["id"]]["status"] != "succeeded":
            continue
        inputs = step["inputs"]
        key = (inputs["panel"], inputs["reference"], step["parameters"]["mode"])
        sample = inputs["sample"]
        group = next((item for item in groups if item["key"] == key and sample not in item["samples"]), None)
        if group is None:
            group = {"key": key, "samples": [], "steps": []}
            groups.append(group)
        group["samples"].append(sample)
        group["steps"].append(step["id"])
    groups = [group for group in groups if len(group["samples"]) >= 2]
    if not groups:
        return []
    summary_root = root / "snp_summary"
    summary_root.mkdir(exist_ok=False)
    summaries = []
    labels = _unique_labels(plan.get("presentation", {}).get("samples", {}))
    for number, group in enumerate(groups, 1):
        directory = summary_root / f"group_{number:04d}"
        directory.mkdir()
        merged = {}
        resources = []
        for sample, step_id in zip(group["samples"], group["steps"], strict=True):
            record = records[step_id]
            artifacts = record["artifacts"]["snp-tables"]
            if len(artifacts) != 1 or artifacts[0]["sample"] != sample:
                raise PlanExecutionError("execution.output", "SNP summary sample identity does not match its step.")
            source = root / artifacts[0]["path"]
            _artifact(source, root, root / "steps" / step_id / "output")
            _, rows = _read_table(source, {"chr", "pos", "REF", "ALT", "GT"})
            keyed = {(row["chr"], row["pos"], row["REF"], row["ALT"]): row for row in rows}
            if len(keyed) != len(rows) or not rows:
                raise PlanExecutionError("execution.output", "SNP summary contains duplicate or missing loci.")
            if not merged:
                merged = {key: {name: row[name] for name in ("chr", "pos", "REF", "ALT")}
                          for key, row in keyed.items()}
            if set(keyed) != set(merged):
                raise PlanExecutionError("execution.output", "SNP sample tables have different loci or alleles.")
            for key, row in keyed.items():
                merged[key][f"GT_{sample}"] = row["GT"]
            resource_path = source.parent / "summary" / "resources.tsv"
            _artifact(resource_path, root, source.parent)
            _, sample_resources = _read_table(resource_path, set(RESOURCE_COLUMNS))
            if len(sample_resources) != 1 or sample_resources[0]["sample"] != "sample_0001":
                raise PlanExecutionError("execution.output", "SNP resource row does not identify the native sample.")
            resource = {name: sample_resources[0][name] for name in RESOURCE_COLUMNS}
            for name in RESOURCE_COLUMNS[1:]:
                raw = resource[name]
                if raw == "NA" and name != "seconds":
                    continue
                try:
                    value = float(raw)
                except ValueError as exc:
                    raise PlanExecutionError("execution.output", f"Invalid SNP resource value: {name}") from exc
                if not math.isfinite(value) or value < 0:
                    raise PlanExecutionError("execution.output", f"Invalid SNP resource value: {name}")
            resource["sample"] = sample
            resources.append(resource)
        genotypes = directory / "merged_genotypes.tsv"
        _write_table(genotypes, ["chr", "pos", "REF", "ALT", *(f"GT_{sample}" for sample in group["samples"])],
                     list(merged.values()))
        resource_path = directory / "resources.tsv"
        _write_table(resource_path, RESOURCE_COLUMNS, resources)
        labels_path = directory / "sample_labels.tsv"
        _write_table(labels_path, ["internal_id", "display_name"],
                     [{"internal_id": sample, "display_name": labels.get(sample, sample)}
                      for sample in group["samples"]])
        log = directory / "plots.log"
        command = ["Rscript", str(Path(__file__).with_name("plots.R")), "--table", str(genotypes),
                   "--out", str(directory), "--labels", str(labels_path)]
        code = run_process(command, directory, log)
        if type(code) is not int or code != 0:
            raise PlanExecutionError("execution.process", f"SNP summary rendering failed (exit {code}); see {log.relative_to(root)}.")
        plots = []
        for name in ("Unassigned_genotypes.pdf", "SNPs_covered_UpSet_plot.pdf"):
            path = directory / name
            artifact = _artifact(path, root, directory)
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-" or path.stat().st_size <= 5:
                    raise PlanExecutionError("execution.output", f"Invalid SNP summary PDF: {name}")
            plots.append(artifact)
        panel, reference, mode = group["key"]
        summaries.append({
            "id": directory.name, "panel": panel, "reference": reference, "mode": mode,
            "samples": group["samples"], "steps": group["steps"],
            "genotypes": _artifact(genotypes, root, directory),
            "resources": _artifact(resource_path, root, directory),
            "sample_labels": _artifact(labels_path, root, directory), "plots": plots,
        })
    return summaries
