"""Publication requires both versioned science gates for the exact five-module build."""

import copy
import csv
import io
import json
from pathlib import Path
import unittest
import zipfile

import test_revised_r_acceptance as legacy_tests
from test_revised_r_acceptance import acceptance, COMMIT, IMAGE, digest

ROOT = Path(__file__).resolve().parents[2]


class FiveModuleAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.legacy = legacy_tests.RevisedRAcceptanceTests()
        self.legacy.setUp()
        self.addCleanup(self.legacy.doCleanups)
        self.legacy.snp2_report()
        self.record = self.legacy.record
        self.manifest = self.legacy.manifest
        self.record.update(schema_version=7, version="0.8.50")
        self.manifest["version"] = "0.8.50"
        self.record["observed_baseline"]["source_comparison_scope"] = acceptance.FIVE_MODULE_SOURCE_SCOPE
        self.record["scientific_analysis_qualification"] = {
            "reference_source_commit": acceptance.ANALYSIS_REFERENCE_COMMIT,
            "report_path": "scientific/nipat-five-modules-check/artifacts/five-module-qualification.json",
            "report_sha256": "e" * 64, "runtime_image": IMAGE,
        }
        sources = self.legacy.sources[COMMIT]
        for path in ["scripts/verify_five_modules.py", acceptance.CPIN_SOURCE,
                *("src/nipat_scientific/" + name for name in acceptance.ANALYSIS_HELPERS),
                *acceptance.CALLER_SUPPORTING_SOURCES]:
            sources[path] = (ROOT / path).read_bytes()
        for path in (ROOT / acceptance.ANALYSIS_REFERENCE_ROOT).rglob("*"):
            if path.is_file():
                sources[path.relative_to(ROOT).as_posix()] = path.read_bytes()
        fixtures = {}
        for path in (ROOT / "tests/fixtures/five_modules").rglob("*"):
            if path.is_file():
                relative = path.relative_to(ROOT).as_posix()
                sources[relative] = path.read_bytes()
                fixtures[path.relative_to(ROOT / "tests/fixtures/five_modules").as_posix()] = digest(path.read_bytes())
        caller = self.legacy.report
        caller["candidate_r_sha256"] = {path: value for path, value in caller["candidate_r_sha256"].items()
                                        if acceptance.R_WORKFLOWS[path] in {"dnp-call", "snp-call"}}
        caller["cases"] = [case for case in caller["cases"] if case["workflow"] in {"dnp-call", "snp-call"}]
        caller["helpers"] = [helper for helper in caller["helpers"]
            if not helper["path"].startswith(("tests/r_optimization/cpi/", "tests/r_optimization/contamination/"))]
        caller["supporting_source_sha256"] = {path: digest(sources[path]) for path in acceptance.CALLER_SUPPORTING_SOURCES}
        sources["scientific/SHA256SUMS"] = "".join(f"{digest(sources[path])}  {path.removeprefix('scientific/')}\n"
            for path in sorted(set(acceptance.R_WORKFLOWS) | {acceptance.CPIN_SOURCE})).encode()
        installed = {"scientific/vendor/NEWPAT/" + name: "scientific/vendor/NEWPAT/" + name
                     for name in acceptance.ANALYSIS_REFERENCE_SHA256}
        installed.update({"lib/nipat_scientific/" + name: "src/nipat_scientific/" + name
                          for name in acceptance.ANALYSIS_HELPERS})
        self.report = {
            "schema_version": 2, "status": "passed", "full_batch_matrix": True,
            "inputs_unchanged": True, "source_unchanged": True,
            "runtime": {"kind": "installed-image", "image_id": IMAGE,
                        "candidate_and_helper_sha256": {key: digest(sources[path]) for key, path in installed.items()}},
            "verification_script_sha256": digest(sources["scripts/verify_five_modules.py"]),
            "upstream_reference": json.loads(sources[acceptance.ANALYSIS_REFERENCE_ROOT + "/manifest.json"]),
            "fixture_sha256": fixtures, "results": [], "reference_comparisons": [],
            "reference_comparison_evidence": {},
        }
        registry = json.loads(sources["src/nipat_scientific/settings_data.json"])["workflows"]
        for name, (workflow, marker, candidate, size, mode, cap, variant) in acceptance.analysis_expected_cases().items():
            settings = None
            if candidate:
                params = {key: value["default"] for key, value in registry[workflow]["parameters"].items()}
                params[{"cpi": "min_fetal_reads", "cpin": "min_child_reads", "contamination": "include_zero"}[workflow]] = (
                    variant["include_zero"] if workflow == "contamination" else variant["minimum"])
                settings = {"schema_version": 1, "workflow": workflow, "parameters": params,
                            "constants": registry[workflow]["constants"]}
            self.report["results"].append({"name": name, "status": "passed", "inputs_unchanged": True,
                "workflow": workflow, "marker": marker, "candidate": candidate, "batch_size": size,
                "mode": mode, "max_workers": cap, "variant": variant, "rows": [{"result": "0.1"}],
                "input_sha256": {"input.tsv": "a" * 64}, "output_sha256": {"result.tsv": "b" * 64},
                "log_sha256": {"stdout.log": "c" * 64}, "summary_sha256": "d" * 64,
                "scientific_settings": settings, "settings_match": True if candidate else None,
                "worker_evidence": {"max_planned_workers": 1 if mode == "serial" else 2,
                                    "observed_peak_workers": 1, "completed_worker_tasks": size,
                                    "observed_child_pids": [] if mode == "serial" else [123, 456]} if candidate else None})
            if name.endswith("-candidate"):
                key = name.removesuffix("-candidate")
                self.report["reference_comparisons"].append(key)
                self.report["reference_comparison_evidence"][key] = {
                    "equal": True, "candidate_sha256": "d" * 64, "reference_sha256": "d" * 64}
        self.summaries = {}
        for case in self.report["results"]:
            marker, workflow, size = case["marker"], case["workflow"], case["batch_size"]
            if workflow == "cpin":
                columns = ["Trio", "Marker_type", "Analysis", "N_sites", "N_heterozygous_child_sites",
                           "N_homozygous_child", "Matching_sites", "Mismatching_sites", "Log10_CPI", "CPI",
                           "Error_constant", "Min_child_reads"]
                trios = ([f"MotherM-FatherF-ChildC_{marker}s"] if size == 1 else
                         [f"MotherM{i}-FatherF{i}-ChildC{i}_{marker}s" for i in range(1, size + 1)])
                rows = [{**dict.fromkeys(columns, "0.1"), "Trio": trio, "Marker_type": marker, "Analysis": selection}
                        for trio in trios for selection in ("heterozygous_child_sites", "all_compatible_sites")]
            elif workflow == "cpi":
                columns = ["Pair", "N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw",
                           "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI", "Median_logCPI",
                           "Mean_logCPI", "CPI_medianFF", "Error_constant"]
                pairs = ([f"MotherM-FatherF_{marker}s", f"MotherN-FatherN_{marker}s"] if size == 1 else
                         [f"MotherM{i}-FatherF{i}_{marker}s" for i in range(1, size + 1)])
                rows = [{**dict.fromkeys(columns, "0.1"), "Pair": pair} for pair in pairs]
            else:
                columns = ["individuo", "informative_sites", "mean_contamination", "sd_contamination"]
                rows = [{**dict.fromkeys(columns, "0.1"), "individuo": f"Sample{i}"} for i in range(1, size + 1)]
            case["rows"] = rows
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=columns, delimiter="," if workflow == "cpi" else "\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            raw = stream.getvalue().encode()
            filename = {"cpin": "Summary_Postnatal_CPI.txt", "cpi": "Summary_FetalFraction_CPI.csv",
                        "contamination": "contamination_summary.txt"}[workflow]
            self.summaries[case["name"] + "/output/" + filename] = raw
            case["summary_sha256"] = digest(raw)
            case["output_sha256"] = {filename: digest(raw)}
        for name, pair in self.report["reference_comparison_evidence"].items():
            for kind in ("candidate", "reference"):
                pair[kind + "_sha256"] = next(case["summary_sha256"] for case in self.report["results"]
                                             if case["name"] == name + "-" + kind)
        self.write_reports()

    def write_reports(self):
        archive = self.legacy.directory / "qualification-evidence.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            base = Path(self.record["scientific_analysis_qualification"]["report_path"]).parent
            for path, raw in self.summaries.items():
                handle.writestr((base / path).as_posix(), raw)
            for field, report in (("scientific_equivalence", self.legacy.report),
                                  ("scientific_analysis_qualification", self.report)):
                raw = json.dumps(report).encode()
                self.record[field]["report_sha256"] = digest(raw)
                handle.writestr(self.record[field]["report_path"], raw)
        self.record["qualification_evidence_sha256"] = digest(archive.read_bytes())

    def verify(self):
        return self.legacy.verify()

    def test_five_modules_require_separate_model_evidence_and_preserve_domain_limits(self):
        checked = self.verify()
        self.assertEqual(checked["cases_verified"], 17)
        analysis = checked["scientific_analysis_qualification"]
        self.assertEqual(analysis["executions_verified"], 86)
        self.assertEqual(analysis["batch_executions_verified"], 54)
        self.assertEqual(analysis["reference_comparisons_verified"], 16)
        self.assertFalse(analysis["domain_validation_claimed"])

    def test_legacy_schema_cannot_qualify_five_modules(self):
        self.record["schema_version"] = 6
        with self.assertRaisesRegex(ValueError, "schema 7"):
            self.verify()

    def test_new_template_preserves_pending_state_and_separate_reference_ids(self):
        installers = dict(self.legacy.installer_set, version="0.8.50")
        record = acceptance.template(installers, 123)
        self.assertEqual(record["schema_version"], 7)
        self.assertEqual(record["decision"], "pending")
        self.assertEqual(record["scientific_analysis_qualification"]["reference_source_commit"],
                         acceptance.ANALYSIS_REFERENCE_COMMIT)
        self.assertEqual(record["scientific_equivalence"]["reference_source_commit"], acceptance.R_REFERENCE_COMMIT)

    def test_cpin_review_allowed_only_in_five_module_contract(self):
        for version, wanted in (("0.8.35", False), ("0.8.50", True)):
            self.assertEqual(acceptance.reviewable_path(acceptance.CPIN_SOURCE, reliability=True,
                multiplatform=True, revised_r=True, version=version), wanted)
        self.assertFalse(acceptance.reviewable_path("scientific/vendor/NEWPAT/new.R", reliability=True,
            multiplatform=True, revised_r=True, version="0.8.50"))

    def test_only_known_development_provenance_is_reviewable_from_schema7(self):
        path = "docs/validation/0.8.50-development.json"
        for version, wanted in (("0.8.35", False), ("0.8.49", False), ("0.8.50", True)):
            self.assertEqual(acceptance.reviewable_path(path, reliability=True, multiplatform=True,
                revised_r=True, version=version), wanted)
        self.assertFalse(acceptance.reviewable_path(path, reliability=True, multiplatform=True,
            revised_r=False, version="0.8.50"))
        self.assertFalse(acceptance.reviewable_path("docs/validation/other.json", reliability=True,
            multiplatform=True, revised_r=True, version="0.8.50"))

    def test_rejects_incomplete_or_relabelled_matrix_and_sources(self):
        original = copy.deepcopy(self.report)
        mutations = [lambda r: r.update(schema_version=1), lambda r: r.update(status="failed"),
            lambda r: r.update(inputs_unchanged=False), lambda r: r.update(source_unchanged=False),
            lambda r: r.update(full_batch_matrix=False), lambda r: r["results"].pop(),
            lambda r: r["results"].append(r["results"][0]),
            lambda r: r["runtime"].update(kind="local-R"),
            lambda r: r["runtime"].update(image_id="sha256:" + "f" * 64),
            lambda r: r["runtime"]["candidate_and_helper_sha256"].pop(acceptance.CPIN_SOURCE),
            lambda r: r.update(verification_script_sha256="f" * 64),
            lambda r: r["upstream_reference"].update(upstream_commit="f" * 40),
            lambda r: r["fixture_sha256"].pop("SNP/cpin/ChildC.txt"),
            lambda r: r["fixture_sha256"].update({"SNP/cpin/ChildC.txt": "f" * 64}),
            lambda r: r["reference_comparisons"].pop(),
            lambda r: r["reference_comparison_evidence"]["SNP-cpin-0"].update(equal=False),
            lambda r: r["reference_comparison_evidence"]["SNP-cpin-0"].update(candidate_sha256="f" * 64),
        ]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(original)
            mutate(self.report)
            self.write_reports()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_numeric_comparisons_reject_false_self_attested_equality(self):
        with self.assertRaisesRegex(ValueError, "numerical results differ"):
            acceptance.compare_analysis_rows([{"CPI": "9999999999999"}], [{"CPI": "-1"}])
        self.assertFalse(acceptance.same_scientific_values({"value": True}, {"value": 1}))
        self.assertTrue(acceptance.same_scientific_values({"value": 1.0}, {"value": 1}))

    def test_rejects_unverified_settings_inputs_output_and_parallel_workers(self):
        original = copy.deepcopy(self.report)
        mutations = [lambda c: c.update(status="failed"), lambda c: c.update(inputs_unchanged=False),
            lambda c: c.update(input_sha256={}), lambda c: c.update(output_sha256={}),
            lambda c: c.update(settings_match=False), lambda c: c.update(scientific_settings={}),
            lambda c: c["rows"][0].update(CPI="999999"),
            lambda c: c.update(batch_size=True),
            lambda c: c["scientific_settings"]["constants"].update({"homozygous_transmission": {"value": True}}),
            lambda c: c["variant"].update(minimum=99),
            lambda c: c["worker_evidence"].update(max_planned_workers=3),
            lambda c: c["worker_evidence"].update(observed_peak_workers=3),
            lambda c: c["worker_evidence"].update(completed_worker_tasks=0),
            lambda c: c["worker_evidence"].update(observed_child_pids=[123]),
        ]
        for index, mutate in enumerate(mutations):
            self.report = copy.deepcopy(original)
            case = next(c for c in self.report["results"] if c["name"] == "SNP-cpin-batch5-auto-cap2")
            mutate(case)
            self.write_reports()
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()


if __name__ == "__main__":
    unittest.main()
