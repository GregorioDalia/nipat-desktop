"""Execute the bundled R scripts without importing the desktop application.

Native script invocation remains available. Contamination also accepts a
versioned request and prepares its inputs with the bundled shared adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


BUNDLE_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATHS = {
    "dnp-call": "vendor/DNPcall/DNPcall.R",
    "snp-call": "vendor/NEWPAT/SNPcall/SNPcall.R",
    "contamination": "vendor/NEWPAT/contamination/detect_contamination.R",
    "cpi": "vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
}
PREPARATION_FILES = (
    "__init__.py", "errors.py", "panels.py", "files.py", "contamination.py",
)


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
        library / "nipat_scientific" / name for name in PREPARATION_FILES
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
    return {"interface": "contamination-v1", "file_sha256": hashes}


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
        "workflow_interfaces": {"contamination": "contamination-v1"},
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
    run = commands.add_parser("run", help="Run a bundled workflow with its native R arguments.")
    run.add_argument("workflow", choices=SCRIPT_PATHS)
    run.add_argument(
        "script_arguments", nargs=argparse.REMAINDER,
        help="Native R arguments, normally preceded by --; no desktop input adaptation.",
    )
    execute = commands.add_parser("execute", help="Prepare and run a bundled workflow request.")
    execute.add_argument("workflow", choices=("contamination",))
    execute.add_argument("--request", type=Path, required=True, help="JSON request with container paths.")
    return parser


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

        if arguments.command == "execute":
            library = preparation_root(BUNDLE_ROOT).resolve()
            sys.path.insert(0, str(library))
            # All required module paths were checked above. This exact bundled
            # library precedes PYTHONPATH; the desktop package is never imported.
            from nipat_scientific.contamination import prepare_contamination
            from nipat_scientific.errors import ValidationError

            try:
                request = json.loads(arguments.request.read_text(encoding="utf-8"))
                native_arguments = prepare_contamination(request)
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
