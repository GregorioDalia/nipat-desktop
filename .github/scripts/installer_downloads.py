"""Summarize the verified packages already retained by their producer jobs."""

import argparse
import json
import os
from pathlib import Path
import re


def download_rows(record):
    if record.get("publication_authorized") is not False:
        raise ValueError("Candidate downloads cannot authorize publication.")
    rows = []
    for key, artifact, label in (("windows", "nipat-windows-setup", "Windows 10/11 x64"),
                                  ("linux", "nipat-linux-setup", "Ubuntu 24.04 amd64"),
                                  ("macos_arm64", "nipat-macos-setup-arm64", "macOS Apple Silicon"),
                                  ("macos_x86_64", "nipat-macos-setup-x86_64", "macOS Intel")):
        package = record[key]
        digest = package["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid verified package digest: " + label)
        rows.append((label, package["file"], artifact, digest))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.evidence.read_text())
    rows = download_rows(record)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write("## Candidate installer downloads\n\n")
        for label, filename, artifact, digest in rows:
            output.write(f"{label}: `{filename}` in artifact `{artifact}`.\n\nSHA-256: `{digest}`\n\n")
        output.write("The original build artifacts contain the installers and their verification reports; available for 14 days. Published releases provide the individual installers directly.\n\n")
        output.write("Candidate build only. Native macOS package checks do not qualify Lima/Rosetta execution. Observed desktop checks are recorded separately before publication.\n")


if __name__ == "__main__":
    main()
