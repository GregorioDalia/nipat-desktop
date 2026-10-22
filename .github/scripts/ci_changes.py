"""Select scientific integration checks without ever skipping the required CI gate."""

import argparse
import json
from pathlib import Path
import re
import subprocess


SCIENTIFIC_PREFIXES = ("src/", "scientific/", "docker/", "engine/", "tests/fixtures/")
SCIENTIFIC_FILES = {
    "compose.yaml", "pyproject.toml", ".dockerignore",
    "tests/test_engine_package.py",
    ".github/workflows/ci.yml", ".github/workflows/windows-installer.yml",
    ".github/scripts/ci_changes.py", ".github/scripts/test_ci_changes.py",
}


def affects_scientific(path):
    return (path.startswith(SCIENTIFIC_PREFIXES) or path in SCIENTIFIC_FILES
            or path.startswith("scripts/verify_")
            or path.startswith("scripts/check_runtime_"))


def scientific_decision(base, head, *, force=False, repository=Path(".")):
    if force:
        return True, "Manual verification requests scientific integration."
    # A missing base (new branch, force push, unavailable history) must never
    # turn an unknown change into a documentation-only success.
    if (not re.fullmatch(r"[0-9a-f]{40}", base or "") or base == "0" * 40
            or not re.fullmatch(r"[0-9a-f]{40}", head or "")):
        return True, "Comparison unavailable; scientific integration is required."
    try:
        # Disabling rename detection includes both old and new paths. Moving a
        # scientific file out of its directory must still trigger integration.
        paths = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
            cwd=repository, stderr=subprocess.PIPE,
        ).decode("utf-8").split("\0")
    except (subprocess.CalledProcessError, UnicodeDecodeError, OSError):
        return True, "Comparison failed; scientific integration is required."
    required = any(affects_scientific(path) for path in paths if path)
    reason = ("Scientific inputs or execution code changed." if required else
              "No scientific inputs or execution code changed; quick checks still run.")
    return required, reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    required, reason = scientific_decision(args.base, args.head, force=args.event == "workflow_dispatch")
    value = str(required).lower()
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(f"scientific={value}\nreason={reason}\n")
    print(json.dumps({"scientific": required, "reason": reason}))


if __name__ == "__main__":
    main()
