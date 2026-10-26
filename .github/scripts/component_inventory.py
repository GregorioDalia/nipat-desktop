"""Record exact scientific and WSL package inventories without executing user inputs."""

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess


def run(image, *command):
    return subprocess.check_output([
        "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m", "--env", "TMPDIR=/tmp",
        "--entrypoint", command[0], image, *command[1:],
    ], text=True, encoding="utf-8")


def image_id(image):
    return subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()


def verify(path, manifest):
    """Validate inventory identities before publishing; image contents are probed during build."""
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 4 * 1024 * 1024:
        raise ValueError("Missing or oversized component inventory")
    value = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {"schema_version", "source_commit", "scientific", "wsl", "scope"}
    if (not isinstance(value, dict) or set(value) != expected_keys
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["source_commit"] != manifest["source_commit"]
            or not isinstance(value["scope"], str) or not value["scope"].strip()):
        raise ValueError("Component inventory source identity mismatch")
    science, wsl = value["scientific"], value["wsl"]
    # The exporter records its original Docker image ID in the manifest, but
    # that export-only field is not inside /etc/nipat-runtime.json. Importing
    # the exact rootfs archive also creates a new image ID; record it separately.
    marker = {key: item for key, item in manifest["rootfs_provenance"].items()
              if key != "rootfs_image_id"}
    if (not isinstance(science, dict) or set(science) != {
            "image_id", "apt_packages_tsv", "r_packages_tsv", "samtools_version"}
            or science["image_id"] != manifest["runtime_image"]
            or not isinstance(wsl, dict) or set(wsl) != {
                "image_id", "apt_packages_tsv", "component_provenance"}
            or not isinstance(wsl["image_id"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", wsl["image_id"])
            or wsl["component_provenance"] != marker):
        raise ValueError("Component inventory runtime identity mismatch")
    for group, field in ((science, "apt_packages_tsv"), (science, "r_packages_tsv"),
                         (science, "samtools_version"), (wsl, "apt_packages_tsv")):
        if not isinstance(group[field], str) or not group[field].strip():
            raise ValueError("Component inventory is incomplete")
    rows = [line.split("\t") for line in wsl["apt_packages_tsv"].splitlines()]
    if (any(len(row) != 2 for row in rows) or len({row[0] for row in rows}) != len(rows)
            or dict(rows) != manifest["rootfs_provenance"]["apt_packages"]):
        raise ValueError("WSL package inventory differs from its component provenance")
    apt_rows = [line.split("\t") for line in science["apt_packages_tsv"].splitlines()]
    r_rows = [line.split("\t") for line in science["r_packages_tsv"].splitlines()]
    if (any(len(row) != 2 or not all(row) for row in apt_rows)
            or len({row[0] for row in apt_rows}) != len(apt_rows)
            or len(r_rows) < 2 or r_rows[0] != ["Package", "Version", "License"]
            or any(len(row) != 3 or not all(row) for row in r_rows[1:])):
        raise ValueError("Scientific package inventory is not valid TSV")
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scientific-image", required=True)
    parser.add_argument("--rootfs-image", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = {
        "schema_version": 1, "source_commit": args.source_commit,
        "scientific": {"image_id": image_id(args.scientific_image),
            "apt_packages_tsv": run(args.scientific_image, "cat", "/usr/share/nipat/apt-versions.tsv"),
            "r_packages_tsv": run(args.scientific_image, "Rscript", "-e",
                'write.table(installed.packages()[,c("Package","Version","License")], row.names=FALSE, quote=FALSE, sep="\\t")'),
            "samtools_version": run(args.scientific_image, "samtools", "--version"),
        },
        "wsl": {"image_id": image_id(args.rootfs_image),
            "apt_packages_tsv": run(args.rootfs_image, "cat", "/usr/share/nipat/apt-versions.tsv"),
            "component_provenance": json.loads(run(args.rootfs_image, "cat", "/etc/nipat-runtime.json")),
        },
        "scope": "Resolved installed package inventories; not a completeness guarantee for a vulnerability scan.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
