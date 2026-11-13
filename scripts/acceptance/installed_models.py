"""Independent analytical checks for the installed 0.8.50 downstream models.

The fixtures declare synthetic counts and population frequencies. Expected
answers below follow their documented arithmetic, never candidate output or R.
Only the caller of build_cases executes NIPAT, using its installed backend.
"""

from __future__ import annotations

import csv
from functools import partial
import hashlib
import json
import math
from pathlib import Path
import shutil


EPSILON = {"SNP": .001, "DNP": .0000892303778101497}
SUMMARY = {"cpi": "Summary_FetalFraction_CPI.csv", "cpin": "Summary_Postnatal_CPI.txt",
           "contamination": "contamination_summary.txt"}
COMMON_PARAMETERS = {
    "other_fraction_max": .1, "homozygous_ref_min": .9, "homozygous_alt_max": .1,
    "heterozygous_min": .4, "heterozygous_max": .6,
    "err_const_snp": EPSILON["SNP"], "err_const_dnp": EPSILON["DNP"],
    "log_cpi_lower": -4., "log_cpi_upper": 4.,
}
COMMON_CONSTANTS = {
    "ploidy": 2, "allele_alphabet": "ACGT", "missing_result": "NA",
    "heterozygous_transmission": .5, "homozygous_transmission": 1,
    "log_cpi_base": 10, "population_frequencies": "(0, 1]",
    "pi_formula": "paternal transmission (or mismatch constant) / obligatory allele population frequency",
    "other_filter_comparison": "<=",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def number(actual, expected, label: str) -> None:
    if expected is None:
        require(actual == "NA", f"{label}: expected explicit NA, got {actual!r}")
        return
    try:
        value = float(actual)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: not numeric: {actual!r}") from exc
    require(not isinstance(actual, bool) and math.isfinite(value)
            and math.isclose(value, expected, rel_tol=1e-11, abs_tol=1e-11),
            f"{label}: expected {expected}, got {actual!r}")


def table(path: Path, required: set[str]) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="," if path.suffix == ".csv" else "\t")
        columns = reader.fieldnames or []
        require(required <= set(columns) and len(columns) == len(set(columns)),
                f"Missing or duplicate columns: {path.name}")
        rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
            f"Incomplete row: {path.name}")
    return rows


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): file_hash(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def settings_expected(workflow: str, minimum: int, include_zero: bool) -> tuple[dict, dict]:
    """Explicit 0.8.50 defaults; observed settings never define the oracle."""
    if workflow == "contamination":
        return ({"other_fraction_max": .1, "homozygous_ref_min": .9,
                 "homozygous_alt_max": .1, "include_zero": include_zero}, {
            "other_fraction_denominator": "N_REF+N_ALT+N_Other",
            "site_contamination": "N_unexpected/(N_REF+N_ALT)",
            "sample_contamination": "arithmetic mean of retained sites",
            "one_site_sd": "NA", "missing_result": "NA"})
    parameters = dict(COMMON_PARAMETERS)
    constants = dict(COMMON_CONSTANTS)
    if workflow == "cpi":
        parameters["min_fetal_reads"] = minimum
        constants["fetal_fraction_formula"] = "median(2 * fetal_reads/(N_REF+N_ALT))"
    else:
        parameters.update(min_child_reads=minimum, site_selection="both")
        constants.update(maternal_selection="homozygous mother only",
                         curve_threshold_semantics="obligatory paternal allele support after initial child genotype support filter")
    return parameters, constants


def check_settings(run: Path, workflow: str, minimum: int, include_zero: bool) -> None:
    parameters, constants = settings_expected(workflow, minimum, include_zero)
    for path in (run / "work/effective-scientific-settings.json", run / "output/scientific-settings.json"):
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        require(record.get("schema_version") == 1 and record.get("workflow") == workflow,
                f"Wrong scientific settings identity: {path.name}")
        observed = record.get("parameters", {})
        require(set(observed) == set(parameters), "Scientific settings are missing or unexpected")
        for name, wanted in parameters.items():
            if type(wanted) in (int, float):
                require(type(observed[name]) in (int, float), f"Wrong settings type: {name}")
                number(observed[name], wanted, f"settings/{name}")
            else:
                require(type(observed[name]) is type(wanted) and observed[name] == wanted,
                        f"Wrong scientific setting: {name}")
        values = record.get("constants", {})
        require(set(values) == set(constants) and all(isinstance(item, dict) and "value" in item
                                                    for item in values.values()),
                "Scientific constants are missing or unexpected")
        for name, wanted in constants.items():
            observed = values[name]["value"]
            if type(wanted) in (int, float):
                require(type(observed) in (int, float), f"Wrong constant type: {name}")
                number(observed, wanted, f"constants/{name}")
            else:
                require(observed == wanted, f"Wrong scientific constant: {name}")


def expected_files(directory: Path, suffix: str, names: set[str]) -> None:
    require({path.name for path in directory.glob(f"*{suffix}")} == names,
            f"Missing, duplicate or unexpected {suffix} files in {directory.name}")


def check_pdfs(output: Path, expected: set[str]) -> None:
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*.pdf")
              if "presentation" not in path.relative_to(output).parts}
    require(actual == expected, "Missing or unexpected analytical PDF")
    for relative in expected:
        data = (output / relative).read_bytes()
        require(len(data) > 64 and data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:],
                f"Empty or incomplete analytical PDF: {relative}")


