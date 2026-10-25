"""Install the Ubuntu package with initially missing dependencies in a container.

APT runs only in a disposable Ubuntu container. No Docker socket, privileged
mode, host package manager, or writable host directory is exposed to it.
This verifies dependency resolution, not desktop or daemon acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


# Official Ubuntu 24.04 amd64 manifest (noble-20260930.1):
# https://hub.docker.com/layers/library/ubuntu/24.04/?tab=layers
BASE_IMAGE = (
    "ubuntu:24.04@sha256:"
    "a2d43bffc46670d7108bb3c0468c67c5557c4c92e83e1e34cbff1322ad1b94dc"
)
RESULT_MARKER = "NIPAT_DEPENDENCY_RESULT="
CHECKS = (
    "dependencies_initially_absent", "apt_installs_required_packages",
    "installed_cli_help_and_version", "no_automatic_docker_access",
    "no_runtime_preparation", "apt_sources_unchanged", "embedded_manifest_matches",
)
PACKAGES = ("python3.12", "docker.io", "docker-compose-v2", "nipat-desktop")

# Fixed paths keep untrusted filenames and manifest strings out of shell code.
# policy-rc.d suppresses service startup in this dependency-only test container.
CONTAINER_SCRIPT = r'''set -euo pipefail
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 24.04
test "$(dpkg --print-architecture)" = amd64
test ! -e /var/run/docker.sock
for package in python3.12 docker.io docker-ce docker-compose-v2 docker-compose-plugin nipat-desktop; do
    status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)
    if test "$status" = installed; then
        echo "Dependency unexpectedly present before APT: $package" >&2
        exit 1
    fi
done
useradd --create-home --user-group nipat-validation
id -G nipat-validation > /tmp/nipat-groups-before
find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) -print0 |
    sort -z | xargs -0 -r sha256sum > /tmp/nipat-apt-sources-before
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
apt-get update
apt-get -y --no-install-recommends install /input/nipat.deb
find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) -print0 |
    sort -z | xargs -0 -r sha256sum > /tmp/nipat-apt-sources-after
cmp /tmp/nipat-apt-sources-before /tmp/nipat-apt-sources-after
id -G nipat-validation > /tmp/nipat-groups-after
cmp /tmp/nipat-groups-before /tmp/nipat-groups-after
if id -Gn nipat-validation | tr ' ' '\n' | grep -qx docker; then
    echo 'APT unexpectedly authorized the user to access Docker.' >&2
    exit 1
fi
docker --version
docker compose version
runuser -u nipat-validation -- /usr/bin/nipat --version > /tmp/nipat-version
runuser -u nipat-validation -- /usr/bin/nipat --help > /tmp/nipat-help
test -s /tmp/nipat-help
test ! -e /var/run/docker.sock
test ! -e /home/nipat-validation/.local/share/nipat-desktop
test ! -e /home/nipat-validation/.local/state/nipat-desktop
python3.12 -I - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess

manifest_bytes = Path('/input/installer-manifest.json').read_bytes()
manifest = json.loads(manifest_bytes)
assert Path('/opt/nipat-desktop/.distribution/installer-manifest.json').read_bytes() == manifest_bytes
assert Path('/tmp/nipat-version').read_text().strip().endswith(manifest['version'])
packages = {}
for package in ('python3.12', 'docker.io', 'docker-compose-v2', 'nipat-desktop'):
    fields = subprocess.check_output(
        ['dpkg-query', '-W', '-f=${Status}\t${Version}', package], text=True,
    ).split('\t')
    assert len(fields) == 2 and fields[0] == 'install ok installed' and fields[1]
    packages[package] = fields[1]
print('NIPAT_DEPENDENCY_RESULT=' + json.dumps({
    'dependency_packages': packages,
    'checks': dict.fromkeys((
        'dependencies_initially_absent', 'apt_installs_required_packages',
        'installed_cli_help_and_version', 'no_automatic_docker_access',
        'no_runtime_preparation', 'apt_sources_unchanged', 'embedded_manifest_matches',
    ), True),
}))
PY
'''


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_result(output: str) -> dict:
    records = [line[len(RESULT_MARKER):] for line in output.splitlines()
               if line.startswith(RESULT_MARKER)]
    if len(records) != 1:
        raise ValueError("The dependency check must produce exactly one result.")
    result = json.loads(records[0])
    if not isinstance(result, dict) or set(result) != {"checks", "dependency_packages"}:
        raise ValueError("Unexpected fields in the dependency result.")
    checks = result.get("checks")
    if (not isinstance(checks, dict) or set(checks) != set(CHECKS)
            or not all(value is True for value in checks.values())):
        raise ValueError("A required dependency check is missing or failed.")
    packages = result.get("dependency_packages")
    if (not isinstance(packages, dict) or set(packages) != set(PACKAGES)
            or not all(isinstance(version, str) and version.strip()
                       for version in packages.values())):
        raise ValueError("Missing installed dependency versions.")
    return {"checks": checks, "dependency_packages": packages}


def container_command(package: Path, manifest: Path) -> list[str]:
    for path in (package, manifest):
        if any(character in str(path) for character in (",", "\n", "\r")):
            raise ValueError("The dependency test mount path contains unsupported characters.")
    return [
        "docker", "--host", "unix:///var/run/docker.sock", "run", "--rm", "--pull", "always",
        "--platform", "linux/amd64", "--interactive",
        "--mount", f"type=bind,source={package},target=/input/nipat.deb,readonly",
        "--mount", f"type=bind,source={manifest},target=/input/installer-manifest.json,readonly",
        "--entrypoint", "/bin/bash", BASE_IMAGE, "-s",
    ]


def verify(package: Path, manifest_path: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("The dependency evidence file must not already exist.")
    if any(path.is_symlink() or not path.is_file() for path in (package, manifest_path)):
        raise ValueError("A regular package and installer manifest are required.")
    package, manifest_path = package.resolve(), manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = {
        "schema_version": 1, "distribution": "native-linux-deb",
        "platform": "ubuntu-24.04-amd64", "scenario": "clean-ubuntu-container",
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": sha256(manifest_path), "package_sha256": sha256(package),
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "base_image": BASE_IMAGE, "checks": dict.fromkeys(CHECKS, False),
    }
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("DOCKER", "COMPOSE", "NIPAT_", "PYTHON"))}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="nipat-dependency-docker-") as configuration:
            environment["DOCKER_CONFIG"] = configuration
            result = subprocess.run(container_command(package, manifest_path),
                                    input=CONTAINER_SCRIPT.encode(), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, env=environment, check=False,
                                    timeout=1200)
        text = result.stdout.decode("utf-8", errors="replace")
        print(text, end="" if text.endswith("\n") else "\n", flush=True)
        if result.returncode != 0:
            raise RuntimeError(f"Ubuntu dependency installation failed ({result.returncode}).")
        evidence.update(parse_result(text))
        print("PASS: APT installed missing Docker Engine, Compose and Python in clean Ubuntu.", flush=True)
    finally:
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.package, args.manifest, args.output)


if __name__ == "__main__":
    main()
