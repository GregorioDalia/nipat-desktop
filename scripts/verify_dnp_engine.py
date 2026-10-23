"""Real-image DNPcall regressions, called by verify_engine_package.py.

Fixture counts are defined from artificial SAM reads, independently of R. The
native-versus-complete comparison supplements that oracle for all other fields.
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
from verify_contamination_update import check_bundled_run


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests/fixtures/dnp_engine"


def table(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def keyed_rows(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    rows = table(path)
    keyed = {(row["chr"], row["pos1"], row["pos2"]): row for row in rows}
    if len(rows) != len(keyed):
        raise ValueError(f"Duplicate DNP loci in {path}.")
    return keyed


def expected_rows(sample: str) -> dict[tuple[str, str, str], dict[str, str]]:
    return {(row["chr"], row["pos1"], row["pos2"]): row
            for row in table(FIXTURE / "expected.tsv") if row["sample"] == sample}


def check_dnp_outputs(run_dir: Path, samples: tuple[str, ...]) -> None:
    output = run_dir / "output"
    sample_ids = [f"sample_{number:04d}" for number in range(1, len(samples) + 1)]
    expected_files = {f"full_output_{sample_id}.txt" for sample_id in sample_ids}
    if {path.name for path in (output / "individual_outputs").iterdir()} != expected_files:
        raise ValueError(f"Unexpected DNP sample output names in {run_dir}.")
    summary = keyed_rows(output / "summary/output_AllGenotypes.txt")
    expected_keys = set(expected_rows(samples[0]))
    if set(summary) != expected_keys:
        raise ValueError(f"Unexpected DNP summary loci in {run_dir}.")
    summary_fields = ["chr", "pos1", "pos2", "REF", "ALT", *[f"GT_{sid}" for sid in sample_ids]]
    if list(next(iter(summary.values()))) != summary_fields:
        raise ValueError(f"Unexpected DNP summary sample order/columns in {run_dir}.")

    pdfs = {"summary/Unassigned_genotypes.pdf"}
    if len(samples) > 1:
        pdfs.add("summary/DNPs_covered_UpSet_plot.pdf")
    for sample_id, source_sample in zip(sample_ids, samples):
        expected = expected_rows(source_sample)
        actual = keyed_rows(output / "individual_outputs" / f"full_output_{sample_id}.txt")
        if set(actual) != set(expected):
            raise ValueError(f"Unexpected loci for {sample_id} in {run_dir}.")
        for key, row in actual.items():
            wanted = expected[key]
            for field in ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other",
                          "GT", "total_count"):
                if row[field] != wanted[field]:
                    raise ValueError(f"{run_dir}/{sample_id}/{key}: {field}={row[field]}, "
                                     f"expected {wanted[field]}.")
            alleles = row["combined_bases"].split("-")
            counts = row["combined_counts"].split("-")
            combined = dict(zip(alleles, map(int, counts)))
            expected_combined = {
                wanted[allele]: int(wanted[count])
                for allele, count in (("REF", "N_REF"), ("ALT", "N_ALT"), ("OTHER", "N_Other"))
                if int(wanted[count])
            }
            if len(alleles) != len(counts) or len(combined) != len(alleles) or combined != expected_combined:
                raise ValueError(f"Unexpected haplotype counts for {sample_id}/{key}: {row}.")
            if row["reads_discarded_for_indels"] != "0" or row["ratio_reads_discarded_for_indels"] != "0":
                raise ValueError(f"Unexpected discarded-indel reads for {sample_id}/{key}.")
            likelihoods = [float(row[f"GL{number}"]) for number in range(3)]
            # For g=1 every REF/ALT probability is exactly 1/2, independent of BAQ.
            heterozygous = -(int(wanted["N_REF"]) + int(wanted["N_ALT"])) * math.log(2)
            if (not all(math.isfinite(value) for value in likelihoods)
                    or not math.isclose(likelihoods[1], heterozygous, abs_tol=0.00051)
                    or ("0/0", "0/1", "1/1")[likelihoods.index(max(likelihoods))] != wanted["GT"]):
                raise ValueError(f"Unexpected likelihoods for {sample_id}/{key}: {likelihoods}.")
            for field in ("chr", "pos1", "pos2", "REF", "ALT"):
                if summary[key][field] != wanted[field]:
                    raise ValueError(f"DNP summary differs for {field}/{key}.")
            if summary[key][f"GT_{sample_id}"] != wanted["GT"]:
                raise ValueError(f"DNP summary genotype differs for {sample_id}/{key}.")
        pdfs.update(f"plots/{sample_id}/{sample_id}_{suffix}.pdf" for suffix in (
            "N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count",
        ))
    actual_pdfs = {path.relative_to(output).as_posix() for path in output.rglob("*.pdf")}
    if actual_pdfs != pdfs or any(not (output / name).read_bytes().startswith(b"%PDF-") for name in pdfs):
        raise ValueError(f"Missing, invalid or unexpected DNP plots in {run_dir}: {actual_pdfs}.")
    if any((run_dir / name).exists() for name in ("mpileup.txt", "bedfile_for_mpileup.bed")):
        raise ValueError("DNPcall did not remove its native temporary pileup/BED after success.")


def compare_dnp_tables(first: Path, second: Path) -> None:
    """Compare all scientific fields, including GL, but not PDF metadata/times."""
    first_tables = {path.relative_to(first / "output"): path
                    for path in (first / "output").rglob("*.txt")}
    second_tables = {path.relative_to(second / "output"): path
                     for path in (second / "output").rglob("*.txt")}
    if set(first_tables) != set(second_tables):
        raise ValueError("DNPcall table names differ between execution modes.")
    for name, path in first_tables.items():
        if keyed_rows(path) != keyed_rows(second_tables[name]):
            raise ValueError(f"DNPcall output differs between execution modes: {name}.")


def check_dnp_preparation(run_dir: Path, sample_paths: list[str]) -> None:
    # Explicit oracle: expected normalized uppercase panel, preserving input order.
    expected_panel = "".join(
        f"chrDnpSynthetic\t{position}\t{position + 1}\t{ref}\t{alt}\n"
        for position, ref, alt in ((50, "AC", "GT"), (140, "TA", "CG"), (230, "GC", "AT"))
    )
    if (run_dir / "work/DNP_list.txt").read_text(encoding="utf-8") != expected_panel:
        raise ValueError("DNP engine panel normalization differs from the independent fixture.")
    if (run_dir / "work/bamlist.txt").read_text(encoding="utf-8").splitlines() != sample_paths:
        raise ValueError("DNP engine BAM order/aliases differ from the selected samples.")


def check_dnp_workflow(identifier: str, root: Path, *, run_container, run_image,
                       write_request) -> Path:
    generated = root / "generated DNP assets"
    inputs = generated / "work"
    (inputs / "bams").mkdir(parents=True)
    for name in ("reference.fa", "DNP_list.txt"):
        shutil.copyfile(FIXTURE / name, inputs / name)
    for number, sample in enumerate(("A", "B"), start=1):
        run_container(identifier, [
            "samtools", "view", "-b", "-o", f"/results/work/bams/sample_{number:04d}.bam",
            f"/inputs/reads_{sample}.sam",
        ], inputs=FIXTURE, results=generated)
    run_container(identifier, ["samtools", "faidx", "/results/work/reference.fa"], results=generated)
    originals = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    if any(inputs.rglob("*.bai")) or any(inputs.rglob("*.csi")):
        raise ValueError("The DNP BAM fixture must exercise unindexed input.")
    selected = [f"/inputs/bams/sample_{number:04d}.bam" for number in (1, 2)]
    complete = root / "complete DNP results"
    write_request(complete, {
        "schema_version": 1, "workflow": "dnp-call", "panel": "/inputs/DNP_list.txt",
        "samples": [{"path": path, "sample_id": f"sample_{number:04d}"}
                    for number, path in enumerate(selected, 1)],
        "reference": "/inputs/reference.fa", "parallel": False,
        "work_dir": "/results/work", "out_dir": "/results/output",
    })
    run_image(identifier, ["execute", "dnp-call", "--request", "/results/work/request.json"],
              inputs=inputs, results=complete)
    check_dnp_outputs(complete, ("A", "B"))
    check_dnp_preparation(complete, selected)

    native = root / "native DNP results"
    (native / "work").mkdir(parents=True)
    # Construct the unchanged R interface independently of engine preparation.
    (native / "work/bamlist.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
    (native / "work/DNP_list.txt").write_text(
        "chrDnpSynthetic\t50\t51\tAC\tGT\n"
        "chrDnpSynthetic\t140\t141\tTA\tCG\n"
        "chrDnpSynthetic\t230\t231\tGC\tAT\n", encoding="utf-8",
    )
    run_container(identifier, [
        "python3", "/opt/nipat/engine/main.py", "run", "dnp-call", "--",
        "--bamlist=work/bamlist.txt", "--DNPs=work/DNP_list.txt",
        "--reference=/inputs/reference.fa", "--out=output",
    ], inputs=inputs, results=native, working_dir="/results")
    check_dnp_outputs(native, ("A", "B"))
    compare_dnp_tables(native, complete)
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("The complete/native DNP workflows modified an original input.")
    print("PASS: complete DNPcall, two unindexed BAMs, independent counts/genotypes, "
          "native R parity for all table fields and ten PDFs.", flush=True)
    return inputs


def check_dnp_client_without_host_scripts(identifier: str, root: Path, inputs: Path) -> None:
    project = root / "DNP client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "DNP client data", root / "DNP client results",
                           project / "compose.yaml")
    originals_dir = root / "DNP original inputs with spaces"
    originals_dir.mkdir()
    # Same original basename, containing spaces and non-ASCII characters, in
    # distinct folders: aliases must be based on selection order, not basenames.
    original_bams = []
    for number, sample in enumerate(("A", "B"), start=1):
        destination = originals_dir / f"campione {sample}" / "stesso campione è.bam"
        destination.parent.mkdir()
        shutil.copyfile(inputs / f"bams/sample_{number:04d}.bam", destination)
        original_bams.append(destination)
    reference = originals_dir / "riferimento è.fa"
    shutil.copyfile(inputs / "reference.fa", reference)
    shutil.copyfile(inputs / "reference.fa.fai", Path(str(reference) + ".fai"))
    panel = originals_dir / "pannello è.txt"
    shutil.copyfile(inputs / "DNP_list.txt", panel)
    bamlist = originals_dir / "lista relativa.txt"
    # Reverse source order, double- and single-quoted relative paths, blank line,
    # UTF-8 BOM: the list represents the same B,A order as the explicit selection.
    selected_bams = [original_bams[1], original_bams[0]]
    bamlist.write_text(
        f'"{selected_bams[0].relative_to(originals_dir).as_posix()}"\n\n'
        f"'{selected_bams[1].relative_to(originals_dir).as_posix()}'\n", encoding="utf-8-sig",
    )
    originals = {path: path.read_bytes() for path in originals_dir.rglob("*") if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        workflow = Workflows(layout, DockerComposeRunner(layout))
        single = workflow.dnp_call(bam=original_bams[0], reference=reference, panel=panel,
                                   run_name="complete-dnp-single")
        sequential = workflow.dnp_call(bams=selected_bams, reference=reference, panel=panel,
                                       run_name="complete-dnp-multiple")
        parallel = workflow.dnp_call(bamlist=bamlist, reference=reference, panel=panel,
                                     parallel=True, run_name="complete-dnp-bamlist-parallel")
    for run, samples, original_paths, is_parallel in (
        (single, ("A",), [original_bams[0]], False),
        (sequential, ("B", "A"), selected_bams, False),
        (parallel, ("B", "A"), selected_bams, True),
    ):
        check_dnp_outputs(run, samples)
        check_bundled_run(run, layout, workflow="dnp-call")
        mapped = [{"sample_id": f"sample_{number:04d}", "original_path": str(path),
                   "container_path": f"/workspace/inputs/bams/sample_{number:04d}.bam"}
                  for number, path in enumerate(original_paths, 1)]
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        parameters = record["parameters"]
        if (parameters["sample_mapping"] != mapped or parameters["parallel"] is not is_parallel
                or parameters["bams"] != [str(path) for path in original_paths]
                or parameters["bamlist"] != (str(bamlist) if is_parallel else None)):
            raise ValueError(f"CLI DNP sample mapping or options were not preserved: {run}.")
        check_dnp_preparation(run, [item["container_path"] for item in mapped])
    compare_dnp_tables(sequential, parallel)
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("The CLI DNP workflows modified an original input.")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("The DNP source-free application directory was unexpectedly populated.")
    print("PASS: CLI DNPcall single/multiple/relative-bamlist inputs without host scientific sources; "
          "duplicate basename mapping, all-field sequential/parallel parity and isolated mounts.", flush=True)