def check_cpi(output: Path, marker: str, minimum: int, families: int, mismatch: bool) -> int:
    identities = ([f"MotherM-FatherF_{marker}s", f"MotherN-FatherN_{marker}s"] if families == 1 else
                  [f"MotherM{i}-FatherF{i}_{marker}s" for i in range(1, families + 1)])
    fields = {"N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw", "Median_fetal_fraction_percent",
              "Max_logCPI", "Min_logCPI", "Median_logCPI", "Mean_logCPI", "CPI_medianFF",
              "Error_constant", "Min_fetal_reads"}
    rows = table(output / SUMMARY["cpi"], fields | {"Pair", "Marker_type"})
    require(len(rows) == len(identities) and {row["Pair"] for row in rows} == set(identities),
            "CPI lost or duplicated an informative/no-sites pair")
    epsilon = EPSILON[marker]
    for row in rows:
        empty = "MotherN-FatherN" in row["Pair"] or minimum > 4
        require(row["Marker_type"] == marker, "Wrong CPI marker type")
        wanted = {
            "N_sites_mother": 0 if empty else (4 if minimum == 1 else 3),
            "N_sites_father": 0 if empty else (4 if minimum == 1 else 3),
            "Median_fetal_fraction_raw": None if empty else (.05 if minimum == 1 else .06),
            "Median_fetal_fraction_percent": None if empty else (5 if minimum == 1 else 6),
            "Max_logCPI": None if empty else (2 if minimum == 1 else 1.301),
            "Min_logCPI": None if empty else .301,
            "Median_logCPI": None if empty else (.952 if minimum == 1 else .602),
            "Mean_logCPI": None if empty else (1.051 if minimum == 1 else .735),
            "CPI_medianFF": None if empty else (1.301 if minimum == 1 else .602),
            "Error_constant": epsilon, "Min_fetal_reads": minimum,
        }
        if mismatch and not empty:
            logs = [math.log10(value) for value in (40 * epsilon, 8 * epsilon, 2)]
            wanted.update(Max_logCPI=round(max(logs), 3), Min_logCPI=round(min(logs), 3),
                          Median_logCPI=round(sorted(logs)[1], 3), Mean_logCPI=round(sum(logs) / 3, 3),
                          CPI_medianFF=round(logs[1], 3))
        for name, value in wanted.items():
            number(row[name], value, f"CPI/{row['Pair']}/{name}")
    expected_files(output / "curves", ".tsv", {f"{name}_panel_1.tsv" for name in identities})
    for identity in identities:
        curve = table(output / "curves" / f"{identity}_panel_1.tsv",
                      {"Iteration", "InfSites_mother", "InfSites_father", "CPI", "log_CPI", "Mismatch", "NotMismatch"})
        if "MotherN-FatherN" in identity or minimum > 4:
            require(not curve, "CPI no-sites pair must have an empty curve")
            continue
        require([int(row["Iteration"]) for row in curve] == list(range(minimum, 5)),
                "CPI curve has missing or duplicate thresholds")
        for row in curve:
            threshold = int(row["Iteration"])
            contributions = [(1, 5), (2, 5), (3, 4 * epsilon if mismatch else 2), (4, 2)]
            retained = [value for support, value in contributions if support >= threshold]
            product = math.prod(retained)
            mismatches = int(mismatch and threshold <= 3)
            for name, value in {"InfSites_mother": len(retained), "InfSites_father": len(retained),
                                "CPI": product, "log_CPI": math.log10(product), "Mismatch": mismatches,
                                "NotMismatch": len(retained) - mismatches}.items():
                number(row[name], value, f"CPI curve/{identity}/{threshold}/{name}")
    check_pdfs(output, {"plots/All_CPIplots.pdf", *(f"plots/{name}_CPIplot.pdf" for name in identities)})
    return len(rows)


