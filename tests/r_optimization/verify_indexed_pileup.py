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
    reference.write_text(f">chr2\n{sequence}\n>chr1\n{sequence}\n", encoding="utf-8")
    bed = root / "panel.bed"
    bed.write_text("chr1\t48\t53\nchr2\t138\t143\nchr2\t48\t52\nchr2\t50\t54\nchr2\t228\t233\n", encoding="utf-8")
    header = "@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr2\tLN:1000\n@SQ\tSN:chr1\tLN:1000\n"
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
    for index in range(10):
        row(f"chr1_{index}", 20, chrom="chr1")
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
        except FileNotFoundError:
            pass
    return found


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

    def arguments(name, bams):
        work = root / name
        work.mkdir()
        bamlist = work / "bamlist.txt"
        bamlist.write_text("\n".join(str(path) for path in bams) + "\n", encoding="utf-8")
        output, metadata = work / "pileup.txt", work / "metadata.json"
        return work, bamlist, output, metadata, [sys.executable, str(helper), "--bamlist", str(bamlist),
            "--bed", str(paths["bed"]), "--reference", str(paths["reference"]), "--output", str(output),
            "--scratch-dir", str(work), "--metadata", str(metadata)]

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

    compare("indexed-single", [paths["dense"]], "indexed-pipe")
    if scenarios[-1]["maximum_first_sample_depth"] < 8000:
        raise AssertionError("Synthetic coverage did not reach the unchanged default depth limit")
    compare("indexed-multiple", [paths["sparse"], paths["dense"]], "indexed-disk")
    missing = root / "missing-index.bam"
    shutil.copyfile(paths["dense"], missing)
    compare("missing-index", [missing], "sequential")
    compare("mixed-index", [missing, paths["sparse"]], "indexed-disk")
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

    work, bamlist, output, metadata, command = arguments("cancelled", [paths["dense"]])
    with (work / "stdout.log").open("wb") as stdout, (work / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        paused = []
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                for pid in samtools_descendants(process.pid):
                    try:
                        os.kill(pid, signal.SIGSTOP)
                        paused.append(pid)
                    except ProcessLookupError:
                        pass
                if paused:
                    break
                time.sleep(0.001)
            if not paused:
                raise AssertionError("Could not observe and pause an active real samtools child")
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
    scenarios.append({"case": "cancellation", "status": "passed", "behavior": "paused real samtools reaped; partial output removed"})
    return {"schema_version": 1, "status": "passed", "samtools_version": execute([samtools, "--version"]).decode().splitlines()[0],
            "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(), "exact_alignment_stream": True,
            "scientific_options": "unchanged samtools mpileup defaults; BAQ and depth limit preserved",
            "coverage": ["overlapping BED intervals", "unsorted panel", "nonlexical contigs", "read crossing disjoint windows",
                         "repeated QNAME", "insertions and deletions", "overlapping paired reads", "filtered flags", "depth above 8000"],
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
