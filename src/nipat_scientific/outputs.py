"""Scientific output contracts shared by individual requests and workflow plans."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from nipat_scientific.errors import PlanExecutionError, ValidationError
from nipat_scientific.files import (
    DNP_OUTPUT_COLUMNS, locus_key, nonnegative_integer, require_columns,
    require_dnp_input, table_rows, tabular_header,
)
from nipat_scientific.panels import read_dnp_list, read_snp_list
from nipat_scientific.settings import normalize_settings, validate_settings_document


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


_CPI_COLUMNS = {
    "Pair", "N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw",
    "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI",
    "Median_logCPI", "Mean_logCPI", "CPI_medianFF", "Error_constant", "Min_fetal_reads", "Marker_type",
}
_SNP_COLUMNS = {
    "chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count", "ratio",
    "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
    "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts",
}
_DNP_LOCI = {"chr", "pos1", "pos2", "REF", "ALT"}


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
            "native_pair": f"Mother{names['mother']}-Father{names['father']}_{step.get('parameters', {}).get('marker_type', 'DNP')}s",
            "native_selection": f"{names['mother']}:{names['father']}",
        })
    return inputs, pairs



def _cpin_bindings(step: dict) -> tuple[list[dict], list[dict]]:
    aliases, inputs, trios = {}, [], []
    marker = step.get("parameters", {}).get("marker_type", "DNP")
    for trio in step["inputs"]["trios"]:
        names = {}
        for role in ("mother", "father", "child"):
            ref = trio[role]
            key = (ref.get("step"), ref["sample"])
            if key not in aliases:
                native = f"s{len(aliases) + 1:04d}"
                aliases[key] = native
                inputs.append({"source": ref.copy(), "name": f"{role.title()}{native}.txt"})
            names[role] = aliases[key]
        trios.append({"trio": trio["id"], **{role: trio[role].copy() for role in names},
                      "native_trio": f"Mother{names['mother']}-Father{names['father']}-Child{names['child']}_{marker}s",
                      "native_selection": ":".join(names.values())})
    return inputs, trios


def _expected_settings(request: dict) -> dict:
    values = normalize_settings(request["workflow"], request.get("scientific_settings"))
    if request["workflow"] == "cpi" and request.get("err_const") is not None:
        values[f"err_const_{request.get('marker_type', 'DNP').lower()}"] = request["err_const"]
    return values


def _check_cpi_summary_settings(row: dict, request: dict, settings: dict, path: Path, number: int):
    marker = request.get("marker_type", "DNP")
    threshold = "Min_child_reads" if request["workflow"] == "cpin" else "Min_fetal_reads"
    if row["Marker_type"] != marker or nonnegative_integer(
            row[threshold], path, number, threshold, positive=True) != settings[threshold.lower()]:
        raise PlanExecutionError("execution.output", "CPI summary marker or read threshold differs from the request.")
    try:
        error = float(row["Error_constant"])
    except ValueError as exc:
        raise PlanExecutionError("execution.output", "Invalid CPI summary error constant.") from exc
    if not math.isclose(error, settings[f"err_const_{marker.lower()}"], rel_tol=1e-12, abs_tol=0):
        raise PlanExecutionError("execution.output", "CPI summary error constant differs from the request.")


def _collect_cpin_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    summary = output_dir / "Summary_Postnatal_CPI.txt"
    summary_artifact = _artifact(summary, root, output_dir)
    columns = {"Trio", "Marker_type", "Analysis", "N_sites", "N_heterozygous_child_sites",
               "N_homozygous_child", "Matching_sites", "Mismatching_sites", "Log10_CPI", "CPI",
               "Error_constant", "Min_child_reads"}
    rows = [row for _, row in table_rows(summary, columns, "CPIN summary")]
    bindings = step.get("native_bindings")
    if bindings is None:
        _, bindings = _cpin_bindings(step)
    selection = request.get("scientific_settings", {}).get("site_selection", "both")
    analyses = {"other_allele": ["heterozygous_child_sites"], "all": ["all_compatible_sites"],
                "both": ["heterozygous_child_sites", "all_compatible_sites"]}[selection]
    expected = {(item["native_trio"], analysis) for item in bindings for analysis in analyses}
    seen, warnings = set(), []
    settings = _expected_settings(request)
    counts = {"N_sites", "N_heterozygous_child_sites", "N_homozygous_child", "Matching_sites", "Mismatching_sites", "Min_child_reads"}
    for number, row in enumerate(rows, 2):
        _check_cpi_summary_settings(row, request, settings, summary, number)
        key = row["Trio"], row["Analysis"]
        if key in seen:
            raise PlanExecutionError("execution.output", "Duplicate CPIN trio/analysis row.")
        seen.add(key)
        values = {column: nonnegative_integer(row[column], summary, number, column) for column in counts}
        if values["Matching_sites"] + values["Mismatching_sites"] != values["N_sites"] or values["N_heterozygous_child_sites"] + values["N_homozygous_child"] != values["N_sites"]:
            raise PlanExecutionError("execution.output", "CPIN site counts disagree.")
        warnings.extend(_numeric_warnings(row, {"Log10_CPI", "CPI", "Error_constant"}, summary, number,
                                         allow_missing=values["N_sites"] == 0))
    if seen != expected:
        raise PlanExecutionError("execution.output", "CPIN results do not match requested trios and analyses.")
    trios = []
    for binding in bindings:
        name = binding["native_trio"]
        sites = output_dir / "sites" / f"{name}_sites.tsv"
        _output_columns(sites, {"Status", "Paternity_Index", "Mismatch"})
        analyses_artifacts = []
        for analysis in analyses:
            curve = output_dir / "curves" / f"{name}_{analysis}_curve.tsv"
            _output_columns(curve, {"Min_child_reads", "Through_min_child_reads", "N_sites", "Log10_CPI", "Matching_sites", "Mismatching_sites"})
            analyses_artifacts.append({"analysis": analysis, "curve": _artifact(curve, root, output_dir),
                "plot": _pdf_artifact(output_dir / "plots" / f"{name}_{analysis}_CPIplot.pdf", root, output_dir)})
        trios.append({**binding, "sites": _artifact(sites, root, output_dir), "analyses": analyses_artifacts})
    return {"summary": summary_artifact, "cpin-trios": trios, "quality_warnings": warnings,
            "combined-plot": _pdf_artifact(output_dir / "All_CPIplots.pdf", root, output_dir)}

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


def _dnp_genotypes(output_dir: Path, root: Path, sample_names: list[str], loci: dict) -> tuple[dict, dict]:
    path = output_dir / "summary" / "output_AllGenotypes.txt"
    artifact = _artifact(path, root, output_dir)
    genotype_columns = [f"GT_{sample}" for sample in sample_names]
    columns = _DNP_LOCI | set(genotype_columns)
    if set(tabular_header(path)) != columns:
        raise PlanExecutionError("execution.output", "DNP genotype summary columns differ from the selected samples.")
    genotypes = {}
    for line, row in table_rows(path, columns, "DNP genotype summary"):
        key = locus_key(row, path, line, "DNP")
        if key in genotypes:
            raise PlanExecutionError("execution.output", "DNP genotype summary contains duplicate loci.")
        if loci.get(key) != (row["REF"], row["ALT"]):
            raise PlanExecutionError("execution.output", "DNP genotype summary loci or alleles differ from the panel.")
        genotypes[key] = tuple(row[column] for column in genotype_columns)
    if genotypes.keys() != loci.keys():
        raise PlanExecutionError("execution.output", "DNP genotype summary loci differ from the panel.")
    return artifact, genotypes


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
    cutoffs = ([None] if mode == "all" else [str(Path(request["work_dir"]) / f"{request.get('marker_type', 'DNP')}panel.txt")]
               if mode == "panel" else [panel["label"] for panel in request["cutoffs"]])
    expected = {(pair["native_pair"], cutoff) for pair in bindings for cutoff in cutoffs}
    found = {}
    warnings = []
    settings = _expected_settings(request)
    for number, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise PlanExecutionError("execution.output", "Malformed CPI summary row.")
        _check_cpi_summary_settings(row, request, settings, summary, number + 1)
        key = (row["Pair"], row.get("Cutoff"))
        if key in found:
            raise PlanExecutionError("execution.output", "CPI summary contains duplicate pair/cutoff rows.")
        found[key] = number
        counts = [nonnegative_integer(row[column], summary, number + 1, column)
                  for column in ("N_sites_mother", "N_sites_father")]
        warnings.extend(_numeric_warnings(row, _CPI_COLUMNS - {"Pair", "Marker_type", "N_sites_mother", "N_sites_father"},
                                         summary, number + 1, allow_missing=0 in counts))
    if set(found) != expected:
        raise PlanExecutionError("execution.output", "CPI summary does not match the declared pairs and cutoffs.")
    plots = output_dir / "plots"
    expected_plots = {"All_CPIplots.pdf", *(f"{pair['native_pair']}_CPIplot.pdf" for pair in bindings)}
    if {path.name for path in plots.glob("*.pdf")} != expected_plots:
        raise PlanExecutionError("execution.output", "CPI plots do not match the declared pair identities.")
    curves = output_dir / "curves"
    curve_columns = {"Iteration", "InfSites_mother", "InfSites_father", "CPI", "log_CPI",
                     "Mismatch", "NotMismatch", "Cutoff"}
    expected_curves = set()
    pairs = []
    for pair in bindings:
        curves_for_pair = []
        for index, cutoff in enumerate(cutoffs, 1):
            curve = curves / f"{pair['native_pair']}_panel_{index}.tsv"
            expected_curves.add(curve.name)
            _output_columns(curve, curve_columns)
            curves_for_pair.append({"cutoff": cutoff, **_artifact(curve, root, output_dir)})
        pairs.append({
            "pair": pair["pair"], "mother": pair["mother"], "father": pair["father"],
            "native_pair": pair["native_pair"],
            "summary_rows": [{"row": found[(pair["native_pair"], cutoff)], "cutoff": cutoff} for cutoff in cutoffs],
            "plot": _pdf_artifact(plots / f"{pair['native_pair']}_CPIplot.pdf", root, output_dir),
            "curves": curves_for_pair,
        })
    if {path.name for path in curves.glob("*.tsv")} != expected_curves:
        raise PlanExecutionError("execution.output", "CPI curves do not match the declared pairs and cutoffs.")
    return {"summary": artifact, "cpi-pairs": pairs, "quality_warnings": warnings,
            "combined-plot": _pdf_artifact(plots / "All_CPIplots.pdf", root, output_dir)}


def _numeric_warnings(row: dict, columns: set[str], path: Path, number: int, *, allow_missing: bool) -> list[dict]:
    warnings = []
    context = {key: row[key] for key in ("chr", "pos", "pos1", "pos2", "Pair", "Trio", "Analysis", "Cutoff", "individuo") if key in row}
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
    if step["workflow"] == "cpin":
        return _collect_cpin_outputs(step, request, root, output_dir)
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
                if ((not sum(counts[:2]) or counts[2] / sum(counts) >= request.get("scientific_settings", {}).get("other_fraction_max", 0.1)) and row["GT"] != "NA"):
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
        expected_loci = {(row.chromosome, row.pos1, row.pos2): (row.reference, row.alternative)
                         for row in read_dnp_list(Path(request["panel"]))}
        sample_names = [item["sample_id"] for item in request["samples"]]
        summary, genotypes = _dnp_genotypes(output_dir, root, sample_names, expected_loci)
        columns = DNP_OUTPUT_COLUMNS | {"GT"}
        for index, (identifier, name) in enumerate(zip(step["inputs"]["samples"], sample_names, strict=True)):
            path = directory / f"full_output_{name}.txt"
            artifact = _artifact(path, root, output_dir)
            warnings = require_dnp_input(path)
            seen = set()
            for line, row in table_rows(path, columns, "DNPcall output"):
                key = locus_key(row, path, line, "DNP")
                if expected_loci.get(key) != (row["REF"], row["ALT"]):
                    raise PlanExecutionError("execution.output", "DNPcall result loci or alleles do not match the selected panel.")
                if row["GT"] != genotypes[key][index]:
                    raise PlanExecutionError("execution.output", f"DNP genotype summary differs from sample {name}.")
                seen.add(key)
            if seen != expected_loci.keys():
                raise PlanExecutionError("execution.output", "DNPcall result loci or alleles do not match the selected panel.")
            all_warnings.extend({**warning, "code": warning["code"].replace("input.", "output.", 1)}
                                for warning in warnings)
            tables.append({"sample": identifier, "native_name": name, **artifact})
        return {"dnp-tables": tables, "dnp-summary": {"genotypes": summary},
                "quality_warnings": all_warnings}

    summary = output_dir / "contamination_summary.txt"
    artifact = _artifact(summary, root, output_dir)
    _output_columns(summary, {"individuo", "informative_sites", "mean_contamination", "sd_contamination"})
    rows = [row for _, row in table_rows(summary, {
        "individuo", "informative_sites", "mean_contamination", "sd_contamination",
    }, "Contamination summary")]
    expected_names = [Path(sample["name"]).stem for sample in request["samples"]]
    if sorted(row["individuo"] for row in rows) != sorted(expected_names):
        raise PlanExecutionError("execution.output", "Contamination summary does not match the selected sample identities.")
    tables = []
    warnings = []
    for number, row in enumerate(rows, 2):
        count = nonnegative_integer(row["informative_sites"], summary, number, "informative_sites")
        warnings.extend(_numeric_warnings(row, {"mean_contamination"}, summary, number, allow_missing=count == 0))
        warnings.extend(_numeric_warnings(row, {"sd_contamination"}, summary, number, allow_missing=count <= 1))
    for reference, name in zip(step["inputs"]["samples"], expected_names, strict=True):
        path = output_dir / f"contamination_{name}.txt"
        table_artifact = _artifact(path, root, output_dir)
        coordinate_columns = ({"chr", "pos"} if request.get("marker_type", "DNP") == "SNP" else {"chr", "pos1", "pos2"})
        _output_columns(path, coordinate_columns | {"contamination"})
        found = set()
        for number, row in table_rows(path, coordinate_columns | {"contamination"}, "Contamination output"):
            key = locus_key(row, path, number)
            if key in found:
                raise PlanExecutionError("execution.output", f"{path.name}: duplicate locus at row {number}.")
            found.add(key)
            warnings.extend(_numeric_warnings(row, {"contamination"}, path, number, allow_missing=False))
        summary_row = next(row for row in rows if row["individuo"] == name)
        if len(found) != nonnegative_integer(summary_row["informative_sites"], summary, 0, "informative_sites"):
            raise PlanExecutionError("execution.output", f"{path.name}: informative site count differs from its summary.")
        tables.append({"sample": reference["sample"], "source": reference.copy(),
                       "native_name": name, **table_artifact})
    return {"summary": artifact, "contamination-tables": tables, "quality_warnings": warnings}


def _collect_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    try:
        result = _collect_outputs_unchecked(step, request, root, output_dir)
        settings = output_dir / "scientific-settings.json"
        artifact = _artifact(settings, root, output_dir)
        document = json.loads(settings.read_text(encoding="utf-8"))
        actual = validate_settings_document(document, step["workflow"])
        if actual != _expected_settings(request):
            raise PlanExecutionError("execution.output", "Scientific settings sidecar differs from the requested parameters.")
        result["scientific-settings"] = artifact
        return result
    except PlanExecutionError:
        raise
    except (ValidationError, UnicodeError, csv.Error, json.JSONDecodeError) as exc:
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
    elif workflow == "cpin":
        bindings = []
        marker = request.get("marker_type", "DNP")
        for trio in request["trios"].split(","):
            mother, father, child = [value.strip() for value in trio.split(":")]
            bindings.append({"trio": f"{mother}:{father}:{child}", "mother": {"sample": mother},
                             "father": {"sample": father}, "child": {"sample": child},
                             "native_trio": f"Mother{mother}-Father{father}-Child{child}_{marker}s"})
        step["native_bindings"] = bindings
    else:
        bindings = []
        for pair in request["pairs"].split(","):
            mother, father = [value.strip() for value in pair.split(":")]
            bindings.append({"pair": f"{mother}:{father}", "mother": {"sample": mother},
                             "father": {"sample": father},
                             "native_pair": f"Mother{mother}-Father{father}_{request.get('marker_type', 'DNP')}s"})
        step["native_bindings"] = bindings
    output = Path(request["out_dir"])
    root = output.parent
    return _collect_outputs(step, request, root, output)

