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


def write_tsv(path: Path, fields: tuple[str, ...], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


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
    for sample in ("A", "B"):
        records = ["@HD\tVN:1.6\tSO:coordinate", f"@SQ\tSN:chrDnpSynthetic\tLN:{len(sequence)}"]
        for start, covered in ((20, (50, 52)), (110, (140,)), (200, (230,))):
            for index, name in enumerate(("a", "A", "z", "Z", "r-1", "r.2", "r_3", "r@skip")):
                bases = list(sequence[start - 1:start + 79])
                for position in covered:
                    if (index + (sample == "B")) % 3 == 1:
                        bases[position - start:position - start + 2] = alternatives[position]
                    elif index == 6:
                        bases[position - start] = "ACGT"[("ACGT".index(bases[position - start]) + 1) % 4]
                quality = "I" * len(bases)
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
    return inputs


def cases() -> list[Case]:
    dnp = ("--bamlist=bamlist.txt", "--DNPs=/inputs/dnp/panel.txt",
           "--reference=/inputs/dnp/reference.fa", "--out=output")
    cpi = ("--pileup_dir", "/inputs/cpi/samples", "--out_dir", "output",
           "--pairs", "Informative:Informative,NoSites:NoSites,Deep:Deep",
           "--mother_prefix", "Mother", "--father_prefix", "Father",
           "--popfreq", "/inputs/cpi/population.tsv")
    return [
        Case("dnp-single", "dnp-call", dnp, ("/inputs/dnp/A.bam",)),
        Case("dnp-multi", "dnp-call", dnp, ("/inputs/dnp/A.bam", "/inputs/dnp/B.bam")),
        Case("dnp-parallel", "dnp-call", (*dnp, "--parallel"), ("/inputs/dnp/A.bam", "/inputs/dnp/B.bam")),
        Case("snp-edge", "snp-call", ("--pileup", "/inputs/snp/pileup.txt", "--snplist", "/inputs/snp/panel.tsv", "--out", "output/SNPcall_output.txt")),
        Case("cpi-all", "cpi", cpi),
        Case("cpi-panels", "cpi", (*cpi, "--cutoff_map", "Full=/inputs/cpi/full.tsv,Subset=/inputs/cpi/subset.tsv")),
        Case("cpi-zero-error", "cpi", (*cpi, "--err_const", "0")),
        Case("contamination-batch", "contamination", ("/inputs/contamination/panel.txt", "/inputs/contamination/samples", "output")),
        Case("contamination-single", "contamination", ("/inputs/contamination/panel.txt", "/inputs/contamination/samples/single.txt", "output")),
        Case("contamination-panel-only", "contamination", ("/inputs/panel-only/panel.txt", "/inputs/panel-only", "output")),
    ]


def verify(root: Path, image: str) -> dict:
    reference = verify_reference()
    if shutil.which("pdftoppm") is None:
        raise ValueError("pdftoppm (Poppler) is required for exact PDF rendering comparisons")
    candidate_hashes = verify_image_sources(image, root)
    inputs = make_inputs(root, image)
    input_hashes = {p.relative_to(inputs).as_posix(): digest(p) for p in inputs.rglob("*") if p.is_file()}
    results = []
    for case in cases():
        case_dir = root / case.name
        timings = {}
        for variant in ("reference", "candidate"):
            destination = case_dir / variant
            (destination / "output").mkdir(parents=True)
            if case.bamlist:
                (destination / "bamlist.txt").write_text("\n".join(case.bamlist) + "\n", encoding="utf-8")
            path = Path(SCRIPTS[case.workflow])
            if variant == "reference":
                path = BASELINE / path
            started = time.monotonic()
            run(image, ["Rscript", "/repo/tests/r_optimization/capture.R", *case.arguments],
                inputs=inputs, results=destination,
                environment={"NIPAT_EQ_SCRIPT": f"/repo/{path.as_posix()}", "NIPAT_EQ_WORKFLOW": case.workflow},
                log=destination / "execution.log")
            timings[variant] = round(time.monotonic() - started, 6)
        table_hashes = compare_tables(case_dir / "reference/output", case_dir / "candidate/output")
        run(image, ["Rscript", "/repo/tests/r_optimization/compare.R",
                    "/inputs/reference/scientific-values.rds", "/inputs/candidate/scientific-values.rds"],
            inputs=case_dir, results=case_dir, log=case_dir / "unrounded-comparison.log")
        plots = compare_pdfs(case_dir / "reference/output", case_dir / "candidate/output", case_dir / "rendered")
        results.append({"case": case.name, "workflow": case.workflow, "status": "passed",
                        "table_sha256": table_hashes, "unrounded_r_values": "identical",
                        "plots": plots, "elapsed_seconds_including_container": timings})
        print(f"PASS: {case.name}; exact tables, unrounded R values and {len(plots)} PDF(s)", flush=True)
    helpers = []
    for helper in sorted((PROJECT / "tests/r_optimization").glob("*/check_*.R")):
        relative = helper.relative_to(PROJECT)
        log = root / f"{helper.parent.name}-{helper.stem}.log"
        run(image, ["Rscript", f"/repo/{relative.as_posix()}", "/repo"],
            inputs=inputs, results=root, log=log)
        helpers.append({"path": relative.as_posix(), "sha256": digest(helper), "status": "passed"})
    current_inputs = {p.relative_to(inputs).as_posix(): digest(p) for p in inputs.rglob("*") if p.is_file()}
    if current_inputs != input_hashes:
        raise ValueError("A reference or candidate execution modified fixture inputs")
    return {"schema_version": 1, "status": "passed", "reference": reference,
            "candidate_r_sha256": candidate_hashes, "runtime_image": image,
            "comparison": {"table_bytes": "exact", "unrounded_r": "identical",
                           "pdf_pixels": "exact", "pdf_metadata": "excluded"},
            "timing_scope": "single observations; includes capture instrumentation and container startup; no speed claim",
            "inputs_unchanged": True, "input_sha256": input_hashes, "cases": results, "helpers": helpers}


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
