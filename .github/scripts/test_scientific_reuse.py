"""Scientific cache hits require matching real identities and complete raw bytes."""

import copy
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import zipfile

import scientific_reuse as reuse


HEAD, TREE, BASE, MERGE = (letter * 40 for letter in "abcd")
IMAGE = {"id": "sha256:" + "f" * 64, "os": "linux", "architecture": "amd64"}


class ScientificReuseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.producer_temp, self.consumer_temp = self.root / "producer", self.root / "consumer"
        self.producer_temp.mkdir()
        self.consumer_temp.mkdir()
        self.output = self.root / "receipt"
        self.source = {"commit": HEAD, "tree": TREE}
        caller_cases = {name for name, workflow in {**reuse.acceptance.R_CASES, **reuse.acceptance.R_AUDIT_CASES,
            **reuse.acceptance.SNP2_CASES}.items() if workflow in {"dnp-call", "snp-call"}}
        helper_paths = {path for path in reuse.acceptance.R_HELPERS | reuse.acceptance.R_AUDIT_HELPERS | {reuse.acceptance.PRESENTATION_HELPER}
            if not path.startswith(("tests/r_optimization/cpi/", "tests/r_optimization/contamination/"))}
        analysis_cases = []
        self.evidence = {f"{name}/verification.log": b"\xef\xbb\xbfPASS\r\n" for name in reuse.CHECK_DIRECTORIES}
        for name, (workflow, *_) in reuse.acceptance.analysis_expected_cases().items():
            filename = {"cpin": "Summary_Postnatal_CPI.txt", "cpi": "Summary_FetalFraction_CPI.csv",
                        "contamination": "contamination_summary.txt"}[workflow]
            self.evidence[f"nipat-five-modules-check/artifacts/{name}/output/{filename}"] = b"qualified summary\r\n"
            digest = reuse.sha256(b"qualified summary\r\n")
            analysis_cases.append({"name": name, "workflow": workflow, "status": "passed",
                                   "summary_sha256": digest, "output_sha256": {filename: digest}})
        self.evidence.update({
            "nipat-validation/runs/self-test/run.json": b'{"status":"passed"}\n',
            "nipat-validation/runs/self-test/execution.log": b"PASS\n",
            "nipat-performance-check/artifacts/verification.json": json.dumps({
                "schema_version": 1, "status": "passed", "image_id": IMAGE["id"]}).encode(),
            next(name for name, kind in reuse.REPORTS.items() if kind == "callers"): json.dumps({
                "schema_version": 1, "status": "passed", "inputs_unchanged": True,
                "runtime_image": IMAGE["id"], "cases": [{"case": name, "status": "passed"} for name in caller_cases],
                "helpers": [{"path": path, "status": "passed", "sha256": "e" * 64} for path in helper_paths],
                "candidate_r_sha256": {"DNPcall.R": "e" * 64}}).encode(),
            next(name for name, kind in reuse.REPORTS.items() if kind == "analyses"): json.dumps({
                "schema_version": 2, "status": "passed", "inputs_unchanged": True,
                "source_unchanged": True, "full_batch_matrix": True,
                "runtime": {"kind": "installed-image", "image_id": IMAGE["id"]},
                "results": analysis_cases, "verification_script_sha256": "e" * 64}).encode(),
        })
        for name, data in self.evidence.items():
            target = self.producer_temp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.bundle = self.root / "sealed"
        with self.runtime(), patch.dict(os.environ, {"GITHUB_REPOSITORY": reuse.REPOSITORY,
                "GITHUB_EVENT_NAME": "push", "GITHUB_SHA": HEAD, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}), \
                patch.object(reuse, "tool_version", return_value="poppler 24.02"):
            self.record = reuse.seal("scientific:test", self.bundle, self.producer_temp)
        self.run = {"id": 123, "run_attempt": 1, "event": "push", "head_sha": HEAD,
                    "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success",
                    "repository": {"id": 9, "full_name": reuse.REPOSITORY},
                    "head_repository": {"id": 9, "full_name": reuse.REPOSITORY}, "pull_requests": []}
        self.job = {"id": 88, "name": "scientific", "run_id": 123, "run_attempt": 1, "head_sha": HEAD,
                    "status": "completed", "conclusion": "success", "started_at": "2026-11-13T10:00:00Z",
                    "completed_at": "2026-11-13T10:20:00Z", "steps": [
                    {"name": name, "status": "completed", "conclusion": "success"} for name in (*reuse.STEPS, *reuse.PRODUCER_STEPS)]}
        self.commit = {"sha": HEAD, "tree": {"sha": TREE}, "parents": []}
        self.artifact = {"id": 44, "name": f"nipat-scientific-qualification-1-{TREE}", "expired": False,
                         "created_at": "2026-11-13T10:19:00Z", "workflow_run": {"id": 123,
                         "head_sha": HEAD, "repository_id": 9, "head_repository_id": 9}}
        self.remote = self.root / "github-artifact.zip"
        self.write_remote()

    def runtime(self):
        stack = ExitStack()
        stack.enter_context(patch.object(reuse, "checkout", side_effect=lambda: dict(self.source)))
        stack.enter_context(patch.object(reuse, "image_identity", return_value=IMAGE))
        stack.enter_context(patch.object(reuse.platform, "python_version", return_value="3.12.10"))
        stack.enter_context(patch.object(reuse.platform, "system", return_value="Linux"))
        stack.enter_context(patch.object(reuse.platform, "machine", return_value="x86_64"))
        stack.enter_context(patch.dict(os.environ, {"GITHUB_REPOSITORY": reuse.REPOSITORY,
            "GITHUB_RUN_ID": "456", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": reuse.REPOSITORY + "/.github/workflows/windows-installer.yml@refs/heads/main"}))
        return stack

    def write_remote(self, members=None):
        if members is not None:
            with zipfile.ZipFile(self.bundle / reuse.ARCHIVE, "w") as archive:
                for name, data in members:
                    archive.writestr(name, data)
            data = (self.bundle / reuse.ARCHIVE).read_bytes()
            self.record["archive"] = {"file": reuse.ARCHIVE, "size": len(data), "sha256": reuse.sha256(data)}
        (self.bundle / reuse.DESCRIPTOR).write_text(json.dumps(self.record))
        with zipfile.ZipFile(self.remote, "w") as archive:
            for name in (reuse.DESCRIPTOR, reuse.ARCHIVE):
                archive.write(self.bundle / name, name)
        data = self.remote.read_bytes()
        self.artifact.update(size_in_bytes=len(data), digest="sha256:" + reuse.sha256(data))

    def fetch(self, path, *, deadline=None):
        if path == "actions/workflows/ci.yml/runs?status=completed&per_page=30":
            return {"workflow_runs": [copy.deepcopy(self.run)]}
        if path == "actions/runs/123/attempts/1/jobs?per_page=100":
            return {"total_count": 1, "jobs": [copy.deepcopy(self.job)]}
        if path == "actions/runs/123/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [copy.deepcopy(self.artifact)]}
        if path == f"git/commits/{self.record['producer']['checkout_commit']}":
            return copy.deepcopy(self.commit)
        raise AssertionError(path)

    def perform_restore(self, *, fetch=None, download=None):
        self.download = Mock(side_effect=download or (lambda artifact, path, **kw: shutil.copyfile(self.remote, path)))
        with self.runtime():
            return reuse.restore("scientific:test", self.output, self.consumer_temp,
                                 fetch=fetch or self.fetch, download=self.download)

    def assert_miss(self, **kwargs):
        receipt = self.perform_restore(**kwargs)
        self.assertFalse(receipt["reused"], receipt)
        self.assertEqual(list(self.consumer_temp.iterdir()), [])
        self.assertEqual([path.name for path in self.output.iterdir()], ["reuse.json"])
        return receipt

    def test_identical_tree_and_image_reuses_exact_raw_bytes(self):
        self.source["commit"] = "e" * 40  # Commit messages/history need not match.
        result = self.perform_restore()
        self.assertTrue(result["reused"], result)
        self.assertEqual(result["producer"], self.record["producer"])
        self.assertEqual(result["consumer"]["run_id"], 456)
        self.assertEqual(result["consumer"]["attempt"], 1)
        self.assertEqual(self.download.call_count, 1)
        for name, data in self.evidence.items():
            self.assertEqual((self.consumer_temp / name).read_bytes(), data)
        self.assertEqual([path.name for path in self.output.iterdir()], ["reuse.json"])

    def test_merged_pr_uses_recorded_immutable_parents_even_without_current_pr_metadata(self):
        self.run["event"] = "pull_request"
        self.record["producer"].update(event="pull_request", checkout_commit=MERGE,
            pull_request={"number": 12, "base_sha": BASE, "head_sha": HEAD})
        self.commit.update(sha=MERGE, parents=[{"sha": BASE}, {"sha": HEAD}])
        self.write_remote()
        result = self.perform_restore()
        self.assertTrue(result["reused"], result)

    def test_pr_merge_with_wrong_historical_head_is_rejected(self):
        self.run["event"] = "pull_request"
        self.record["producer"].update(event="pull_request", checkout_commit=MERGE,
            pull_request={"number": 12, "base_sha": BASE, "head_sha": HEAD})
        self.commit.update(sha=MERGE, parents=[{"sha": BASE}, {"sha": "e" * 40}])
        self.write_remote()
        self.assert_miss()

    def test_changed_tree_is_filtered_before_download(self):
        self.source["tree"] = "e" * 40
        self.assert_miss()
        self.download.assert_not_called()

    def test_github_tree_is_checked_independently_of_manifest(self):
        self.commit["tree"]["sha"] = "e" * 40
        self.assert_miss()

    def test_different_image_or_producer_attempt_cannot_be_reused(self):
        for field in ("image", "attempt"):
            original = copy.deepcopy(self.record)
            with self.subTest(field=field):
                if field == "image":
                    self.record["image"]["id"] = "sha256:" + "e" * 64
                else:
                    self.record["producer"]["attempt"] = 2
                self.write_remote()
                self.assert_miss()
            self.record = original

    def test_failed_skipped_fork_or_other_attempt_jobs_are_misses(self):
        original_run, original_job, original_artifact = copy.deepcopy(self.run), copy.deepcopy(self.job), copy.deepcopy(self.artifact)
        changes = (
            lambda: self.run.update(conclusion="failure"),
            lambda: self.run["head_repository"].update(id=10, full_name="outsider/nipat-desktop"),
            lambda: self.job.update(run_attempt=2),
            lambda: self.job.update(conclusion="skipped"),
            lambda: self.job["steps"][0].update(conclusion="skipped"),
            lambda: self.job["steps"].pop(),
            lambda: self.job["steps"].append(copy.deepcopy(self.job["steps"][0])),
            lambda: self.artifact.update(expired=True),
            lambda: self.artifact.update(created_at="2026-11-13T09:00:00Z"),
        )
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                change()
                self.assert_miss()
                self.download.assert_not_called()
            self.run, self.job, self.artifact = copy.deepcopy(original_run), copy.deepcopy(original_job), copy.deepcopy(original_artifact)

    def test_api_and_download_failure_leave_no_partial_scientific_directories(self):
        self.assert_miss(fetch=Mock(side_effect=urllib.error.URLError("unavailable")))
        self.assert_miss(download=Mock(side_effect=OSError("download interrupted")))

    def test_incomplete_or_replaced_report_inventory_is_rejected(self):
        for change in (lambda: self.record["entries"].pop(),
                       lambda: self.record["entries"][0].update(sha256="0" * 64)):
            original = copy.deepcopy(self.record)
            change()
            self.write_remote()
            self.assert_miss()
            self.record = original

    def test_unsafe_zip_paths_symlinks_duplicates_and_non_text_are_rejected(self):
        cases = [([("../outside.json", b"{}")]), ([('/outside.json', b'{}')]),
                 ([("nipat-engine-check/a.json", b"{}"), ("nipat-engine-check/A.json", b"{}")]),
                 ([("nipat-engine-check/a.json", b"{}"), ("nipat-engine-check/a.json/b.json", b"{}")]),
                 ([("nipat-engine-check/bad.json", b"\xff")])]
        symlink = zipfile.ZipInfo("nipat-engine-check/link.json")
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append([(symlink, b"/outside")])
        for index, members in enumerate(cases):
            with self.subTest(case=index):
                self.write_remote(members)
                self.assert_miss()

    def test_missing_core_report_is_rejected_before_seal(self):
        del self.evidence[next(iter(reuse.REPORTS))]
        with self.assertRaisesRegex(ValueError, "report is missing"):
            reuse.verify_required(self.evidence, IMAGE)

    def test_existing_restore_roots_are_never_overwritten(self):
        target = self.consumer_temp / reuse.CHECK_DIRECTORIES[0]
        target.mkdir()
        (target / "keep.txt").write_text("existing")
        result = self.perform_restore()
        self.assertFalse(result["reused"])
        self.assertEqual((target / "keep.txt").read_text(), "existing")
        self.assertEqual(list(self.consumer_temp.iterdir()), [target])

    def test_rename_failure_rolls_back_only_newly_installed_directories(self):
        original_rename = Path.rename
        calls = []
        def rename(path, target):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("rename failed")
            return original_rename(path, target)
        with patch.object(Path, "rename", rename):
            self.assert_miss()

    def test_changed_consumer_after_download_is_a_miss(self):
        with self.runtime(), patch.object(reuse, "checkout", side_effect=[self.source, {"commit": HEAD, "tree": "e" * 40}]):
            result = reuse.restore("scientific:test", self.output, self.consumer_temp, fetch=self.fetch,
                                   download=lambda artifact, path, **kw: shutil.copyfile(self.remote, path))
        self.assertFalse(result["reused"])
        self.assertEqual(list(self.consumer_temp.iterdir()), [])

    def test_download_checks_github_zip_digest_and_never_forwards_api_token(self):
        data = self.remote.read_bytes()
        for correct in (True, False):
            artifact = dict(self.artifact)
            if not correct:
                artifact["digest"] = "sha256:" + "0" * 64
            destination = self.root / f"download-{correct}.zip"
            api, signed = Mock(), Mock()
            location = "https://productionresultssa1.blob.core.windows.net/actions/value?sig=opaque"
            api.open.side_effect = urllib.error.HTTPError(reuse.api_url("actions/artifacts/44/zip"), 302,
                "Found", {"Location": location}, None)
            signed.open.return_value = io.BytesIO(data)
            with self.subTest(correct=correct), patch.dict(os.environ, {"GH_TOKEN": "private-token"}), \
                    patch.object(reuse.urllib.request, "build_opener", side_effect=[api, signed]):
                if correct:
                    reuse.download_artifact(artifact, destination)
                    self.assertEqual(destination.read_bytes(), data)
                else:
                    with self.assertRaisesRegex(ValueError, "digest mismatch"):
                        reuse.download_artifact(artifact, destination)
                    self.assertFalse(destination.exists())
            request = api.open.call_args.args[0]
            self.assertEqual(request.unredirected_hdrs["Authorization"], "Bearer private-token")
            self.assertEqual(signed.open.call_args.args, (location,))

    def test_archive_size_and_entry_bounds_are_enforced_before_decompression(self):
        with zipfile.ZipFile(self.root / "bounded.zip", "w") as archive:
            archive.writestr("nipat-engine-check/a.json", b"12345")
        for limits in ({"maximum": 4, "max_file": 8, "max_entries": 2},
                       {"maximum": 8, "max_file": 4, "max_entries": 2},
                       {"maximum": 8, "max_file": 8, "max_entries": 0}):
            with self.subTest(limits=limits), self.assertRaisesRegex(ValueError, "bound"):
                reuse.read_zip(self.root / "bounded.zip", allowed=reuse.selected_path, **limits)

    def test_dirty_tracked_checkout_is_not_eligible(self):
        with patch.object(reuse.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git diff")), \
                patch.object(reuse, "run") as git:
            with self.assertRaises(subprocess.CalledProcessError):
                reuse.checkout()
        git.assert_not_called()

    def test_untracked_source_cannot_be_hidden_behind_a_clean_commit_tree(self):
        with patch.object(reuse.subprocess, "run"), patch.object(reuse, "run", return_value="src/untracked.py"):
            with self.assertRaisesRegex(ValueError, "Untracked source"):
                reuse.checkout()

    def test_missing_or_modified_summary_and_shortened_matrix_are_rejected(self):
        summary = next(name for name in self.evidence if name.endswith("/Summary_Postnatal_CPI.txt"))
        for mutation in (lambda evidence: evidence.pop(summary),
                         lambda evidence: evidence.update({summary: b"replaced"})):
            data = dict(self.evidence)
            mutation(data)
            with self.assertRaisesRegex(ValueError, "summary is missing or differs"):
                reuse.verify_required(data, IMAGE)
        name = next(name for name, kind in reuse.REPORTS.items() if kind == "analyses")
        report = json.loads(self.evidence[name])
        report["results"] = report["results"][:1]
        with self.assertRaisesRegex(ValueError, "coverage is incomplete"):
            reuse.verify_required(dict(self.evidence, **{name: json.dumps(report).encode()}), IMAGE)

    def test_search_budget_is_global_and_falls_back_without_waiting_for_other_runs(self):
        calls = []
        clock = [0]
        def fetch(path, **kwargs):
            calls.append(path)
            clock[0] += 61
            if path.startswith("actions/workflows/"):
                return {"workflow_runs": [self.run] * 30}
            return self.fetch(path, **kwargs)
        with patch.object(reuse.time, "monotonic", side_effect=lambda: clock[0]):
            result = self.assert_miss(fetch=fetch)
        self.assertIn("budget exhausted", result["reason"])
        self.assertLessEqual(len(calls), 4)

    def test_api_transport_error_does_not_repeat_thirty_times(self):
        calls = []
        def fetch(path, **kwargs):
            calls.append(path)
            if path.startswith("actions/workflows/"):
                return {"workflow_runs": [self.run] * 30}
            raise urllib.error.URLError("unavailable")
        self.assert_miss(fetch=fetch)
        self.assertEqual(len(calls), 2)

    def test_untrusted_parser_details_are_not_written_to_receipts(self):
        self.assertFalse(reuse.allowed_download("https://example.blob.core.windows.net:SIGNED_SECRET/path?sig=SECRET"))
        self.artifact["created_at"] = "SIGNED_SECRET"
        self.assert_miss()
        self.assertNotIn("SIGNED_SECRET", (self.output / "reuse.json").read_text())

    def test_workflow_output_is_false_on_lookup_failure(self):
        workflow_output = self.root / "github-output"
        with self.runtime(), patch("sys.argv", ["scientific_reuse", "restore", "--image", "science:test",
                "--runner-temp", str(self.consumer_temp), "--output-dir", str(self.output), "--output", str(workflow_output)]), \
                patch.object(reuse.urllib.request, "build_opener", side_effect=OSError("unavailable")):
            reuse.main()
        self.assertEqual(workflow_output.read_text(), "reused=false\n")
        self.assertEqual(list(self.consumer_temp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
