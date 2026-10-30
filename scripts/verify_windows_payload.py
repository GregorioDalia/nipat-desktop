"""Qualify the staged Windows client with its real embedded Python.

This deliberately does not claim an Inno installation or scientific/WSL run.
Dry-run BAM placeholders exercise file selection and plan transport only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys


PYTHON_ARCHIVE = "python-3.12.10-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
CHECKS = (
    "payload_integrity", "embedded_python", "packaged_imports", "scientific_catalog",
    "wizard_navigation", "composed_workflow_plans", "snp_batch_plans",
    "read_only_input_mounts", "original_inputs_unchanged",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def payload_file(app: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative != "" and
            PurePosixPath(relative).as_posix() == relative and
            not PurePosixPath(relative).is_absolute() and
            all(part not in {".", "..", ""} and not part.endswith((".", " ")) and
                re.search(r'[<>:"|?*\\\x00-\x1f]', part) is None
                for part in relative.split("/")), "Unsafe payload path.")
    path = app / relative
    require(not any(parent.is_symlink() for parent in (path, *path.parents)) and
            path.is_file() and path.resolve().is_relative_to(app.resolve()),
            f"Missing or redirected payload file: {relative}")
    return path


def verify_payload(app: Path) -> tuple[dict, dict]:
    manifest_path = app / ".distribution/installer-manifest.json"
    manifest = read_json(manifest_path)
    inventory = read_json(app / ".distribution/application-files.json")
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1 and
            re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")) is not None,
            "Invalid installer identity.")
    require(inventory.get("schema_version") == 1 and
            inventory.get("installation_channel") == "experimental08" and
            inventory.get("source_commit") == manifest["source_commit"], "Inventory identity mismatch.")
    sources = manifest.get("source_sha256")
    require(isinstance(sources, dict) and bool(sources), "Missing source inventory.")
    files = inventory.get("files")
    require(isinstance(files, list) and bool(files), "Missing application inventory.")
    recorded = {}
    for entry in files:
        require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}, "Invalid inventory entry.")
        path = payload_file(app, entry["path"])
        require(entry["path"].casefold() not in {key.casefold() for key in recorded},
                "Duplicate application inventory path.")
        require(digest(path) == entry["sha256"], f"Changed packaged file: {entry['path']}")
        recorded[entry["path"]] = entry["sha256"]
    generated = {"release.json", "NIPAT.exe", "installer/windows/EnableWsl.exe",
                 ".distribution/installer-manifest.json", f".distribution/{PYTHON_ARCHIVE}"}
    require(set(recorded) == set(sources) | generated, "Incomplete application inventory.")
    require(all(recorded[path] == value for path, value in sources.items()), "Source digest mismatch.")
    require(recorded[f".distribution/{PYTHON_ARCHIVE}"] == PYTHON_SHA256,
            "The verified embedded Python archive is required.")
    release = read_json(app / "release.json")
    require(release.get("schema_version") == 1 and
            release.get("package_version") == manifest.get("version") and
            release.get("source_git") == {"commit": manifest["source_commit"], "dirty": False, "available": True} and
            release.get("source_sha256") == sources and
            release.get("installer_manifest_sha256") == digest(manifest_path) and
            release.get("runtime") == {"image_id": manifest.get("runtime_image")} and
            release.get("python") == {"version": "3.12.10", "architecture": "amd64", "archive_sha256": PYTHON_SHA256},
            "Release metadata does not describe the compiled payload.")
    return manifest, inventory


def verify_plan(run: Path, *, workflows: list[str], mode: str, originals: list[Path], commit: str) -> None:
    from nipat_scientific.plan import validate_plan

    record = read_json(run / "run.json")
    plan = read_json(run / "work/engine-plan.json")
    require(validate_plan(plan)["plan"] == plan, "Noncanonical engine plan.")
    require([step["workflow"] for step in plan["steps"]] == workflows, "Wrong planned workflow order.")
    require(record.get("status") == "planned" and record.get("engine_verification") == "not_run_dry_run",
            "A client-only check must not report scientific success.")
    commands = record.get("commands", [])
    require(len(commands) == 1 and commands[0].get("status") == "planned" and
            "execute-plan" in commands[0].get("argv", []), "Expected one planned image-owned execution.")
    source = record.get("source", {})
    require(source.get("role") == "client" and
            source.get("release", {}).get("source_git", {}).get("commit") == commit,
            "Run source identity mismatch.")
    expected = [{"id": step["id"], "workflow": step["workflow"],
                 **({"sample": step["inputs"]["sample"], "mode": step["parameters"]["mode"]}
                    if step["workflow"] == "snp-call" else {})} for step in plan["steps"]]
    require(record["parameters"].get("expected_steps") == expected, "Step provenance mismatch.")
    mapping = record["parameters"]["sample_mapping"]
    require([Path(item["original_path"]) for item in mapping] == originals,
            "Original sample selection/order was lost.")
    require([(item["sample_id"], item["container_path"]) for item in mapping] ==
            [(item["id"], item["path"]) for item in plan["samples"]], "Sample mapping mismatch.")
    for step in plan["steps"]:
        if step["workflow"] == "snp-call":
            require(step["parameters"]["mode"] == mode and
                    (step["inputs"]["reference"] is None) == (mode == "pileup"), "Incorrect SNP input mode.")
        if step["workflow"] == "cpi":
            pair = step["inputs"]["pairs"]
            require(len(pair) == 1 and pair[0]["id"] == "family_a" and
                    pair[0]["mother"] == {"step": "dnp", "output": "dnp-tables", "sample": "sample_0001"} and
                    pair[0]["father"] == {"step": "dnp", "output": "dnp-tables", "sample": "sample_0002"} and
                    step["parameters"]["err_const"] == 0.1, "CPI roles or tunable value changed.")
    service = read_json(run / "work/engine-compose.json")["services"]["scientific"]
    require(service.get("read_only") is True and service.get("network_mode") == "none", "Unsafe service configuration.")
    volumes = service["volumes"]
    writable = [mount for mount in volumes if mount.get("read_only") is not True]
    require(len(writable) == 1 and writable[0].get("read_only") is False and
            writable[0]["target"] == f"/workspace/runs/{run.name}", "Unexpected writable mount.")
    require(all(any(mount["target"] == sample["path"] and mount.get("read_only") is True
                    for mount in volumes) for sample in plan["samples"]), "Samples are not read-only mounts.")
    require(not any((run / "output").iterdir()), "Dry-run produced scientific output.")


def fixtures(work: Path) -> dict[str, Path]:
    external = work / "external inputs $ ,= è"
    external.mkdir()
    contents = {
        "mother.bam": "DRY-RUN PLACEHOLDER mother; not a scientific BAM\n",
        "father.bam": "DRY-RUN PLACEHOLDER father; not a scientific BAM\n",
        "reference.fa": ">chr1\n" + "ACGT" * 10 + "\n",
        "reference.fa.fai": "chr1\t40\t6\t40\t41\n",
        "dnp.tsv": "chr1\t10\t11\tAC\tGT\nchr1\t20\t21\tTA\tCG\n",
        "snp.tsv": "pos\tref\talt\nchr1:10\tA\tG\nchr1:20\tT\tC\n",
        "population.tsv": "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t10\t11\t0.75\t0.25\n",
        "one.pileup": "chr1\t10\tA\t2\t.G\tII\tread1,read2\n",
        "two.pileup": "chr1\t20\tT\t2\t.C\tII\tread3,read4\n",
    }
    paths = {}
    for name, content in contents.items():
        paths[name] = external / name
        paths[name].write_text(content, encoding="utf-8")
    return paths


def exercise_client(app: Path, work: Path, manifest: dict) -> None:
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("NIPAT_") and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    environment.update({"NIPAT_PROJECT_DIR": str(app), "NIPAT_WORKSPACE_DIR": str(work),
                        "NIPAT_DATA_DIR": str(work / "data"), "NIPAT_RUNS_DIR": str(work / "runs"),
                        "LOCALAPPDATA": str(work / "local-app-data"), "APPDATA": str(work / "roaming"),
                        "NIPAT_BACKEND": "wsl", "NIPAT_WSL_DISTRO": "NIPAT-Package-Verification",
                        "NIPAT_RUNTIME_IMAGE": manifest["runtime_image"], "PYTHONIOENCODING": "utf-8"})
    logs = work / "logs"
    logs.mkdir()
    cwd = work / "working directory è"
    cwd.mkdir()

    def invoke(name: str, args: list, stdin: str | None = None) -> str:
        command = [sys.executable, "-B", "-X", "utf8", "-m", "nipat", *map(str, args)]
        result = subprocess.run(command, input=stdin, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=cwd, env=environment, timeout=120)
        (logs / f"{name}.log").write_text(json.dumps(command, ensure_ascii=False) + "\n" +
                                         result.stdout + "\nSTDERR:\n" + result.stderr, encoding="utf-8")
        require(result.returncode == 0, f"Packaged command failed: {name}; see {logs}.")
        return result.stdout

    require(invoke("version", ["--version"]).strip() == f"NIPAT {manifest['version']}", "Wrong packaged version.")
    catalog = json.loads(invoke("catalog", ["parameters", "--json"]))
    require(set(catalog["workflows"]) ==
            {"dnp-call", "snp-call", "contamination", "cpi"}, "Incomplete packaged scientific catalog.")
    menu = invoke("wizard", ["--dry-run", "wizard"], "w\n0\n0\n")
    require(all(label in menu for label in ("Workflow automatici", "DNPcall -> Contamination",
            "DNPcall -> CPI", "DNPcall -> Contamination e CPI", "SNPcall su piu' campioni",
            "Analisi singole", "Configurazione e strumenti", "Ctrl+C")),
            "Packaged workflow menu is incomplete.")
    cancelled = invoke("wizard-cancellation", ["--dry-run", "wizard"],
                       "7\n6\n1\n:annulla\nW\n1\n1\n:annulla\n5\n1\n2\n:annulla\n0\n")
    require(cancelled.count("Operazione annullata. Ritorno al menu principale.") == 3 and
            not list((work / "runs").rglob("run.json")),
            "Packaged cancellation did not return to the main menu without creating runs.")
    paths = fixtures(work)
    hashes = {path: digest(path) for path in paths.values()}
    bams = [paths["mother.bam"], paths["father.bam"]]
    common = ["--reference", paths["reference.fa"], "--panel", paths["dnp.tsv"], "--snp-panel", paths["snp.tsv"]]
    for preset in ("dnp-contamination", "dnp-cpi", "dnp-contamination-cpi"):
        selected = (["--bam", bams[0], "--bam", bams[1]] if preset == "dnp-contamination" else
                    ["--pair", "family_a", *bams, "--popfreq", paths["population.tsv"], "--err-const", "0.1"])
        invoke(preset, ["--dry-run", "workflow", preset, *selected, *common, "--run-name", preset])
        steps = ["dnp-call"] + (["contamination"] if "contamination" in preset else []) + (["cpi"] if "cpi" in preset else [])
        verify_plan(work / "runs" / preset, workflows=steps + ["snp-call"] * 2,
                    mode="bam", originals=bams, commit=manifest["source_commit"])
    for mode in ("bam", "pileup"):
        originals = bams if mode == "bam" else [paths["one.pileup"], paths["two.pileup"]]
        selected = [f"--{mode}", originals[0], f"--{mode}", originals[1]]
        if mode == "bam":
            selected.extend(["--reference", paths["reference.fa"]])
        name = f"snp-batch-{mode}"
        invoke(name, ["--dry-run", "workflow", "snp-batch", *selected, "--panel", paths["snp.tsv"], "--run-name", name])
        verify_plan(work / "runs" / name, workflows=["snp-call"] * 2, mode=mode,
                    originals=originals, commit=manifest["source_commit"])
    require(hashes == {path: digest(path) for path in paths.values()}, "Original inputs were changed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("app-dir", "work-dir", "installer", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    app, work = args.app_dir.resolve(), args.work_dir.resolve()
    require(os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"}, "Windows amd64 is required.")
    require(sys.version_info[:3] == (3, 12, 10) and Path(sys.executable).resolve() ==
            app / ".runtime/python/python.exe", "The staged embedded Python must execute this check.")
    require(args.installer.is_file() and not args.output.exists(), "Missing installer or existing evidence.")
    manifest, inventory = verify_payload(app)
    for name in ("nipat", "nipat.workflow_forms", "nipat.catalog_ui", "nipat_scientific.plan", "nipat_scientific.executor"):
        module = importlib.import_module(name)
        require(Path(module.__file__).resolve().is_relative_to(app / "src"), f"Import escaped packaged sources: {name}")
    require(importlib.import_module("nipat").__version__ == manifest["version"], "Manifest/version mismatch.")
    exercise_client(app, work, manifest)
    require(verify_payload(app) == (manifest, inventory), "The payload changed during client verification.")
    report = {"schema_version": 1, "platform": "windows-amd64", "scenario": "staged-embedded-python-client",
              "version": manifest["version"], "source_commit": manifest["source_commit"],
              "installer_manifest_sha256": digest(app / ".distribution/installer-manifest.json"),
              "application_inventory_sha256": digest(app / ".distribution/application-files.json"),
              "launcher_sha256": digest(app / "NIPAT.exe"), "installer_sha256": digest(args.installer),
              "python_version": "3.12.10", "scientific_execution": False, "wsl_execution": False,
              "checks": {name: True for name in CHECKS}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("PASS: staged Windows client; no installation, WSL or scientific execution claimed.")


if __name__ == "__main__":
    main()
