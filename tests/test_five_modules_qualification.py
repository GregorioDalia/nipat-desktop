"""The independent qualification must reject wrong numbers and damaged references."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "five_modules_qualification", Path(__file__).resolve().parents[1] / "scripts/verify_five_modules.py",
)
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class FiveModuleQualificationTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.tmp_path = Path(temporary)

    def test_frozen_reference_source_hashes(self):
        manifest = qualification.verify_frozen_sources()
        assert len(manifest["sha256"]) == 3

    def test_native_settings_require_parameters_constants_and_json_types(self):
        expected = {"workflow": "contamination", "parameters": {"include_zero": True, "threshold": .1},
                    "constants": {"ploidy": {"value": 2}}}
        self.assertTrue(qualification.same_settings(expected, expected))
        for actual in (
            {**expected, "parameters": {"include_zero": 1, "threshold": .1}},
            {**expected, "parameters": {"include_zero": True, "threshold": .2}},
            {**expected, "constants": {}},
            {**expected, "unexpected": True},
        ):
            with self.subTest(actual=actual):
                self.assertFalse(qualification.same_settings(actual, expected))

    def test_same_number_of_rows_cannot_hide_missing_family_or_sample_identities(self):
        cpin_rows = [{"Trio": "MotherM1-FatherF1-ChildC1_SNPs", "Analysis": selection}
                     for selection in ("heterozygous_child_sites", "all_compatible_sites")] * 2
        cpi_rows = [{"Pair": "MotherM1-FatherF1_SNPs"}] * 2
        contamination_rows = [{"individuo": "Sample1"}] * 2
        for check, rows, kwargs in (
            (qualification.check_cpin, cpin_rows, {"marker": "SNP", "families": 2}),
            (qualification.check_cpi, cpi_rows, {"marker": "SNP", "families": 2}),
            (qualification.check_contamination, contamination_rows, {"include_zero": True, "samples": 2}),
        ):
            with self.subTest(check=check.__name__), mock.patch.object(qualification, "table", return_value=rows):
                with self.assertRaisesRegex(AssertionError, "each distinct"):
                    check(self.tmp_path, **kwargs)


    def test_numerical_comparison_permits_diagnostics_not_changed_science(self):
        expected = [{"Pair": "M:F", "CPI": "0.602", "Missing": "NA"}]
        qualification.compare_tables(
            [{"Pair": "M:F", "CPI": "0.602000000000001", "Missing": "NA", "Diagnostic": "new"}], expected,
        )
        with self.assertRaises(AssertionError):
            qualification.compare_tables([{"Pair": "M:F", "CPI": "0.603", "Missing": "NA"}], expected)
        with self.assertRaises(AssertionError):
            qualification.compare_tables([{"Pair": "M:F", "CPI": "0.602", "Missing": "0"}], expected)


    def test_duplicate_or_missing_reference_rows_are_not_accepted(self):
        expected = [{"Trio": "M:F:C", "CPI": "2"}]
        with self.assertRaises(AssertionError):
            qualification.compare_tables(expected * 2, expected)
        with self.assertRaises(AssertionError):
            qualification.compare_tables([], expected)


    def test_marker_fixtures_encode_the_same_counts_but_distinct_coordinates(self):
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


    def test_installed_payload_gate_rejects_stale_helpers_and_r(self):
        tmp_path = self.tmp_path
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
        with self.assertRaisesRegex(AssertionError, "Stale scientific image"):
            qualification.verify_installed_payload(tmp_path)


    def test_docker_gate_runs_immutable_installed_payload_without_host_overrides(self):
        tmp_path = self.tmp_path
        image_id = "sha256:" + "a" * 64
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[1] == "image":
                return subprocess.CompletedProcess(command, 0, image_id + "\n", "")
            (tmp_path / qualification.REPORT_NAME).write_text(json.dumps(
                {"status": "passed", "runtime": {"image_id": image_id}, "results": []}))
            return subprocess.CompletedProcess(command, 0, "passed", "")

        self.enterContext(mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/docker"))
        self.enterContext(mock.patch.object(qualification.subprocess, "run", side_effect=run))
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


    def test_worker_gate_checks_observed_concurrency_and_task_completion(self):
        tmp_path = self.tmp_path
        plan = {"event": "plan", "workers": 2, "tasks": 2, "cpu_limit": 4,
                "memory_worker_limit": 4, "observed_at_unix": 0, "coordinator_pid": 10,
                "label": "native-work", "mode": "auto"}

        def interval(pid, start, end):
            identity = {**plan, "pid": pid, "task_index": pid - 10}
            return [{**identity, "event": "task-start", "observed_at_unix": start},
                    {**identity, "event": "task-end", "observed_at_unix": end, "outcome": "succeeded"}]

        events = [plan, *interval(11, 1, 3), *interval(12, 2, 4)]
        target = tmp_path / "worker.jsonl"
        target.write_text("".join(json.dumps(event) + "\n" for event in events))
        assert qualification.check_worker_limits(tmp_path, 2)["observed_peak_workers"] == 2
        over = [{**event, "tasks": 3} for event in [*events, *interval(13, 2.5, 3.5)]]
        target.write_text("".join(json.dumps(event) + "\n" for event in over))
        with self.assertRaisesRegex(AssertionError, "Observed worker concurrency"):
            qualification.check_worker_limits(tmp_path, 2)
        with self.assertRaisesRegex(AssertionError, "Observed worker concurrency exceeded shared budget"):
            qualification.check_worker_limits(tmp_path, None)
        target.write_text("".join(json.dumps(event) + "\n" for event in events[:-1]))
        with self.assertRaisesRegex(AssertionError, "did not complete"):
            qualification.check_worker_limits(tmp_path, 2)

    def test_worker_gate_rejects_repeated_completed_task_and_undeclared_plan(self):
        plan = {"event": "plan", "workers": 1, "tasks": 2, "cpu_limit": 4,
                "memory_worker_limit": 4, "observed_at_unix": 0, "coordinator_pid": 10,
                "label": "native-work", "mode": "serial"}
        def task(index, start):
            identity = {**plan, "pid": 10, "task_index": index}
            return [{**identity, "event": "task-start", "observed_at_unix": start},
                    {**identity, "event": "task-end", "observed_at_unix": start + 1, "outcome": "succeeded"}]
        target = self.tmp_path / "worker.jsonl"
        events = [plan, *task(1, 1), *task(1, 3)]
        target.write_text("".join(json.dumps(event) + "\n" for event in events))
        with self.assertRaisesRegex(AssertionError, "Duplicated scientific task start"):
            qualification.check_worker_limits(self.tmp_path, 1)
        events = [plan, *task(1, 1), *[{**event, "label": "unplanned"} for event in task(2, 3)]]
        target.write_text("".join(json.dumps(event) + "\n" for event in events))
        with self.assertRaisesRegex(AssertionError, "no matching resource plan"):
            qualification.check_worker_limits(self.tmp_path, 1)

    def test_sequential_invocations_may_reuse_the_same_label_and_task_indices(self):
        base = {"workers": 1, "cpu_limit": 4, "memory_worker_limit": 4,
                "coordinator_pid": 10, "pid": 10, "mode": "serial"}
        def event(label, tasks, kind, stamp, index=None):
            return {**base, "label": label, "tasks": tasks, "event": kind,
                    "observed_at_unix": stamp, "task_index": index, "outcome": "succeeded"}
        events = [event("pairs", 2, "plan", 0)]
        for index in (1, 2):
            start = 1 + (index - 1) * 5
            events.extend((event("pairs", 2, "task-start", start, index),
                           event("cutoffs", 1, "plan", start + 1),
                           event("cutoffs", 1, "task-start", start + 2, 1),
                           event("cutoffs", 1, "task-end", start + 3, 1),
                           event("pairs", 2, "task-end", start + 4, index)))
        (self.tmp_path / "worker.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events))
        result = qualification.check_worker_limits(self.tmp_path, 1)
        self.assertEqual(result["completed_worker_tasks"], 4)
        self.assertEqual(result["observed_peak_workers"], 1)
