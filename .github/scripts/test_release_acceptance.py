import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("acceptance", Path(__file__).with_name("release_acceptance.py"))
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)
COMMIT = "a" * 40
PROCEDURE = "b" * 40
SET = {
    "version": "0.5.0a1", "source_commit": COMMIT,
    "installer_manifest_sha256": "1" * 64,
    "scientific_archive": {"sha256": "2" * 64},
    "windows": {"sha256": "3" * 64}, "linux": {"sha256": "4" * 64},
}


def accepted_record():
    record = acceptance.template(SET, 123)
    record["decision"] = "accepted"
    for test in record["tests"].values():
        test.update(result="passed", tester="Example tester", tested_at="2026-01-01T12:00:00Z",
                    evidence=["https://github.com/example/repository/issues/1"])
    return record


def research_record():
    record = {key: value for key, value in accepted_record().items() if key != "tests"}
    record.update({
        "schema_version": 2, "version": "0.6.0", "decision": "accepted-for-research",
        "scope": "pre-1.0-research",
        "review": {"reviewer": "Example reviewer", "reviewed_at": "2026-01-01T12:00:00Z",
                   "evidence": ["https://github.com/example/repository/blob/main/review.md"]},
        "observed_baseline": {
            "source_commit": "c" * 40,
            "observations": ["installation_ready", "runtime_diagnostics", "scientific_self_tests",
                             "dnp_sample_analysis"],
            "evidence": ["https://github.com/example/repository/blob/main/observed-baseline.md"],
            "source_equivalence_scope": "distributed-operative-sources-v1",
        },
        "deferred_desktop_scenarios": sorted(acceptance.SCENARIOS),
        "domain_validation": "planned-for-0.7",
    })
    return record


