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
    "automatic_workflow_plan", "preferences_preserved",
)


def checks_for_version(version: str) -> tuple[str, ...]:
    require(isinstance(version, str) and re.fullmatch(r"0\.[67]\.\d+(?:(?:a|b|rc)\d+)?", version) is not None,
            "The installed-package check supports Desktop 0.6 and 0.7 releases.")
    return CHECKS if version.startswith("0.7.") else CHECKS[:-2]


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


def read_table(path: Path, *, delimiter: str = "\t") -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def check_dnp_table(path: Path, fixture: Path, sample: str) -> None:
    with (fixture / "expected.tsv").open(newline="", encoding="utf-8") as handle:
        expected = {row["pos1"]: row for row in csv.DictReader(handle, delimiter="\t")
                    if row["sample"] == sample}
    rows = read_table(path)
    require(len(rows) == len(expected) and {row["pos1"] for row in rows} == set(expected),
            "Installed DNPcall loci differ from the independent synthetic fixture.")
    for row in rows:
        for column in ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other",
                       "GT", "total_count"):
            require(row[column] == expected[row["pos1"]][column],
                    f"Installed DNPcall result mismatch: {row['pos1']}/{column}")


def check_dnp_results(run_directory: Path, fixture: Path) -> None:
    tables = list((run_directory / "output/individual_outputs").glob("full_output_*.txt"))
    require(len(tables) == 1, "Installed DNPcall did not produce one sample table.")
    check_dnp_table(tables[0], fixture, "A")


def checked_artifact(root: Path, artifact: dict) -> Path:
    relative = artifact.get("path")
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            "Installed workflow recorded an invalid artifact path.")
    path = root / relative
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            "Installed workflow artifact escaped its run or is missing.")
    require(sha256(path) == artifact.get("sha256"), "Installed workflow artifact hash differs.")
    return path


