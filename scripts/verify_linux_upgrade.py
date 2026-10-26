"""Exercise the real 0.7.1-to-candidate DEB upgrade on a prepared Ubuntu CI runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess

_SPEC = importlib.util.spec_from_file_location("nipat_upgrade_installation", Path(__file__).with_name("verify_linux_installer.py"))
install = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(install)

BASELINE = {
    "version": "0.7.1", "source_commit": "9bbdb8bf1163302c77ce94be687596b07e9d1250",
    "file": "nipat-desktop_0.7.1_amd64.deb",
    "sha256": "4f0a43710ed92fe0299a182814c93ee6f215f43e00c9050a7cfc5e697846edd5",
}
CHECKS = (
    "previous_package_installed", "previous_runtime_ready", "candidate_package_installed",
    "candidate_runtime_ready", "candidate_scientific_self_tests", "existing_results_preserved",
    "preferences_preserved", "user_data_preserved", "shared_docker_configuration_preserved",
)


def preserved_files(root, before):
    after = install.snapshot(root)
    return all(after.get(name) == value for name, value in before.items())


def verify(previous, candidate, manifest_path, work, output):
    release = platform.freedesktop_os_release()
    install.require(platform.system() == "Linux" and platform.machine() == "x86_64"
                    and release.get("ID") == "ubuntu" and release.get("VERSION_ID") == "24.04",
                    "Upgrade integration requires Ubuntu 24.04 amd64.")
    install.require(os.getuid() != 0, "Use a non-root CI account with sudo and Docker access.")
    install.require(not work.exists(), "The upgrade workspace must be new.")
    install.require(previous.name == BASELINE["file"] and install.sha256(previous) == BASELINE["sha256"],
                    "The previous DEB must be the exact published 0.7.1 baseline.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    install.require(manifest["version"] != BASELINE["version"], "An upgrade must use distinct versions.")
    evidence = {
        "schema_version": 1, "platform": "ubuntu-24.04-amd64",
        "scenario": "prepared-ci-runner-real-upgrade", "source_commit": manifest["source_commit"],
        "version": manifest["version"], "installer_manifest_sha256": install.sha256(manifest_path),
        "package_sha256": install.sha256(candidate), "previous": BASELINE,
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "nonroot_uid": os.getuid(), "checks": dict.fromkeys(CHECKS, False),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, mode=0o700)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("NIPAT_", "PYTHON", "DOCKER_", "COMPOSE_"))}
    environment.update({"XDG_DATA_HOME": str(work / "data è"), "XDG_STATE_HOME": str(work / "state è"),
                        "XDG_CONFIG_HOME": str(work / "config è"), "DEBIAN_FRONTEND": "noninteractive",
                        "LC_ALL": "C.UTF-8"})
    data = Path(environment["XDG_DATA_HOME"]) / install.PACKAGE
    configuration = Path(environment["XDG_CONFIG_HOME"])
    state_file = Path(environment["XDG_STATE_HOME"]) / install.PACKAGE / "state.json"
    docker_before = install.docker_configuration(Path.home())
    installed = False
    try:
        status = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Status}", install.PACKAGE],
                                capture_output=True, text=True, check=False)
        install.require(status.stdout.strip() != "installed", "NIPAT must be initially uninstalled on this disposable runner.")
        for package, key in ((previous, "previous_package_installed"), (candidate, "candidate_package_installed")):
            install.run(["sudo", "-n", "apt-get", "-y", "--no-install-recommends", "install", str(package)],
                        environment=environment, cwd=work)
            installed = True
            evidence["checks"][key] = True
            installed_manifest = json.loads((install.APP / ".distribution/installer-manifest.json").read_text())
            if package == previous:
                install.require(installed_manifest["version"] == BASELINE["version"]
                                and installed_manifest["source_commit"] == BASELINE["source_commit"],
                                "Installed baseline identity mismatch.")
            else:
                install.require(install.sha256(install.APP / ".distribution/installer-manifest.json")
                                == evidence["installer_manifest_sha256"], "Installed candidate manifest mismatch.")
            install.run([install.COMMAND, "--setup"], environment=environment, cwd=work)
            state = json.loads(state_file.read_text())
            image = install.check_state(state, installed_manifest,
                                        install.sha256(install.APP / ".distribution/installer-manifest.json"))
            if package == previous:
                evidence["checks"]["previous_runtime_ready"] = True
                baseline_runs = list((data / "runs").rglob("run.json"))
                install.require(baseline_runs and all(json.loads(path.read_text())["status"] == "succeeded"
                                                     for path in baseline_runs),
                                "Baseline setup did not leave successful scientific regression runs.")
                (data / "data").mkdir(parents=True, exist_ok=True)
                (data / "data/user-sentinel.txt").write_text("Keep user data across upgrades.\n", encoding="utf-8")
                preferences = configuration / install.PACKAGE / "preferences.json"
                preferences.parent.mkdir(parents=True, exist_ok=True)
                preferences.write_text(json.dumps({
                    "schema_version": 1, "data_dir": None, "runs_dir": None,
                    "workflows": {"4": {"err_const": 0.01}}, "update_channel": "testing",
                    "check_updates_on_startup": False,
                }) + "\n", encoding="utf-8")
                before_data = install.snapshot(data / "data")
                before_runs = install.snapshot(data / "runs")
                before_preferences = install.snapshot(configuration)
            else:
                evidence["resolved_runtime_image"] = image
                evidence["checks"]["candidate_runtime_ready"] = True
                install.run([install.COMMAND, "doctor", "--runtime"], environment=environment, cwd=work)
                after_runs = work / "candidate verification runs"
                install.run([install.COMMAND, "--runs-dir", str(after_runs), "self-test"],
                            environment=environment, cwd=work)
                install.require(any(after_runs.rglob("run.json")), "Candidate self-test did not produce executions.")
                evidence["checks"]["candidate_scientific_self_tests"] = True
                install.run([install.COMMAND, "wizard"], environment=environment, cwd=work, input_bytes=b"0\n")
                install.require(preserved_files(data / "runs", before_runs), "Upgrade changed existing results.")
                evidence["checks"]["existing_results_preserved"] = True
                install.require(install.snapshot(configuration) == before_preferences, "Upgrade changed saved preferences.")
                evidence["checks"]["preferences_preserved"] = True
                install.require(install.snapshot(data / "data") == before_data, "Upgrade changed user data.")
                evidence["checks"]["user_data_preserved"] = True
        install.require(install.docker_configuration(Path.home()) == docker_before,
                        "Upgrade changed shared Docker configuration.")
        evidence["checks"]["shared_docker_configuration_preserved"] = True
        print("PASS: exact published 0.7.1 DEB upgraded to candidate; runtime, scientific checks and user files verified.")
    finally:
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        if installed:
            subprocess.run(["sudo", "-n", "apt-get", "-y", "remove", install.PACKAGE],
                           env=environment, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-package", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system-package-test", action="store_true")
    args = parser.parse_args()
    if not args.system_package_test:
        parser.error("This check changes packages; --system-package-test is required on a disposable runner.")
    verify(args.previous_package.resolve(), args.package.resolve(), args.manifest.resolve(),
           args.work_dir.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
