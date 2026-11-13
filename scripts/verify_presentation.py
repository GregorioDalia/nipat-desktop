"""Render readable results in the real image and prove canonical numeric parity.

Requires Docker and host pdftotext (Ubuntu package poppler-utils). No scientific
source is mounted into the runtime. Inputs are synthetic committed fixtures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unicodedata

from verify_engine_package import image_id, run_container, run_image, write_request
from verify_dnp_engine import check_dnp_outputs


PROJECT = Path(__file__).resolve().parents[1]
ERR = 0.0000892303778101497


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_table(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter="," if path.suffix == ".csv" else "\t"))


def check_canonical(first: Path, second: Path) -> None:
    def tables(root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.suffix in {".txt", ".csv", ".tsv"}
                and "presentation" not in path.relative_to(root).parts and path.name != "resources.tsv"}
    if tables(first) != tables(second) or not tables(first):
        raise ValueError(f"Canonical scientific tables changed: {first} / {second}")


def check_readable(run: Path, *, artifact_root: Path | None = None) -> dict:
    root = artifact_root or run
    config = json.loads((run / "work/presentation-config.json").read_text())
    report = json.loads((run / "work/presentation-report.json").read_text())
    if report["status"] != "complete":
        raise ValueError("Incomplete readable results report")
    for record in [report["index"], report["sample_map"], *report["files"]]:
        artifact = root / record["path"]
        if digest(artifact) != record["sha256"]:
            raise ValueError(f"Readable artifact checksum mismatch: {artifact}")
    directory = run / "output/presentation"
    for source, export in config["tables"].items():
        expected = read_table(run / "output" / source)
        headers = expected[0][:]
        expected[0] = [config["replacements"].get(value, value) if value.startswith("GT_") else value
                       for value in headers]
        for row in expected[1:]:
            for number, header in enumerate(headers):
                if header in {"Pair", "Trio", "individuo", "sample"}:
                    row[number] = config["replacements"].get(row[number], row[number])
        if export["sample"]:
            expected[0].insert(0, "Sample")
            for row in expected[1:]:
                row.insert(0, config["samples"][export["sample"]])
        if read_table(directory / export["target"]) != expected:
            raise ValueError(f"Readable table changed a scientific field: {source}")
    extracted = {}
    for source, export in config["plots"].items():
        info = subprocess.run(["pdfinfo", str(directory / export["target"])], text=True, capture_output=True, check=True)
        dimensions = re.search(r"Page size:\s+([0-9.]+) x ([0-9.]+) pts", info.stdout)
        if dimensions is None or any(not 0 < float(value) <= 20 * 72 for value in dimensions.groups()):
            raise ValueError(f"Unreadable/unbounded PDF dimensions: {source}\n{info.stdout}")
        process = subprocess.run(["pdftotext", "-enc", "UTF-8", str(directory / export["target"]), "-"],
                                 text=True, capture_output=True, check=True)
        text = " ".join(unicodedata.normalize("NFC", process.stdout).split())
        extracted[source] = text
        labels = []
        if export["sample"]:
            labels = [config["samples"][export["sample"]]]
        elif source.endswith(("DNPs_covered_UpSet_plot.pdf", "SNPs_covered_UpSet_plot.pdf")):
            labels = list(config["samples"].values())
        elif config["workflow"] in {"cpi", "cpin"}:
            if source.endswith("All_CPIplots.pdf"):
                labels = list(config["pairs"].values())
            else:
                stem = Path(source).name.removesuffix("_CPIplot.pdf")
                matches = [label for identity, label in config["pairs"].items()
                           if stem == identity or stem.startswith(identity + "_")]
                if len(matches) != 1:
                    raise ValueError(f"Ambiguous family identity in plot: {source}")
                labels = matches
        for label in labels:
            if "".join(unicodedata.normalize("NFC", label).split()) not in "".join(text.split()):
                raise ValueError(f"Original sample label missing inside PDF {source}: {label!r}\n{text}")
    if config["workflow"] == "snp-call":
        table = read_table(run / "output/SNPcall_output.txt")
        expected_columns = {"chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count", "ratio",
                            "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
                            "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts"}
        if set(table[0]) != expected_columns or len(config["plots"]) != 5:
            raise ValueError("Incomplete SNPcall 2.0 presentation contract")
        resources = read_table(run / "output/summary/resources.tsv")
        for row in resources[1:]:
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in row[1:]):
                raise ValueError("SNP resource observations must be finite and non-negative")
    (run / "work/presentation-pdf-text.json").write_text(json.dumps(extracted, ensure_ascii=False, indent=2))
    return config


def execute(identifier: str, root: Path, inputs: Path, request: dict, labels: dict, name: str) -> Path:
    common = {"schema_version": 1, "work_dir": "/results/work", "out_dir": "/results/output", **request}
    runs = []
    for mode in ("canonical", "readable"):
        run = root / f"{name}-{mode}"
        value = {**common, **({"presentation": {"samples": labels, "pairs": {}}} if mode == "readable" else {})}
        write_request(run, value)
        output = run_image(identifier, ["execute", request["workflow"], "--request", "/results/work/request.json"],
                           inputs=inputs, results=run)
        (run / "engine.log").write_text(output)
        runs.append(run)
    check_canonical(runs[0] / "output", runs[1] / "output")
    check_readable(runs[1])
    print(f"PASS: {name}, canonical numeric parity and readable table/PDF labels.", flush=True)
    return runs[1]


def fixtures(identifier: str, root: Path) -> Path:
    generated = root / "generated"
    inputs = generated / "work"
    (inputs / "bams").mkdir(parents=True)
    source = PROJECT / "tests/fixtures/dnp_engine"
    for name in ("reference.fa", "DNP_list.txt"):
        shutil.copyfile(source / name, inputs / name)
    for number, sample in enumerate(("A", "B"), 1):
        run_container(identifier, ["samtools", "view", "-b", "-o", f"/results/work/bams/sample_{number:04d}.bam",
                                  f"/inputs/reads_{sample}.sam"], inputs=source, results=generated)
    run_container(identifier, ["samtools", "faidx", "/results/work/reference.fa"], results=generated)
    (inputs / "population.tsv").write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" + "".join(
        f"chrDnpSynthetic\t{position}\t{position + 1}\t0.5\t0.5\n" for position in (50, 140, 230)))
    (inputs / "SNPlist.tsv").write_text("pos\tref\talt\nchrDnpSynthetic:50\tA\tG\nchrDnpSynthetic:140\tT\tC\nchrDnpSynthetic:230\tG\tA\n")
    return inputs


def check_plan(identifier: str, root: Path, inputs: Path) -> None:
    sample_ids = ("maternal", "paternal")
    refs = [{"step": "dnp", "output": "dnp-tables", "sample": identity} for identity in sample_ids]
    plan = {"schema_version": 1,
            "samples": [{"id": identity, "kind": "bam", "path": f"/inputs/bams/sample_{number:04d}.bam"}
                        for number, identity in enumerate(sample_ids, 1)],
            "steps": [
                {"id": "dnp", "workflow": "dnp-call", "inputs": {"samples": list(sample_ids),
                    "reference": "/inputs/reference.fa", "panel": "/inputs/DNP_list.txt"}, "parameters": {"parallel": False}},
                {"id": "contamination", "workflow": "contamination", "inputs": {"samples": list(reversed(refs)),
                    "panel": "/inputs/DNP_list.txt"}, "parameters": {}},
                {"id": "cpi", "workflow": "cpi", "inputs": {"pairs": [{"id": "family", "mother": refs[0], "father": refs[1]}],
                    "popfreq": "/inputs/population.tsv", "cutoffs": []}, "parameters": {"cutoff_mode": "all", "err_const": ERR}},
                {"id": "snp", "workflow": "snp-call", "inputs": {"sample": "maternal", "reference": "/inputs/reference.fa",
                    "panel": "/inputs/SNPlist.tsv"}, "parameters": {"mode": "bam"}},
                {"id": "snp_paternal", "workflow": "snp-call", "inputs": {"sample": "paternal", "reference": "/inputs/reference.fa",
                    "panel": "/inputs/SNPlist.tsv"}, "parameters": {"mode": "bam"}},
            ]}
    roots = []
    for mode in ("canonical", "readable"):
        run = root / f"plan-{mode}"
        value = {**plan, **({"presentation": {"samples": {"maternal": 'Madre à "A".bam', "paternal": "Padre β.bam"}, "pairs": {}}}
                           if mode == "readable" else {})}
        write_request(run, value)
        output = run_image(identifier, ["execute-plan", "--plan", "/results/work/request.json", "--run-dir", "/results/workflow"],
                           inputs=inputs, results=run)
        (run / "engine.log").write_text(output)
        roots.append(run / "workflow")
    state = json.loads((roots[1] / "workflow-state.json").read_text())
    if state["status"] != "succeeded" or not (roots[1] / state["presentation"]["index"]["path"]).is_file():
        raise ValueError("Readable workflow did not finish")
    for step in state["steps"]:
        if step["status"] != "succeeded":
            raise ValueError(f"Readable workflow step failed: {step}")
        relative = Path("steps") / step["id"]
        check_canonical(roots[0] / relative / "output", roots[1] / relative / "output")
        check_readable(roots[1] / relative, artifact_root=roots[1])
    # The consumer deliberately receives reversed registry order.
    config = json.loads((roots[1] / "steps/contamination/work/presentation-config.json").read_text())
    if config["samples"] != {"table_0001": "Padre β.bam", "table_0002": 'Madre à "A".bam'}:
        raise ValueError("Workflow lost original names while rebinding downstream inputs")
    groups = state.get("snp_summary", [])
    if len(groups) != 1 or set(groups[0]["samples"]) != {"maternal", "paternal"}:
        raise ValueError("Two-sample SNP 2.0 summary is missing or misidentified")
    group = groups[0]
    table = roots[1] / group["genotypes"]["path"]
    if table.read_bytes() != (roots[0] / group["genotypes"]["path"]).read_bytes():
        raise ValueError("Presentation changed batch genotype values or identities")
    plots = {Path(item["path"]).name: roots[1] / item["path"] for item in group["plots"]}
    upset = plots.get("SNPs_covered_UpSet_plot.pdf")
    if upset is None:
        raise ValueError("Two-sample SNP 2.0 UpSet plot is missing")
    extracted = subprocess.run(["pdftotext", "-enc", "UTF-8", str(upset), "-"],
                               text=True, capture_output=True, check=True).stdout
    for name in ('Madre à "A".bam', "Padre β.bam"):
        if "".join(name.split()) not in "".join(extracted.split()):
            raise ValueError(f"Quoted/Unicode batch sample label changed: {name!r}\n{extracted}")
    print("PASS: four-module automatic workflow including a two-sample SNP 2.0 summary; canonical identities, labels and reversed sample order preserved.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if shutil.which("pdftotext") is None or shutil.which("pdfinfo") is None:
        parser.error("pdftotext and pdfinfo are required; install poppler-utils on Ubuntu")
    root = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="nipat-presentation-")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(f"Presentation regression artifacts: {root}", flush=True)
    identifier = image_id(args.image)
    inputs = fixtures(identifier, root)
    original = {path: digest(path) for path in inputs.rglob("*") if path.is_file()}
    dnp = {"workflow": "dnp-call", "samples": [{"path": f"/inputs/bams/sample_{number:04d}.bam", "sample_id": f"sample_{number:04d}"}
            for number in (1, 2)], "reference": "/inputs/reference.fa", "panel": "/inputs/DNP_list.txt", "parallel": False}
    run = execute(identifier, root, inputs, dnp,
                  {"sample_0001": 'Campione à "uno".bam', "sample_0002": "sample_0001.bam"}, "dnp")
    check_dnp_outputs(run, ("A", "B"))
    execute(identifier, root, inputs, dnp, {"sample_0001": "Duplicato.bam", "sample_0002": "Duplicato.bam"}, "dnp-duplicates")
    execute(identifier, root, inputs, {"workflow": "snp-call", "mode": "bam", "bam": "/inputs/bams/sample_0001.bam",
            "pileup": None, "reference": "/inputs/reference.fa", "panel": "/inputs/SNPlist.tsv"},
            {"sample_0001": "SNP à.bam"}, "snp")
    contamination = PROJECT / "tests/fixtures/contamination"
    names = ("NoRatio.tsv", "WithRatio.TXT", "NoSites.txt")
    execute(identifier, root, contamination, {"workflow": "contamination", "panel": "/inputs/DNP_list.txt",
            "samples": [{"path": f"/inputs/samples/{name}", "name": Path(name).stem + ".txt"} for name in names]},
            {Path(name).stem: name for name in names}, "contamination")
    cpi = PROJECT / "tests/fixtures/cpi"
    names = ("MotherInformative", "FatherInformative", "MotherNoSites", "FatherNoSites")
    execute(identifier, root, cpi, {"workflow": "cpi", "samples": [{"path": f"/inputs/samples/{name}.txt", "name": name + ".txt"} for name in names],
            "pairs": "Informative:Informative,NoSites:NoSites", "mother_prefix": "Mother", "father_prefix": "Father",
            "popfreq": "/inputs/pop_allFreq.txt", "err_const": ERR, "cutoff_mode": "all", "cutoffs": []},
            {name: f'{"Madre" if name.startswith("Mother") else "Padre"} à {index}_' + "IonXpress_008_" * 13 + ".txt"
             for index, name in enumerate(names)}, "cpi")
    for marker in ("SNP", "DNP"):
        cpin = PROJECT / "tests/fixtures/cpin" / marker
        names = ("MotherM1", "FatherF1", "ChildC1")
        execute(identifier, root, cpin, {
            "workflow": "cpin", "marker_type": marker,
            "samples": [{"path": f"/inputs/{name}.txt", "name": name + ".txt"} for name in names],
            "trios": "M1:F1:C1", "mother_prefix": "Mother", "father_prefix": "Father",
            "child_prefix": "Child", "popfreq": "/inputs/population.txt",
        }, {"MotherM1": 'Madre à "M".txt', "FatherF1": "Padre β.txt", "ChildC1": "Figlio è.txt"},
           "cpin-" + marker.lower())
    check_plan(identifier, root, inputs)
    if any(digest(path) != expected for path, expected in original.items()):
        raise ValueError("Presentation regression modified an original input")
    print("PASS: readable exports, extracted PDF labels, immutable scientific tables and input files.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
