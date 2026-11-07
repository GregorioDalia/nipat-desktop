"""Acquire the unchanged DNP pileup with optional indexed BAM preselection.

The BED and all mpileup scientific options come from DNPcall. Indexed view only
selects alignments overlapping the same BED; no reads are deduplicated by name,
no quality/filter/depth options are changed, and original BAMs remain read-only.
Single indexed BAMs stream through an uncompressed pipe. Multiple BAMs retain
one file per input, in the original order, on the supplied disk scratch.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
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


def generate_pileup(bamlist, bed, reference, output, scratch_dir, metadata, *, samtools="samtools"):
    """Return acquisition metadata only after both processes and output succeed."""
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
        "mpileup_options": MPILEUP_OPTIONS.copy(), "processes": [], "output_bytes": None,
        "elapsed_seconds": None,
        "timing_scope": "all acquisition work, including indexed selection and disk staging; pipeline stages overlap",
        "byte_scope": "input file sizes and disk intermediates; pipe transfer bytes are not measured",
    }
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
            command = [samtools, "mpileup", "-l", str(bed), "-f", str(reference), *MPILEUP_OPTIONS, *inputs]
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
    args = parser.parse_args(argv)
    try:
        generate_pileup(args.bamlist, args.bed, args.reference, args.output, args.scratch_dir, args.metadata)
    except Cancelled as error:
        print(str(error), file=sys.stderr)
        return 128 + error.signum
    except (OSError, ValueError, PileupError) as error:
        print(f"DNP pileup acquisition failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
