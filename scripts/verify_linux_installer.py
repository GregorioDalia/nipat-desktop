"""Exercise the installed Linux package on a prepared Ubuntu CI runner.

This is an integration check with explicit package-manager mutations, not a
claim of validation on an unconfigured Ubuntu Desktop installation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import uuid


APP = Path("/opt/nipat-desktop")
COMMAND = "/usr/bin/nipat"
PACKAGE = "nipat-desktop"
DOCKER = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
CHECKS = (
    "package_installation", "initial_setup", "immutable_runtime_binding",
    "all_four_workflows", "private_inputs_unchanged", "user_owned_results",
    "repeated_launch", "package_reinstallation",
    "package_removal_preserves_user_data", "shared_docker_unchanged",
)


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(arguments: list[str], *, environment: dict[str, str], cwd: Path,
        input_bytes: bytes | None = None) -> str:
    print("$ " + " ".join(arguments), flush=True)
    result = subprocess.run(arguments, cwd=cwd, env=environment, input=input_bytes,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False)
    text = result.stdout.decode("utf-8", errors="replace")
    print(text, end="" if text.endswith("\n") else "\n", flush=True)
    require(result.returncode == 0, f"Command failed ({result.returncode}): {arguments}")
    return text


def snapshot(directory: Path) -> dict[str, dict]:
    result = {}
    if directory.exists():
        for path in sorted(directory.rglob("*")):
            require(not path.is_symlink(), f"Unexpected symlink in test data: {path}")
            if path.is_file():
                result[path.relative_to(directory).as_posix()] = {
                    "sha256": sha256(path), "uid": path.stat().st_uid,
                    "mode": path.stat().st_mode & 0o777,
                }
    return result


def docker_configuration(home: Path) -> dict[str, str | None]:
    paths = [Path("/etc/docker/daemon.json"), home / ".docker/config.json"]
    contexts = home / ".docker/contexts"
    if contexts.is_dir():
        paths += sorted(path for path in contexts.rglob("*") if path.is_file())
    return {str(path): sha256(path) if path.is_file() else None for path in paths}


def check_state(state: dict, manifest: dict, manifest_hash: str) -> str:
    require(state.get("schema_version") == 1 and state.get("phase") == "ready",
            "Installed launcher did not save a ready state.")
    expected = {
        "channel": "desktop", "version": manifest["version"],
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": manifest_hash,
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "source_runtime_image": manifest["runtime_image"],
    }
    for name, value in expected.items():
        require(state.get(name) == value, f"Runtime state binding mismatch: {name}")
    image = state.get("resolved_runtime_image", "")
    require(isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image) is not None,
            "Installed launcher did not resolve an immutable image ID.")
    return image


def check_workflows(runs: Path, uid: int) -> None:
    records = [json.loads(path.read_text()) for path in runs.glob("*/run.json")]
    successful = {record.get("workflow") for record in records
                  if record.get("status") == "succeeded"}
    require({"dnp-call", "snp-call", "contamination", "cpi"} <= successful,
            f"Installed CLI did not complete all four workflows: {successful}")
    files = [path for path in runs.rglob("*") if path.is_file()]
    require(bool(files), "No installed CLI results were written.")
    require(all(path.stat().st_uid == uid for path in files),
            "The installed CLI produced files owned by another user.")
    require(all(os.access(path, os.R_OK | os.W_OK) for path in files),
            "The installed CLI results are not readable and writable by their user.")


def check_dnp_results(run_directory: Path, fixture: Path) -> None:
    with (fixture / "expected.tsv").open(newline="", encoding="utf-8") as handle:
        expected = {row["pos1"]: row for row in csv.DictReader(handle, delimiter="\t")
                    if row["sample"] == "A"}
    tables = list((run_directory / "output/individual_outputs").glob("full_output_*.txt"))
    require(len(tables) == 1, "Installed DNPcall did not produce one sample table.")
    with tables[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows) == len(expected) and {row["pos1"] for row in rows} == set(expected),
            "Installed DNPcall loci differ from the independent synthetic fixture.")
    for row in rows:
        for column in ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other",
                       "GT", "total_count"):
            require(row[column] == expected[row["pos1"]][column],
                    f"Installed DNPcall result mismatch: {row['pos1']}/{column}")


def verify(package: Path, manifest_path: Path, work: Path, output: Path) -> None:
    require(platform.system() == "Linux" and platform.machine() == "x86_64",
            "This integration check requires Ubuntu 24.04 x86_64.")
    release = platform.freedesktop_os_release()
    require(release.get("ID") == "ubuntu" and release.get("VERSION_ID") == "24.04",
            "This integration check requires Ubuntu 24.04.")
    require(os.getuid() != 0, "Run this check as a non-root CI user with sudo and Docker access.")
    require(not work.exists(), "The installation-check workspace must be new.")
    require(package.is_file() and package.suffix == ".deb", "A real .deb package is required.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = sha256(manifest_path)
    evidence = {
        "schema_version": 1, "distribution": "native-linux-deb",
        "platform": "ubuntu-24.04-amd64", "scenario": "prepared-ci-runner",
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": manifest_hash, "package_sha256": sha256(package),
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "nonroot_uid": os.getuid(), "checks": {name: False for name in CHECKS},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, mode=0o700)
    work.chmod(0o700)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("NIPAT_", "PYTHON", "DOCKER_", "COMPOSE_"))}
    environment.update({"XDG_DATA_HOME": str(work / "user data with spaces"),
                        "XDG_STATE_HOME": str(work / "user state with spaces"),
                        "DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C.UTF-8"})
    data = Path(environment["XDG_DATA_HOME"]) / PACKAGE
    state_file = Path(environment["XDG_STATE_HOME"]) / PACKAGE / "state.json"
    configuration_before = docker_configuration(Path.home())
    foreign_tag = "nipat-linux-install-check-unrelated:" + uuid.uuid4().hex
    foreign_image = None
    installed = False
    try:
        status = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Status}", PACKAGE],
                                capture_output=True, text=True, check=False)
        require(status.stdout.strip() != "installed", "The NIPAT Desktop package is already installed.")
        run([*DOCKER, "info", "--format", "{{json .}}"], environment=environment, cwd=work)
        preexisting = subprocess.run([*DOCKER, "image", "inspect", manifest["runtime_image"]],
                                     cwd=work, env=environment, capture_output=True, check=False)
        require(preexisting.returncode != 0,
                "This installation check requires the scientific image to be initially absent.")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as handle:
            member = tarfile.TarInfo("unrelated-ci-sentinel")
            member.size = 0
            handle.addfile(member, io.BytesIO())
        foreign_image = run([*DOCKER, "image", "import", "-", foreign_tag],
                            environment=environment, cwd=work, input_bytes=archive.getvalue()).strip()
        require(re.fullmatch(r"sha256:[0-9a-f]{64}", foreign_image) is not None,
                "Could not create the unrelated Docker image sentinel.")

        simulation = run(["sudo", "-n", "apt-get", "--simulate", "--no-install-recommends",
                          "install", str(package)], environment=environment, cwd=work)
        require(not any(line.startswith("Remv ") for line in simulation.splitlines()),
                "Installing NIPAT would remove an existing system package.")
        run(["sudo", "-n", "apt-get", "-y", "--no-install-recommends", "install", str(package)],
            environment=environment, cwd=work)
        installed = True
        evidence["checks"]["package_installation"] = True
        dependencies = subprocess.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Status}\t${Version}\n",
             "python3.12", "docker.io", "docker-ce", "docker-compose-v2", "docker-compose-plugin"],
            capture_output=True, text=True, check=False,
        )
        evidence["dependency_packages"] = {
            fields[0]: fields[2] for line in dependencies.stdout.splitlines()
            if len(fields := line.split("\t")) == 3 and fields[1] == "install ok installed"
        }
        print("Installed dependency packages: " + json.dumps(evidence["dependency_packages"]), flush=True)
        require(APP.is_dir() and Path(COMMAND).is_file(), "Installed application or launcher missing.")
        installed_manifest = APP / ".distribution/installer-manifest.json"
        require(sha256(installed_manifest) == manifest_hash, "Installed common manifest differs.")
        scientific = manifest["assets"]["scientific_image"]
        installed_archive = APP / ".distribution" / scientific["file"]
        require(installed_archive.stat().st_size == scientific["size"]
                and sha256(installed_archive) == scientific["sha256"],
                "The installed scientific archive differs from the Windows archive.")
        run([COMMAND, "--version"], environment=environment, cwd=work)
        require(not state_file.exists(), "--version unexpectedly prepared a runtime.")
        run([COMMAND, "--setup"], environment=environment, cwd=work)
        evidence["checks"]["initial_setup"] = True
        state = json.loads(state_file.read_text())
        image = check_state(state, manifest, manifest_hash)
        evidence["resolved_runtime_image"] = image
        evidence["checks"]["immutable_runtime_binding"] = True
        inspected = json.loads(run([*DOCKER, "image", "inspect", image],
                                   environment=environment, cwd=work))
        require(len(inspected) == 1 and inspected[0]["Id"] == image
                and inspected[0]["Os"] == "linux" and inspected[0]["Architecture"] == "amd64",
                "Resolved image is not an immutable Linux amd64 runtime.")
        before_launch = snapshot(data / "runs")
        state_before = sha256(state_file)
        run([COMMAND, "doctor", "--runtime"], environment=environment, cwd=work)
        require(snapshot(data / "runs") == before_launch and sha256(state_file) == state_before,
                "Repeated launch overwrote results or unnecessarily prepared the runtime.")
        evidence["checks"]["repeated_launch"] = True

        fixture = APP / "tests/fixtures/dnp_engine"
        inputs = work / "private original inputs è"
        inputs.mkdir(mode=0o700)
        for name in ("reads_A.sam", "reference.fa", "DNP_list.txt"):
            shutil.copyfile(fixture / name, inputs / name)
            (inputs / name).chmod(0o600)
        bam = inputs / "sample A è.bam"
        run([*DOCKER, "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
             "--user", f"{os.getuid()}:{os.getgid()}", "--mount",
             f"type=bind,source={inputs},target=/fixtures", image,
             "samtools", "view", "-b", "-o", "/fixtures/" + bam.name,
             "/fixtures/reads_A.sam"], environment=environment, cwd=work)
        bam.chmod(0o600)
        run([*DOCKER, "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
             "--user", f"{os.getuid()}:{os.getgid()}", "--mount",
             f"type=bind,source={inputs},target=/fixtures", image,
             "samtools", "faidx", "/fixtures/reference.fa"], environment=environment, cwd=work)
        (inputs / "reference.fa.fai").chmod(0o600)
        originals = snapshot(inputs)
        run([COMMAND, "dnp-call", "--bam", str(bam), "--reference", str(inputs / "reference.fa"),
             "--panel", str(inputs / "DNP_list.txt"), "--run-name", "installed-dnp-private-inputs"],
            environment=environment, cwd=work)
        check_dnp_results(data / "runs/installed-dnp-private-inputs", fixture)
        require(snapshot(inputs) == originals, "The installed workflow changed original inputs.")
        evidence["checks"]["private_inputs_unchanged"] = True
        check_workflows(data / "runs", os.getuid())
        evidence["checks"]["all_four_workflows"] = True
        evidence["checks"]["user_owned_results"] = True
        sentinel = data / "data/user-sentinel.txt"
        sentinel.write_text("User data must survive reinstall and removal.\n", encoding="utf-8")
        preserved = snapshot(data)
        run(["sudo", "-n", "apt-get", "-y", "--no-install-recommends", "--reinstall",
             "install", str(package)], environment=environment, cwd=work)
        run([COMMAND, "doctor", "--runtime"], environment=environment, cwd=work)
        require(snapshot(data) == preserved, "Reinstallation changed existing data or results.")
        evidence["checks"]["package_reinstallation"] = True
        run(["sudo", "-n", "apt-get", "-y", "remove", PACKAGE], environment=environment, cwd=work)
        installed = False
        require(not Path(COMMAND).exists(), "Package removal left its launcher installed.")
        require(snapshot(data) == preserved and state_file.is_file(),
                "Package removal deleted or changed user data, results, or runtime state.")
        evidence["checks"]["package_removal_preserves_user_data"] = True
        foreign_after = json.loads(run([*DOCKER, "image", "inspect", foreign_tag],
                                       environment=environment, cwd=work))
        require(foreign_after[0]["Id"] == foreign_image, "Package lifecycle changed an unrelated image.")
        require(docker_configuration(Path.home()) == configuration_before,
                "Package lifecycle changed the user's Docker context or daemon configuration.")
        run([*DOCKER, "image", "inspect", image], environment=environment, cwd=work)
        evidence["checks"]["shared_docker_unchanged"] = True
        print("PASS: Linux package installation, four scientific workflows as a non-root user, "
              "repeated launch, reinstallation and removal preserving data and shared Docker.", flush=True)
    finally:
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        if installed:
            subprocess.run(["sudo", "-n", "apt-get", "-y", "remove", PACKAGE],
                           env=environment, check=False)
        if foreign_image:
            subprocess.run([*DOCKER, "image", "rm", foreign_tag], env=environment, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system-package-test", action="store_true",
                        help="authorize install/reinstall/remove of NIPAT Desktop on this CI host")
    args = parser.parse_args()
    if not args.system_package_test:
        parser.error("This check changes system packages; --system-package-test is required.")
    verify(args.package.resolve(), args.manifest.resolve(), args.work_dir.resolve(),
           args.output.resolve())


if __name__ == "__main__":
    main()