class AcceptanceTests(unittest.TestCase):
    def test_generated_template_cannot_authorize_publication(self):
        pending = acceptance.template(SET, 123)
        self.assertEqual(pending["decision"], "pending")
        self.assertTrue(all(test["result"] == "pending" for test in pending["tests"].values()))
        with self.assertRaisesRegex(ValueError, "pending or rejected"):
            acceptance.validate(pending, "0.5.0a1", COMMIT, 123, SET)

    def test_committed_acceptance_is_read_from_procedure_not_built_source(self):
        record = accepted_record()
        with patch("builtins.print"), patch.object(acceptance, "validate", wraps=acceptance.validate) as validator:
            calls = []
            def read_source(commit, path):
                calls.append((commit, path))
                return json.dumps(record).encode()
            actual, raw = acceptance.load("0.5.0a1", COMMIT, 123, PROCEDURE, read_source)
        self.assertEqual(calls, [(PROCEDURE, ".github/release-acceptance/v0.5.0a1.json")])
        self.assertEqual(actual, record)
        self.assertEqual(json.loads(raw), record)
        validator.assert_called_once()

    def test_missing_git_path_has_clear_error(self):
        def missing(commit, path):
            raise subprocess.CalledProcessError(128, ["git", "show", f"{commit}:{path}"])
        with self.assertRaisesRegex(ValueError, "Missing committed desktop acceptance"):
            acceptance.load("0.5.0a1", COMMIT, 123, PROCEDURE, missing)

    def test_pending_rejected_or_incomplete_acceptance_fails(self):
        original = accepted_record()
        for decision in ("pending", "rejected", True):
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, "pending or rejected"):
                acceptance.validate(dict(original, decision=decision), "0.5.0a1", COMMIT, 123)
        for scenario in acceptance.SCENARIOS:
            record = copy.deepcopy(original)
            del record["tests"][scenario]
            with self.subTest(missing=scenario), self.assertRaisesRegex(ValueError, "scenario is missing"):
                acceptance.validate(record, "0.5.0a1", COMMIT, 123)
            record = copy.deepcopy(original)
            record["tests"][scenario]["result"] = "pending"
            with self.subTest(pending=scenario), self.assertRaisesRegex(ValueError, "has not passed"):
                acceptance.validate(record, "0.5.0a1", COMMIT, 123)

    def test_build_identity_cannot_be_substituted(self):
        original = accepted_record()
        for field, value in (("version", "0.5.0a2"), ("source_commit", PROCEDURE),
                             ("build_run_id", 124), ("build_run_id", True)):
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "different version, source or build"):
                acceptance.validate(dict(original, **{field: value}), "0.5.0a1", COMMIT, 123)
        for field in acceptance.DIGESTS:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "hashes do not identify"):
                acceptance.validate(dict(original, **{field: "f" * 64}), "0.5.0a1", COMMIT, 123, SET)
        acceptance.validate(original, "0.5.0a1", COMMIT, 123, SET)

    def test_boolean_schema_and_missing_or_extra_fields_are_rejected(self):
        original = accepted_record()
        variants = [dict(original, schema_version=True), dict(original, ignored=True)]
        for field in original:
            record = copy.deepcopy(original)
            del record[field]
            variants.append(record)
        for record in variants:
            with self.subTest(record=record.keys()), self.assertRaises(ValueError):
                acceptance.validate(record, "0.5.0a1", COMMIT, 123)

    def test_tester_date_and_evidence_are_required_for_each_scenario(self):
        invalid = {
            "tester": ["", "  ", None],
            "tested_at": ["", "2026-99-01T12:00:00Z", "2999-01-01T12:00:00Z", "2026-01-01", True],
            "evidence": [[], ["file:///tmp/results"], ["https://example.com"],
                         ["https://user:password@example.com/private"], ["https://example.com/some path"], [True]],
        }
        for field, values in invalid.items():
            for value in values:
                record = accepted_record()
                record["tests"]["windows_clean_wsl"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    acceptance.validate(record, "0.5.0a1", COMMIT, 123)

    def test_future_distribution_contracts_are_not_implicitly_authorized(self):
        for version in ("0.4.1", "0.8.0", "1.0.0", "../0.5.0a1"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "only for the 0.5"):
                acceptance.acceptance_path(version)

    def test_desktop_06_retains_all_acceptance_requirements(self):
        current = dict(SET, version="0.6.0")
        record = acceptance.template(current, 123)
        self.assertEqual(acceptance.acceptance_path("0.6.0"),
                         ".github/release-acceptance/v0.6.0.json")
        with self.assertRaisesRegex(ValueError, "pending or rejected"):
            acceptance.validate(record, "0.6.0", COMMIT, 123, current)
        record = dict(accepted_record(), version="0.6.0")
        acceptance.validate(record, "0.6.0", COMMIT, 123, current)
        for name in acceptance.SCENARIOS:
            incomplete = copy.deepcopy(record)
            incomplete["tests"][name]["result"] = "pending"
            with self.subTest(scenario=name), self.assertRaisesRegex(ValueError, "has not passed"):
                acceptance.validate(incomplete, "0.6.0", COMMIT, 123, current)

    def test_template_command_never_overwrites_an_existing_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "set.json"
            destination = root / "acceptance.json"
            source.write_text(json.dumps(SET))
            argv = ["acceptance", "--installer-set", str(source), "--run-id", "123", "--output", str(destination)]
            with patch("sys.argv", argv), patch("builtins.print"):
                acceptance.main()
                original = destination.read_bytes()
                with self.assertRaises(FileExistsError):
                    acceptance.main()
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(json.loads(original)["decision"], "pending")


class ResearchAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.record = research_record()
        self.pair = dict(SET, version="0.6.0")
        paths = acceptance.REQUIRED_OPERATIVE_PATHS | {"README.md", ".github/workflows/ci.yml"}
        common = {path: ("fixture bytes: " + path).encode() for path in paths}
        common["distribution-files.txt"] = self.allowlist(common)
        self.sources = {COMMIT: copy.deepcopy(common), "c" * 40: copy.deepcopy(common)}

    @staticmethod
    def allowlist(files):
        return ("\n".join(sorted(set(files) | {"distribution-files.txt"})) + "\n").encode()

    def read_source(self, commit, path):
        return self.sources[commit][path]

    def validate(self, record):
        acceptance.validate(record, "0.6.0", COMMIT, 123, self.pair)

    def test_limited_research_acceptance_retains_exact_candidate_and_deferred_scope(self):
        self.validate(self.record)
        self.assertNotIn("tests", self.record)
        self.assertNotIn("installer_sha256", self.record["observed_baseline"])
        self.assertEqual(set(self.record["deferred_desktop_scenarios"]), acceptance.SCENARIOS)
        self.assertEqual(self.record["domain_validation"], "planned-for-0.7")
        for field in acceptance.DIGESTS:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "hashes do not identify"):
                self.validate(dict(self.record, **{field: "f" * 64}))
        for field, value in (("source_commit", PROCEDURE), ("build_run_id", 124),
                             ("build_run_id", True), ("version", "0.6.1")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "different version, source or build"):
                self.validate(dict(self.record, **{field: value}))

    def test_research_policy_is_not_implicitly_available_for_other_versions(self):
        for version in ("0.5.0a1", "0.7.0", "1.0.0", "1.0.0rc1", "2.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                acceptance.validate(dict(self.record, version=version), version, COMMIT, 123)

    def test_research_cannot_hide_pending_scenarios_or_claim_domain_validation(self):
        for scenarios in ([], sorted(acceptance.SCENARIOS)[1:],
                          sorted(acceptance.SCENARIOS) + ["windows_clean_wsl"],
                          sorted(acceptance.SCENARIOS) + ["unknown"], {"windows_clean_wsl": "passed"}):
            with self.subTest(scenarios=scenarios), self.assertRaisesRegex(ValueError, "six desktop"):
                self.validate(dict(self.record, deferred_desktop_scenarios=scenarios))
        for domain in ("passed", "validated", "accepted", True, {"status": "passed"}):
            with self.subTest(domain=domain), self.assertRaisesRegex(ValueError, "domain validation"):
                self.validate(dict(self.record, domain_validation=domain))

    def test_research_requires_explicit_decision_valid_review_and_evidence(self):
        for decision in ("pending", "rejected", "accepted", True):
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, "stated scope"):
                self.validate(dict(self.record, decision=decision))
        for key, values in {
            "reviewer": ["", "  ", None],
            "reviewed_at": ["2026-01-01", "2026-99-01T12:00:00Z", "2999-01-01T12:00:00Z", True],
            "evidence": [[], ["file:///tmp/results"], ["https://example.com"],
                         ["https://user:pass@example.com/private"], [True]],
        }.items():
            for value in values:
                changed = copy.deepcopy(self.record)
                changed["review"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.validate(changed)
        for schema in (True, False, 2.0, "2", 3):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                self.validate(dict(self.record, schema_version=schema))
        for field in self.record:
            changed = copy.deepcopy(self.record)
            del changed[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.validate(changed)
        with self.assertRaises(ValueError):
            self.validate(dict(self.record, tests={"windows_clean_wsl": "passed"}))

    def test_baseline_requires_identified_installation_and_execution_observations(self):
        for key, values in {
            "source_commit": ["", "short", True],
            "source_equivalence_scope": ["all-binaries-identical", "", True],
            "observations": [[], ["installation_ready"], ["runtime_diagnostics"],
                             ["installation_ready", "domain_validation_passed"],
                             ["installation_ready", "scientific_self_tests", "scientific_self_tests"]],
            "evidence": [[], ["https://example.com"], ["http://example.com/evidence"]],
        }.items():
            for value in values:
                changed = copy.deepcopy(self.record)
                changed["observed_baseline"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.validate(changed)
        changed = copy.deepcopy(self.record)
        changed["observed_baseline"]["installer_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "baseline fields"):
            self.validate(changed)

    def test_baseline_equivalence_allows_only_excluded_documentation_and_maintenance_changes(self):
        candidate = self.sources[COMMIT]
        candidate["README.md"] = b"new documentation"
        candidate[".github/workflows/ci.yml"] = b"new maintenance procedure"
        candidate["docs/extra.md"] = b"new guide"
        candidate["distribution-files.txt"] = self.allowlist(candidate)
        result = acceptance.verify_baseline(self.record, self.read_source)
        self.assertEqual(result["baseline_source_commit"], "c" * 40)
        self.assertEqual(result["source_commit"], COMMIT)
        self.assertEqual(result["files_verified"], len(acceptance.REQUIRED_OPERATIVE_PATHS))
        self.assertEqual(result["scope"], acceptance.SOURCE_EQUIVALENCE_SCOPE)

    def test_baseline_equivalence_rejects_application_runtime_and_build_changes(self):
        for path in acceptance.REQUIRED_OPERATIVE_PATHS:
            original = self.sources[COMMIT][path]
            self.sources[COMMIT][path] = b"altered source"
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "operative source differs"):
                acceptance.verify_baseline(self.record, self.read_source)
            self.sources[COMMIT][path] = original

    def test_baseline_equivalence_rejects_added_removed_or_unreadable_operative_sources(self):
        original = copy.deepcopy(self.sources)
        self.sources[COMMIT]["new_code.py"] = b"new application code"
        self.sources[COMMIT]["distribution-files.txt"] = self.allowlist(self.sources[COMMIT])
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            acceptance.verify_baseline(self.record, self.read_source)
        self.sources = copy.deepcopy(original)
        del self.sources[COMMIT]["engine/main.py"]
        with self.assertRaisesRegex(ValueError, "Cannot read baseline"):
            acceptance.verify_baseline(self.record, self.read_source)
        self.sources[COMMIT]["distribution-files.txt"] = self.allowlist(self.sources[COMMIT])
        with self.assertRaisesRegex(ValueError, "omits required"):
            acceptance.verify_baseline(self.record, self.read_source)
        self.sources = copy.deepcopy(original)
        del self.sources["c" * 40]
        with self.assertRaisesRegex(ValueError, "Cannot read baseline"):
            acceptance.verify_baseline(self.record, self.read_source)

    def test_only_actual_removal_of_legacy_signing_helpers_is_exempt(self):
        for path in acceptance.REMOVABLE_SIGNING_HELPERS:
            baseline = self.sources["c" * 40]
            candidate = self.sources[COMMIT]
            baseline[path] = b"old optional signing helper"
            baseline["distribution-files.txt"] = self.allowlist(baseline)
            acceptance.verify_baseline(self.record, self.read_source)
            candidate[path] = b"changed helper"
            candidate["distribution-files.txt"] = self.allowlist(candidate)
            with self.assertRaisesRegex(ValueError, "operative source differs"):
                acceptance.verify_baseline(self.record, self.read_source)
            del baseline[path]
            baseline["distribution-files.txt"] = self.allowlist(baseline)
            with self.assertRaisesRegex(ValueError, "inventory differs"):
                acceptance.verify_baseline(self.record, self.read_source)
            del candidate[path]
            candidate["distribution-files.txt"] = self.allowlist(candidate)

    def test_baseline_equivalence_rejects_malformed_inventory_and_missing_record_fields(self):
        original = self.sources[COMMIT]["distribution-files.txt"]
        for additional in (b"engine/main.py\n", b"../outside.py\n", b"/absolute.py\n", b"src\\bad.py\n"):
            self.sources[COMMIT]["distribution-files.txt"] = original + additional
            with self.subTest(additional=additional), self.assertRaisesRegex(ValueError, "inventory path"):
                acceptance.verify_baseline(self.record, self.read_source)
        changed = copy.deepcopy(self.record)
        del changed["source_commit"]
        with self.assertRaisesRegex(ValueError, "record fields"):
            acceptance.verify_baseline(changed, self.read_source)

    def test_schema_one_still_requires_full_acceptance_and_has_no_baseline_reuse(self):
        self.assertIsNone(acceptance.verify_baseline(accepted_record(), self.read_source))
        changed = dict(self.record, schema_version=1)
        with self.assertRaises(ValueError):
            self.validate(changed)


class ReviewedResearchAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.record = research_record()
        self.record.update(schema_version=3, version="0.7.1", reviewed_source_changes=[],
                           domain_validation="pending-domain-researchers")
        self.record["observed_baseline"].update(
            observations=["installation_ready", "automatic_workflow_sample_analysis"],
            source_equivalence_scope=acceptance.REVIEWED_SOURCE_SCOPE,
        )
        self.pair = dict(SET, version="0.7.1")
        paths = acceptance.REQUIRED_OPERATIVE_PATHS | {
            "src/nipat/wizard.py", "src/nipat_scientific/executor.py", "scientific/vendor/example.R",
            "installer/windows/bootstrap-common.ps1", "tests/test_cli_validation.py",
        }
        common = {path: ("fixture bytes: " + path).encode() for path in paths}
        common["distribution-files.txt"] = ResearchAcceptanceTests.allowlist(common)
        self.sources = {COMMIT: copy.deepcopy(common), "c" * 40: copy.deepcopy(common)}

    def read_source(self, commit, path):
        return self.sources[commit][path]

    def validate(self, record=None):
        acceptance.validate(record or self.record, "0.7.1", COMMIT, 123, self.pair)

    def change(self, path, new=b"reviewed client change"):
        before = self.sources["c" * 40].get(path)
        if new is None:
            del self.sources[COMMIT][path]
        else:
            self.sources[COMMIT][path] = new
        self.sources[COMMIT]["distribution-files.txt"] = ResearchAcceptanceTests.allowlist(self.sources[COMMIT])
        return {"path": path,
                "before_sha256": hashlib.sha256(before).hexdigest() if before is not None else None,
                "after_sha256": hashlib.sha256(new).hexdigest() if new is not None else None}

    def test_exact_build_identity_and_research_scope_remain_required(self):
        self.validate()
        self.assertEqual(acceptance.acceptance_path("0.7.1"), ".github/release-acceptance/v0.7.1.json")
        for field, value in (("source_commit", "f" * 40), ("build_run_id", 124),
                             ("decision", "pending"), ("domain_validation", "passed"),
                             ("windows_installer_sha256", "f" * 64), ("reviewed_source_changes", None)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(dict(self.record, **{field: value}))
        for version in ("0.6.0", "0.8.0", "1.0.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                acceptance.validate(dict(self.record, version=version), version, COMMIT, 123)
        with self.assertRaises(ValueError):
            self.validate(dict(self.record, deferred_desktop_scenarios=[]))

    def test_reviewed_delta_uses_actual_bytes_and_does_not_claim_new_installation(self):
        paths = ("src/nipat/wizard.py", "installer/windows/bootstrap-common.ps1", "tests/new_case.py")
        self.record["reviewed_source_changes"] = sorted([self.change(path) for path in paths], key=lambda item: item["path"])
        self.validate()
        result = acceptance.verify_baseline(self.record, self.read_source)
        self.assertEqual(result["reviewed_source_changes"], self.record["reviewed_source_changes"])
        self.assertEqual(result["scope"], acceptance.REVIEWED_SOURCE_SCOPE)
        self.assertFalse(result["candidate_windows_installation_claimed"])
        self.assertGreater(result["unchanged_files_verified"], 0)

    def test_unreported_extra_missing_or_wrongly_hashed_changes_fail(self):
        delta = self.change("src/nipat/wizard.py")
        for changes in ([], [dict(delta, after_sha256="f" * 64)],
                        [dict(delta, before_sha256=None)], [dict(delta, path="src/nipat/cli.py")]):
            self.record["reviewed_source_changes"] = changes
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "exact baseline-to-candidate"):
                acceptance.verify_baseline(self.record, self.read_source)
        self.record["reviewed_source_changes"] = [delta]
        acceptance.verify_baseline(self.record, self.read_source)
        self.change("src/nipat/cli.py")
        with self.assertRaisesRegex(ValueError, "exact baseline-to-candidate"):
            acceptance.verify_baseline(self.record, self.read_source)

    def test_scientific_and_runtime_changes_cannot_be_approved_as_client_changes(self):
        original = copy.deepcopy(self.sources)
        for path in ("engine/main.py", "src/nipat_scientific/executor.py", "scientific/vendor/example.R",
                     "docker/scientific-runtime/Dockerfile", "installer/runtime/nipat-engine", "compose.yaml"):
            self.sources = copy.deepcopy(original)
            delta = self.change(path)
            self.record["reviewed_source_changes"] = [delta]
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Only explicit client"):
                self.validate()
            self.record["reviewed_source_changes"] = []
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Protected scientific or runtime"):
                acceptance.verify_baseline(self.record, self.read_source)

    def test_client_additions_and_removals_require_exact_null_digest(self):
        added = self.change("tests/new_case.py")
        removed = self.change("tests/test_cli_validation.py", None)
        self.assertIsNone(added["before_sha256"])
        self.assertIsNone(removed["after_sha256"])
        self.record["reviewed_source_changes"] = sorted([added, removed], key=lambda item: item["path"])
        acceptance.verify_baseline(self.record, self.read_source)
        self.record["reviewed_source_changes"].pop()
        with self.assertRaises(ValueError):
            acceptance.verify_baseline(self.record, self.read_source)

    def test_invalid_duplicate_or_unreviewable_delta_entries_fail(self):
        delta = self.change("src/nipat/wizard.py")
        for changes in ([delta, delta], [dict(delta, path="../outside.py")],
                        [dict(delta, path="/tmp/source.py")], [dict(delta, path="README.md")],
                        [dict(delta, before_sha256=True)], [dict(delta, extra=True)],
                        [dict(delta, before_sha256=delta["after_sha256"])],
                        [dict(delta, before_sha256=None, after_sha256=None)]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.validate(dict(self.record, reviewed_source_changes=changes))

    def test_documentation_changes_do_not_need_a_source_delta(self):
        self.sources[COMMIT]["docs/review.md"] = b"review evidence, not executable application input"
        self.sources[COMMIT]["distribution-files.txt"] = ResearchAcceptanceTests.allowlist(self.sources[COMMIT])
        result = acceptance.verify_baseline(self.record, self.read_source)
        self.assertEqual(result["reviewed_source_changes"], [])


class ReliabilityResearchAcceptanceTests(ReviewedResearchAcceptanceTests):
    # Override the fixture and exercise the expanded policy independently of
    # the inherited schema-3 expectations.
    def setUp(self):
        super().setUp()
        self.record.update(schema_version=4, version="0.7.2",
                           qualification_evidence_sha256="5" * 64,
                           linux_upgrade_check_sha256="6" * 64)
        baseline = self.record["observed_baseline"]
        del baseline["source_equivalence_scope"]
        baseline.update(source_comparison_scope=acceptance.RELIABILITY_SOURCE_SCOPE,
                        role="historical-platform-evidence")
        self.pair.update(version="0.7.2",
                         linux_upgrade_check={"file": "linux-upgrade-check.json", "sha256": "6" * 64})

    def validate(self, record=None):
        acceptance.validate(record or self.record, "0.7.2", COMMIT, 123, self.pair)

    def test_exact_build_identity_and_research_scope_remain_required(self):
        self.validate()
        for field, value in (("qualification_evidence_sha256", "invalid"),
                             ("linux_upgrade_check_sha256", "f" * 64),
                             ("domain_validation", "passed"), ("decision", "pending")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(dict(self.record, **{field: value}))
        old = copy.deepcopy(self.record)
        old["version"] = "0.7.1"
        with self.assertRaisesRegex(ValueError, "from 0.7.2"):
            acceptance.validate(old, "0.7.1", COMMIT, 123)

    def test_reviewed_delta_uses_actual_bytes_and_does_not_claim_new_installation(self):
        paths = ("src/nipat_scientific/executor.py", "engine/main.py", "installer/runtime/nipat-engine")
        self.record["reviewed_source_changes"] = sorted([self.change(p) for p in paths], key=lambda x: x["path"])
        self.validate()
        result = acceptance.verify_baseline(self.record, self.read_source)
        self.assertEqual(result["scope"], acceptance.RELIABILITY_SOURCE_SCOPE)
        self.assertFalse(result["operational_equivalence_claimed"])
        self.assertFalse(result["candidate_windows_installation_claimed"])
        self.assertTrue(result["r_sources_unchanged"])
        self.assertEqual(result["reviewed_source_changes"], self.record["reviewed_source_changes"])

    def test_scientific_and_runtime_changes_cannot_be_approved_as_client_changes(self):
        original = copy.deepcopy(self.sources)
        for path in ("scientific/vendor/example.R", "scientific/SHA256SUMS", "engine/changed.R"):
            self.sources = copy.deepcopy(original)
            delta = self.change(path)
            self.record["reviewed_source_changes"] = [delta]
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "non-R operative"):
                self.validate()
            self.record["reviewed_source_changes"] = []
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Protected scientific"):
                acceptance.verify_baseline(self.record, self.read_source)

    def test_baseline_is_not_relabelled_as_candidate_installation_or_equivalence(self):
        for change in ({"role": "candidate-tested"}, {"source_comparison_scope": acceptance.REVIEWED_SOURCE_SCOPE},
                       {"source_equivalence_scope": acceptance.REVIEWED_SOURCE_SCOPE}):
            record = copy.deepcopy(self.record)
            record["observed_baseline"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(record)

    def test_new_research_contract_cannot_use_historical_less_complete_schema(self):
        old = research_record()
        old.update(schema_version=3, version="0.7.2", reviewed_source_changes=[],
                   domain_validation="pending-domain-researchers")
        with self.assertRaisesRegex(ValueError, "require reliability acceptance"):
            acceptance.validate(old, "0.7.2", COMMIT, 123)


if __name__ == "__main__":
    unittest.main()
