"""Acquire DNP pileup within the shared scientific process budget.

The BED comes from DNPcall and acquisition options from the scientific registry.
Indexed view selects alignments overlapping the same BED; reads are not
deduplicated by name and original BAMs remain read-only. Default quality,
filter and depth options preserve the original acquisition behavior.
An explicit R-owned budget enables whole-chromosome indexed tasks, with exactly
one samtools process per task. Output is reassembled in BAM dictionary order.
The unbudgeted API retains the 0.8.12 acquisition path for regression comparison.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

# R invokes this source-verified helper by its absolute filename. Resolve only
# the sibling installed package, never the caller's working directory.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nipat_scientific import progress
from nipat_scientific.errors import ValidationError
from nipat_scientific.files import input_text, require_sidecar
from nipat_scientific.panels import read_bam_dictionary, require_bam_targets, require_reference_windows
from nipat_scientific.settings import samtools_options, settings_from_environment

MPILEUP_OPTIONS = ["--output-QNAME", "--no-output-ins", "--no-output-del", "--no-output-ends"]


class PileupError(RuntimeError):
    pass


class Cancelled(KeyboardInterrupt):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"Pileup acquisition cancelled by signal {signum}")


class Cancellation:
    def __init__(self):
        self.signum = None

    def receive(self, signum, _frame):
        self.signum = signum

    def check(self):
        if self.signum is not None:
            raise Cancelled(self.signum)


@contextmanager
def cancellation_handlers(cancellation):
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, cancellation.receive)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _stop_processes(processes):
    """Reap our direct children; do not signal the supervising R process group."""
    for process, _ in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 2.0
    for process, _ in processes:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


def _wait(processes, cancellation):
    finished = {}
    while len(finished) != len(processes):
        cancellation.check()
        for index, (process, started) in enumerate(processes):
            if index in finished:
                continue
            code = process.poll()
            if code is not None:
                finished[index] = {"returncode": code, "elapsed_seconds": time.monotonic() - started}
                if code:
                    # Group cancellation can terminate samtools just before
                    # this poll observes the signal handled by the helper.
                    cancellation.check()
                    raise PileupError(f"samtools process {index + 1} failed with exit code {code}; see stderr")
        if len(finished) != len(processes):
            time.sleep(0.05)
    cancellation.check()
    return [finished[index] for index in range(len(processes))]


def _execute(command, output, cancellation):
    processes = []
    try:
        cancellation.check()
        started = time.monotonic()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output)
        processes.append((process, started))
        return _wait(processes, cancellation)[0]
    finally:
        _stop_processes(processes)


def _pipeline(view_command, pileup_command, output, cancellation):
    processes = []
    try:
        cancellation.check()
        started = time.monotonic()
        view = subprocess.Popen(view_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        processes.append((view, started))
        cancellation.check()
        started = time.monotonic()
        pileup = subprocess.Popen(pileup_command, stdin=view.stdout, stdout=output)
        processes.append((pileup, started))
        # Without closing this duplicate FD, an early consumer failure could
        # leave view blocked forever rather than receiving a broken pipe.
        view.stdout.close()
        return _wait(processes, cancellation)
    finally:
        _stop_processes(processes)


def _index_candidates(bam):
    candidates = []
    for suffix in (".bai", ".csi"):
        for path in (Path(str(bam) + suffix), bam.with_suffix(suffix)):
            if path.is_symlink() or path.exists():
                if not path.is_file():
                    raise PileupError(f"BAM index is not a readable file: {path}")
                candidates.append(str(path))
    return list(dict.fromkeys(candidates))


def _write_json(path, document):
    descriptor, name = tempfile.mkstemp(prefix=".dnp-pileup-", suffix=".json", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _budget(value):
    """Consume the source-verified R policy; do not independently invent a pool."""
    if value is None:
        return None
    if isinstance(value, (str, os.PathLike)):
        with Path(value).open("r", encoding="utf-8") as handle:
            text = handle.read(65537)
        if len(text) > 65536:
            raise PileupError("Acquisition budget is too large")
        value = json.loads(text)
    if (not isinstance(value, dict) or not isinstance(value.get("mode"), str)
            or value["mode"] not in {"auto", "serial"}
            or type(value.get("workers")) is not int or value["workers"] < 1):
        raise PileupError("Acquisition budget requires a mode and positive whole worker count")
    workers = value["workers"]
    for key in ("max_workers", "memory_worker_limit", "cpu_limit"):
        limit = value.get(key)
        if limit is None:
            continue
        if (type(limit) not in {int, float} or not math.isfinite(limit) or limit <= 0
                or key != "cpu_limit" and int(limit) != limit):
            raise PileupError(f"Invalid acquisition budget {key}")
        workers = min(workers, max(1, math.floor(limit)))
    if value["mode"] == "serial":
        workers = 1
    return {"budget": value.copy(), "workers": workers, "tasks": 0,
            "observed_max_processes": 0, "reason": "planning"}


def _finish_record(record, process, started, cancellation):
    code = process.poll()
    record.update(returncode=code, finished_at_unix=time.time(),
                  elapsed_seconds=time.monotonic() - started,
                  outcome=("cancelled" if cancellation.signum is not None else
                           "succeeded" if code == 0 else "failed"))


def _tracked_execute(command, output, cancellation, document, record):
    """Run one planning/fallback child with the same cancellation and evidence."""
    process = None
    started = time.monotonic()
    record.update(pid=None, started_at_unix=time.time(), finished_at_unix=None,
                  elapsed_seconds=None, returncode=None, outcome="running")
    document["processes"].append(record)
    try:
        cancellation.check()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output)
        record["pid"] = process.pid
        if "parallel" in document:
            document["parallel"]["observed_max_processes"] = max(
                1, document["parallel"]["observed_max_processes"])
        _wait([(process, started)], cancellation)
    finally:
        if process is not None:
            _stop_processes([(process, started)])
            _finish_record(record, process, started, cancellation)
        else:
            record.update(outcome="cancelled" if cancellation.signum else "failed",
                          finished_at_unix=time.time(), elapsed_seconds=time.monotonic() - started)


def _chromosomes(bams, samples, bed, reference, staging, samtools, cancellation, document):
    """Validate the joint target IDs before choosing an acquisition strategy."""
    windows = []
    with input_text(bed) as handle:
        for line in handle:
            cancellation.check()
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            if (len(fields) < 3 or not fields[1].isdecimal() or not fields[2].isdecimal()
                    or int(fields[2]) <= int(fields[1])):
                raise PileupError(f"{bed.name}: invalid target interval")
            windows.append((fields[0], int(fields[1]) + 1, int(fields[2])))
    targets = require_reference_windows(require_sidecar(reference, ".fai", "Indice FASTA"), windows)
    if not targets:
        raise PileupError(f"{bed.name}: no target intervals")
    dictionary = None
    all_coordinate_sorted = True
    for number, bam in enumerate(bams, 1):
        header = staging / f"header-{number:04d}.sam"
        with header.open("xb") as handle:
            _tracked_execute([samtools, "view", "--no-PG", "-H", str(bam)], handle,
                             cancellation, document, {"stage": "header", "sample_id": samples[number - 1]["sample_id"]})
        sequences, coordinate_sorted = read_bam_dictionary(header, bam)
        require_bam_targets(bam, sequences, targets)
        order = list(sequences.items())
        # Joint mpileup matches BAM target IDs by position, even in serial mode.
        if dictionary is not None and order != dictionary:
            raise PileupError(
                f"Dizionari BAM incompatibili: i contig e le lunghezze di {bam.name} "
                f"devono coincidere nello stesso ordine con {bams[0].name}."
            )
        dictionary = order
        all_coordinate_sorted &= coordinate_sorted
    if not all(sample["indexed"] for sample in samples):
        return [], "missing-index"
    if not all_coordinate_sorted:
        return [], "non-coordinate-header"
    selected = [name for name, _ in dictionary if name in targets]
    # ':' and region metacharacters can change -r interpretation. Exotic but
    # valid BAM names still work through the unpartitioned fallback.
    if any(name == "." or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in selected):
        return [], "ambiguous-contig"
    return selected, "indexed-chromosomes"


def _parallel_chromosomes(contigs, command, staging, output, cancellation, document, metadata):
    """Bound actual samtools processes, then concatenate complete chromosomes."""
    workers = document["parallel"]["workers"]
    active = {}
    paths = []
    next_index = 0
    try:
        while next_index < len(contigs) or active:
            cancellation.check()
            while next_index < len(contigs) and len(active) < workers:
                cancellation.check()
                index, contig = next_index, contigs[next_index]
                path = staging / f"chromosome-{index:06d}.pileup"
                paths.append(path)
                record = {"stage": "mpileup-chromosome", "task_index": index + 1,
                          "contig": contig, "pid": None, "started_at_unix": time.time(),
                          "finished_at_unix": None, "elapsed_seconds": None,
                          "returncode": None, "outcome": "running"}
                document["processes"].append(record)
                started = time.monotonic()
                try:
                    with path.open("xb") as handle:
                        process = subprocess.Popen([*command, "-r", contig], stdin=subprocess.DEVNULL, stdout=handle)
                except BaseException:
                    record.update(outcome="failed", finished_at_unix=time.time(),
                                  elapsed_seconds=time.monotonic() - started)
                    raise
                record["pid"] = process.pid
                # Key by task, not PID: polling may reap a short-lived child
                # before its record is collected, allowing its PID to be reused.
                active[index] = (process, started, record)
                document["parallel"]["observed_max_processes"] = max(
                    document["parallel"]["observed_max_processes"],
                    sum(child.poll() is None for child, _, _ in active.values()))
                next_index += 1
                _write_json(metadata, document)
            completed = []
            failed = None
            for index, (process, started, record) in active.items():
                code = process.poll()
                if code is None:
                    continue
                process.wait()
                _finish_record(record, process, started, cancellation)
                completed.append(index)
                if code and failed is None:
                    failed = record
            for index in completed:
                del active[index]
            if completed:
                _write_json(metadata, document)
            if failed is not None:
                cancellation.check()
                raise PileupError(f"samtools chromosome {failed['contig']} failed with exit code {failed['returncode']}; see stderr")
            if active and not completed:
                time.sleep(0.05)
        # Concatenate in BAM dictionary order, never completion or lexical order.
        # Read fixed-size chunks, including when a high-depth pileup line is huge.
        for path in paths:
            cancellation.check()
            with path.open("rb") as source:
                while True:
                    cancellation.check()
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            path.unlink()
    finally:
        _stop_processes([(process, started) for process, started, _ in active.values()])
        for process, started, record in active.values():
            _finish_record(record, process, started, cancellation)
            if cancellation.signum is None:
                record["outcome"] = "aborted"


def _budgeted_acquisition(bams, samples, bed, reference, staging, output, cancellation,
                          document, metadata, samtools):
    contigs, reason = _chromosomes(bams, samples, bed, reference, staging, samtools, cancellation, document)
    selected_list = staging / "original-bamlist.txt"
    parallel = document["parallel"]
    parallel.update(tasks=len(contigs) or 1, workers=min(parallel["workers"], len(contigs)) if contigs else 1,
                    reason=reason)
    document["strategy"] = "indexed-chromosomes" if contigs else "sequential-budgeted"
    selected = []
    for number, (bam, sample) in enumerate(zip(bams, samples), 1):
        cancellation.check()
        if contigs or not sample["indexed"]:
            sample["strategy"] = "indexed-chromosomes" if contigs else "sequential-no-index"
            selected.append(str(bam))
            continue
        # Preserve the established fallback's validation of every PRESENT index.
        # Ignoring one because another BAM lacks an index would hide corruption.
        # Stage sequentially (one samtools at a time), as in 0.8.12 multi-BAM.
        directory = staging / f"sample-{number:04d}"
        directory.mkdir()
        destination = directory / bam.name
        record = {"stage": "indexed-selection", "sample_id": sample["sample_id"]}
        with progress.phase("dnp-indexed-selection", workflow="dnp-call", sample_ids=[sample["sample_id"]]):
            with destination.open("xb") as handle:
                _tracked_execute([samtools, "view", "--no-PG", "-u", "-M", "-L", str(bed), str(bam)],
                                 handle, cancellation, document, record)
        size = destination.stat().st_size
        sample.update(strategy="indexed-disk", elapsed_seconds=record["elapsed_seconds"],
                      selected_bytes=size, staged_bytes=size)
        selected.append(str(destination))
    selected_list.write_text("".join(name + "\n" for name in selected), encoding="utf-8")
    command = [samtools, "mpileup", "-l", str(bed), "-f", str(reference),
               *document["mpileup_options"], "-b", str(selected_list)]
    _write_json(metadata, document)
    sample_ids = [sample["sample_id"] for sample in samples]
    with progress.phase("dnp-indexed-pileup" if contigs else "dnp-pileup",
                        workflow="dnp-call", sample_ids=sample_ids):
        if contigs:
            _parallel_chromosomes(contigs, command, staging, output, cancellation, document, metadata)
        else:
            _tracked_execute(command, output, cancellation, document, {"stage": "mpileup"})


def generate_pileup(bamlist, bed, reference, output, scratch_dir, metadata, *, samtools="samtools", budget=None):
    """Return acquisition metadata only after both processes and output succeed."""
    scientific = settings_from_environment("dnp-call")
    mpileup_options = [*MPILEUP_OPTIONS, *samtools_options("dnp-call", scientific)]
    parallel = _budget(budget)
    bamlist, bed, reference = (Path(value).resolve() for value in (bamlist, bed, reference))
    scratch_dir = Path(scratch_dir)
    if not scratch_dir.is_absolute() or scratch_dir.is_symlink() or not scratch_dir.is_dir():
        raise PileupError("Scratch must be an existing absolute disk directory")
    scratch_dir = scratch_dir.resolve()
    output, metadata = Path(output).absolute(), Path(metadata).absolute()
    for path in (output, metadata):
        if path.exists() or path.is_symlink():
            raise PileupError(f"Refusing to overwrite an existing acquisition file: {path}")
        if not path.parent.is_dir():
            raise PileupError(f"Acquisition parent directory does not exist: {path.parent}")
    if not output.parent.resolve().is_relative_to(scratch_dir):
        raise PileupError("The seekable pileup must be written inside the selected disk scratch")
    if output == metadata:
        raise PileupError("Pileup and metadata destinations must be distinct")
    for path in (bamlist, bed, reference):
        if not path.is_file():
            raise PileupError(f"Missing acquisition input: {path}")
    # DNP's native list contains one mounted BAM path per line. Resolve relative
    # entries from the invocation directory, matching samtools -b behavior.
    bams = [Path(line.strip()).resolve() for line in bamlist.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not bams or any(not bam.is_file() for bam in bams):
        raise PileupError("BAM list is empty or identifies a missing file")
    samples = [{"sample_id": bam.stem, "bam": str(bam), "input_bytes": bam.stat().st_size,
                "index_candidates": _index_candidates(bam), "staged_bytes": 0,
                "selected_bytes": None, "elapsed_seconds": 0.0}
               for bam in bams]
    for sample in samples:
        sample["indexed"] = bool(sample["index_candidates"])
    indexed = sum(sample["indexed"] for sample in samples)
    strategy = "indexed-pipe" if len(bams) == 1 and indexed else "indexed-disk" if indexed else "sequential"
    disk = os.statvfs(scratch_dir)
    started = time.monotonic()
    document = {
        "schema_version": 1, "status": "running", "strategy": strategy, "samples": samples,
        "scratch": {"storage": "disk", "available_bytes_before": disk.f_bavail * disk.f_frsize},
        "mpileup_options": mpileup_options, "scientific_settings": scientific,
        "processes": [], "output_bytes": None,
        "elapsed_seconds": None,
        "timing_scope": "all acquisition work, including indexed selection and disk staging; pipeline stages overlap",
        "byte_scope": "input file sizes and disk intermediates; pipe transfer bytes are not measured",
    }
    if parallel is not None:
        document.update(strategy="planning", parallel=parallel)
    # Claim only the explicitly supplied new metadata destination. Subsequent
    # atomic replacements update this invocation's own record.
    with metadata.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    cancellation = Cancellation()
    partial = None
    try:
        with cancellation_handlers(cancellation), tempfile.TemporaryDirectory(
                prefix="indexed-", dir=scratch_dir) as temporary:
            staging = Path(temporary)
            if parallel is not None:
                descriptor, name = tempfile.mkstemp(prefix=".pileup-", suffix=".partial", dir=output.parent)
                partial = Path(name)
                with os.fdopen(descriptor, "wb") as handle:
                    _budgeted_acquisition(bams, samples, bed, reference, staging, handle,
                                          cancellation, document, metadata, samtools)
                cancellation.check()
                os.replace(partial, output)
                partial = None
                document.update(status="succeeded", output_bytes=output.stat().st_size)
                return document
            _chromosomes(bams, samples, bed, reference, staging, samtools, cancellation, document)
            selected_list = staging / "bamlist.txt"
            selected = []
            if strategy == "indexed-pipe":
                selected = ["-"]
            else:
                for number, (bam, sample) in enumerate(zip(bams, samples), 1):
                    cancellation.check()
                    if not sample["indexed"]:
                        sample["strategy"] = "sequential-no-index"
                        selected.append(str(bam))
                        continue
                    directory = staging / f"sample-{number:04d}"
                    directory.mkdir()
                    destination = directory / bam.name
                    command = [samtools, "view", "--no-PG", "-u", "-M", "-L", str(bed), str(bam)]
                    with progress.phase("dnp-indexed-selection", workflow="dnp-call", sample_ids=[sample["sample_id"]]):
                        with destination.open("xb") as handle:
                            result = _execute(command, handle, cancellation)
                    sample.update(strategy="indexed-disk", elapsed_seconds=result["elapsed_seconds"],
                                  selected_bytes=destination.stat().st_size, staged_bytes=destination.stat().st_size)
                    document["processes"].append({"stage": "indexed-selection", "sample_id": sample["sample_id"], **result})
                    selected.append(str(destination))
            selected_list.write_text("".join(name + "\n" for name in selected), encoding="utf-8")
            inputs = ["-"] if strategy == "indexed-pipe" else ["-b", str(selected_list)]
            # samtools 1.21 accepts stdin as a positional input, but its -b
            # file-list reader rejects a list entry named "-" as missing.
            command = [samtools, "mpileup", "-l", str(bed), "-f", str(reference), *mpileup_options, *inputs]
            descriptor, name = tempfile.mkstemp(prefix=".pileup-", suffix=".partial", dir=output.parent)
            partial = Path(name)
            sample_ids = [sample["sample_id"] for sample in samples]
            with os.fdopen(descriptor, "wb") as handle:
                if strategy == "indexed-pipe":
                    view = [samtools, "view", "--no-PG", "-u", "-M", "-L", str(bed), str(bams[0])]
                    with progress.phase("dnp-indexed-pileup", workflow="dnp-call", sample_ids=sample_ids):
                        results = _pipeline(view, command, handle, cancellation)
                    samples[0].update(strategy="indexed-pipe", elapsed_seconds=results[0]["elapsed_seconds"])
                    document["processes"].extend([
                        {"stage": stage, **result} for stage, result in zip(("indexed-selection", "mpileup"), results)
                    ])
                else:
                    with progress.phase("dnp-pileup", workflow="dnp-call", sample_ids=sample_ids):
                        result = _execute(command, handle, cancellation)
                    document["processes"].append({"stage": "mpileup", **result})
            cancellation.check()
            os.replace(partial, output)
            partial = None
            document.update(status="succeeded", output_bytes=output.stat().st_size)
    except Cancelled as error:
        document.update(status="cancelled", exit_code=128 + error.signum,
                        error={"type": "cancelled", "signal": error.signum})
        raise
    except BaseException as error:
        document.update(status="cancelled" if isinstance(error, KeyboardInterrupt) else "failed",
                        error={"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
        document["elapsed_seconds"] = time.monotonic() - started
        document["staged_bytes"] = sum(sample["staged_bytes"] for sample in samples)
        try:
            _write_json(metadata, document)
        except OSError as error:
            print(f"Could not retain pileup acquisition metadata: {error}", file=sys.stderr)
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("bamlist", "bed", "reference", "output", "scratch-dir", "metadata"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--budget", type=Path, help="Shared process budget generated by the R coordinator")
    args = parser.parse_args(argv)
    try:
        generate_pileup(args.bamlist, args.bed, args.reference, args.output, args.scratch_dir, args.metadata,
                        budget=args.budget)
    except Cancelled as error:
        print(str(error), file=sys.stderr)
        return 128 + error.signum
    except (OSError, ValueError, ValidationError, PileupError) as error:
        print(f"DNP pileup acquisition failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