def check_cpin_sites(path: Path, marker: str) -> None:
    position = "pos" if marker == "SNP" else "pos1"
    rows = table(path, {"chr", position, "Status", "Paternity_Index", "Child_support",
                        "Mismatch", "Paternal_transmission", "Required_paternal_allele"})
    expected_status = ["eligible", "eligible", "eligible", "mother_child_incompatible",
                       "mother_not_homozygous", "insufficient_child_support", "quality_filter",
                       "quality_filter", "father_unassigned"]
    require(len(rows) == 9 and {int(row[position]) for row in rows} == set(range(100, 1000, 100)),
            "CPIN sites are missing or duplicated")
    for row in rows:
        index = int(row[position]) // 100 - 1
        require(row["chr"] == "chr1" and row["Status"] == expected_status[index],
                f"Wrong CPIN exclusion at locus {row[position]}")
        if marker == "DNP":
            number(row["pos2"], int(row[position]) + 1, "CPIN second coordinate")
        number(row["Paternity_Index"], [1.25, EPSILON[marker] / .4, 1 / .6][index] if index < 3 else None,
               f"CPIN site/{row[position]}/PI")
        number(row["Child_support"], [5, 6, 10, None, None, 1, None, 5, 5][index], "CPIN child support")
        require(row["Required_paternal_allele"] == ["ALT", "ALT", "REF", "NA", "NA", "ALT", "NA", "ALT", "ALT"][index],
                "Wrong obligatory paternal allele")
        require(row["Mismatch"] == (["FALSE", "TRUE", "FALSE"][index] if index < 3 else "NA"),
                "Wrong CPIN per-site mismatch")
        number(row["Paternal_transmission"], [.5, 0, 1][index] if index < 3 else None,
               "CPIN paternal transmission")


def check_cpin(output: Path, marker: str, minimum: int, families: int) -> int:
    identities = ([f"MotherM-FatherF-ChildC_{marker}s"] if families == 1 else
                  [f"MotherM{i}-FatherF{i}-ChildC{i}_{marker}s" for i in range(1, families + 1)])
    selections = {"heterozygous_child_sites": False, "all_compatible_sites": True}
    fields = {"N_sites", "N_heterozygous_child_sites", "N_homozygous_child", "Matching_sites",
              "Mismatching_sites", "CPI", "Log10_CPI", "Error_constant", "Min_child_reads"}
    rows = table(output / SUMMARY["cpin"], fields | {"Trio", "Analysis", "Marker_type"})
    require(len(rows) == 2 * families and {(row["Trio"], row["Analysis"]) for row in rows}
            == {(name, selection) for name in identities for selection in selections},
            "CPIN lost or duplicated a trio/selection")
    for row in rows:
        homozygous = selections[row["Analysis"]]
        count = 3 if homozygous else 2
        cpi = 3.125 * EPSILON[marker] / (.6 if homozygous else 1)
        require(row["Marker_type"] == marker, "Wrong CPIN marker type")
        for name, value in {"N_sites": count, "N_heterozygous_child_sites": 2,
                            "N_homozygous_child": count - 2, "Matching_sites": count - 1,
                            "Mismatching_sites": 1, "CPI": cpi, "Log10_CPI": math.log10(cpi),
                            "Error_constant": EPSILON[marker], "Min_child_reads": minimum}.items():
            number(row[name], value, f"CPIN/{row['Trio']}/{row['Analysis']}/{name}")
    expected_files(output / "curves", ".tsv", {f"{name}_{selection}_curve.tsv"
                                               for name in identities for selection in selections})
    expected_files(output / "sites", ".tsv", {f"{name}_sites.tsv" for name in identities})
    for identity in identities:
        check_cpin_sites(output / "sites" / f"{identity}_sites.tsv", marker)
        for selection, homozygous in selections.items():
            curve = table(output / "curves" / f"{identity}_{selection}_curve.tsv",
                          {"Min_child_reads", "Through_min_child_reads", "N_sites", "Log10_CPI",
                           "Matching_sites", "Mismatching_sites"})
            expanded = {}
            for row in curve:
                first, last = int(row["Min_child_reads"]), int(row["Through_min_child_reads"])
                require(2 <= first <= last <= 10, "CPIN curve interval out of range")
                for threshold in range(first, last + 1):
                    require(threshold not in expanded, "CPIN curve has overlapping intervals")
                    expanded[threshold] = row
            require(set(expanded) == set(range(2, 11 if homozygous else 7)), "CPIN curve has gaps")
            for threshold, row in expanded.items():
                contributions = [(5, 1.25, False), (6, EPSILON[marker] / .4, True)]
                if homozygous:
                    contributions.append((10, 1 / .6, False))
                retained = [item for item in contributions if item[0] >= threshold]
                for name, value in {"N_sites": len(retained),
                                    "Log10_CPI": sum(math.log10(item[1]) for item in retained),
                                    "Matching_sites": sum(not item[2] for item in retained),
                                    "Mismatching_sites": sum(item[2] for item in retained)}.items():
                    number(row[name], value, f"CPIN curve/{identity}/{selection}/{threshold}/{name}")
    check_pdfs(output, {"All_CPIplots.pdf", *(f"plots/{name}_{selection}_CPIplot.pdf"
                                          for name in identities for selection in selections)})
    return len(rows)


