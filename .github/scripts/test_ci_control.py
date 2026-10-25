import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("ci_control", Path(__file__).with_name("ci_control.py"))
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)

REPOSITORY = "example/nipat"
HEAD = "a" * 40
EVENT = {"repository": {"default_branch": "main"}}


class CheckOwnership(unittest.TestCase):
    def pull(self):
        return {"number": 42, "state": "open", "head": {
            "sha": HEAD, "ref": "feature/new", "repo": {"full_name": REPOSITORY},
        }}

    def workflow_run(self):
        return {"event": "pull_request", "head_sha": HEAD, "status": "in_progress",
                "conclusion": None, "pull_requests": [{"number": 42}]}

    def decision(self, pulls, *, name="push", ref="refs/heads/feature/new", runs=None):
        runs = {"workflow_runs": [self.workflow_run()]} if runs is None else runs
        return control.check_ownership(name, EVENT, REPOSITORY, ref, HEAD, lambda *_: pulls, lambda *_: runs)

    def test_matching_open_pr_owns_branch_push(self):
        run, duplicate, _ = self.decision([self.pull()])
        self.assertFalse(run)
        self.assertEqual(duplicate, "42")

    def test_different_commit_fork_branch_or_closed_pr_never_suppresses_checks(self):
        alternatives = [self.pull() for _ in range(5)]
        alternatives[0]["head"]["sha"] = "b" * 40
        alternatives[1]["head"]["repo"]["full_name"] = "another/nipat"
        alternatives[2]["head"]["ref"] = "different"
        alternatives[3]["state"] = "closed"
        alternatives[4]["number"] = "42"
        for pull in alternatives:
            with self.subTest(pull=pull):
                self.assertTrue(self.decision([pull])[0])

    def test_pr_draft_main_and_manual_always_run_without_api_lookup(self):
        for name, ref in (("pull_request", "refs/pull/42/merge"), ("push", "refs/heads/main"),
                          ("workflow_dispatch", "refs/heads/feature/new")):
            with self.subTest(event=name, ref=ref):
                fetch = Mock(side_effect=AssertionError("must not query"))
                self.assertTrue(control.check_ownership(name, {**EVENT, "pull_request": {"draft": True}},
                                                       REPOSITORY, ref, HEAD, fetch, fetch)[0])
                fetch.assert_not_called()

    def test_missing_or_invalid_api_response_preserves_coverage(self):
        for response in ([], None, {}, [None], [{"head": None}]):
            with self.subTest(response=response):
                self.assertTrue(self.decision(response)[0])
        self.assertTrue(control.check_ownership("push", EVENT, REPOSITORY, "refs/heads/feature/new", HEAD,
                                               Mock(side_effect=OSError("API unavailable")), Mock())[0])

    def test_missing_default_branch_never_delegates(self):
        self.assertTrue(control.check_ownership("push", {}, REPOSITORY, "refs/heads/feature/new", HEAD,
                                               Mock(return_value=[self.pull()]), Mock())[0])

    def test_open_pr_without_observed_run_keeps_push_coverage(self):
        self.assertTrue(self.decision([self.pull()], runs={"workflow_runs": []})[0])
        self.assertTrue(control.check_ownership("push", EVENT, REPOSITORY, "refs/heads/feature/new", HEAD,
                                               Mock(return_value=[self.pull()]),
                                               Mock(side_effect=OSError("Actions API unavailable")))[0])

    def test_canceled_unrelated_or_skipped_runs_never_replace_push_checks(self):
        alternatives = [self.workflow_run() for _ in range(7)]
        alternatives[0].update(status="completed", conclusion="cancelled")
        alternatives[1].update(status="completed", conclusion="skipped")
        alternatives[2]["head_sha"] = "b" * 40
        alternatives[3]["event"] = "push"
        alternatives[4]["pull_requests"] = [{"number": 43}]
        alternatives[5]["pull_requests"] = []
        alternatives[6]["status"] = "unknown"
        for run in alternatives:
            with self.subTest(run=run):
                self.assertTrue(self.decision([self.pull()], runs={"workflow_runs": [run]})[0])

    def test_observed_success_or_failure_is_owned_by_pr_required_gate(self):
        for status, conclusion in (("queued", None), ("in_progress", None),
                                   ("completed", "success"), ("completed", "failure")):
            run = self.workflow_run()
            run.update(status=status, conclusion=conclusion)
            self.assertFalse(self.decision([self.pull()], runs={"workflow_runs": [run]})[0])


