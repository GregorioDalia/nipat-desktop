"""Audit the production DNP pileup helper against unchanged samtools mpileup.

Run with the pinned runtime samtools, using only generated reads. This is a
Linux process test: cancellation deliberately pauses a real samtools child,
then verifies that cancelling its parent reaps the child and removes outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def execute(arguments: list[str], *, output: Path | None = None) -> bytes:
    result = subprocess.run(arguments, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {arguments}\n{result.stderr.decode(errors='replace')}")
    if output is not None:
        output.write_bytes(result.stdout)
    return result.stdout


def fixture(root: Path, samtools: str) -> dict[str, Path]:
    sequence = "ACGT" * 250
    reference = root / "reference.fa"
    # Deliberately not lexical order, with enough independent tasks to exercise
    # both the two-process and four-process acquisition budgets.
    contigs = ("chr2", "chr1", "chr10", "chr3")
    reference.write_text("".join(f">{chrom}\n{sequence}\n" for chrom in contigs), encoding="utf-8")
    bed = root / "panel.bed"
    bed.write_text("chr1\t48\t53\nchr2\t138\t143\nchr2\t48\t52\nchr2\t50\t54\nchr2\t228\t233\n"
                   "chr3\t48\t53\nchr10\t48\t53\n", encoding="utf-8")
    header = "@HD\tVN:1.6\tSO:coordinate\n" + "".join(
        f"@SQ\tSN:{chrom}\tLN:1000\n" for chrom in contigs)
    records = []

    def row(name, start, cigar="80M", bases=None, flag=0, chrom="chr2", mate="*", matepos=0, tlen=0):
        if bases is None:
            bases = sequence[start - 1:start + 79]
        records.append("\t".join(map(str, (name, flag, chrom, start, 60, cigar, mate, matepos, tlen, bases, "I" * len(bases)))))

    # More than the unchanged default 8000-depth limit. Coordinate order and
    # alternating alleles make changes to the retained read set observable.
    for index in range(20050):
        start = 20 + index % 31
        bases = list(sequence[start - 1:start + 79])
        if index % 3 == 1:
            bases[50 - start] = "T" if bases[50 - start] != "T" else "C"
        row(f"dense_{index:06}", start, bases="".join(bases))
    for start in (120, 210):
        for index in range(12):
            row("shared" if index < 3 else f"other_{index}", start)
    row("del", 10, "40M1D39M", sequence[9:49] + sequence[50:89])
    row("ins", 10, "40M1I40M", sequence[9:49] + "A" + sequence[49:89])
    row("spanning", 20, "250M", sequence[19:269])
    for index in range(50):
        row(f"pair{index}", 20, flag=99, mate="=", matepos=50, tlen=110)
        row(f"pair{index}", 50, flag=147, mate="=", matepos=20, tlen=-110)
    for flag in (256, 512, 1024):
        row(f"filtered_{flag}", 20, flag=flag)
    for chrom in contigs[1:]:
        for index in range(20050):
            start = 20 + index % 31
            bases = list(sequence[start - 1:start + 79])
            if index % 3 == 1:
                bases[50 - start] = "T" if bases[50 - start] != "T" else "C"
            row(f"{chrom}_{index:06}", start, chrom=chrom, bases="".join(bases))
    dense_sam = root / "dense.sam"
    dense_sam.write_text(header + "\n".join(records) + "\n", encoding="utf-8")
    sparse_sam = root / "sparse.sam"
    sparse_sam.write_text(header + "\n".join(records[-10:]) + "\n", encoding="utf-8")
    paths = {"reference": reference, "bed": bed}
    for name, sam in (("dense", dense_sam), ("sparse", sparse_sam)):
        bam = root / f"{name}.bam"
        execute([samtools, "sort", "-O", "BAM", "-o", str(bam), str(sam)])
        execute([samtools, "index", str(bam)])
        paths[name] = bam
    execute([samtools, "faidx", str(reference)])
    return paths


def children(pid: int) -> list[int]:
    try:
        return [int(value) for value in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
    except ProcessLookupError:
        return []  # A child can exit between enumeration and the proc read.
    except FileNotFoundError:
        # Some rootless Linux runtimes expose status but omit task/children.
        found = []
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                status = dict(line.split(":", 1) for line in (entry / "status").read_text().splitlines() if ":" in line)
                if int(status["PPid"]) == pid:
                    found.append(int(entry.name))
            except (FileNotFoundError, ProcessLookupError):
                pass
        return found


def samtools_descendants(pid: int) -> list[int]:
    found = []
    pending = children(pid)
    while pending:
        child = pending.pop()
        pending.extend(children(child))
        try:
            if Path(f"/proc/{child}/comm").read_text().strip() == "samtools":
                found.append(child)
        except (FileNotFoundError, ProcessLookupError):
            pass
    return found


def process_budget(workers: int, mode: str = "auto") -> dict:
    """An explicit allocation, as supplied by the shared R resource policy."""
    return {"mode": mode, "workers": workers, "max_workers": workers,
            "tasks": 2147483647, "cpu_limit": workers,
            "memory_available_mib": 32768, "memory_per_worker_mib": 2048,
            "memory_worker_limit": 12, "reason": "qualification"}


def observe_helper(command: list[str], work: Path, maximum: int) -> int:
    """Observe real samtools children, independently of the helper's own log."""
    peak = 0
    with (work / "helper.stdout").open("wb") as stdout, (work / "helper.stderr").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        try:
            deadline = time.monotonic() + 120
            while process.poll() is None:
                peak = max(peak, len(samtools_descendants(process.pid)))
                if peak > maximum:
                    raise AssertionError(f"Acquisition exceeded its process budget: {peak} > {maximum}")
                if time.monotonic() > deadline:
                    raise AssertionError("Timed out observing acquisition")
                time.sleep(0.005)
            if process.returncode:
                raise AssertionError(f"Acquisition failed ({process.returncode}): "
                                     + (work / "helper.stderr").read_text(errors="replace"))
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    return peak


