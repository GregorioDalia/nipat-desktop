"""Publish candidate download links only when their bytes match the verified set."""

import argparse
import json
import os
from pathlib import Path
import re


def download_rows(record, environment):
    if record.get("publication_authorized") is not False:
        raise ValueError("Candidate downloads cannot authorize publication.")
    rows = []
    for key, prefix, label in (("windows", "WINDOWS", "Windows 10/11 x64"),
                               ("linux", "LINUX", "Ubuntu 24.04 amd64"),
                               ("macos_arm64", "ARM64", "macOS Apple Silicon"),
                               ("macos_x86_64", "INTEL", "macOS Intel")):
        package = record[key]
        digest = environment[prefix + "_SHA256"]
        url = environment[prefix + "_URL"]
        if digest != package["sha256"] or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Direct download differs from the verified package: " + label)
        if not re.fullmatch(r"https://github\.com/GregorioDalia/nipat-desktop/actions/runs/[0-9]+/artifacts/[0-9]+", url):
            raise ValueError("Unexpected candidate artifact URL.")
        rows.append((label, package["file"], url, digest))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.evidence.read_text())
    rows = download_rows(record, os.environ)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write("## Candidate installer downloads\n\n")
        for label, filename, url, digest in rows:
            output.write(f"{label}: [{filename}]({url})\n\nSHA-256: `{digest}`\n\n")
        output.write("One self-contained installer per platform. Sign in to GitHub to download; available for 14 days.\n\n")
        output.write("Candidate build only. Native macOS package checks do not qualify Lima/Rosetta execution. Observed desktop checks are recorded separately before publication.\n")


if __name__ == "__main__":
    main()
