"""Scientific output contracts shared by individual requests and workflow plans."""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path

from nipat_scientific.errors import PlanExecutionError, ValidationError
from nipat_scientific.files import (
    DNP_OUTPUT_COLUMNS, locus_key, nonnegative_integer, require_columns,
    require_dnp_input, table_rows,
)
from nipat_scientific.panels import read_dnp_list, read_snp_list


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


_CPI_COLUMNS = {
    "Pair", "N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw",
    "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI",
    "Median_logCPI", "Mean_logCPI", "CPI_medianFF",
}
_SNP_COLUMNS = {
    "chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count", "ratio",
    "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
    "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts",
}


def _artifact(path: Path, root: Path, output_dir: Path) -> dict:
    resolved_output = output_dir.resolve()
    if (path.is_symlink() or not path.is_file() or not resolved_output.is_relative_to(root.resolve())
            or not path.resolve().is_relative_to(resolved_output)):
        raise PlanExecutionError("execution.output", f"Expected output is missing or outside its directory: {path.name}")
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _output_columns(path: Path, columns: set[str]) -> None:
    try:
        require_columns(path, columns, "Invalid scientific result")
    except ValidationError as exc:
        raise PlanExecutionError("execution.output", str(exc)) from exc


def _cpi_bindings(step: dict) -> tuple[list[dict], list[dict]]:
    """Assign controlled aliases by typed identity, never by biological guesswork."""
    aliases = {}
    inputs, pairs = [], []
    for pair in step["inputs"]["pairs"]:
        names = {}
        for role, prefix in (("mother", "Mother"), ("father", "Father")):
            reference = pair[role]
            key = (reference.get("step"), reference["sample"])
            if key not in aliases:
                native = f"s{len(aliases) + 1:04d}"
                aliases[key] = native
                inputs.append({"source": reference.copy(), "name": f"{prefix}{native}.txt"})
            names[role] = aliases[key]
        pairs.append({
            "pair": pair["id"], "mother": pair["mother"].copy(), "father": pair["father"].copy(),
            "native_pair": f"Mother{names['mother']}-Father{names['father']}_DNPs",
            "native_selection": f"{names['mother']}:{names['father']}",
        })
    return inputs, pairs


def _pdf_artifact(path: Path, root: Path, output_dir: Path) -> dict:
    artifact = _artifact(path, root, output_dir)
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-" or path.stat().st_size <= 5:
            raise PlanExecutionError("execution.output", f"Invalid scientific PDF: {path.name}")
    return artifact


