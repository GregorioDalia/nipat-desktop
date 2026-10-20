"""Record the exact filesystem inputs while building the dedicated WSL rootfs."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


commit, base_image = sys.argv[1:]
if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise SystemExit("SOURCE_COMMIT must identify the exact source checkout")
packages = dict(
    line.split("\t", 1)
    for line in Path("/usr/share/nipat/apt-versions.tsv").read_text().splitlines()
)
marker = {
    "schema_version": 1,
    "vendor": "nipat-desktop",
    "purpose": "dedicated-wsl-runtime",
    "source_commit": commit,
    "base_image": base_image,
    "os": "debian-bookworm",
    "architecture": subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip(),
    "apt_packages": packages,
    "docker_apt_repository": "https://download.docker.com/linux/debian",
    "docker_apt_key_sha256": hashlib.sha256(
        Path("/etc/apt/keyrings/docker.asc").read_bytes()
    ).hexdigest(),
    "docker_version": subprocess.check_output(["docker", "--version"], text=True).strip(),
    "compose_version": subprocess.check_output(["docker", "compose", "version"], text=True).strip(),
    "license_directory": "/usr/share/doc",
    "package_metadata": "/usr/share/nipat/docker-package-metadata.txt",
}
Path("/etc/nipat-runtime.json").write_text(json.dumps(marker, indent=2) + "\n")