def check_automatic_plan(run_directory: Path, fixture: Path, manifest: dict,
                         image: str, sources: list[Path]) -> None:
    """Check the installed CLI's composed outputs against the committed SAM design.

    Fixture A/B has no retained CPI sites; SNP and DNP counts remain nontrivial.
    Positive CPI compositions are covered independently by real-image regression.
    """
    record = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    require(record.get("status") == "succeeded" and record.get("workflow") == "dnp-contamination-cpi"
            and record.get("bundled_workflow") == "workflow-plan-with-snp",
            "Installed automatic workflow did not complete.")
    source = record["source"]
    require(source.get("role") == "client" and source.get("nipat_version") == manifest["version"]
            and source["release"]["source_git"]["commit"] == manifest["source_commit"]
            and record["runtime"]["image_id"] == image,
            "Installed workflow does not identify the tested package and loaded image.")
    require(set(record["runtime"]["engine"]["plan_execution"]["workflows"])
            == {"dnp-call", "snp-call", "contamination", "cpi"},
            "Installed image lacks the complete plan interface.")
    require(len(record["commands"]) == 1 and "execute-plan" in record["commands"][0]["argv"],
            "Installed composition must execute in one scientific container.")
    require([item["original_path"] for item in record["parameters"]["sample_mapping"]]
            == [str(path.resolve()) for path in sources], "Installed plan changed original sample identities.")
    root = run_directory / "output/workflow"
    state = json.loads((root / "workflow-state.json").read_text(encoding="utf-8"))
    order = ["dnp", "contamination", "cpi", "snp_0001", "snp_0002"]
    require(state.get("status") == "succeeded" and state.get("execution_order") == order
            and [item["id"] for item in state["steps"]] == order
            and all(item["status"] == "succeeded" and item["exit_code"] == 0 for item in state["steps"]),
            "Installed automatic plan has missing, reordered or unsuccessful steps.")
    require(state["plan_sha256"] == sha256(root / "plan.json"), "Installed plan identity differs.")
    steps = {item["id"]: item for item in state["steps"]}
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    cpi = next(item for item in plan["steps"] if item["id"] == "cpi")
    pair = cpi["inputs"]["pairs"]
    expected_pair = {"id": "installed_pair", "mother": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0001"},
                     "father": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0002"}}
    require(pair == [expected_pair], "Installed CPI must consume the declared original DNP tables.")
    for step in steps.values():
        require((root / step["log"]).is_file(), "Installed workflow lost a scientific log.")
    dnp = steps["dnp"]["artifacts"]["dnp-tables"]
    require([item["sample"] for item in dnp] == ["sample_0001", "sample_0002"],
            "Installed DNP output mapping differs.")
    for artifact, sample in zip(dnp, ("A", "B"), strict=True):
        check_dnp_table(checked_artifact(root, artifact), fixture, sample)
    # In the synthetic SAMs, Other dinucleotides share the REF first base.
    snp_counts = (((21, 0), (11, 10), (1, 20)), ((1, 20), (13, 8), (21, 0)))
    for number, expected_counts in enumerate(snp_counts, 1):
        identifier = f"sample_{number:04d}"
        step = steps[f"snp_{number:04d}"]
        require(step["sample_mapping"]["sample"] == identifier and step["sample_mapping"]["mode"] == "bam",
                "Installed SNP step lost its sample identity.")
        tables = step["artifacts"]["snp-tables"]
        require(len(tables) == 1 and tables[0]["sample"] == identifier, "Installed SNP output mapping differs.")
        rows = read_table(checked_artifact(root, tables[0]))
        found = {(row["chr"], int(row["pos"])): row for row in rows}
        require(len(rows) == 3 and set(found) == {("chrDnpSynthetic", position) for position in (50, 140, 230)},
                "Installed SNP loci differ from the synthetic design.")
        for position, alleles, counts in zip((50, 140, 230), (("A", "G"), ("T", "C"), ("G", "A")), expected_counts, strict=True):
            row = found[("chrDnpSynthetic", position)]
            require((row["Reference"], row["Alternative"]) == alleles
                    and tuple(int(row[name]) for name in ("N_Reference", "N_Alternative", "N_Altro", "total_count"))
                    == (*counts, 0, 21) and abs(float(row["ratio"]) - counts[0] / 21) < 1e-12,
                    "Installed SNP counts differ from the independent SAM oracle.")
        preparation = step["artifacts"]["preparation"]
        require(len(preparation) == 2 and {item["kind"] for item in preparation} == {"regions-bed", "pileup"}
                and step["preparation_exit_code"] == 0 and (root / step["preparation_log"]).is_file(),
                "Installed SNP preparation evidence is incomplete.")
        for artifact in preparation:
            checked_artifact(root, artifact)
    contamination = steps["contamination"]["artifacts"]
    rows = read_table(checked_artifact(root, contamination["summary"]))
    require(len(rows) == 2 and {row["individuo"] for row in rows} == {"table_0001", "table_0002"}
            and all(int(row["informative_DNPs"]) == 2 and float(row["mean_contamination"]) == 0
                    and float(row["sd_contamination"]) == 0 for row in rows),
            "Installed Contamination differs from the two homozygous loci per sample.")
    for artifact in contamination["contamination-tables"]:
        rows = read_table(checked_artifact(root, artifact))
        require(len(rows) == 2 and {int(row["pos1"]) for row in rows} == {50, 230}
                and all(float(row["contamination"]) == 0 for row in rows),
                "Installed per-site contamination differs from its oracle.")
    cpi_artifacts = steps["cpi"]["artifacts"]
    rows = read_table(checked_artifact(root, cpi_artifacts["summary"]), delimiter=",")
    require(len(rows) == 1, "Installed CPI summary does not contain the declared pair.")
    result = rows[0]
    mapping = cpi_artifacts["cpi-pairs"]
    require(len(mapping) == 1 and mapping[0]["pair"] == "installed_pair"
            and result["Pair"] == mapping[0]["native_pair"]
            and mapping[0]["mother"] == expected_pair["mother"] and mapping[0]["father"] == expected_pair["father"],
            "Installed CPI result identity differs.")
    require(result["N_sites_mother"] == "0" and result["N_sites_father"] == "0"
            and all(result[name] == "NA" for name in ("Median_fetal_fraction_raw", "Median_fetal_fraction_percent",
                    "Max_logCPI", "Min_logCPI", "Median_logCPI", "Mean_logCPI", "CPI_medianFF")),
            "Installed CPI no-information case must contain zero sites and NA estimates.")
    for artifact in (mapping[0]["plot"], cpi_artifacts["combined-plot"]):
        require(checked_artifact(root, artifact).read_bytes().startswith(b"%PDF-"), "Installed CPI plot is invalid.")


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
    checks = checks_for_version(manifest["version"])
    composed = "automatic_workflow_plan" in checks
    evidence = {
        "schema_version": 1, "distribution": "native-linux-deb",
        "platform": "ubuntu-24.04-amd64", "scenario": "prepared-ci-runner",
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": manifest_hash, "package_sha256": sha256(package),
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "nonroot_uid": os.getuid(), "checks": {name: False for name in checks},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, mode=0o700)
    work.chmod(0o700)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("NIPAT_", "PYTHON", "DOCKER_", "COMPOSE_"))}
    environment.update({"XDG_DATA_HOME": str(work / "user data with spaces"),
                        "XDG_STATE_HOME": str(work / "user state with spaces"),
                        "XDG_CONFIG_HOME": str(work / "user configuration è"),
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
        for name in ("reads_A.sam", "reads_B.sam", "reference.fa", "DNP_list.txt"):
            shutil.copyfile(fixture / name, inputs / name)
            (inputs / name).chmod(0o600)
        bam = inputs / "sample A è.bam"
        paternal = inputs / "sample B è.bam"
        for sample, destination in (("A", bam), ("B", paternal)):
            run([*DOCKER, "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                 "--user", f"{os.getuid()}:{os.getgid()}", "--mount",
                 f"type=bind,source={inputs},target=/fixtures", image,
                 "samtools", "view", "-b", "-o", "/fixtures/" + destination.name,
                 f"/fixtures/reads_{sample}.sam"], environment=environment, cwd=work)
            destination.chmod(0o600)
        run([*DOCKER, "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
             "--user", f"{os.getuid()}:{os.getgid()}", "--mount",
             f"type=bind,source={inputs},target=/fixtures", image,
             "samtools", "faidx", "/fixtures/reference.fa"], environment=environment, cwd=work)
        (inputs / "reference.fa.fai").chmod(0o600)
        population = inputs / "population.tsv"
        population.write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" + "".join(
            f"chrDnpSynthetic\t{position}\t{position + 1}\t0.75\t0.25\n" for position in (50, 140, 230)
        ), encoding="utf-8")
        snp_panel = inputs / "first-base SNPs.tsv"
        snp_panel.write_text("pos\tref\talt\nchrDnpSynthetic:50\tA\tG\n"
                             "chrDnpSynthetic:140\tT\tC\nchrDnpSynthetic:230\tG\tA\n", encoding="utf-8")
        population.chmod(0o600)
        snp_panel.chmod(0o600)
        originals = snapshot(inputs)
        run([COMMAND, "dnp-call", "--bam", str(bam), "--reference", str(inputs / "reference.fa"),
             "--panel", str(inputs / "DNP_list.txt"), "--run-name", "installed-dnp-private-inputs"],
            environment=environment, cwd=work)
        check_dnp_results(data / "runs/installed-dnp-private-inputs", fixture)
        configuration = Path(environment["XDG_CONFIG_HOME"])
        preferences = configuration / PACKAGE / "preferences.json"
        preferences.parent.mkdir(parents=True, mode=0o700)
        preferences.write_text(json.dumps({
            "schema_version": 1, "data_dir": None, "runs_dir": None,
            "workflows": {"4": {"err_const": 0.01}}, "update_channel": "testing",
            "check_updates_on_startup": False,
        }) + "\n", encoding="utf-8")
        preferences.chmod(0o600)
        preferences_before = snapshot(configuration)
        run([COMMAND, "wizard"], environment=environment, cwd=work, input_bytes=b"0\n")
        if composed:
            run([COMMAND, "workflow", "dnp-contamination-cpi", "--pair", "installed_pair", str(bam), str(paternal),
                 "--reference", str(inputs / "reference.fa"), "--panel", str(inputs / "DNP_list.txt"),
                 "--popfreq", str(population), "--snp-panel", str(snp_panel), "--run-name", "installed-automatic-plan"],
                environment=environment, cwd=work)
            check_automatic_plan(data / "runs/installed-automatic-plan", fixture, manifest, image, [bam, paternal])
            evidence["checks"]["automatic_workflow_plan"] = True
        require(snapshot(inputs) == originals, "The installed workflow changed original inputs.")
        require(snapshot(configuration) == preferences_before, "Installed analysis changed saved preferences.")
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
        require(snapshot(data) == preserved and snapshot(configuration) == preferences_before,
                "Reinstallation changed existing data, results or preferences.")
        evidence["checks"]["package_reinstallation"] = True
        run(["sudo", "-n", "apt-get", "-y", "remove", PACKAGE], environment=environment, cwd=work)
        installed = False
        require(not Path(COMMAND).exists(), "Package removal left its launcher installed.")
        require(snapshot(data) == preserved and state_file.is_file()
                and snapshot(configuration) == preferences_before,
                "Package removal deleted or changed user data, results, preferences or runtime state.")
        evidence["checks"]["package_removal_preserves_user_data"] = True
        if composed:
            evidence["checks"]["preferences_preserved"] = True
        foreign_after = json.loads(run([*DOCKER, "image", "inspect", foreign_tag],
                                       environment=environment, cwd=work))
        require(foreign_after[0]["Id"] == foreign_image, "Package lifecycle changed an unrelated image.")
        require(docker_configuration(Path.home()) == configuration_before,
                "Package lifecycle changed the user's Docker context or daemon configuration.")
        run([*DOCKER, "image", "inspect", image], environment=environment, cwd=work)
        evidence["checks"]["shared_docker_unchanged"] = True
        print("PASS: Linux package installation, four individual scientific analyses"
              + (" and one automatic four-analysis plan" if composed else "")
              + " as a non-root user, numeric results, repeated launch, reinstallation "
              "and removal preserving data, preferences and shared Docker.", flush=True)
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
