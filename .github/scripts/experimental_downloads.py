"""Expose direct downloads only when uploaded bytes match the verified installer set."""

import argparse
import json
import os
from pathlib import Path


def download_rows(evidence, environment):
    if evidence.get("publication_authorized") is not False or evidence.get("desktop_acceptance") is not False:
        raise ValueError("Expected an experimental review record, not release approval")
    rows = []
    for key, package in (("WINDOWS", evidence["windows"]), ("ARM64", evidence["macos"]["arm64"]),
                         ("INTEL", evidence["macos"]["x86_64"])):
        if environment.get(f"{key}_SHA256") != package["sha256"]:
            raise ValueError(f"Direct {key} download differs from the verified installer")
        url = environment.get(f"{key}_URL", "")
        if not url.startswith("https://github.com/GregorioDalia/nipat-desktop/actions/runs/"):
            raise ValueError("Expected a download from this repository's review run")
        rows.append(f"- [{package['file']}]({url}) — SHA-256 `{package['sha256']}`")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    rows = download_rows(evidence, os.environ)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write("## Experimental installer downloads\n\n" + "\n".join(rows) + "\n\n")
        summary.write("One file per platform. GitHub sign-in is required; artifacts expire after 14 days.\n\n")
        summary.write("Client/package checks and the Linux scientific regression passed. Windows 10/11 desktop "
                      "installation and macOS Lima/Rosetta execution are separate qualifications. "
                      "Real macOS runtime results, when explicitly requested, are recorded in the "
                      "macos-runtime jobs; the hosted package reports do not imply VM acceptance. "
                      "This unsigned experimental build does not replace the stable release or update feed.\n")


if __name__ == "__main__":
    main()
