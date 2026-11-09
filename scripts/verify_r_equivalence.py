"""Compare optimized scientific R against the immutable NIPAT 0.8.5 reference.

Both implementations run in the same immutable, locally built image. Complete
table bytes, unrounded R objects and rasterized PDF pages are compared strictly.
Timings are descriptive observations, not a noisy CI performance threshold.
Only generated or public synthetic inputs are used. No network is available to
the execution containers, and source/input mounts are read-only.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "eafadf7002a9c7d7c1b9af9ccafc47d698a059e5"
BASELINE = Path("tests/reference_r/0.8.5")
EXPECTED_REFERENCE = {
    "docker/scientific-runtime/verify-packages.R": "ef30c69555f6871f7c38c89baba5b52e1ef7d82fd02aaf206ae4568e2f686af7",
    "scientific/vendor/DNPcall/DNPcall.R": "d0600427d058a141da8683d98904c51be95ec09ebd5804ea879164d1f5ce7e36",
    "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R": "10ca01a476f5259b65a063aea95ff76e57c11567a304667065ea9c7b9206545a",
    "scientific/vendor/NEWPAT/SNPcall/SNPcall.R": "00068e501d1fefe2b721001f141fc2595be42c9349873ee353a29a305816c9c9",
    "scientific/vendor/NEWPAT/contamination/detect_contamination.R": "28f0d0298cdce06c6d9f33ec5d7a224a8c9fa7dfb6fde87b930ee938e703cc08",
    "src/nipat_scientific/presentation.R": "f368a60172d0bc9c632c09c49a1ea5924b835fb7a1db91413dffc8817ab1f193",
}
SCRIPTS = dict(zip(("dnp-call", "cpi", "snp-call", "contamination"), (
    "scientific/vendor/DNPcall/DNPcall.R",
    "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
    "scientific/vendor/NEWPAT/SNPcall/SNPcall.R",
    "scientific/vendor/NEWPAT/contamination/detect_contamination.R",
)))
SUPPORTING_SOURCES = tuple(f"src/nipat_scientific/{name}" for name in (
    "dnp_blocks.R", "dnp_pileup.py", "scratch.py", "progress.py", "progress.R", "parallel.R", "parallel.py",
))
PARALLEL_CASES = {"dnp-blocks-1", "dnp-multi-blocks-2", "dnp-multi-blocks-3", "dnp-multi-blocks-6",
                  "snp-edge", "cpi-shared-parents",
                  "cpi-single-intervals", "cpi-single-cutoffs", "contamination-batch"}
CONCURRENT_CASES = {"dnp-blocks-1", "dnp-multi-blocks-2", "dnp-multi-blocks-3", "dnp-multi-blocks-6",
                    "snp-edge", "cpi-shared-parents", "contamination-batch"}
PARALLEL_VARIANTS = {
    "auto": {"NIPAT_EXECUTION_MODE": "auto", "NIPAT_MAX_WORKERS": ""},
    "manual-2": {"NIPAT_EXECUTION_MODE": "auto", "NIPAT_MAX_WORKERS": "2"},
    "manual-4": {"NIPAT_EXECUTION_MODE": "auto", "NIPAT_MAX_WORKERS": "4"},
    "manual-4-repeat": {"NIPAT_EXECUTION_MODE": "auto", "NIPAT_MAX_WORKERS": "4"},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_reference(project: Path = PROJECT) -> dict:
    root = project / BASELINE
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    declared = {item["path"]: item["sha256"] for item in manifest["files"]}
    if (manifest.get("schema_version") != 1 or manifest.get("version") != "0.8.5"
            or manifest.get("source_commit") != BASELINE_COMMIT
            or manifest.get("source_tag") != "v0.8.5"
            or len(manifest["files"]) != len(EXPECTED_REFERENCE)
            or declared != EXPECTED_REFERENCE):
        raise ValueError("The frozen reference manifest differs from stable NIPAT 0.8.5")
    actual = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*.R")}
    if actual != EXPECTED_REFERENCE:
        raise ValueError("The frozen R reference was modified or is incomplete")
    return manifest


def mount(path: Path, destination: str, *, readonly: bool = False) -> str:
    buffer = io.StringIO()
    fields = ["type=bind", f"source={path.resolve()}", f"target={destination}"]
    if readonly:
        fields.append("readonly")
    csv.writer(buffer, lineterminator="").writerow(fields)
    return buffer.getvalue()


def command(arguments: list[str], *, log: Path | None = None, timeout: int = 900) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False,
                            timeout=timeout, encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    if log is not None:
        log.write_text(output, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {arguments}\n{output[-12000:]}")
    return result.stdout


def immutable_image(reference: str) -> str:
    if not reference or reference.startswith("-"):
        raise ValueError("A local Linux image reference is required")
    metadata = json.loads(command(["docker", "image", "inspect", reference]))
    if len(metadata) != 1 or metadata[0].get("Os") != "linux":
        raise ValueError("Expected one local Linux image")
    identifier = metadata[0].get("Id", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identifier):
        raise ValueError("Missing immutable scientific image ID")
    return identifier


def run(image: str, arguments: list[str], *, inputs: Path, results: Path,
        environment: dict[str, str] | None = None, log: Path | None = None) -> str:
    arguments_prefix = ["docker", "run", "--rm", "--pull", "never", "--network", "none",
                        "--cpus", "4", "--memory", "8g",
                        "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
                        "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
                        "--env", "LANG=C.UTF-8", "--env", "LC_ALL=C.UTF-8"]
    if hasattr(os, "getuid"):
        arguments_prefix += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for key, value in (environment or {}).items():
        arguments_prefix += ["--env", f"{key}={value}"]
    arguments_prefix += ["--mount", mount(PROJECT, "/repo", readonly=True),
                         "--mount", mount(inputs, "/inputs", readonly=True),
                         "--mount", mount(results, "/results"), "--workdir", "/results"]
    return command([*arguments_prefix, image, *arguments], log=log)


def verify_image_sources(image: str, root: Path) -> dict[str, str]:
    bundled = {path: f"/opt/nipat/{path}" for path in SCRIPTS.values()}
    code = ("import hashlib,json; p=" + repr(bundled) + "; "
            "print(json.dumps({k:hashlib.sha256(open(v,'rb').read()).hexdigest() for k,v in p.items()}))")
    actual = json.loads(run(image, ["python3", "-c", code], inputs=root, results=root))
    wanted = {path: digest(PROJECT / path) for path in SCRIPTS.values()}
    if actual != wanted:
        raise ValueError("The image does not contain this checkout's candidate R scripts; rebuild it")
    return actual


def verify_supporting_sources(image: str, root: Path) -> dict[str, str]:
    bundled = {path: f"/opt/nipat/lib/nipat_scientific/{Path(path).name}" for path in SUPPORTING_SOURCES}
    code = ("import hashlib,json; p=" + repr(bundled) + "; "
            "print(json.dumps({k:hashlib.sha256(open(v,'rb').read()).hexdigest() for k,v in p.items()}))")
    actual = json.loads(run(image, ["python3", "-c", code], inputs=root, results=root))
    wanted = {path: digest(PROJECT / path) for path in SUPPORTING_SOURCES}
    if actual != wanted:
        raise ValueError("The image does not contain this checkout's scientific supporting sources; rebuild it")
    return actual


def compare_tables(reference: Path, candidate: Path) -> dict[str, str]:
    def files(root: Path) -> dict[str, Path]:
        return {p.relative_to(root).as_posix(): p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in (".txt", ".tsv", ".csv")}
    original, optimized = files(reference), files(candidate)
    if not original or set(original) != set(optimized):
        raise ValueError("Scientific table files are missing or differ")
    hashes = {}
    for name, path in original.items():
        if path.read_bytes() != optimized[name].read_bytes():
            raise ValueError(f"Scientific table differs (values, schema, formatting or row order): {name}")
        hashes[name] = digest(path)
    return hashes


def compare_pdfs(reference: Path, candidate: Path, root: Path) -> dict[str, dict]:
    originals = {p.relative_to(reference).as_posix(): p for p in reference.rglob("*.pdf")}
    optimized = {p.relative_to(candidate).as_posix(): p for p in candidate.rglob("*.pdf")}
    if set(originals) != set(optimized):
        raise ValueError("Scientific PDF files are missing or differ")
    evidence = {}
    for number, (name, source) in enumerate(sorted(originals.items())):
        pages = []
        for label, path in (("reference", source), ("candidate", optimized[name])):
            if not path.read_bytes().startswith(b"%PDF-"):
                raise ValueError(f"Invalid PDF: {path}")
            directory = root / str(number) / label
            directory.mkdir(parents=True)
            # PPM has no timestamp metadata; identical pixels are compared strictly.
            command(["pdftoppm", "-r", "36", str(path), str(directory / "page")])
            page_hashes = {p.name: digest(p) for p in directory.glob("page-*.ppm")}
            if not page_hashes:
                raise ValueError(f"No rendered PDF pages: {path}")
            pages.append(page_hashes)
        if pages[0] != pages[1]:
            raise ValueError(f"Rendered scientific PDF differs: {name}")
        evidence[name] = {"pages": len(pages[0]), "raster_dpi": 36, "page_sha256": pages[0]}
    return evidence


@dataclass(frozen=True)
class Case:
    name: str
    workflow: str
    arguments: tuple[str, ...]
    bamlist: tuple[str, ...] = ()
    candidate_environment: tuple[tuple[str, str], ...] = ()
    compare_pileup: bool = False
    expected_compatibility_reason: str | None = None


def case_environment(case: Case, variant: str, script: Path,
                     execution: dict[str, str] | None = None) -> dict[str, str]:
    environment = {"NIPAT_EQ_SCRIPT": f"/repo/{script.as_posix()}", "NIPAT_EQ_WORKFLOW": case.workflow}
    if case.compare_pileup:
        environment["NIPAT_EQ_KEEP_PILEUP"] = "1"
    if variant == "candidate":
        environment.update({"NIPAT_EXECUTION_MODE": "serial", "NIPAT_MAX_WORKERS": "",
                            "NIPAT_PARALLEL_LOG_DIR": "/results/parallel-log"})
        environment.update(case.candidate_environment)
        environment.update(execution or {})
        if case.compare_pileup:
            environment["NIPAT_DNP_KEEP_PILEUP"] = "1"
    return environment


def verify_parallel_execution(directory: Path, *, mode: str, cap: int | None,
                              require_parallel: bool, require_overlap: bool = True) -> dict:
    """Require real scientific worker events, concurrency and respected limits.

    A requested pool size alone is not evidence that a workflow used it. Each
    process writes its own events; only matching actual child task intervals
    establish simultaneous execution. Scientific output equality is checked
    independently of these nondeterministically ordered diagnostic records.
    """
    events = []
    files = sorted(directory.glob("worker-*.jsonl"))
    if not files:
        raise ValueError("Parallel qualification has no actual scientific worker events")
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if value.get("interface") != "nipat-parallel-v1" or value.get("schema_version") != 1:
                raise ValueError("Invalid scientific worker event schema")
            events.append(value)
    plans = [event for event in events if event.get("event") == "plan"]
    if not plans:
        raise ValueError("Parallel qualification has no worker plans")
    for plan in plans:
        workers, tasks = plan.get("workers"), plan.get("tasks")
        if (not isinstance(workers, int) or not isinstance(tasks, int) or tasks < 0
                or not 1 <= workers <= max(1, tasks) or plan.get("mode") != mode):
            raise ValueError("Invalid effective scientific worker count")
        cpu, memory = plan.get("cpu_limit"), plan.get("memory_worker_limit")
        if (not isinstance(cpu, (int, float)) or not math.isfinite(cpu) or cpu <= 0
                or not isinstance(memory, (int, float)) or memory < 1
                or workers > math.ceil(cpu) or workers > memory
                or (cap is not None and workers > cap)):
            raise ValueError("Scientific worker plan exceeded CPU, memory or requested process budget")
        if mode == "serial" and workers != 1:
            raise ValueError("Serial scientific execution created a parallel plan")
    budget_fields = ("workers", "tasks", "mode", "cpu_limit", "memory_worker_limit")
    declared = {
        (plan.get("coordinator_pid"), plan.get("label"), *(plan.get(name) for name in budget_fields))
        for plan in plans
    }
    pending = {}
    intervals = []
    for event in sorted(events, key=lambda item: item.get("observed_at_unix", -1)):
        if event.get("event") not in {"task-start", "task-end"}:
            continue
        pid, coordinator = event.get("pid"), event.get("coordinator_pid")
        stamp, index = event.get("observed_at_unix"), event.get("task_index")
        if (not isinstance(pid, int) or not isinstance(coordinator, int)
                or not isinstance(stamp, (int, float)) or not math.isfinite(stamp)
                or not isinstance(index, int)):
            raise ValueError("Invalid observed scientific task identity or time")
        key = (coordinator, pid, event.get("label"), index)
        budget_key = (coordinator, event.get("label"), *(event.get(name) for name in budget_fields))
        if budget_key not in declared:
            raise ValueError("Scientific worker task has no matching resource plan")
        if event["event"] == "task-start":
            if key in pending:
                raise ValueError("Scientific worker task starts twice without ending")
            pending[key] = (stamp, event["workers"])
        else:
            if key not in pending or stamp < pending[key][0]:
                raise ValueError("Scientific worker task has no matching start")
            if event.get("outcome") != "succeeded":
                raise ValueError("Scientific worker task did not succeed")
            started, workers = pending.pop(key)
            if workers != event["workers"]:
                raise ValueError("Scientific worker task changed its resource plan")
            if pid != coordinator:
                intervals.append((started, stamp, pid, coordinator, workers))
    if pending:
        raise ValueError("Scientific worker tasks did not finish")
    child_pids = sorted({value[2] for value in intervals})
    if mode == "serial" and child_pids:
        raise ValueError("Serial scientific execution used child workers")
    # A declared pool size is not proof of respecting it. Count actual child
    # intervals, including children of different coordinators, so an accidental
    # nested pool cannot hide behind individually valid resource plans. End
    # events precede starts at a shared timestamp; touching intervals do not
    # overlap. Serial nested callbacks have pid == coordinator and are not
    # counted twice as additional processes.
    boundaries = []
    for number, (started, finished, *_rest) in enumerate(intervals):
        if finished > started:
            boundaries.extend(((started, 1, number), (finished, -1, number)))
    active = {}
    maximum_observed = 0
    maximum_planned = max(plan["workers"] for plan in plans)
    overlap = False
    for _stamp, delta, number in sorted(boundaries):
        if delta == -1:
            del active[number]
            continue
        active[number] = intervals[number]
        live_pids = {value[2] for value in active.values()}
        maximum_observed = max(maximum_observed, len(live_pids))
        # The currently active outer pool owns the budget. A larger plan in a
        # different (possibly later) phase cannot authorize extra descendants
        # now. A nested coordinator is itself one of these live child PIDs.
        outer_budgets = [value[4] for value in active.values() if value[3] not in live_pids]
        if not outer_budgets:
            raise ValueError("Scientific worker coordinator ancestry is cyclic")
        shared_limit = min(outer_budgets)
        if len(live_pids) > shared_limit or (cap is not None and len(live_pids) > cap):
            raise ValueError("Observed scientific workers exceeded the shared process budget")
        for value in active.values():
            siblings = {item[2] for item in active.values() if item[3] == value[3]}
            if len(siblings) > value[4]:
                raise ValueError("Observed scientific workers exceeded their coordinator's process budget")
            overlap = overlap or len(siblings) > 1
    if require_parallel and len(child_pids) < 2:
        raise ValueError("Scientific parallel qualification did not observe two actual child workers")
    if require_parallel and require_overlap and not overlap:
        raise ValueError("Scientific parallel qualification did not observe two simultaneous child workers")
    return {"event_sha256": {path.name: digest(path) for path in files},
            "observed_child_pids": child_pids, "simultaneous_child_workers": overlap,
            "maximum_planned_workers": maximum_planned,
            "maximum_observed_child_workers": maximum_observed,
            "requested_mode": mode, "requested_max_workers": cap,
            "overlapping_workers_required": require_parallel and require_overlap,
            "plans": plans}


def compare_pileup(reference: Path, candidate: Path) -> dict:
    if not reference.is_file() or not candidate.is_file():
        raise ValueError("A retained reference or candidate pileup is missing")
    original = reference.read_bytes()
    if not original or original != candidate.read_bytes():
        raise ValueError("Indexed pileup differs from the sequential 0.8.5 pileup")
    return {"comparison": "exact-bytes", "sha256": hashlib.sha256(original).hexdigest(),
            "size_bytes": len(original), "rows": len(original.splitlines())}


def verify_block_execution(path: Path, expected_limit: int, compatibility_reason: str | None = None) -> dict:
    """Confirm the forced partitions were actually used, not just requested."""
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if (metadata.get("status") != "succeeded" or metadata.get("block_loci_limit") != expected_limit
            or not metadata.get("samples")):
        raise ValueError("The candidate did not use the requested DNP block limit")
    samples = {}
    reasons = metadata.get("compatibility_reasons", [])
    if not isinstance(reasons, list) or reasons != ([compatibility_reason] if compatibility_reason else []):
        raise ValueError("The DNP compatibility path differs from the intended synthetic scenario")
    for name, sample in metadata["samples"].items():
        blocks = sample.get("blocks", [])
        invalid = (len(blocks) != 1 if compatibility_reason else
                   len(blocks) < 2 or any(not 0 < block.get("loci", 0) <= expected_limit for block in blocks)
                   or (expected_limit == 1 and not any(block.get("raw_rows") == 0 for block in blocks)))
        if invalid:
            raise ValueError("The synthetic DNP block boundaries or uncovered windows were not exercised")
        samples[name] = {"blocks": len(blocks), "loci": sum(block["loci"] for block in blocks),
                         "maximum_block_loci": max(block["loci"] for block in blocks),
                         "uncovered_blocks": sum(block["raw_rows"] == 0 for block in blocks)}
    return {"metadata_sha256": digest(path), "block_loci_limit": expected_limit,
            "compatibility_reasons": reasons, "samples": samples}


def write_tsv(path: Path, fields: tuple[str, ...], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def make_dnp_block_inputs(inputs: Path, image: str) -> None:
    """Small full-script cases exercise window boundaries without large BAMs."""
    source_sequence = "".join(line for line in (PROJECT / "tests/fixtures/dnp_engine/reference.fa").read_text().splitlines()
                              if not line.startswith(">"))
    # Integer coordinates at 100000 must keep their decimal key. R formats a
    # numeric/double 100000 as 1e+05 in some contexts, unlike integer positions.
    sequence = source_sequence * 400
    for fixture_name, contigs, panel in (
        ("dnp-blocks", ("1", "X"),
         (("X", 620), ("1", 60), ("1", 62), ("X", 250), ("1", 250),
          ("1", 440), ("X", 60), ("1", 800), ("X", 440), ("1", 1000), ("1", 100000), ("X", 1000))),
        # read.table converts the numeric-looking panel chromosome column to
        # integer, collapsing 01 and 1 into the same effective DNP key.
        ("dnp-numeric", ("01", "1", "100000"),
         (("01", 250), ("1", 60), ("01", 62), ("1", 440), ("01", 800), ("100000", 100000), ("1", 1000))),
    ):
        directory = inputs / fixture_name
        directory.mkdir()
        reference = directory / "reference.fa"
        reference.write_text("".join(f">{chromosome}\n{sequence}\n" for chromosome in contigs), encoding="utf-8")
        panel_rows = []
        for chromosome, position in panel:
            bases = sequence[position - 1:position + 1]
            alt = bases.translate(str.maketrans("ACGT", "TGCA"))
            panel_rows.append(f"{chromosome}\t{position}\t{position + 1}\t{bases}\t{alt}\n")
        (directory / "panel.txt").write_text("".join(panel_rows), encoding="utf-8")
        records = ["@HD\tVN:1.6\tSO:coordinate", *(f"@SQ\tSN:{chromosome}\tLN:{len(sequence)}" for chromosome in contigs)]

        def add(name: str, chromosome: str, start: int, length: int = 90,
                *, flag: int = 0, cigar: str | None = None, bases: str | None = None,
                quality: str = "I", mate: str = "*", mate_position: int = 0, template_length: int = 0):
            bases = sequence[start - 1:start - 1 + length] if bases is None else bases
            records.append("\t".join(map(str, (name, flag, chromosome, start, 60,
                cigar or f"{length}M", mate, mate_position, template_length, bases, quality * len(bases)))))

        effective_contigs = ("1", "100000") if fixture_name == "dnp-numeric" else contigs
        for chromosome in effective_contigs:
            # The first covered windows have one numeric QNAME and a digit
            # quality character; later windows force global character types.
            add("0001", chromosome, 30, quality="5")
            add("large-coordinate", chromosome, 99970)
            for start in (220, 410, 590):
                for number, name in enumerate(("shared", "shared2", "001", "1", "z", "A", "r_12", "r@excluded")):
                    bases = list(sequence[start - 1:start + 89])
                    if number % 3 == 1:
                        position = start + 30
                        bases[30:32] = list(sequence[position - 1:position + 1].translate(str.maketrans("ACGT", "TGCA")))
                    add(name, chromosome, start, bases="".join(bases), flag=16 if number % 2 else 0)
            # One alignment intersects two disjoint windows. An indexed
            # multi-region iterator must emit it once, in original BAM order.
            add("spanning", chromosome, 220, length=260)
            add("deletion", chromosome, 220, cigar="30M1D59M",
                bases=sequence[219:249] + sequence[250:309])
            add("insertion", chromosome, 220, cigar="30M1I60M",
                bases=sequence[219:249] + "A" + sequence[249:309])
            add("skip", chromosome, 410, cigar="30M2N58M",
                bases=sequence[409:439] + sequence[441:499])
            add("softclip", chromosome, 590, cigar="4S90M", bases="ACGT" + sequence[589:679])
            add("paired", chromosome, 220, flag=99, mate="=", mate_position=240, template_length=110)
            add("paired", chromosome, 240, flag=147, mate="=", mate_position=220, template_length=-110)
            # 800 and 1000 remain uncovered, including the final block.
        sam = directory / "Boundary.sam"
        sam.write_text("\n".join(records) + "\n", encoding="utf-8")
        run(image, ["samtools", "sort", "-O", "BAM", "-o", "/results/Boundary.bam", "/inputs/Boundary.sam"],
            inputs=directory, results=directory)
        run(image, ["samtools", "index", "/results/Boundary.bam"], inputs=directory, results=directory)
        run(image, ["samtools", "faidx", "/results/reference.fa"], inputs=directory, results=directory)
        if fixture_name == "dnp-blocks":
            # Distinct sample depths expose column/closure mixups in the global
            # sample-block queue. Six samples exceed the four-CPU qualification
            # budget; every sample is still compared with the unchanged oracle.
            for sample in range(2, 7):
                subset = [record for number, record in enumerate(records)
                          if record.startswith("@") or number % sample != 0]
                (directory / f"Boundary{sample}.sam").write_text(
                    "\n".join(subset) + "\n", encoding="utf-8")
                run(image, ["samtools", "sort", "-O", "BAM", "-o", f"/results/Boundary{sample}.bam",
                            f"/inputs/Boundary{sample}.sam"], inputs=directory, results=directory)
                run(image, ["samtools", "index", f"/results/Boundary{sample}.bam"],
                    inputs=directory, results=directory)
            # Duplicate names at one position retain a legacy cross-window
            # grouping dependency and explicitly exercise its compatibility path.
            duplicate = ["shared\t" + record.split("\t", 1)[1] if record.startswith("shared2\t") else record
                         for record in records]
            (directory / "Duplicate.sam").write_text("\n".join(duplicate) + "\n", encoding="utf-8")
            run(image, ["samtools", "sort", "-O", "BAM", "-o", "/results/Duplicate.bam", "/inputs/Duplicate.sam"],
                inputs=directory, results=directory)
            run(image, ["samtools", "index", "/results/Duplicate.bam"], inputs=directory, results=directory)


def make_inputs(root: Path, image: str) -> Path:
    inputs = root / "inputs"
    inputs.mkdir()
    for folder in ("dnp", "snp", "cpi", "contamination", "panel-only"):
        (inputs / folder).mkdir()
    dnp = inputs / "dnp"
    fixture = PROJECT / "tests/fixtures/dnp_engine"
    shutil.copyfile(fixture / "reference.fa", dnp / "reference.fa")
    sequence = "".join(line for line in (dnp / "reference.fa").read_text().splitlines()
                       if not line.startswith(">"))
    positions = (50, 52, 140, 230, 280)
    alternatives = {}
    panel_rows = []
    for position in positions:
        ref = sequence[position - 1:position + 1]
        alt = ref.translate(str.maketrans("ACGT", "TGCA"))
        alternatives[position] = alt
        panel_rows.append(f"chrDnpSynthetic\t{position}\t{position + 1}\t{ref}\t{alt}\n")
    (dnp / "panel.txt").write_text("".join(panel_rows), encoding="utf-8")
    for sample in ("A", "B", "Quality"):
        records = ["@HD\tVN:1.6\tSO:coordinate", f"@SQ\tSN:chrDnpSynthetic\tLN:{len(sequence)}"]
        for start, covered in ((20, (50, 52)), (110, (140,)), (200, (230,))):
            for index, name in enumerate(("a", "A", "z", "Z", "r-1", "r.2", "r_3", "r@skip")):
                bases = list(sequence[start - 1:start + 79])
                for position in covered:
                    if (index + (sample == "B")) % 3 == 1:
                        bases[position - start:position - start + 2] = alternatives[position]
                    elif index == 6:
                        bases[position - start] = "ACGT"[("ACGT".index(bases[position - start]) + 1) % 4]
                # Cover distinct central qualities and every printable score
                # retained by samtools' default minimum base quality. The
                # repeated pattern also exercises caching without making all
                # reads numerically identical.
                quality = ("".join(chr(33 + 13 + (offset * 7 + index * 13) % 81)
                                   for offset in range(len(bases)))
                           if sample == "Quality" else "I" * len(bases))
                records.append("\t".join(map(str, (f"{name}_{start}", 16 if index % 2 else 0,
                    "chrDnpSynthetic", start, 60, f"{len(bases)}M", "*", 0, 0, "".join(bases), quality))))
        # A deletion and an insertion at the first DNP exercise discarded-read handling.
        for name, cigar, bases in (
            ("del", "40M1D39M", sequence[9:49] + sequence[50:89]),
            ("ins", "40M1I40M", sequence[9:49] + "A" + sequence[49:89]),
        ):
            records.append("\t".join(map(str, (name, 0, "chrDnpSynthetic", 10, 60, cigar,
                                              "*", 0, 0, bases, "I" * len(bases)))))
        # Sort through samtools: no assumption that the generated SAM is position sorted.
        sam = dnp / f"{sample}.sam"
        sam.write_text("\n".join(records) + "\n", encoding="utf-8")
        run(image, ["samtools", "sort", "-O", "BAM", "-o", f"/results/{sample}.bam",
                    f"/inputs/{sample}.sam"], inputs=dnp, results=dnp)
    run(image, ["samtools", "faidx", "/results/reference.fa"], inputs=dnp, results=dnp)

    names = ["a", "A", "z", "Z", "r-1", "r.2", "r@skip", "shared"]
    lines = []
    for center, ref, alt in ((50, "A", "G"), (120, "C", "T")):
        for position in (center - 1, center, center + 1):
            bases = [".", ",", ".", ",", ".", ",", ".", ","]
            if position == center:
                bases[2:6] = [alt, alt.lower(), "T" if ref == "A" else "G", "*"]
            qnames = [f"{name}_{center}" if name != "shared" else name for name in names]
            lines.append(f"chrSynthetic\t{position}\t{ref}\t8\t{''.join(bases)}\tIIIIIIII\t{','.join(qnames)}\n")
    (inputs / "snp/pileup.txt").write_text("".join(lines), encoding="utf-8")
    # Optional mpileup output columns remain accepted by the native reader.
    # A selective import must skip them without shifting the QNAME column.
    wide_lines = [line.rstrip("\n") + f"\tunused {index}\t{index}\tNA\n"
                  for index, line in enumerate(lines)]
    (inputs / "snp/pileup-wide.txt").write_text("".join(wide_lines), encoding="utf-8")
    write_tsv(inputs / "snp/panel.tsv", ("pos", "ref", "alt"),
              [("chrSynthetic:50", "A", "G"), ("chrSynthetic:120", "C", "T"),
               ("chrSynthetic:180", "A", "C")])

    cpi = inputs / "cpi"
    (cpi / "samples").mkdir()
    for path in (PROJECT / "tests/fixtures/cpi/samples").iterdir():
        shutil.copyfile(path, cpi / "samples" / path.name)
    counts = [(900, 100, 0, 100, 0), (90, 10, 0, 10, 90), (10, 90, 0, 40, 60),
              (400, 40, 0, 60, 40), (950, 50, 0, 90, 10), (800, 20, 0, 30, 70),
              (980, 20, 200, 50, 50), (50, 50, 0, 100, 0), (0, 0, 0, 50, 50)]
    header = ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count")
    for parent in ("Mother", "Father"):
        rows = []
        for n, (mr, ma, other, fr, fa) in enumerate(counts, 1):
            r, a, o = (mr, ma, other) if parent == "Mother" else (fr, fa, 0)
            rows.append(("chr1", n * 100, n * 100 + 1, "AA", "CC", r, a, o, r + a + o))
        write_tsv(cpi / "samples" / f"{parent}Deep.txt", header, rows)
    write_tsv(cpi / "population.tsv", ("chr", "pos1", "pos2", "Ref_f.pop", "Alt_f.pop", "annotation"),
              [("chr1", n * 100, n * 100 + 1, 0.8, 0.2, "NA" if n == 4 else "present")
               for n in (1, 2, 3, 4, 5, 7, 8, 9)])
    for name, selected in (("full", range(1, 10)), ("subset", (1, 3, 5))):
        write_tsv(cpi / f"{name}.tsv", ("chr", "pos1", "pos2"),
                  [("chr1", n * 100, n * 100 + 1) for n in selected])

    contamination = inputs / "contamination"
    (contamination / "samples").mkdir()
    shutil.copyfile(PROJECT / "tests/fixtures/contamination/DNP_list.txt", contamination / "panel.txt")
    for number, source in enumerate(sorted((PROJECT / "tests/fixtures/contamination/samples").iterdir())):
        shutil.copyfile(source, contamination / "samples" / f"sample{number}.txt")
    write_tsv(contamination / "samples/boundaries.txt", (*header, "ratio_REF_ALT", "annotation"), [
        ("chr1", 100, 101, "AA", "CC", 90, 10, 0, 100, 0.9, "boundary"),
        ("chr1", 200, 201, "GG", "TT", 10, 90, 10, 110, 0.1, "boundary"),
        ("chr1", 300, 301, "AC", "GT", 50, 50, 0, 100, 0.95, "provided-ratio"),
    ])
    write_tsv(contamination / "samples/single.txt", header,
              [("chr1", 100, 101, "AA", "CC", 99, 1, 0, 100)])
    # A larger batch catches accumulation/order/type changes without large input data.
    for number in range(12):
        shutil.copyfile(contamination / "samples/single.txt", contamination / "samples" / f"batch{number:02}.txt")
    shutil.copyfile(contamination / "panel.txt", inputs / "panel-only/panel.txt")
    make_dnp_block_inputs(inputs, image)
    return inputs


def cases() -> list[Case]:
    dnp = ("--bamlist=bamlist.txt", "--DNPs=/inputs/dnp/panel.txt",
           "--reference=/inputs/dnp/reference.fa", "--out=output")
    cpi = ("--pileup_dir", "/inputs/cpi/samples", "--out_dir", "output",
           "--pairs", "Informative:Informative,NoSites:NoSites,Deep:Deep",
           "--mother_prefix", "Mother", "--father_prefix", "Father",
           "--popfreq", "/inputs/cpi/population.tsv")
    shared_parents = list(cpi)
    shared_parents[shared_parents.index("--pairs") + 1] = (
        "Deep:Deep,Deep:Informative,Informative:Informative,"
        "NoSites:Informative,Informative:Deep"
    )
    single_pair = list(cpi)
    single_pair[single_pair.index("--pairs") + 1] = "Informative:Informative"
    original = [
        Case("dnp-single", "dnp-call", dnp, ("/inputs/dnp/A.bam",)),
        Case("dnp-multi", "dnp-call", dnp, ("/inputs/dnp/A.bam", "/inputs/dnp/B.bam")),
        Case("dnp-parallel", "dnp-call", (*dnp, "--parallel"), ("/inputs/dnp/A.bam", "/inputs/dnp/B.bam")),
        Case("dnp-varied-qualities", "dnp-call", dnp, ("/inputs/dnp/Quality.bam",)),
        Case("snp-edge", "snp-call", ("--pileup", "/inputs/snp/pileup.txt", "--snplist", "/inputs/snp/panel.tsv", "--out", "output/SNPcall_output.txt")),
        Case("snp-extra-columns", "snp-call", ("--pileup", "/inputs/snp/pileup-wide.txt", "--snplist", "/inputs/snp/panel.tsv", "--out", "output/SNPcall_output.txt")),
        Case("cpi-all", "cpi", cpi),
        Case("cpi-panels", "cpi", (*cpi, "--cutoff_map", "Full=/inputs/cpi/full.tsv,Subset=/inputs/cpi/subset.tsv")),
        Case("cpi-zero-error", "cpi", (*cpi, "--err_const", "0")),
        Case("cpi-shared-parents", "cpi", tuple(shared_parents)),
        Case("cpi-single-intervals", "cpi", tuple(single_pair)),
        Case("cpi-single-cutoffs", "cpi", (*single_pair, "--cutoff_map",
                                           "Full=/inputs/cpi/full.tsv,Subset=/inputs/cpi/subset.tsv")),
        Case("contamination-batch", "contamination", ("/inputs/contamination/panel.txt", "/inputs/contamination/samples", "output")),
        Case("contamination-single", "contamination", ("/inputs/contamination/panel.txt", "/inputs/contamination/samples/single.txt", "output")),
        Case("contamination-panel-only", "contamination", ("/inputs/panel-only/panel.txt", "/inputs/panel-only", "output")),
    ]
    blocks = []
    for count in (1, 2, 3):
        arguments = ("--bamlist=bamlist.txt", "--DNPs=/inputs/dnp-blocks/panel.txt",
                     "--reference=/inputs/dnp-blocks/reference.fa", "--out=output")
        blocks.append(Case(f"dnp-blocks-{count}", "dnp-call", arguments,
                           ("/inputs/dnp-blocks/Boundary.bam",),
                           (("NIPAT_DNP_BLOCK_LOCI", str(count)),), True))
    numeric = Case("dnp-numeric-blocks", "dnp-call",
                   ("--bamlist=bamlist.txt", "--DNPs=/inputs/dnp-numeric/panel.txt",
                    "--reference=/inputs/dnp-numeric/reference.fa", "--out=output"),
                   ("/inputs/dnp-numeric/Boundary.bam",), (("NIPAT_DNP_BLOCK_LOCI", "1"),), True)
    duplicate = Case("dnp-repeated-qname-compatibility", "dnp-call", blocks[0].arguments,
                     ("/inputs/dnp-blocks/Duplicate.bam",), (("NIPAT_DNP_BLOCK_LOCI", "1"),), True,
                     "legacy-repeated-qname-within-position")
    multi_blocks = [Case(f"dnp-multi-blocks-{count}", "dnp-call", blocks[0].arguments,
                         ("/inputs/dnp-blocks/Boundary.bam", *(
                             f"/inputs/dnp-blocks/Boundary{number}.bam" for number in range(2, count + 1))),
                         (("NIPAT_DNP_BLOCK_LOCI", "1"),), True)
                    for count in (2, 3, 6)]
    return [*original, *blocks, numeric, duplicate, *multi_blocks]


def verify_case(root: Path, image: str, inputs: Path, case: Case) -> dict:
    """Run one immutable oracle, the serial candidate and selected pool variants."""
    case_dir = root / case.name
    timings = {}
    executions = {"reference": None, "candidate": None}
    if case.name in PARALLEL_CASES:
        executions.update(PARALLEL_VARIANTS)
    comparisons = {}
    for variant, execution in executions.items():
        destination = case_dir / variant
        (destination / "output").mkdir(parents=True)
        if case.bamlist:
            (destination / "bamlist.txt").write_text("\n".join(case.bamlist) + "\n", encoding="utf-8")
        path = Path(SCRIPTS[case.workflow])
        kind = "reference" if variant == "reference" else "candidate"
        if kind == "reference":
            path = BASELINE / path
        started = time.monotonic()
        run(image, ["Rscript", "/repo/tests/r_optimization/capture.R", *case.arguments],
            inputs=inputs, results=destination,
            environment=case_environment(case, kind, path, execution),
            log=destination / "execution.log")
        timings[variant] = round(time.monotonic() - started, 6)
        if variant == "reference":
            continue
        table_hashes = compare_tables(case_dir / "reference/output", destination / "output")
        run(image, ["Rscript", "/repo/tests/r_optimization/compare.R",
                    "/inputs/reference/scientific-values.rds", f"/inputs/{variant}/scientific-values.rds"],
            inputs=case_dir, results=case_dir, log=case_dir / f"{variant}-unrounded-comparison.log")
        plots = compare_pdfs(case_dir / "reference/output", destination / "output", case_dir / f"rendered-{variant}")
        comparison = {"status": "passed", "table_sha256": table_hashes,
                      "unrounded_r_values": "identical", "plots": plots}
        if case.compare_pileup:
            comparison.update({"candidate_environment": dict(case.candidate_environment),
                "pileup": compare_pileup(case_dir / "reference/mpileup.txt", destination / "mpileup.txt"),
                "block_execution": verify_block_execution(destination / "work/dnp-blocks.json",
                    int(dict(case.candidate_environment)["NIPAT_DNP_BLOCK_LOCI"]), case.expected_compatibility_reason)})
        if case.name in PARALLEL_CASES:
            configured = execution or {"NIPAT_EXECUTION_MODE": "serial", "NIPAT_MAX_WORKERS": ""}
            cap = configured.get("NIPAT_MAX_WORKERS")
            comparison["parallel_execution"] = verify_parallel_execution(destination / "parallel-log",
                mode=configured["NIPAT_EXECUTION_MODE"], cap=int(cap) if cap else None,
                require_parallel=variant != "candidate", require_overlap=case.name in CONCURRENT_CASES)
        if variant == "manual-4-repeat":
            # Both independent runs equal the same exact oracle, including
            # output order and unrounded values; equivalence is transitive.
            comparison["deterministic_repeat_of"] = "manual-4"
        comparisons[variant] = comparison
        print(f"PASS: {case.name}/{variant}; exact tables, unrounded R values and {len(plots)} PDF(s)", flush=True)
    return {"case": case.name, "workflow": case.workflow, **comparisons["candidate"],
            "elapsed_seconds_including_container": timings,
            "execution_variants": comparisons}


def verify(root: Path, image: str) -> dict:
    reference = verify_reference()
    if shutil.which("pdftoppm") is None:
        raise ValueError("pdftoppm (Poppler) is required for exact PDF rendering comparisons")
    candidate_hashes = verify_image_sources(image, root)
    supporting_hashes = verify_supporting_sources(image, root)
    inputs = make_inputs(root, image)
    input_hashes = {p.relative_to(inputs).as_posix(): digest(p) for p in inputs.rglob("*") if p.is_file()}
    results = [verify_case(root, image, inputs, case) for case in cases()]
    qualified = {result["workflow"] for result in results if result["case"] in PARALLEL_CASES}
    if qualified != set(SCRIPTS):
        raise ValueError("All four scientific workflows must pass real parallel qualification")
    helpers = []
    for helper in sorted((PROJECT / "tests/r_optimization").glob("*/check_*.R")):
        relative = helper.relative_to(PROJECT)
        log = root / f"{helper.parent.name}-{helper.stem}.log"
        run(image, ["Rscript", f"/repo/{relative.as_posix()}", "/repo"],
            inputs=inputs, results=root, log=log)
        helpers.append({"path": relative.as_posix(), "sha256": digest(helper), "status": "passed"})
    indexed_helper = "tests/r_optimization/verify_indexed_pileup.py"
    run(image, ["python3", f"/repo/{indexed_helper}", "--project", "/repo",
                "--output-dir", "/results/indexed-pileup"],
        inputs=inputs, results=root, log=root / "indexed-pileup.log")
    indexed_report = root / "indexed-pileup/indexed-pileup.json"
    indexed_evidence = json.loads(indexed_report.read_text(encoding="utf-8"))
    if indexed_evidence.get("status") != "passed":
        raise ValueError("Indexed pileup audit did not pass")
    cancellation_helper = "tests/r_optimization/verify_dnp_cancellation.py"
    run(image, ["python3", f"/repo/{cancellation_helper}", "--bundle", "/opt/nipat",
                "--output-dir", "/results/dnp-cancellation"],
        inputs=inputs, results=root, log=root / "dnp-cancellation.log")
    cancellation_report = root / "dnp-cancellation/dnp-cancellation.json"
    cancellation_evidence = json.loads(cancellation_report.read_text(encoding="utf-8"))
    if cancellation_evidence.get("status") != "passed":
        raise ValueError("DNP R block cancellation audit did not pass")
    current_inputs = {p.relative_to(inputs).as_posix(): digest(p) for p in inputs.rglob("*") if p.is_file()}
    if current_inputs != input_hashes:
        raise ValueError("A reference or candidate execution modified fixture inputs")
    performance = root / "performance-observations.tsv"
    if not performance.is_file():
        raise ValueError("Synthetic performance observations are missing")
    return {"schema_version": 1, "status": "passed", "reference": reference,
            "candidate_r_sha256": candidate_hashes, "supporting_source_sha256": supporting_hashes,
            "runtime_image": image,
            "parallel_qualification": {"workflows": sorted(qualified),
                                       "variants": ["serial", *PARALLEL_VARIANTS],
                                       "concurrent_worker_cases": sorted(CONCURRENT_CASES),
                                       "distinct_worker_cases": sorted(PARALLEL_CASES - CONCURRENT_CASES),
                                       "container_limits": {"cpus": 4, "memory_gib": 8}},
            "comparison": {"table_bytes": "exact", "unrounded_r": "identical",
                           "pdf_pixels": "exact", "pdf_metadata": "excluded"},
            "timing_scope": "single observations; includes capture instrumentation and container startup; no speed claim",
            "inputs_unchanged": True, "input_sha256": input_hashes, "cases": results, "helpers": helpers,
            "indexed_pileup": {"file": indexed_report.relative_to(root).as_posix(),
                               "sha256": digest(indexed_report), "test_source_sha256": digest(PROJECT / indexed_helper),
                               "status": "passed", "cases": indexed_evidence["cases"]},
            "dnp_cancellation": {"file": cancellation_report.relative_to(root).as_posix(),
                                 "sha256": digest(cancellation_report),
                                 "test_source_sha256": digest(PROJECT / cancellation_helper),
                                 "status": "passed", "observed_r_progress": cancellation_evidence["observed_r_progress"]},
            "synthetic_performance": {
                "file": performance.name, "sha256": digest(performance),
                "scope": "source transformations and CPI core; three timing observations per variant",
                "memory": "Rprofmem allocation totals from a separate pass; not peak RAM",
                "speed_threshold": "none",
            }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=os.environ.get("NIPAT_RUNTIME_IMAGE", "nipat-scientific-runtime:ci-test"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = args.output_dir.resolve() if args.output_dir else Path(tempfile.mkdtemp(prefix="nipat-r-equivalence-"))
    if args.output_dir:
        root.mkdir(parents=True, exist_ok=False)
    try:
        result = verify(root, immutable_image(args.image))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        result = {"schema_version": 1, "status": "failed", "reference_commit": BASELINE_COMMIT, "error": str(exc)}
        (root / "r-equivalence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"R equivalence failed: {exc}\nEvidence: {root}", file=sys.stderr)
        return 1
    (root / "r-equivalence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"R equivalence passed. Evidence: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
