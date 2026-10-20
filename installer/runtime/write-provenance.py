"""Record the exact filesystem inputs while building the dedicated WSL rootfs."""

import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def collect_engine_notices(engine_version: str, destination: Path) -> dict:
    """Keep the actual engine's upstream notices; official .deb lacks copyright."""
    match = re.fullmatch(r"Docker version ([0-9]+\.[0-9]+\.[0-9]+), build [0-9a-f]+", engine_version)
    if not match:
        raise ValueError(f"Cannot identify the installed Docker Engine version: {engine_version}")
    version = match[1]
    # Moby moved Docker Engine release tags to docker-v with Docker 29.
    tag = ("docker-v" if int(version.split(".")[0]) >= 29 else "v") + version
    destination.mkdir(parents=True, exist_ok=True)
    notices = []
    for name in ("LICENSE", "NOTICE"):
        url = f"https://raw.githubusercontent.com/moby/moby/{tag}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read(2 * 1024 * 1024 + 1)
        except (OSError, urllib.error.URLError) as error:
            raise ValueError(f"Cannot preserve upstream Docker Engine notice {url}: {error}") from error
        if not content or len(content) > 2 * 1024 * 1024:
            raise ValueError(f"Unexpected upstream Docker Engine notice size: {url}")
        path = destination / f"upstream-{name}"
        path.write_bytes(content)
        notices.append({"url": url, "path": str(path), "sha256": hashlib.sha256(content).hexdigest()})
    return {"version": version, "source_tag": tag, "files": notices}


def main() -> None:
    commit, base_image = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("SOURCE_COMMIT must identify the exact source checkout")
    packages = dict(
        line.split("\t", 1)
        for line in Path("/usr/share/nipat/apt-versions.tsv").read_text().splitlines()
    )
    engine_version = subprocess.check_output(["dockerd", "--version"], text=True).strip()
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
        "docker_engine_version": engine_version,
        "compose_version": subprocess.check_output(["docker", "compose", "version"], text=True).strip(),
        "license_directory": "/usr/share/doc",
        "package_metadata": "/usr/share/nipat/docker-package-metadata.txt",
        "upstream_engine_notices": collect_engine_notices(engine_version, Path("/usr/share/doc/docker-ce")),
    }
    Path("/etc/nipat-runtime.json").write_text(json.dumps(marker, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from error
