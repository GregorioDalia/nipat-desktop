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
                       "plots": {f"plot{number}.pdf": {"pages": 1, "raster_dpi": 36, "page_sha256": {"page-1.ppm": "d" * 64}}
                                 for number in range(acceptance.R_REQUIRED_PDFS.get(name, 0))}}
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

    def audited_report(self):
        self.record["version"] = self.manifest["version"] = "0.8.20"
        for name, workflow in acceptance.R_AUDIT_CASES.items():
            # Real 0.8.5 oracle: four plots per sample and two shared plots.
            # The prior five-per-BAM assumption incorrectly rejected 3/6 BAM.
            plot_count = {"dnp-multi-blocks-2": 10, "dnp-multi-blocks-3": 14,
                          "dnp-multi-blocks-6": 26}.get(name, 5)
            case = {"case": name, "workflow": workflow, "status": "passed", "unrounded_r_values": "identical",
                    "table_sha256": {"result.tsv": "c" * 64},
                    "plots": {f"plot{number}.pdf": {"pages": 1, "raster_dpi": 36,
                              "page_sha256": {"page-1.ppm": "d" * 64}} for number in range(plot_count)}}
            if name.startswith("dnp-multi-blocks-"):
                variants = {}
                for variant, cap in (("candidate", None), ("auto", None), ("manual-2", 2),
                                     ("manual-4", 4), ("manual-4-repeat", 4)):
                    serial = variant == "candidate"
                    variants[variant] = {key: copy.deepcopy(case[key]) for key in
                                         ("status", "unrounded_r_values", "table_sha256", "plots")}
                    variants[variant]["parallel_execution"] = {
                        "requested_mode": "serial" if serial else "auto", "requested_max_workers": cap,
                        "maximum_planned_workers": 1 if serial else (cap or 4),
                        "maximum_observed_child_workers": 0 if serial else 2,
                        "simultaneous_child_workers": not serial, "overlapping_workers_required": not serial,
                    }
                    if variant == "manual-4-repeat":
                        variants[variant]["deterministic_repeat_of"] = "manual-4"
                case["execution_variants"] = variants
            self.report["cases"].append(case)
        for path in sorted(acceptance.R_AUDIT_HELPERS):
            raw = ("test source " + path).encode()
            self.sources[COMMIT][path] = raw
            self.report["helpers"].append({"path": path, "status": "passed", "sha256": digest(raw)})
        self.write_report()

    def test_0820_requires_all_23_cases_and_11_focused_helpers(self):
        self.audited_report()
        checked = self.verify()
        self.assertEqual((checked["cases_verified"], checked["focused_scripts_verified"]), (23, 11))
        complete = copy.deepcopy(self.report)
        for field, identity, names in (("cases", "case", acceptance.R_AUDIT_CASES),
                                       ("helpers", "path", acceptance.R_AUDIT_HELPERS)):
            for name in names:
                self.report = copy.deepcopy(complete)
                self.report[field] = [item for item in self.report[field] if item[identity] != name]
                self.write_report()
                with self.subTest(missing=name), self.assertRaises(ValueError):
                    self.verify()

    def test_0820_requires_actual_bounded_multibam_parallelism_and_repeat(self):
        self.audited_report()
        complete = copy.deepcopy(self.report)
        mutations = [
            lambda c: c["execution_variants"].pop("manual-2"),
            lambda c: c["execution_variants"]["auto"]["parallel_execution"].update(maximum_observed_child_workers=0),
            lambda c: c["execution_variants"]["manual-2"]["parallel_execution"].update(maximum_observed_child_workers=3),
            lambda c: c["execution_variants"]["candidate"]["parallel_execution"].update(maximum_observed_child_workers=1),
            lambda c: c["execution_variants"]["manual-4-repeat"].pop("deterministic_repeat_of"),
            lambda c: c["execution_variants"]["auto"].update(table_sha256={"result.tsv": "e" * 64}),
            lambda c: c.update(plots={}),
        ]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(complete)
            case = next(item for item in self.report["cases"] if item["case"] == "dnp-multi-blocks-6")
            mutate(case)
            self.write_report()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_0820_requires_every_expected_oracle_plot_for_each_multibam_fixture(self):
        self.audited_report()
        complete = copy.deepcopy(self.report)
        for name, expected_count in (("dnp-multi-blocks-2", 10), ("dnp-multi-blocks-3", 14),
                                     ("dnp-multi-blocks-6", 26)):
            self.report = copy.deepcopy(complete)
            case = next(item for item in self.report["cases"] if item["case"] == name)
            self.assertEqual(len(case["plots"]), expected_count)
            self.write_report()
            self.verify()
            case["plots"].pop(next(iter(case["plots"])))
            # Even mutually consistent serial/parallel reports must retain all
            # plots expected from the known fixture and immutable oracle.
            for variant in case["execution_variants"].values():
                variant["plots"] = copy.deepcopy(case["plots"])
            self.write_report()
            with self.subTest(case=name), self.assertRaisesRegex(ValueError, "Multi-BAM PDF comparisons are incomplete"):
                self.verify()

    def snp2_report(self):
        self.audited_report()
        self.record["version"] = self.manifest["version"] = "0.8.30"
        self.report["snp_reference"] = copy.deepcopy(acceptance.SNP2_REFERENCE)
        frozen = Path(__file__).resolve().parents[2] / acceptance.SNP2_REFERENCE["frozen_path"]
        self.sources[COMMIT][acceptance.SNP2_REFERENCE["frozen_path"]] = frozen.read_bytes()
        self.report["comparison"].update(pdf_pixels="candidate-serial-vs-parallel",
                                         pdf_reference="structural-and-reviewed-presentation")
        self.sources[COMMIT][acceptance.PRESENTATION_SOURCE] = b"candidate plotting source"
        self.report["supporting_source_sha256"] = {
            acceptance.PRESENTATION_SOURCE: digest(self.sources[COMMIT][acceptance.PRESENTATION_SOURCE]),
        }
        for name, workflow in acceptance.SNP2_CASES.items():
            self.report["cases"].append({"case": name, "workflow": workflow, "status": "passed",
                "unrounded_r_values": "identical", "table_sha256": {"result.tsv": "c" * 64}, "plots": {}})
        for case in self.report["cases"]:
            case["scientific_reference"] = "SNPcall 2.0" if case["workflow"] == "snp-call" else "NIPAT 0.8.5"
            case["plots_comparison"] = "renderable-and-bounded"
            for plot in case["plots"].values():
                plot["page_size_points"] = [720, 432]
            if "execution_variants" not in case:
                compared = {key: copy.deepcopy(case[key]) for key in
                            ("status", "unrounded_r_values", "table_sha256", "plots")}
                case["execution_variants"] = {"candidate": compared}
                if case["plots"]:
                    case["execution_variants"]["parallel"] = copy.deepcopy(compared)
            for name, variant in case["execution_variants"].items():
                variant["plots"] = copy.deepcopy(case["plots"])
                variant["plots_comparison"] = ("renderable-and-bounded" if name == "candidate"
                                                else "candidate-serial-exact-pixels")
                variant["execution_configuration"] = {
                    "requested_mode": "serial" if name == "candidate" else "auto",
                    "requested_max_workers": None if name == "candidate" else 2,
                }
        helper = acceptance.PRESENTATION_HELPER
        self.sources[COMMIT][helper] = b"histogram boundaries and PDF presentation checks"
        self.report["helpers"].append({"path": helper, "status": "passed", "sha256": digest(self.sources[COMMIT][helper])})
        self.write_report()

    def test_0830_requires_both_scientific_references_and_corrected_presentation(self):
        self.snp2_report()
        checked = self.verify()
        self.assertEqual((checked["cases_verified"], checked["focused_scripts_verified"]), (26, 12))
        self.assertEqual(checked["snp_reference"], acceptance.SNP2_REFERENCE)
        self.assertFalse(checked["domain_validation_claimed"])

    def test_0830_rejects_missing_or_relabelled_scientific_references(self):
        self.snp2_report()
        complete = copy.deepcopy(self.report)
        mutations = [lambda r: r.pop("snp_reference"),
                     lambda r: r["snp_reference"].update(source_commit="f" * 40),
                     lambda r: r["snp_reference"].update(sha256="f" * 64),
                     lambda r: r["snp_reference"].update(repository="other/NEWPAT"),
                     lambda r: r["cases"][0].pop("scientific_reference"),
                     lambda r: r["cases"][0].update(scientific_reference="SNPcall 2.0")]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(complete)
            mutate(self.report)
            self.write_report()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()
        self.report = copy.deepcopy(complete)
        case = next(item for item in self.report["cases"] if item["workflow"] == "snp-call")
        case["scientific_reference"] = "NIPAT 0.8.5"
        self.write_report()
        with self.assertRaisesRegex(ValueError, "wrong algorithm reference"):
            self.verify()

    def test_0830_frozen_snp_reference_is_independently_pinned(self):
        self.snp2_report()
        path = acceptance.SNP2_REFERENCE["frozen_path"]
        self.sources[COMMIT][path] += b"\n# changed scientific oracle\n"
        with self.assertRaisesRegex(ValueError, "pinned upstream bytes"):
            self.verify()
        # A candidate cannot bless its own altered oracle by updating the report.
        self.report["snp_reference"]["sha256"] = digest(self.sources[COMMIT][path])
        self.write_report()
        with self.assertRaisesRegex(ValueError, "immutable SNPcall 2.0"):
            self.verify()

    def test_0830_requires_all_new_cases_and_presentation_helper(self):
        self.snp2_report()
        complete = copy.deepcopy(self.report)
        for field, identity, names in (("cases", "case", acceptance.SNP2_CASES),
                                       ("helpers", "path", [acceptance.PRESENTATION_HELPER])):
            for name in names:
                self.report = copy.deepcopy(complete)
                self.report[field] = [item for item in self.report[field] if item[identity] != name]
                self.write_report()
                with self.subTest(missing=name), self.assertRaises(ValueError):
                    self.verify()

    def test_0830_rejects_false_or_incomplete_pdf_comparisons(self):
        self.snp2_report()
        complete = copy.deepcopy(self.report)
        mutations = [lambda c: c.pop("execution_variants"),
                     lambda c: c["execution_variants"].pop("parallel"),
                     lambda c: c.pop("plots_comparison"),
                     lambda c: c["execution_variants"]["parallel"].update(plots_comparison="exact-to-0.8.5"),
                     lambda c: c["execution_variants"]["parallel"].update(plots={}),
                     lambda c: c["execution_variants"]["parallel"].update(table_sha256={"result.tsv": "e" * 64}),
                     lambda c: c["execution_variants"]["candidate"].update(plots_comparison="not-compared"),
                     lambda c: c["execution_variants"]["parallel"].pop("execution_configuration"),
                     lambda c: c["execution_variants"]["parallel"]["execution_configuration"].update(requested_mode="serial"),
                     lambda c: c["plots"]["plot0.pdf"].update(page_size_points=[720, 10000])]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(complete)
            mutate(self.report["cases"][0])
            self.write_report()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_0830_cannot_claim_old_pixel_oracle_or_unbound_plotting_source(self):
        self.snp2_report()
        complete = copy.deepcopy(self.report)
        for mutation in (lambda r: r["comparison"].update(pdf_pixels="exact"),
                         lambda r: r["comparison"].pop("pdf_reference"),
                         lambda r: r.pop("supporting_source_sha256"),
                         lambda r: r["supporting_source_sha256"].update({acceptance.PRESENTATION_SOURCE: "e" * 64})):
            self.report = copy.deepcopy(complete)
            mutation(self.report)
            self.write_report()
            with self.assertRaises(ValueError):
                self.verify()

    def test_new_presentation_policy_does_not_relax_0820_acceptance(self):
        self.snp2_report()
        self.record["version"] = self.manifest["version"] = "0.8.20"
        with self.assertRaisesRegex(ValueError, "exact tables, unrounded R values and PDF pixels"):
            self.verify()

    def test_0830_prereleases_cannot_downgrade_the_new_scientific_contract(self):
        self.snp2_report()
        self.record["version"] = self.manifest["version"] = "0.8.30rc1"
        self.verify()
        self.report["cases"] = [item for item in self.report["cases"] if item["case"] != "dnp-multi-blocks-6"]
        self.write_report()
        with self.assertRaisesRegex(ValueError, "Required scientific differential cases"):
            self.verify()

    def test_old_schema_still_rejects_revised_r_even_with_reviewed_hashes(self):
        record = copy.deepcopy(self.record)
        record.update(schema_version=5)
        del record["scientific_equivalence"]
        record["observed_baseline"]["source_comparison_scope"] = acceptance.MULTIPLATFORM_SOURCE_SCOPE
        with self.assertRaisesRegex(ValueError, "require scientific equivalence acceptance schema 6"):
            acceptance.validate(record, "0.8.9", COMMIT, 123)

    def test_changing_baseline_to_candidate_cannot_downgrade_scientific_acceptance(self):
        self.record.update(schema_version=5, reviewed_source_changes=[])
        del self.record["scientific_equivalence"]
        self.record["observed_baseline"].update(source_commit=COMMIT,
            source_comparison_scope=acceptance.MULTIPLATFORM_SOURCE_SCOPE)
        with self.assertRaisesRegex(ValueError, "require scientific equivalence acceptance schema 6"):
            acceptance.validate(self.record, "0.8.9", COMMIT, 123)

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
            lambda r: r["cases"][0]["plots"]["plot0.pdf"].update(page_sha256={}),
            lambda r: [case.update(plots={}) for case in r["cases"]],
            lambda r: r["cases"][0]["plots"].pop("plot0.pdf"),
            lambda r: r["cases"][1].update(plots={}),
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
