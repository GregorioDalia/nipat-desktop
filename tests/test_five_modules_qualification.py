"""The independent qualification must reject wrong numbers and damaged references."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


SPEC = importlib.util.spec_from_file_location(
    "five_modules_qualification", Path(__file__).resolve().parents[1] / "scripts/verify_five_modules.py",
)
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def test_frozen_reference_source_hashes():
    manifest = qualification.verify_frozen_sources()
    assert len(manifest["sha256"]) == 3


def test_numerical_comparison_permits_diagnostics_not_changed_science():
    expected = [{"Pair": "M:F", "CPI": "0.602", "Missing": "NA"}]
    qualification.compare_tables(
        [{"Pair": "M:F", "CPI": "0.602000000000001", "Missing": "NA", "Diagnostic": "new"}], expected,
    )
    with pytest.raises(AssertionError):
        qualification.compare_tables([{"Pair": "M:F", "CPI": "0.603", "Missing": "NA"}], expected)
    with pytest.raises(AssertionError):
        qualification.compare_tables([{"Pair": "M:F", "CPI": "0.602", "Missing": "0"}], expected)


def test_duplicate_or_missing_reference_rows_are_not_accepted():
    expected = [{"Trio": "M:F:C", "CPI": "2"}]
    with pytest.raises(AssertionError):
        qualification.compare_tables(expected * 2, expected)
    with pytest.raises(AssertionError):
        qualification.compare_tables([], expected)


def test_marker_fixtures_encode_the_same_counts_but_distinct_coordinates():
    for workflow, name in (("cpin", "ChildC.txt"), ("cpi", "MotherM.txt"),
                           ("contamination", "Calls.txt")):
        snp = qualification.table(qualification.FIXTURE / "SNP" / workflow / name)
        dnp = qualification.table(qualification.FIXTURE / "DNP" / workflow / name)
        assert len(snp) == len(dnp)
        for s, d in zip(snp, dnp, strict=True):
            assert "pos" in s and "pos1" in d and "pos2" in d
            assert s["pos"] == d["pos1"]
            for key in ("N_REF", "N_ALT", "N_Other", "total_count"):
                assert s[key] == d[key]


def test_installed_payload_gate_rejects_stale_helpers_and_r(tmp_path):
    for relative in qualification.SOURCES.values():
        installed = tmp_path / "scientific/vendor/NEWPAT" / relative
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(qualification.PROJECT / "scientific/vendor/NEWPAT" / relative, installed)
    helpers = tmp_path / "lib/nipat_scientific"
    helpers.mkdir(parents=True)
    for name in qualification.HELPERS:
        shutil.copyfile(qualification.PROJECT / "src/nipat_scientific" / name, helpers / name)
    hashes = qualification.verify_installed_payload(tmp_path)
    assert len(hashes) == 3 + len(qualification.HELPERS)
    (helpers / "settings_data.json").write_text("{}\n")
    with pytest.raises(AssertionError, match="Stale scientific image"):
        qualification.verify_installed_payload(tmp_path)


def test_docker_gate_runs_immutable_installed_payload_without_host_overrides(tmp_path, monkeypatch):
    image_id = "sha256:" + "a" * 64
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "image":
            return subprocess.CompletedProcess(command, 0, image_id + "\n", "")
        (tmp_path / "qualification.json").write_text(json.dumps(
            {"status": "passed", "runtime": {"image_id": image_id}, "results": []}))
        return subprocess.CompletedProcess(command, 0, "passed", "")

    monkeypatch.setattr(qualification.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(qualification.subprocess, "run", run)
    qualification.qualify_image("mutable-tag", tmp_path, True)
    command = commands[1]
    assert "mutable-tag" not in command and image_id in command
    assert "--network=none" in command and "--full" in command
    assert command[command.index("--installed-root") + 1] == "/opt/nipat"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert len(mounts) == 2
    assert all("/opt/nipat" not in mount for mount in mounts)
    assert any("target=/qualification" in mount and "readonly" in mount for mount in mounts)
    assert "--env" not in command and "-e" not in command


def test_worker_gate_checks_observed_concurrency_and_task_completion(tmp_path):
    plan = {"event": "plan", "workers": 2, "tasks": 2, "cpu_limit": 4,
            "memory_worker_limit": 4, "observed_at_unix": 0}

    def interval(pid, start, end):
        identity = {"pid": pid, "coordinator_pid": 10, "label": "native-work", "task_index": pid}
        return [{**identity, "event": "task-start", "observed_at_unix": start},
                {**identity, "event": "task-end", "observed_at_unix": end, "outcome": "succeeded"}]

    events = [plan, *interval(11, 1, 3), *interval(12, 2, 4)]
    target = tmp_path / "worker.jsonl"
    target.write_text("".join(json.dumps(event) + "\n" for event in events))
    assert qualification.check_worker_limits(tmp_path, 2)["observed_peak_workers"] == 2
    target.write_text("".join(json.dumps(event) + "\n" for event in [*events, *interval(13, 2.5, 3.5)]))
    with pytest.raises(AssertionError, match="Observed worker concurrency"):
        qualification.check_worker_limits(tmp_path, 2)
    target.write_text("".join(json.dumps(event) + "\n" for event in events[:-1]))
    with pytest.raises(AssertionError, match="did not complete"):
        qualification.check_worker_limits(tmp_path, 2)
