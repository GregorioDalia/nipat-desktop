"""A changed scientific core needs exact, retained, candidate-bound evidence."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("revised_acceptance", Path(__file__).with_name("release_acceptance.py"))
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)
COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64


def digest(value):
    return hashlib.sha256(value).hexdigest()


class RevisedRAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.installer_set = {
            "version": "0.8.9", "source_commit": COMMIT,
            "installer_manifest_sha256": "1" * 64,
            "scientific_archive": {"sha256": "2" * 64},
            "windows": {"sha256": "3" * 64}, "linux": {"sha256": "4" * 64},
            "macos_arm64": {"sha256": "5" * 64}, "macos_x86_64": {"sha256": "6" * 64},
            "linux_upgrade_check": {"sha256": "7" * 64},
        }
        self.record = acceptance.template(self.installer_set, 123)
        self.record.update(decision="accepted-for-research")
        evidence = ["https://github.com/example/repository/blob/commit/review.md"]
        self.record["review"].update(reviewer="Technical reviewer", reviewed_at="2026-01-01T00:00:00Z", evidence=evidence)
        self.record["observed_baseline"].update(source_commit=acceptance.R_REFERENCE_COMMIT,
            observations=["installation_ready", "scientific_self_tests"], evidence=evidence)
        paths = set(acceptance.R_WORKFLOWS) | {
            "docker/scientific-runtime/verify-packages.R", "src/nipat_scientific/presentation.R",
        }
        original = {path: ("original " + path).encode() for path in paths}
        candidate = {path: ("candidate " + path).encode() for path in paths}
        self.reference = {
            "schema_version": 1, "version": "0.8.5", "source_tag": "v0.8.5",
            "source_commit": acceptance.R_REFERENCE_COMMIT,
            "files": [{"path": path, "sha256": digest(original[path])} for path in sorted(paths)],
        }
        candidate.update({acceptance.R_REFERENCE_ROOT + "/" + path: value for path, value in original.items()})
        candidate[acceptance.R_REFERENCE_ROOT + "/manifest.json"] = json.dumps(self.reference).encode()
        for path in acceptance.R_HELPERS:
            candidate[path] = ("test source " + path).encode()
        candidate["scientific/SHA256SUMS"] = "".join(
            f"{digest(candidate[path])}  {path.removeprefix('scientific/')}\n"
            for path in acceptance.R_WORKFLOWS).encode()
        for path in acceptance.REQUIRED_OPERATIVE_PATHS:
            original.setdefault(path, ("common " + path).encode())
            candidate.setdefault(path, original[path])
        for files in (original, candidate):
            # The frozen oracle and test harness are not installed application inputs.
            files["distribution-files.txt"] = ("\n".join(sorted(
                {path for path in files if not path.startswith("tests/")} | {"distribution-files.txt"})) + "\n").encode()
        self.sources = {acceptance.R_REFERENCE_COMMIT: original, COMMIT: candidate}
        self.record["reviewed_source_changes"] = sorted([
            {"path": path, "before_sha256": digest(original[path]), "after_sha256": digest(candidate[path])}
            for path in set(acceptance.R_WORKFLOWS) | {"scientific/SHA256SUMS", "src/nipat_scientific/presentation.R",
                                                    "docker/scientific-runtime/verify-packages.R"}
        ], key=lambda row: row["path"])
        self.report = {
            "schema_version": 1, "status": "passed", "inputs_unchanged": True,
            "runtime_image": IMAGE, "reference": self.reference,
            "candidate_r_sha256": {path: digest(candidate[path]) for path in acceptance.R_WORKFLOWS},
            "comparison": {"table_bytes": "exact", "unrounded_r": "identical", "pdf_pixels": "exact", "pdf_metadata": "excluded"},
            "cases": [{"case": name, "workflow": workflow, "status": "passed", "unrounded_r_values": "identical",
                       "table_sha256": {"result.tsv": "c" * 64},
                       "plots": {"plot.pdf": {"pages": 1, "raster_dpi": 36, "page_sha256": {"page-1.ppm": "d" * 64}}}}
                      for name, workflow in acceptance.R_CASES.items()],
            "helpers": [{"path": path, "status": "passed", "sha256": digest(candidate[path])}
                        for path in sorted(acceptance.R_HELPERS)],
        }
        self.record["scientific_equivalence"].update(
            report_path="scientific/r-equivalence/artifacts/r-equivalence.json", runtime_image=IMAGE)
        self.manifest = {"version": "0.8.9", "source_commit": COMMIT, "runtime_image": IMAGE}
        self.write_report()

    def write_report(self):
        raw = json.dumps(self.report).encode()
        archive = self.directory / "qualification-evidence.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(self.record["scientific_equivalence"]["report_path"], raw)
        self.record["qualification_evidence_sha256"] = digest(archive.read_bytes())
        self.record["scientific_equivalence"]["report_sha256"] = digest(raw)

    def read_source(self, commit, path):
        return self.sources[commit][path]

    def verify(self):
        return acceptance.verify_scientific_equivalence(self.record, self.directory, self.manifest, self.read_source)

    def test_new_template_is_pending_and_incomplete(self):
        record = acceptance.template(self.installer_set, 123)
        self.assertEqual(record["schema_version"], 6)
        self.assertEqual(record["decision"], "pending")
        with self.assertRaises(ValueError):
            acceptance.validate(record, "0.8.9", COMMIT, 123, self.installer_set)

    def test_exact_sources_build_and_scientific_evidence_pass_without_domain_claim(self):
        acceptance.validate(self.record, "0.8.9", COMMIT, 123, self.installer_set)
        baseline = acceptance.verify_baseline(self.record, self.read_source)
        self.assertFalse(baseline["vendored_r_sources_unchanged"])
        self.assertFalse(baseline["operational_equivalence_claimed"])
        checked = self.verify()
        self.assertEqual(checked["cases_verified"], 13)
        self.assertEqual(checked["focused_scripts_verified"], 4)
        self.assertFalse(checked["domain_validation_claimed"])

    def test_old_schema_still_rejects_revised_r_even_with_reviewed_hashes(self):
        record = copy.deepcopy(self.record)
        record.update(schema_version=5)
        del record["scientific_equivalence"]
        record["observed_baseline"]["source_comparison_scope"] = acceptance.MULTIPLATFORM_SOURCE_SCOPE
        with self.assertRaisesRegex(ValueError, "protected vendored R"):
            acceptance.validate(record, "0.8.9", COMMIT, 123)

    def test_new_schema_does_not_allow_unknown_scientific_sources(self):
        self.record["reviewed_source_changes"].insert(0, {
            "path": "scientific/vendor/new.R", "before_sha256": None, "after_sha256": "f" * 64,
        })
        with self.assertRaisesRegex(ValueError, "Only known scientific"):
            acceptance.validate(self.record, "0.8.9", COMMIT, 123)

    def test_report_cannot_be_relabelled_as_different_package_source_or_image(self):
        for key, value in (("version", "0.8.10"), ("source_commit", "b" * 40), ("runtime_image", "sha256:" + "c" * 64)):
            original = self.manifest[key]
            self.manifest[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "packaged source and image"):
                self.verify()
            self.manifest[key] = original

    def test_accepted_archive_and_report_hashes_are_independently_enforced(self):
        self.record["qualification_evidence_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "archive differs"):
            self.verify()
        self.write_report()
        self.record["scientific_equivalence"]["report_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "report bytes differ"):
            self.verify()

    def test_success_status_cannot_hide_failed_or_incomplete_comparisons(self):
        original = copy.deepcopy(self.report)
        mutations = [
            lambda r: r.update(status="failed"), lambda r: r.update(inputs_unchanged=False),
            lambda r: r.update(runtime_image="sha256:" + "f" * 64),
            lambda r: r["comparison"].update(unrounded_r="rounded"),
            lambda r: r["cases"].pop(), lambda r: r["cases"].append(r["cases"][0]),
            lambda r: r["cases"][0].update(status="failed"),
            lambda r: r["cases"][0].update(unrounded_r_values="not-compared"),
            lambda r: r["cases"][0].update(table_sha256={}),
            lambda r: r["cases"][0]["plots"]["plot.pdf"].update(page_sha256={}),
            lambda r: [case.update(plots={}) for case in r["cases"]],
            lambda r: r["helpers"].pop(), lambda r: r["helpers"][0].update(status="failed"),
            lambda r: r["helpers"][0].update(sha256="f" * 64),
            lambda r: r["candidate_r_sha256"].update({next(iter(acceptance.R_WORKFLOWS)): "f" * 64}),
            lambda r: r["reference"].update(source_commit="f" * 40),
            lambda r: r["reference"]["files"][0].update(sha256="f" * 64),
        ]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(original)
            mutate(self.report)
            self.write_report()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_frozen_reference_and_scientific_manifest_are_checked_against_git(self):
        paths = [acceptance.R_REFERENCE_ROOT + "/" + next(iter(acceptance.R_WORKFLOWS)),
                 "scientific/SHA256SUMS", acceptance.R_REFERENCE_ROOT + "/manifest.json"]
        for path in paths:
            original = self.sources[COMMIT][path]
            self.sources[COMMIT][path] = b"altered"
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify()
            self.sources[COMMIT][path] = original

    def test_report_locator_is_safe_and_exact(self):
        for path in ("../r-equivalence.json", "/scientific/r-equivalence.json", "scientific/../r-equivalence.json",
                     "scientific/a\\r-equivalence.json", "other/r-equivalence.json", "scientific/summary.json"):
            self.record["scientific_equivalence"]["report_path"] = path
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "retained qualification"):
                self.verify()


if __name__ == "__main__":
    unittest.main()
