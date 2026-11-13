"""Run all five modules from three synthetic BAMs in serial and capped modes.

Local development qualification; requires Rscript, samtools and bundled R libraries.
The BAMs contain two synthetic contigs from the existing caller fixtures. They
exercise role routing and output contracts, not a simulated real biological trio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from nipat_scientific.executor import execute_plan


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify(destination: Path):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    inputs = destination / "inputs"
    inputs.mkdir()
    dnp, snp = (PROJECT / "tests/fixtures" / name for name in ("dnp_engine", "snp_engine"))
    original = {str(path): digest(path) for directory in (dnp, snp) for path in directory.iterdir() if path.is_file()}
    reference = inputs / "reference.fa"
    reference.write_bytes((dnp / "reference.fa").read_bytes() + (snp / "reference.fa").read_bytes())
    subprocess.run(["samtools", "faidx", str(reference)], check=True)
    snp_lines = (snp / "reads.sam").read_text().splitlines()
    for index, source in enumerate(("reads_A.sam", "reads_B.sam", "reads_A.sam"), 1):
        lines = (dnp / source).read_text().splitlines()
        header = [line for line in lines if line.startswith("@")] + [line for line in snp_lines if line.startswith("@SQ")]
        reads = [f"sample{index}_" + line for line in lines + snp_lines if not line.startswith("@")]
        sam = inputs / f"sample_{index:04d}.sam"
        sam.write_text("\n".join(header + reads) + "\n")
        bam = inputs / f"sample_{index:04d}.bam"
        subprocess.run(["samtools", "sort", "-o", str(bam), str(sam)], check=True)
        subprocess.run(["samtools", "index", str(bam)], check=True)
    (inputs / "dnp-panel.tsv").write_bytes((dnp / "DNP_list.txt").read_bytes())
    (inputs / "snp-panel.tsv").write_bytes((snp / "SNPlist.tsv").read_bytes())
    (inputs / "snp-positions.tsv").write_text("chr\tpos\nchrSynthetic\t50\nchrSynthetic\t120\n")
    (inputs / "dnp-frequency.tsv").write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" +
        "".join(f"chrDnpSynthetic\t{position}\t{position+1}\t0.6\t0.4\n" for position in (50, 140, 230)))
    (inputs / "snp-frequency.tsv").write_text("chr\tpos\tRef_f.pop\tAlt_f.pop\n" +
        "".join(f"chrSynthetic\t{position}\t0.6\t0.4\n" for position in (50, 120)))
    input_hashes = {str(path): digest(path) for path in inputs.iterdir() if path.is_file()}
    ids = ("mother", "father", "child")
    plan = {"schema_version": 1, "samples": [
        {"id": name, "kind": "bam", "path": str(inputs / f"sample_{number:04d}.bam")}
        for number, name in enumerate(ids, 1)], "steps": [],
        "presentation": {"samples": {name: name + "_synthetic.bam" for name in ids}, "pairs": {}}}
    plan["steps"].append({"id": "dnp", "workflow": "dnp-call", "inputs": {
        "samples": list(ids), "panel": str(inputs / "dnp-panel.tsv"), "reference": str(reference)},
        "parameters": {"parallel": True}})
    for name in ids:
        plan["steps"].append({"id": "snp_" + name, "workflow": "snp-call", "inputs": {
            "sample": name, "panel": str(inputs / "snp-panel.tsv"), "reference": str(reference)}, "parameters": {"mode": "bam"}})
    for marker in ("dnp", "snp"):
        def ref(name):
            return {"step": "dnp" if marker == "dnp" else "snp_" + name, "output": marker + "-tables", "sample": name}
        plan["steps"].extend([
            {"id": marker + "_contamination", "workflow": "contamination", "inputs": {
                "samples": [ref(name) for name in ids], "panel": str(inputs / ("dnp-panel.tsv" if marker == "dnp" else "snp-panel.tsv"))}, "parameters": {}},
            {"id": marker + "_cpi", "workflow": "cpi", "inputs": {
                "pairs": [{"id": marker + "_prenatal", "mother": ref("mother"), "father": ref("father")}],
                "popfreq": str(inputs / (marker + "-frequency.tsv")), "cutoffs": []}, "parameters": {"cutoff_mode": "all"}},
            {"id": marker + "_cpin", "workflow": "cpin", "inputs": {
                "trios": [{"id": marker + "_postnatal", "mother": ref("mother"), "father": ref("father"), "child": ref("child")}],
                "popfreq": str(inputs / (marker + "-frequency.tsv")), "markers": str(inputs / (marker + "-panel.tsv"))}, "parameters": {}},
        ])
    helper = PROJECT / "src/nipat_scientific"
    os.environ.update({"NIPAT_PARALLEL_HELPER": str(helper / "parallel.R"), "NIPAT_PLOTS_HELPER": str(helper / "plots.R"),
                       "NIPAT_DNP_BLOCKS_HELPER": str(helper / "dnp_blocks.R"), "NIPAT_DNP_PILEUP_HELPER": str(helper / "dnp_pileup.py")})
    scripts = {"dnp-call": PROJECT / "scientific/vendor/DNPcall/DNPcall.R", "snp-call": PROJECT / "scientific/vendor/NEWPAT/SNPcall/SNPcall.R",
               "contamination": PROJECT / "scientific/vendor/NEWPAT/contamination/detect_contamination.R",
               "cpi": PROJECT / "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
               "cpin": PROJECT / "scientific/vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R"}
    source_hashes = {str(path): digest(path) for path in [Path(__file__).resolve(), PROJECT / "engine/main.py", *scripts.values(), *helper.glob("*.py"), *helper.glob("*.R"), helper / "settings_data.json"]}
    results, tables = {}, {}
    for mode in ("serial", "capped"):
        os.environ.update({"NIPAT_EXECUTION_MODE": "serial" if mode == "serial" else "auto", "NIPAT_MAX_WORKERS": "2"})
        run = destination / mode
        result = execute_plan(plan, run_dir=run, script_paths=scripts)
        if result["status"] != "succeeded":
            raise AssertionError(f"{mode}: {result['error']}; inspect {run / 'workflow-state.json'}")
        results[mode] = {"status": result["status"], "steps": len(result["steps"]), "snp_parallel": result.get("snp_parallel")}
        tables[mode] = {str(path.relative_to(run)): digest(path) for path in run.glob("steps/*/output/**/*")
                        if path.is_file() and path.suffix in {".txt", ".tsv", ".csv"}
                        and "presentation" not in path.parts and path.name != "resources.tsv"}
    if tables["serial"] != tables["capped"]:
        raise AssertionError("Serial/capped scientific tables differ")
    if results["capped"]["snp_parallel"]["workers"] != 2:
        raise AssertionError("Capped run did not exercise two SNP workers")
    for path, expected in {**original, **input_hashes, **source_hashes}.items():
        if digest(Path(path)) != expected:
            raise AssertionError(f"Input or execution source changed: {path}")
    report = {"status": "passed", "bam_count": 3, "scope": "all five modules, both marker branches, presentation and original inputs",
              "runs": results, "identical_scientific_tables": len(tables["serial"]),
              "input_sha256": input_hashes, "fixture_sha256": original,
              "script_sha256": {name: source_hashes[str(path)] for name, path in scripts.items()}, "engine_sha256": source_hashes}
    (destination / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    print(json.dumps(qualify(args.output), indent=2))
