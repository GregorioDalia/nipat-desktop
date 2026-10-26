"""Execute the bundled R scripts without importing the desktop application.

Native script invocation remains available. All four workflows also
accept versioned requests prepared with the bundled shared adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys


BUNDLE_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATHS = {
    "dnp-call": "vendor/DNPcall/DNPcall.R",
    "snp-call": "vendor/NEWPAT/SNPcall/SNPcall.R",
    "contamination": "vendor/NEWPAT/contamination/detect_contamination.R",
    "cpi": "vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
}
PREPARATION_FILES = (
    "__init__.py", "errors.py", "panels.py", "files.py", "contamination.py", "snp.py", "dnp.py", "cpi.py",
    "catalog.py", "plan.py", "executor.py",
)
CATALOG_FILES = tuple(f"catalog_data/{workflow}.json" for workflow in SCRIPT_PATHS)
WORKFLOW_INTERFACES = {
    "contamination": "contamination-v1", "snp-call": "snp-call-v1", "dnp-call": "dnp-call-v1",
    "cpi": "cpi-v1",
}


class BundleError(Exception):
    """The installed scientific bundle cannot be verified or executed."""


def preparation_root(bundle_root: Path) -> Path:
    """Select explicit in-image code, or the repository's shared source tree.

    A deployed bundle never searches PYTHONPATH for missing components. The
    source-tree mode is for development and requires the checkout marker.
    """
    if (bundle_root / "lib").exists():
        return bundle_root / "lib"
    if (bundle_root / "pyproject.toml").is_file():
        return bundle_root / "src"
    return bundle_root / "lib"


def describe_preparation(bundle_root: Path) -> dict:
    root = bundle_root.resolve()
    library = preparation_root(root)
    paths = [root / "engine" / "main.py", *(
        library / "nipat_scientific" / name for name in (*PREPARATION_FILES, *CATALOG_FILES)
    )]
    hashes = {}
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise BundleError(f"Preparation module escapes its bundle: {path.name}")
        try:
            with resolved.open("rb") as source:
                hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    source, "sha256"
                ).hexdigest()
        except OSError as exc:
            raise BundleError(f"Cannot read preparation module: {path.name}") from exc
    return {"interface": "workflow-preparation-v1", "file_sha256": hashes}


def verify_bundle(bundle_root: Path) -> dict:
    """Verify every expected script and describe the exact bundled source bytes."""
    scientific_root = (bundle_root / "scientific").resolve()
    manifest = scientific_root / "SHA256SUMS"
    try:
        manifest_bytes = manifest.read_bytes()
        lines = manifest_bytes.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BundleError(f"Cannot read scientific manifest: {manifest}") from exc

    expected_hashes: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) is None:
            raise BundleError(f"Invalid scientific manifest entry at line {line_number}.")
        expected, relative_name = parts
        if relative_name in expected_hashes:
            raise BundleError(f"Duplicate scientific manifest entry: {relative_name}")
        expected_hashes[relative_name] = expected.lower()

    required = set(SCRIPT_PATHS.values())
    if set(expected_hashes) != required:
        missing = sorted(required - set(expected_hashes))
        unexpected = sorted(set(expected_hashes) - required)
        raise BundleError(
            "Scientific manifest does not match the supported workflows. "
            f"Missing: {missing}; unexpected: {unexpected}."
        )

    workflows = {}
    for workflow, relative_name in SCRIPT_PATHS.items():
        target = (scientific_root / relative_name).resolve()
        if not target.is_relative_to(scientific_root):
            raise BundleError(f"Scientific script escapes its bundle: {relative_name}")
        try:
            with target.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
        except OSError as exc:
            raise BundleError(f"Cannot read scientific script: {relative_name}") from exc
        if actual != expected_hashes[relative_name]:
            raise BundleError(f"Scientific script does not match its manifest: {relative_name}")
        workflows[workflow] = {
            "script": f"scientific/{relative_name}",
            "sha256": actual,
        }

    return {
        "schema_version": 1,
        "interface": "native-r-v1",
        "manifest": {
            "path": "scientific/SHA256SUMS",
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "workflows": workflows,
        "workflow_interfaces": WORKFLOW_INTERFACES.copy(),
        "plan_execution": {
            "interface": "workflow-plan-execution-v1",
            "schema_version": 1,
            "workflows": ["dnp-call", "contamination"],
            "scheduling": "sequential",
            "resume": False,
        },
        "preparation": describe_preparation(bundle_root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nipat-scientific",
        description="Verify and execute the R scripts bundled with the NIPAT image.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    describe = commands.add_parser("describe", help="Describe the verified scientific bundle.")
    describe.add_argument("--json", action="store_true", help="Write machine-readable metadata.")
    commands.add_parser("verify", help="Verify the bundled scientific source manifest.")
    catalog = commands.add_parser("catalog", help="Read the source-verified scientific catalog.")
    catalog.add_argument("workflow", nargs="?", choices=SCRIPT_PATHS)
    catalog.add_argument("--json", action="store_true", help="Write machine-readable catalog (default).")
    plan = commands.add_parser(
        "validate-plan", help="Validate a workflow plan without executing analyses or reading inputs.",
    )
    plan.add_argument("--plan", type=Path, required=True, help="JSON workflow plan with container paths.")
    execute_plan = commands.add_parser(
        "execute-plan", help="Execute supported workflow steps and preserve per-step status/results.",
    )
    execute_plan.add_argument("--plan", type=Path, required=True, help="JSON plan with container paths.")
    execute_plan.add_argument("--run-dir", type=Path, required=True, help="New workflow run directory.")
    execute_plan.add_argument("--json", action="store_true", help="Write the complete machine-readable execution report.")
    run = commands.add_parser("run", help="Run a bundled workflow with its native R arguments.")
    run.add_argument("workflow", choices=SCRIPT_PATHS)
    run.add_argument(
        "script_arguments", nargs=argparse.REMAINDER,
        help="Native R arguments, normally preceded by --; no desktop input adaptation.",
    )
    execute = commands.add_parser("execute", help="Prepare and run a bundled workflow request.")
    execute.add_argument("workflow", choices=WORKFLOW_INTERFACES)
    execute.add_argument("--request", type=Path, required=True, help="JSON request with container paths.")
    return parser


def run_preparation(command: list[str]) -> int:
    """Run samtools with inherited output and forward container stop signals.

    Python is PID 1 until it replaces itself with R. Explicit handlers ensure
    cancellation also reaches samtools; R is never started after cancellation,
    even when the child catches the signal and returns success.
    """
    child = None
    received_signal = None

    def forward(signum, _frame):
        nonlocal received_signal
        received_signal = signum
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        for signum in previous:
            signal.signal(signum, forward)
        print("$ " + shlex.join(command), flush=True)
        child = subprocess.Popen(command)
        if received_signal is not None:
            forward(received_signal, None)
        returncode = child.wait()
        if received_signal is not None:
            return 128 + received_signal
        return returncode if returncode >= 0 else 128 - returncode
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        description = verify_bundle(BUNDLE_ROOT)
        if arguments.command == "describe":
            if arguments.json:
                print(json.dumps(description, indent=2, sort_keys=True))
            else:
                print(f"NIPAT scientific interface: {description['interface']}")
                print(f"Manifest SHA-256: {description['manifest']['sha256']}")
                for workflow, source in description["workflows"].items():
                    print(f"{workflow}: {source['script']} ({source['sha256']})")
            return 0
        if arguments.command == "verify":
            print(f"Scientific bundle verified ({len(SCRIPT_PATHS)} workflows).")
            return 0

        if arguments.command in {"catalog", "validate-plan"}:
            library = preparation_root(BUNDLE_ROOT).resolve()
            sys.path.insert(0, str(library))
            from nipat_scientific.errors import ValidationError

            try:
                if arguments.command == "catalog":
                    from nipat_scientific.catalog import load_catalog
                    result = load_catalog(arguments.workflow, source_root=BUNDLE_ROOT)
                else:
                    from nipat_scientific.plan import validate_plan
                    result = validate_plan(json.loads(arguments.plan.read_text(encoding="utf-8")))
                # JSON escapes preserve every Unicode value while keeping the
                # transport independent of Windows console/pipe code pages.
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0
            except (ValidationError, ValueError, UnicodeError) as exc:
                raise BundleError(str(exc)) from exc

        if arguments.command == "execute-plan":
            library = preparation_root(BUNDLE_ROOT).resolve()
            sys.path.insert(0, str(library))
            from nipat_scientific.errors import ValidationError
            from nipat_scientific.executor import execute_plan

            try:
                document = json.loads(arguments.plan.read_text(encoding="utf-8"))
                result = execute_plan(
                    document, run_dir=arguments.run_dir,
                    script_paths={
                        workflow: BUNDLE_ROOT / description["workflows"][workflow]["script"]
                        for workflow in ("dnp-call", "contamination")
                    },
                )
                if arguments.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print(f"Workflow: {result['status']}")
                    print(f"Report: {arguments.run_dir / 'workflow-state.json'}")
                    if result.get("error"):
                        print(str(result["error"]), file=sys.stderr)
                return result["exit_code"]
            except (ValidationError, ValueError, UnicodeError) as exc:
                raise BundleError(str(exc)) from exc

        if arguments.command == "execute":
            library = preparation_root(BUNDLE_ROOT).resolve()
            sys.path.insert(0, str(library))
            # All required module paths were checked above. This exact bundled
            # library precedes PYTHONPATH; the desktop package is never imported.
            from nipat_scientific.errors import ValidationError

            try:
                request = json.loads(arguments.request.read_text(encoding="utf-8"))
                if arguments.workflow == "contamination":
                    from nipat_scientific.contamination import prepare_contamination
                    native_arguments = prepare_contamination(request)
                elif arguments.workflow == "cpi":
                    from nipat_scientific.cpi import prepare_cpi
                    native_arguments = prepare_cpi(request)
                elif arguments.workflow == "dnp-call":
                    from nipat_scientific.dnp import prepare_dnp
                    prepared = prepare_dnp(request)
                    native_arguments = prepared.native_arguments
                    os.chdir(prepared.working_dir)
                else:
                    from nipat_scientific.files import require_snp_pileup
                    from nipat_scientific.snp import prepare_snp
                    prepared = prepare_snp(request)
                    if prepared.preparation_command is not None:
                        returncode = run_preparation(prepared.preparation_command)
                        if returncode:
                            return returncode
                        require_snp_pileup(prepared.generated_pileup)
                    native_arguments = prepared.native_arguments
            except (ValidationError, ValueError) as exc:
                raise BundleError(str(exc)) from exc
        else:
            native_arguments = arguments.script_arguments
            if native_arguments[:1] == ["--"]:
                native_arguments = native_arguments[1:]
        script = BUNDLE_ROOT / description["workflows"][arguments.workflow]["script"]
        # Replace this process so R receives the container's signals and its exit
        # code is reported directly, without an extra shell or Python supervisor.
        os.execvp("Rscript", ["Rscript", str(script), *native_arguments])
        raise BundleError("Rscript execution unexpectedly returned.")
    except (BundleError, OSError) as exc:
        print(f"NIPAT scientific engine: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