class RequiredGate(unittest.TestCase):
    def results(self, scientific="true"):
        return {
            "changes": {"result": "success", "outputs": {"run_checks": "true", "scientific": scientific}},
            "linux-checks": {"result": "success"}, "windows-checks": {"result": "success"},
            "scientific": {"result": "success" if scientific == "true" else "skipped"},
        }

    def errors(self, results, event="pull_request", ref="refs/pull/42/merge"):
        return control.gate_errors(results, event_name=event, ref=ref)

    def test_full_and_documentation_only_success(self):
        self.assertEqual(self.errors(self.results()), [])
        self.assertEqual(self.errors(self.results("false")), [])

    def test_failed_cancelled_skipped_or_missing_required_jobs_fail_closed(self):
        for name in ("changes", "linux-checks", "windows-checks", "scientific"):
            for result in ("failure", "cancelled", "skipped", None):
                with self.subTest(job=name, result=result):
                    results = self.results()
                    results[name]["result"] = result
                    self.assertTrue(self.errors(results))
            results = self.results()
            del results[name]
            self.assertTrue(self.errors(results))

    def test_unknown_selection_fails_closed(self):
        for field in ("run_checks", "scientific"):
            for value in (None, "", "unexpected"):
                results = self.results()
                results["changes"]["outputs"][field] = value
                self.assertTrue(self.errors(results))

    def test_documentation_selection_does_not_hide_an_unexpected_scientific_result(self):
        results = self.results("false")
        results["scientific"]["result"] = "failure"
        self.assertTrue(self.errors(results))

    def test_only_branch_context_may_report_delegation(self):
        results = self.results()
        results["changes"]["outputs"].update(run_checks="false", duplicate_pr="42")
        for name in ("linux-checks", "windows-checks", "scientific"):
            results[name]["result"] = "skipped"
        self.assertEqual(self.errors(results, "push", "refs/heads/feature/new"), [])
        self.assertTrue(self.errors(results))
        self.assertTrue(self.errors(results, "push", "refs/heads/main"))
        for invalid in ("", "0", "not-a-pr"):
            broken = copy.deepcopy(results)
            broken["changes"]["outputs"]["duplicate_pr"] = invalid
            self.assertTrue(self.errors(broken, "push", "refs/heads/feature/new"))


class SourceIdentity(unittest.TestCase):
    def test_checkout_and_branch_head_are_not_conflated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
            git("init", "-q")
            git("config", "user.name", "CI source test")
            git("config", "user.email", "ci-source@example.invalid")
            (root / "input.txt").write_text("source\n", encoding="utf-8")
            git("add", "input.txt")
            git("commit", "-qm", "source")
            with patch.dict(os.environ, {"GITHUB_SHA": "e" * 40}):
                record = control.source_record("pull_request", {"pull_request": {"head": {"sha": HEAD}}},
                                               repository=root)
            self.assertEqual(record["source_commit"], git("rev-parse", "HEAD"))
            self.assertEqual(record["source_tree"], git("rev-parse", "HEAD^{tree}"))
            self.assertEqual(record["pull_request_head"], HEAD)
            self.assertEqual(record["event_sha"], "e" * 40)
            self.assertNotEqual(record["source_commit"], record["pull_request_head"])


if __name__ == "__main__":
    unittest.main()