def check_contamination(output: Path, marker: str, include_zero: bool, families: int) -> int:
    identities = {f"Sample{i}" for i in range(1, families + 1)}
    rows = table(output / SUMMARY["contamination"], {"individuo", "informative_sites", "mean_contamination", "sd_contamination"})
    require(len(rows) == families and {row["individuo"] for row in rows} == identities,
            "Contamination lost or duplicated a sample")
    for row in rows:
        for name, value in {"informative_sites": 2 if include_zero else 1,
                            "mean_contamination": .025 if include_zero else .05,
                            "sd_contamination": math.sqrt(.00125) if include_zero else None}.items():
            number(row[name], value, f"Contamination/{row['individuo']}/{name}")
    expected_files(output, ".txt", {SUMMARY["contamination"], *(f"contamination_{name}.txt" for name in identities)})
    position = "pos" if marker == "SNP" else "pos1"
    for identity in identities:
        sites = table(output / f"contamination_{identity}.txt",
                      {"chr", position, "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count",
                       "ratio_REF_ALT", "ratio_Other", "N_unexpected", "contamination"})
        wanted_positions = {100, 200} if include_zero else {100}
        require(len(sites) == len(wanted_positions) and {int(row[position]) for row in sites} == wanted_positions,
                "Contamination retained the wrong sites")
        for row in sites:
            first = int(row[position]) == 100
            require(row["chr"] == "chr1" and row["REF"] == ("A" if marker == "SNP" else "AA")
                    and row["ALT"] == ("C" if marker == "SNP" else "CC"), "Wrong contamination locus/alleles")
            if marker == "DNP":
                number(row["pos2"], int(row[position]) + 1, "Contamination second coordinate")
            for name, value in {"N_REF": 95 if first else 100, "N_ALT": 5 if first else 0,
                                "N_Other": 11 if first else 0, "total_count": 111 if first else 100,
                                "ratio_REF_ALT": .95 if first else 1, "ratio_Other": 11 / 111 if first else 0,
                                "N_unexpected": 5 if first else 0, "contamination": .05 if first else 0}.items():
                number(row[name], value, f"Contamination site/{identity}/{row[position]}/{name}")
    return len(rows)


def validate_model(run: Path, *, workflow: str, marker: str, families: int = 1,
                   minimum: int = 2, include_zero: bool = True, mismatch: bool = False) -> dict:
    output = run / "output"
    check_settings(run, workflow, minimum, include_zero)
    if workflow == "cpi":
        count = check_cpi(output, marker, minimum, families, mismatch)
    elif workflow == "cpin":
        count = check_cpin(output, marker, minimum, families)
    else:
        count = check_contamination(output, marker, include_zero, families)
    scientific = {path.relative_to(output).as_posix(): file_hash(path)
                  for path in sorted(output.rglob("*"))
                  if path.is_file() and path.suffix in {".txt", ".tsv", ".csv"}
                  and "presentation" not in path.relative_to(output).parts and path.name != "resources.tsv"}
    return {"workflow": workflow, "marker": marker, "families": families,
            "summary_rows": count, "scientific_sha256": scientific}


def validate_case(run: Path, *, inputs: Path, original: dict, **options) -> dict:
    require(tree_hashes(inputs) == original, "The installed analysis modified an original test input")
    return validate_model(run, **options)


