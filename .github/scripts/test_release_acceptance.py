import copy
import importlib.util
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
        for version in ("0.4.1", "0.7.0", "1.0.0", "../0.5.0a1"):
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


if __name__ == "__main__":
    unittest.main()