def overlap_count(records: list[dict]) -> int:
    events = []
    for record in records:
        start, finish = record.get("started_at_unix"), record.get("finished_at_unix")
        if not isinstance(start, (int, float)) or not isinstance(finish, (int, float)) or finish < start:
            raise AssertionError("Missing or invalid chromosome process timestamps")
        if not isinstance(record.get("pid"), int) or record["pid"] <= 0:
            raise AssertionError("Missing chromosome process identity")
        if record.get("returncode") != 0 or record.get("outcome") != "succeeded":
            raise AssertionError("A chromosome did not finish successfully")
        events.extend(((start, 1), (finish, -1)))
    active = peak = 0
    for _, change in sorted(events):
        active += change
        peak = max(peak, active)
    return peak


def audit(project: Path, root: Path, samtools: str) -> dict:
    resolved = shutil.which(samtools)
    if resolved is None:
        raise ValueError(f"samtools is not available: {samtools}")
    samtools = str(Path(resolved).resolve())
    # The production CLI also resolves samtools through PATH. Pin both sides
    # to the requested executable, rather than comparing different versions.
    os.environ["PATH"] = str(Path(samtools).parent) + os.pathsep + os.environ.get("PATH", "")
    root.mkdir(parents=True, exist_ok=False)
    paths = fixture(root, samtools)
    helper = project / "src/nipat_scientific/dnp_pileup.py"
    helper_sha256 = hashlib.sha256(helper.read_bytes()).hexdigest()
    mpileup = [samtools, "mpileup", "-l", str(paths["bed"]), "-f", str(paths["reference"]),
               "--output-QNAME", "--no-output-ins", "--no-output-del", "--no-output-ends"]
    # Compare the alignment stream as well as the pileup; -M must deduplicate
    # reads crossing several BED intervals while preserving coordinate order.
    selection = [samtools, "view", "-h", "--no-PG", "-L", str(paths["bed"])]
    sequential = execute([*selection, str(paths["dense"])])
    indexed = execute([*selection, "-M", str(paths["dense"])])
    if sequential != indexed:
        raise AssertionError("The indexed alignment stream differs")
    scenarios = []

    def arguments(name, bams, *, budget=None, panel=None, reference=None):
        work = root / name
        work.mkdir()
        bamlist = work / "bamlist.txt"
        bamlist.write_text("\n".join(str(path) for path in bams) + "\n", encoding="utf-8")
        output, metadata = work / "pileup.txt", work / "metadata.json"
        command = [sys.executable, str(helper), "--bamlist", str(bamlist),
            "--bed", str(panel or paths["bed"]), "--reference", str(reference or paths["reference"]), "--output", str(output),
            "--scratch-dir", str(work), "--metadata", str(metadata)]
        if budget is not None:
            allocation = work / "budget.json"
            allocation.write_text(json.dumps(budget) + "\n", encoding="utf-8")
            command.extend(("--budget", str(allocation)))
        return work, bamlist, output, metadata, command

    def compare(name, bams, strategy):
        work, bamlist, output, metadata, command = arguments(name, bams)
        expected = execute([*mpileup, "-b", str(bamlist)], output=work / "sequential.pileup")
        execute(command, output=work / "helper.stdout")
        actual = output.read_bytes()
        details = json.loads(metadata.read_text())
        if not expected or expected != actual:
            raise AssertionError(f"Exact pileup comparison failed: {name}")
        if details["status"] != "succeeded" or details["strategy"] != strategy:
            raise AssertionError(f"Unexpected helper path: {name}: {details}")
        depths = [int(line.split(b"\t")[3]) for line in actual.splitlines()]
        scenarios.append({"case": name, "status": "passed", "strategy": strategy,
                          "pileup_sha256": hashlib.sha256(actual).hexdigest(),
                          "size_bytes": len(actual), "rows": len(depths), "maximum_first_sample_depth": max(depths)})

    def compare_budget(name, bams, workers, *, mode="auto", panel=None, reference=None,
                       strategy="indexed-chromosomes", reason=None, expected_contigs=None,
                       require_overlap=False, allow_empty=False):
        work, bamlist, output, metadata, command = arguments(
            name, bams, budget=process_budget(workers, mode), panel=panel, reference=reference)
        oracle = [samtools, "mpileup", "-l", str(panel or paths["bed"]),
                  "-f", str(reference or paths["reference"]), *mpileup[6:], "-b", str(bamlist)]
        expected = execute(oracle, output=work / "sequential.pileup")
        observed = observe_helper(command, work, workers)
        actual = output.read_bytes()
        details = json.loads(metadata.read_text())
        if (not expected and not allow_empty) or expected != actual:
            raise AssertionError(f"Exact budgeted pileup comparison failed: {name}")
        if details.get("status") != "succeeded" or details.get("strategy") != strategy:
            raise AssertionError(f"Unexpected budgeted helper path: {name}: {details}")
        parallel = details.get("parallel", {})
        if reason is not None and parallel.get("reason") != reason:
            raise AssertionError(f"Missing fallback explanation: {name}: {parallel}")
        if parallel.get("workers", workers + 1) > workers:
            raise AssertionError(f"Recorded allocation exceeds the requested budget: {name}")
        records = [item for item in details["processes"] if item.get("stage") == "mpileup-chromosome"]
        overlap = overlap_count(records) if records else 0
        if overlap > workers or parallel.get("observed_max_processes", workers + 1) > workers:
            raise AssertionError(f"Recorded processes exceed the requested budget: {name}")
        if expected_contigs is not None:
            if [item.get("contig") for item in sorted(records, key=lambda item: item["task_index"])] != expected_contigs:
                raise AssertionError(f"Chromosome ordering differs from BAM dictionary: {name}")
        if require_overlap and (observed < 2 or overlap < 2):
            raise AssertionError(f"The parallel case did not actually overlap samtools processes: {name}")
        scenarios.append({"case": name, "status": "passed", "strategy": strategy,
                          "mode": mode, "process_budget": workers,
                          "observed_samtools_maximum": observed, "recorded_overlap": overlap,
                          "pileup_sha256": hashlib.sha256(actual).hexdigest(),
                          "size_bytes": len(actual), "rows": len(actual.splitlines())})
        return details

    compare("indexed-single", [paths["dense"]], "indexed-pipe")
    if scenarios[-1]["maximum_first_sample_depth"] < 8000:
        raise AssertionError("Synthetic coverage did not reach the unchanged default depth limit")
    compare("indexed-multiple", [paths["sparse"], paths["dense"]], "indexed-disk")
    missing = root / "missing-index.bam"
    shutil.copyfile(paths["dense"], missing)
    compare("missing-index", [missing], "sequential")
    compare("mixed-index", [missing, paths["sparse"]], "indexed-disk")

    contigs = ["chr2", "chr1", "chr10", "chr3"]
    compare_budget("chromosomes-serial", [paths["dense"]], 1, mode="serial", expected_contigs=contigs)
    compare_budget("chromosomes-auto-1", [paths["dense"]], 1, expected_contigs=contigs)
    compare_budget("chromosomes-auto-2", [paths["dense"]], 2, expected_contigs=contigs, require_overlap=True)
    compare_budget("chromosomes-auto-4", [paths["dense"]], 4, expected_contigs=contigs, require_overlap=True)
    compare_budget("chromosomes-auto-4-repeat", [paths["dense"]], 4,
                   expected_contigs=contigs, require_overlap=True)
    compare_budget("chromosomes-multiple", [paths["sparse"], paths["dense"]], 4,
                   expected_contigs=contigs, require_overlap=True)
    compare_budget("budgeted-missing-index", [missing], 4,
                   strategy="sequential-budgeted", reason="missing-index")
    compare_budget("budgeted-mixed-index", [missing, paths["sparse"]], 2,
                   strategy="sequential-budgeted", reason="missing-index")

    unknown_panel = root / "unknown-panel.bed"
    unknown_panel.write_text(paths["bed"].read_text() + "not_in_bam\t10\t20\n", encoding="utf-8")
    compare_budget("chromosomes-unknown-panel-contig", [paths["dense"]], 2,
                   panel=unknown_panel, expected_contigs=contigs, require_overlap=True)
    single_panel = root / "single-contig.bed"
    single_panel.write_text("chr10\t48\t53\n", encoding="utf-8")
    compare_budget("chromosomes-single-task", [paths["dense"]], 4,
                   panel=single_panel, expected_contigs=["chr10"])
    empty_panel = root / "empty-selection.bed"
    empty_panel.write_text("not_in_bam\t10\t20\n", encoding="utf-8")
    compare_budget("chromosomes-empty-selection", [paths["dense"]], 4, panel=empty_panel,
                   strategy="sequential-budgeted", reason="no-panel-contigs", allow_empty=True)

    # The old whole-file mpileup accepts a different length declaration in a
    # second BAM. The partition planner must retain that behavior via fallback,
    # rather than silently choosing one of two incompatible dictionaries.
    changed_header = root / "different-dictionary.sam"
    header = execute([samtools, "view", "-H", str(paths["sparse"])]).decode()
    changed_header.write_text(header.replace("LN:1000", "LN:1001", 1), encoding="utf-8")
    changed_bam = root / "different-dictionary.bam"
    execute([samtools, "reheader", str(changed_header), str(paths["sparse"])], output=changed_bam)
    execute([samtools, "index", str(changed_bam)])
    compare_budget("budgeted-incompatible-dictionaries", [paths["dense"], changed_bam], 4,
                   strategy="sequential-budgeted", reason="incompatible-dictionaries")

    unknown_order_header = root / "non-coordinate-header.sam"
    unknown_order_header.write_text(header.replace("SO:coordinate", "SO:unknown"), encoding="utf-8")
    unknown_order_bam = root / "non-coordinate-header.bam"
    execute([samtools, "reheader", str(unknown_order_header), str(paths["sparse"])], output=unknown_order_bam)
    execute([samtools, "index", str(unknown_order_bam)])
    compare_budget("budgeted-non-coordinate-header", [unknown_order_bam], 4,
                   strategy="sequential-budgeted", reason="non-coordinate-header")

    # A legal SAM reference name containing ':' is ambiguous to a region parser.
    # The fallback must preserve the full-stream behavior instead of rewriting it.
    sequence = "ACGT" * 250
    for case, contig in (("ambiguous-contig", "chr1:odd"), ("special-dot-contig", ".")):
        ambiguous_reference = root / f"{case}.fa"
        ambiguous_reference.write_text(f">{contig}\n{sequence}\n", encoding="utf-8")
        execute([samtools, "faidx", str(ambiguous_reference)])
        ambiguous_sam = root / f"{case}.sam"
        ambiguous_sam.write_text(f"@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:{contig}\tLN:1000\n" +
            "".join(f"ambiguous_{index}\t0\t{contig}\t20\t60\t80M\t*\t0\t0\t"
                    f"{sequence[19:99]}\t{'I' * 80}\n" for index in range(10)), encoding="utf-8")
        ambiguous_bam = root / f"{case}.bam"
        execute([samtools, "sort", "-O", "BAM", "-o", str(ambiguous_bam), str(ambiguous_sam)])
        execute([samtools, "index", str(ambiguous_bam)])
        ambiguous_panel = root / f"{case}.bed"
        ambiguous_panel.write_text(f"{contig}\t48\t53\n", encoding="utf-8")
        compare_budget(f"budgeted-{case}", [ambiguous_bam], 4,
                       panel=ambiguous_panel, reference=ambiguous_reference,
                       strategy="sequential-budgeted", reason="ambiguous-contig")

    corrupt = root / "corrupt-index.bam"
    shutil.copyfile(paths["dense"], corrupt)
    corrupt.with_suffix(".bam.bai").write_bytes(b"not a BAM index\n")
    work, bamlist, output, metadata, command = arguments("corrupt-index", [corrupt])
    failed = subprocess.run(command, capture_output=True, timeout=30)
    if failed.returncode == 0 or output.exists() or json.loads(metadata.read_text())["status"] != "failed":
        raise AssertionError("An existing corrupt index was silently accepted or left a partial output")
    if list(work.glob(".pileup-*.partial")) or list(work.glob("indexed-*")):
        raise AssertionError("A failed acquisition left staged intermediates")
    scenarios.append({"case": "corrupt-index", "status": "passed", "behavior": "fails without sequential fallback"})

    for name, bams in (("budgeted-corrupt-index", [corrupt]),
                       ("budgeted-mixed-corrupt-index", [missing, corrupt]),
                       ("budgeted-dictionary-corrupt-index", [corrupt, changed_bam])):
        work, bamlist, output, metadata, command = arguments(name, bams, budget=process_budget(4))
        failed = subprocess.run(command, capture_output=True, timeout=30)
        if failed.returncode == 0 or output.exists() or json.loads(metadata.read_text())["status"] != "failed":
            raise AssertionError(f"Budgeted acquisition ignored a corrupt index or left a partial output: {name}")
        if list(work.glob(".pileup-*.partial")) or list(work.glob("indexed-*")):
            raise AssertionError("Failed budgeted acquisition left staged intermediates")
        scenarios.append({"case": name, "status": "passed", "behavior": "fails without sequential fallback"})

    def cancel_case(name, *, budget=None, minimum_children=1):
        work, bamlist, output, metadata, command = arguments(name, [paths["dense"]], budget=budget)
        with (work / "stdout.log").open("wb") as stdout, (work / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            paused = []
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    candidates = samtools_descendants(process.pid)
                    # A budgeted run reads headers serially first. Do not pause
                    # that probe: this case must cancel a genuinely active pool.
                    if len(candidates) >= minimum_children:
                        for pid in candidates:
                            try:
                                os.kill(pid, signal.SIGSTOP)
                                paused.append(pid)
                            except ProcessLookupError:
                                pass
                    if len(paused) >= minimum_children:
                        break
                    time.sleep(0.001)
                if len(paused) < minimum_children:
                    raise AssertionError(f"Could not pause {minimum_children} real samtools children: {name}")
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=15)
                if process.returncode != 128 + signal.SIGTERM:
                    raise AssertionError(f"Cancellation exit status was {process.returncode}")
                if output.exists() or json.loads(metadata.read_text())["status"] != "cancelled":
                    raise AssertionError("Cancelled helper left output or failed to record cancellation")
                if list(work.glob(".pileup-*.partial")) or list(work.glob("indexed-*")):
                    raise AssertionError("Cancellation left staged intermediates")
                if any(Path(f"/proc/{pid}").exists() for pid in paused):
                    raise AssertionError("Cancellation left a paused samtools child")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for pid in paused:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        scenarios.append({"case": name, "status": "passed", "paused_children": len(paused),
                          "behavior": "paused real samtools reaped; partial output removed"})

    cancel_case("cancellation")
    cancel_case("parallel-cancellation", budget=process_budget(4), minimum_children=2)
    if hashlib.sha256(helper.read_bytes()).hexdigest() != helper_sha256:
        raise AssertionError("The acquisition helper changed during qualification")
    return {"schema_version": 1, "status": "passed", "samtools_version": execute([samtools, "--version"]).decode().splitlines()[0],
            "helper_sha256": helper_sha256, "exact_alignment_stream": True,
            "scientific_options": "unchanged samtools mpileup defaults; BAQ and depth limit preserved",
            "coverage": ["overlapping BED intervals", "unsorted panel", "nonlexical contigs", "read crossing disjoint windows",
                         "repeated QNAME", "insertions and deletions", "overlapping paired reads", "filtered flags", "depth above 8000",
                         "one/two/four-process budgets", "actual samtools overlap", "parallel repeated run",
                         "multi-BAM column order", "incompatible dictionaries", "non-coordinate header", "ambiguous contig",
                         "unknown BED contig", "empty selection",
                         "missing/mixed/corrupt indexes", "parallel cancellation"],
            "cases": scenarios}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samtools", default="samtools")
    args = parser.parse_args()
    report = audit(args.project.resolve(), args.output_dir.resolve(), args.samtools)
    (args.output_dir / "indexed-pileup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