def _collect_snp_auxiliary(output_dir: Path, root: Path, genotypes: dict) -> dict:
    """Require the complete SNPcall 2.0 result, including native summaries."""
    summary = output_dir / "summary"
    table = summary / "SNPcall_AllGenotypes.txt"
    genotype_artifact = _artifact(table, root, output_dir)
    actual = {}
    for number, row in table_rows(table, {"chr", "pos", "REF", "ALT", "GT_sample_0001"}, "SNP genotypes"):
        key = (row["chr"], nonnegative_integer(row["pos"], table, number, "pos", positive=True))
        if key in actual:
            raise PlanExecutionError("execution.output", "SNP genotype summary contains duplicate loci.")
        actual[key] = (row["REF"], row["ALT"], row["GT_sample_0001"])
    if actual != genotypes:
        raise PlanExecutionError("execution.output", "SNP genotype summary differs from its sample result.")
    resource_path = summary / "resources.tsv"
    resource_artifact = _artifact(resource_path, root, output_dir)
    resources = list(table_rows(resource_path, {"sample", "seconds", "resident_MB_start", "resident_MB_end"},
                                "SNP resources"))
    if len(resources) != 1 or resources[0][1]["sample"] != "sample_0001":
        raise PlanExecutionError("execution.output", "SNP resource summary must contain the native sample exactly once.")
    _, resource = resources[0]
    for column in ("seconds", "resident_MB_start", "resident_MB_end"):
        raw = resource[column]
        if raw == "NA" and column != "seconds":
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise PlanExecutionError("execution.output", f"Invalid SNP resource value: {column}") from exc
        if not math.isfinite(value) or value < 0:
            raise PlanExecutionError("execution.output", f"Invalid SNP resource value: {column}")
    plots = [_pdf_artifact(output_dir / "plots" / "sample_0001" / f"sample_0001_{name}.pdf", root, output_dir)
             for name in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count")]
    plots.append(_pdf_artifact(summary / "Unassigned_genotypes.pdf", root, output_dir))
    return {"genotypes": genotype_artifact, "resources": resource_artifact, "plots": plots}


def _collect_cpi_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    summary = output_dir / "Summary_FetalFraction_CPI.csv"
    artifact = _artifact(summary, root, output_dir)
    mode = request["cutoff_mode"]
    with summary.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames or []
        required = _CPI_COLUMNS | ({"Cutoff"} if mode != "all" else set())
        if (not required.issubset(columns) or len(columns) != len(set(columns))
                or (mode == "all" and "Cutoff" in columns)):
            raise PlanExecutionError("execution.output", "CPI summary columns do not match the requested cutoff mode.")
        rows = list(reader)
    if "native_bindings" in step:
        bindings = step["native_bindings"]
    else:
        _, bindings = _cpi_bindings(step)
    cutoffs = ([None] if mode == "all" else [str(Path(request["work_dir"]) / "DNPpanel.txt")]
               if mode == "panel" else [panel["label"] for panel in request["cutoffs"]])
    expected = {(pair["native_pair"], cutoff) for pair in bindings for cutoff in cutoffs}
    found = {}
    warnings = []
    for number, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise PlanExecutionError("execution.output", "Malformed CPI summary row.")
        key = (row["Pair"], row.get("Cutoff"))
        if key in found:
            raise PlanExecutionError("execution.output", "CPI summary contains duplicate pair/cutoff rows.")
        found[key] = number
        counts = [nonnegative_integer(row[column], summary, number + 1, column)
                  for column in ("N_sites_mother", "N_sites_father")]
        warnings.extend(_numeric_warnings(row, _CPI_COLUMNS - {"Pair", "N_sites_mother", "N_sites_father"},
                                         summary, number + 1, allow_missing=0 in counts))
    if set(found) != expected:
        raise PlanExecutionError("execution.output", "CPI summary does not match the declared pairs and cutoffs.")
    plots = output_dir / "plots"
    expected_plots = {"All_CPIplots.pdf", *(f"{pair['native_pair']}_CPIplot.pdf" for pair in bindings)}
    if {path.name for path in plots.glob("*.pdf")} != expected_plots:
        raise PlanExecutionError("execution.output", "CPI plots do not match the declared pair identities.")
    pairs = []
    for pair in bindings:
        pairs.append({
            "pair": pair["pair"], "mother": pair["mother"], "father": pair["father"],
            "native_pair": pair["native_pair"],
            "summary_rows": [{"row": found[(pair["native_pair"], cutoff)], "cutoff": cutoff} for cutoff in cutoffs],
            "plot": _pdf_artifact(plots / f"{pair['native_pair']}_CPIplot.pdf", root, output_dir),
        })
    return {"summary": artifact, "cpi-pairs": pairs, "quality_warnings": warnings,
            "combined-plot": _pdf_artifact(plots / "All_CPIplots.pdf", root, output_dir)}


def _numeric_warnings(row: dict, columns: set[str], path: Path, number: int, *, allow_missing: bool) -> list[dict]:
    warnings = []
    context = {key: row[key] for key in ("chr", "pos", "pos1", "pos2", "Pair", "Cutoff", "individuo") if key in row}
    for column in sorted(columns):
        raw = row[column].strip()
        if raw == "NA" and allow_missing:
            continue
        if raw == "NA":
            warnings.append({"code": "output.missing_estimate", "file": path.name, "row": number,
                             "column": column, "value": raw, "context": context,
                             "message": "Missing scientific estimate despite informative input; inspect the R result and model conditions."})
            continue
        try:
            number_value = float(raw)
        except ValueError as exc:
            raise PlanExecutionError("execution.output", f"{path.name}: row {number}, {column} is not numeric.") from exc
        if not math.isfinite(number_value):
            warnings.append({"code": "output.nonfinite", "file": path.name, "row": number,
                             "column": column, "value": raw, "context": context,
                             "message": "Non-finite scientific result; interpretation requires domain review. The R value is unchanged."})
    return warnings


def _collect_outputs_unchecked(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    if step["workflow"] == "cpi":
        return _collect_cpi_outputs(step, request, root, output_dir)
    if step["workflow"] == "snp-call":
        path = output_dir / "SNPcall_output.txt"
        artifact = _artifact(path, root, output_dir)
        expected = {(record.chromosome, record.position): record for record in
                    read_snp_list(Path(request["panel"]))}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", strict=True)
            columns = reader.fieldnames or []
            if not _SNP_COLUMNS.issubset(columns) or len(columns) != len(set(columns)):
                raise PlanExecutionError("execution.output", "SNPcall result columns are missing or duplicated.")
            found = set()
            genotypes = {}
            warnings = []
            for number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise PlanExecutionError("execution.output", "Malformed SNPcall result row.")
                try:
                    key = row["chr"], int(row["pos"])
                except ValueError as exc:
                    raise PlanExecutionError("execution.output", "Invalid SNPcall result coordinate.") from exc
                if key in found:
                    raise PlanExecutionError("execution.output", "SNPcall result contains duplicate loci.")
                found.add(key)
                genotypes[key] = (row["REF"], row["ALT"], row["GT"])
                panel_record = expected.get(key)
                if panel_record is None or (row["REF"], row["ALT"]) != (
                        panel_record.reference, panel_record.alternative):
                    raise PlanExecutionError("execution.output", "SNPcall result alleles or loci differ from the selected panel.")
                counts = [nonnegative_integer(row[column], path, number, column)
                          for column in ("N_REF", "N_ALT", "N_Other")]
                if nonnegative_integer(row["total_count"], path, number, "total_count") != sum(counts):
                    raise PlanExecutionError("execution.output", "SNPcall total_count does not equal the read-count sum.")
                warnings.extend(_numeric_warnings(row, {"ratio"}, path, number, allow_missing=sum(counts[:2]) == 0))
                for column in ("GL0", "GL1", "GL2"):
                    if row[column] == "NA":
                        warnings.extend(_numeric_warnings(row, {column}, path, number,
                                                          allow_missing=sum(counts[:2]) == 0))
                        continue
                    try:
                        likelihood = float(row[column])
                    except ValueError as exc:
                        raise PlanExecutionError("execution.output", f"Invalid SNPcall {column}.") from exc
                    # Q=0 legitimately produces log(0) = -Inf in this model.
                    if math.isnan(likelihood) or likelihood == math.inf:
                        raise PlanExecutionError("execution.output", f"Invalid SNPcall {column}: NaN or +Inf.")
                if row["GT"] not in {"NA", "0/0", "0/1", "1/1"}:
                    raise PlanExecutionError("execution.output", "SNPcall genotype must be 0/0, 0/1, 1/1 or NA.")
                if ((not sum(counts[:2]) or counts[2] * 10 >= sum(counts)) and row["GT"] != "NA"):
                    raise PlanExecutionError("execution.output", "SNPcall genotype violates the unassigned-genotype rule.")
                if row["reads_discarded_for_indels"] != "NA":
                    nonnegative_integer(row["reads_discarded_for_indels"], path, number,
                                        "reads_discarded_for_indels")
                warnings.extend(_numeric_warnings(row, {"ratio_reads_discarded_for_indels"},
                                                  path, number, allow_missing=True))
        # R outer-joins the selected panel, retaining zero-coverage loci. A
        # header-only file is therefore incomplete for every valid panel.
        if found != set(expected):
            raise PlanExecutionError("execution.output", "SNPcall result loci do not match the selected panel.")
        preparation = []
        if request["mode"] == "bam":
            work = Path(request["work_dir"])
            preparation = [{"kind": kind, **_artifact(work / name, root, work)}
                           for kind, name in (("regions-bed", "snp_regions.bed"), ("pileup", "pileup.txt"))]
        return {"snp-tables": [{"sample": step["inputs"]["sample"], **artifact}],
                "snp-summary": _collect_snp_auxiliary(output_dir, root, genotypes),
                "preparation": preparation, "quality_warnings": warnings}
    if step["workflow"] == "dnp-call":
        directory = output_dir / "individual_outputs"
        expected = {f"full_output_sample_{number:04d}.txt" for number in range(1, len(request["samples"]) + 1)}
        actual = {path.name for path in directory.glob("full_output_*.txt")}
        if expected != actual:
            raise PlanExecutionError("execution.output", f"{step['id']}: DNP tables do not match the declared sample identities.")
        tables = []
        all_warnings = []
        expected_loci = {(row.chromosome, row.pos1, row.pos2)
                         for row in read_dnp_list(Path(request["panel"]))}
        for number, identifier in enumerate(step["inputs"]["samples"], 1):
            name = f"sample_{number:04d}"
            path = directory / f"full_output_{name}.txt"
            artifact = _artifact(path, root, output_dir)
            _output_columns(path, DNP_OUTPUT_COLUMNS)
            try:
                warnings = require_dnp_input(path)
            except ValidationError as exc:
                raise PlanExecutionError("execution.output", str(exc)) from exc
            loci = {locus_key(row, path, line) for line, row in table_rows(
                path, DNP_OUTPUT_COLUMNS, "DNPcall output", whitespace=True)}
            if loci != expected_loci:
                raise PlanExecutionError("execution.output", "DNPcall result loci do not match the selected panel.")
            all_warnings.extend({**warning, "code": warning["code"].replace("input.", "output.", 1)}
                                for warning in warnings)
            tables.append({"sample": identifier, "native_name": name, **artifact})
        return {"dnp-tables": tables, "quality_warnings": all_warnings}

    summary = output_dir / "contamination_summary.txt"
    artifact = _artifact(summary, root, output_dir)
    _output_columns(summary, {"individuo", "informative_DNPs", "mean_contamination", "sd_contamination"})
    rows = [row for _, row in table_rows(summary, {
        "individuo", "informative_DNPs", "mean_contamination", "sd_contamination",
    }, "Contamination summary")]
    expected_names = [Path(sample["name"]).stem for sample in request["samples"]]
    if sorted(row["individuo"] for row in rows) != sorted(expected_names):
        raise PlanExecutionError("execution.output", "Contamination summary does not match the selected sample identities.")
    tables = []
    warnings = []
    for number, row in enumerate(rows, 2):
        count = nonnegative_integer(row["informative_DNPs"], summary, number, "informative_DNPs")
        warnings.extend(_numeric_warnings(row, {"mean_contamination"}, summary, number, allow_missing=count == 0))
        warnings.extend(_numeric_warnings(row, {"sd_contamination"}, summary, number, allow_missing=count <= 1))
    for reference, name in zip(step["inputs"]["samples"], expected_names, strict=True):
        path = output_dir / f"contamination_{name}.txt"
        table_artifact = _artifact(path, root, output_dir)
        _output_columns(path, {"chr", "pos1", "pos2", "contamination"})
        found = set()
        for number, row in table_rows(path, {"chr", "pos1", "pos2", "contamination"}, "Contamination output"):
            key = locus_key(row, path, number)
            if key in found:
                raise PlanExecutionError("execution.output", f"{path.name}: duplicate locus at row {number}.")
            found.add(key)
            warnings.extend(_numeric_warnings(row, {"contamination"}, path, number, allow_missing=False))
        summary_row = next(row for row in rows if row["individuo"] == name)
        if len(found) != nonnegative_integer(summary_row["informative_DNPs"], summary, 0, "informative_DNPs"):
            raise PlanExecutionError("execution.output", f"{path.name}: informative site count differs from its summary.")
        tables.append({"sample": reference["sample"], "source": reference.copy(),
                       "native_name": name, **table_artifact})
    return {"summary": artifact, "contamination-tables": tables, "quality_warnings": warnings}


def _collect_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    try:
        return _collect_outputs_unchecked(step, request, root, output_dir)
    except PlanExecutionError:
        raise
    except (ValidationError, UnicodeError, csv.Error) as exc:
        raise PlanExecutionError("execution.output", str(exc)) from exc


def validate_standalone_outputs(request: dict) -> dict:
    """Apply plan output contracts to native aliases of a single request."""
    workflow = request["workflow"]
    step = {"id": "analysis", "workflow": workflow}
    if workflow == "dnp-call":
        step["inputs"] = {"samples": [sample["sample_id"] for sample in request["samples"]]}
    elif workflow == "snp-call":
        step["inputs"] = {"sample": "sample_0001"}
    elif workflow == "contamination":
        step["inputs"] = {"samples": [{"sample": Path(sample["name"]).stem}
                                      for sample in request["samples"]]}
    else:
        bindings = []
        for pair in request["pairs"].split(","):
            mother, father = [value.strip() for value in pair.split(":")]
            bindings.append({"pair": f"{mother}:{father}", "mother": {"sample": mother},
                             "father": {"sample": father},
                             "native_pair": f"Mother{mother}-Father{father}_DNPs"})
        step["native_bindings"] = bindings
    output = Path(request["out_dir"])
    root = output.parent
    return _collect_outputs(step, request, root, output)