def build_cases(fixtures: Path, generated: Path) -> list[dict]:
    """Create 34 positive numerical cases and three precise input rejections."""
    cases = []
    generated.mkdir(parents=True, exist_ok=True)

    def add(marker, workflow, variant, *, mode="serial", families=1, minimum=2,
            include_zero=True, metadata=False, mismatch=False):
        identity = f"models-{marker.lower()}-{workflow}-{variant}"
        inputs = generated / identity
        shutil.copytree(fixtures / "five_modules" / marker / workflow, inputs)
        if families > 1 and workflow in {"cpi", "cpin"}:
            for index in range(1, families + 1):
                roles = (("Mother", "M"), ("Father", "F"), ("Child", "C")) if workflow == "cpin" else (("Mother", "M"), ("Father", "F"))
                for role, name in roles:
                    shutil.copyfile(inputs / f"{role}{name}.txt", inputs / f"{role}{name}{index}.txt")
        if metadata:
            path = inputs / "population.tsv"
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text(lines[0] + "\tunused_metadata\n" + "".join(line + "\tNA\n" for line in lines[1:]), encoding="utf-8")
        if mismatch:
            path = inputs / "FatherF.txt"
            rows = table(path, {"N_REF", "N_ALT"})
            rows[1].update(N_REF="100", N_ALT="0")
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        if workflow == "contamination":
            calls = inputs / "calls"
            calls.mkdir()
            for index in range(1, families + 1):
                shutil.copyfile(inputs / "Calls.txt", calls / f"Sample{index}.txt")
            args = ["--set", f"contamination.include_zero={str(include_zero).lower()}",
                    workflow, "--input-dir", calls, "--panel", inputs / "panel.tsv"]
        else:
            setting = "min_child_reads" if workflow == "cpin" else "min_fetal_reads"
            selected = ("M:F:C" if workflow == "cpin" else "M:F,N:N") if families == 1 else ",".join(
                f"M{i}:F{i}:C{i}" if workflow == "cpin" else f"M{i}:F{i}" for i in range(1, families + 1))
            args = ["--set", f"{workflow}.{setting}={minimum}", workflow, "--input-dir", inputs,
                    "--trios" if workflow == "cpin" else "--pairs", selected,
                    "--popfreq", inputs / "population.tsv"]
        cases.append({"id": identity, "category": "downstream-analytical" if families == 1 else "downstream-batch",
                      "args": args, "mode": mode,
                      "validate": partial(validate_case, inputs=inputs, original=tree_hashes(inputs),
                                          workflow=workflow, marker=marker, families=families,
                                          minimum=minimum, include_zero=include_zero, mismatch=mismatch),
                      **({"compare_group": f"models-{marker.lower()}-{workflow}-batch3"} if families > 1 else {})})

    for marker in ("SNP", "DNP"):
        add(marker, "cpin", "default")
        for name, options in (("default", {}), ("minimum1", {"minimum": 1}),
                              ("no-sites", {"minimum": 5}), ("metadata-na", {"metadata": True}),
                              ("mismatch", {"mismatch": True})):
            add(marker, "cpi", name, **options)
        add(marker, "contamination", "include-zero")
        add(marker, "contamination", "exclude-zero", include_zero=False)
        for workflow in ("cpin", "cpi", "contamination"):
            for mode in ("serial", "auto", "cap2"):
                add(marker, workflow, f"batch3-{mode}", families=3, mode=mode)
    for workflow, variant, expected in (
        ("contamination", "negative-count", r"N_REF.*intero non negativo"),
        ("cpi", "zero-frequency", r"Ref_f\.pop.*finita tra 0 e 1"),
        ("cpin", "duplicate-trio", r"Terna CPIN duplicata\."),
    ):
        identity = f"models-invalid-{workflow}-{variant}"
        inputs = generated / identity
        shutil.copytree(fixtures / "five_modules/SNP" / workflow, inputs)
        if workflow != "cpin":
            path = inputs / ("Calls.txt" if workflow == "contamination" else "population.tsv")
            column = "N_REF" if workflow == "contamination" else "Ref_f.pop"
            rows = table(path, {column})
            rows[0][column] = "-1" if workflow == "contamination" else "0"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        if workflow == "contamination":
            args = [workflow, "--input", inputs / "Calls.txt", "--panel", inputs / "panel.tsv"]
        else:
            args = [workflow, "--input-dir", inputs, "--pairs" if workflow == "cpi" else "--trios",
                    "M:F" if workflow == "cpi" else "M:F:C,M:F:C", "--popfreq", inputs / "population.tsv"]
        cases.append({"id": identity, "category": "invalid-input", "args": args,
                      "mode": "serial", "validate": None, "expect_failure": expected})
    return cases
