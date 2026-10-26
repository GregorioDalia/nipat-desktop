import importlib.util
import csv
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "linux_installation_check", Path(__file__).resolve().parents[1] / "scripts/verify_linux_installer.py",
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class LinuxInstallationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = {
            "version": "0.6.0", "source_commit": "1" * 40,
            "runtime_image": "sha256:" + "2" * 64,
            "assets": {"scientific_image": {"sha256": "3" * 64}},
        }
        self.state = {
            "schema_version": 1, "phase": "ready", "channel": "desktop",
            "version": "0.6.0", "source_commit": "1" * 40,
            "installer_manifest_sha256": "4" * 64,
            "runtime_archive_sha256": "3" * 64,
            "source_runtime_image": "sha256:" + "2" * 64,
            # Different storage drivers may resolve the same archive to different IDs.
            "resolved_runtime_image": "sha256:" + "5" * 64,
        }

    def test_ready_state_requires_exact_archive_and_source_binding(self):
        self.assertEqual(check.check_state(self.state, self.manifest, "4" * 64),
                         "sha256:" + "5" * 64)
        for name, value in (
            ("phase", "failed"), ("channel", "stable"), ("channel", "preview-0.5"),
            ("version", "0.4.1"),
            ("source_commit", "0" * 40), ("installer_manifest_sha256", "0" * 64),
            ("runtime_archive_sha256", "0" * 64),
            ("source_runtime_image", "sha256:" + "0" * 64),
            ("resolved_runtime_image", "mutable:tag"),
        ):
            with self.subTest(field=name), self.assertRaises(RuntimeError):
                check.check_state({**self.state, name: value}, self.manifest, "4" * 64)

    def test_plan_checks_are_required_for_07_without_reinterpreting_06_evidence(self):
        previous = set(check.checks_for_version("0.6.0"))
        current = set(check.checks_for_version("0.7.0a1"))
        self.assertEqual(current - previous, {"automatic_workflow_plan", "preferences_preserved"})
        self.assertEqual(set(check.checks_for_version("0.7.0")), current)
        for version in ("0.5.0a1", "0.8.0", "0.7.0dev1"):
            with self.subTest(version=version), self.assertRaises(RuntimeError):
                check.checks_for_version(version)

    def test_all_four_workflows_must_have_successful_run_records(self):
        for workflow in ("dnp-call", "snp-call", "contamination", "cpi"):
            directory = self.root / workflow
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps({
                "workflow": workflow, "status": "succeeded",
            }))
        uid = (self.root / "cpi/run.json").stat().st_uid
        check.check_workflows(self.root, uid)
        (self.root / "cpi/run.json").write_text(json.dumps({"workflow": "cpi", "status": "failed"}))
        with self.assertRaisesRegex(RuntimeError, "all four"):
            check.check_workflows(self.root, uid)

    def test_foreign_owned_result_is_rejected(self):
        for workflow in ("dnp-call", "snp-call", "contamination", "cpi"):
            directory = self.root / workflow
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps({
                "workflow": workflow, "status": "succeeded",
            }))
        wrong_uid = (self.root / "cpi/run.json").stat().st_uid + 1
        with self.assertRaisesRegex(RuntimeError, "owned by another"):
            check.check_workflows(self.root, wrong_uid)

    def test_snapshot_detects_changed_or_removed_user_data(self):
        path = self.root / "user result.txt"
        path.write_text("original")
        original = check.snapshot(self.root)
        path.write_text("changed")
        self.assertNotEqual(original, check.snapshot(self.root))
        path.unlink()
        self.assertNotEqual(original, check.snapshot(self.root))


class InstalledAutomaticPlanEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "installed-run"
        self.workflow = self.run / "output/workflow"
        self.workflow.mkdir(parents=True)
        self.fixture = Path(__file__).resolve().parent / "fixtures/dnp_engine"
        self.manifest = {"version": "0.7.0a1", "source_commit": "1" * 40}
        self.image = "sha256:" + "2" * 64
        self.sources = [self.root / "maternal.bam", self.root / "paternal.bam"]
        self.record = {
            "workflow": "dnp-contamination-cpi", "status": "succeeded", "bundled_workflow": "workflow-plan-with-snp",
            "source": {"role": "client", "nipat_version": "0.7.0a1", "release": {"source_git": {"commit": "1" * 40}}},
            "runtime": {"image_id": self.image, "engine": {"plan_execution": {
                "workflows": ["dnp-call", "snp-call", "contamination", "cpi"]}}},
            "commands": [{"argv": ["python3", "main.py", "execute-plan"]}],
            "parameters": {"sample_mapping": [{"original_path": str(path)} for path in self.sources]},
        }
        pair = {"id": "installed_pair", "mother": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0001"},
                "father": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0002"}}
        (self.workflow / "plan.json").write_text(json.dumps({"steps": [{"id": "cpi", "inputs": {"pairs": [pair]}}]}))
        order = ["dnp", "contamination", "cpi", "snp_0001", "snp_0002"]
        self.state = {"status": "succeeded", "execution_order": order,
                      "plan_sha256": check.sha256(self.workflow / "plan.json"), "steps": []}
        for name in order:
            self.state["steps"].append({"id": name, "status": "succeeded", "exit_code": 0,
                                        "log": f"steps/{name}/command.log", "artifacts": {}})
            self.artifact(f"steps/{name}/command.log", "executed\n")
        steps = {step["id"]: step for step in self.state["steps"]}
        expected = check.read_table(self.fixture / "expected.tsv")
        dnp = []
        for number, sample in enumerate(("A", "B"), 1):
            artifact = self.table(f"steps/dnp/output/table{sample}.txt", [row for row in expected if row["sample"] == sample])
            dnp.append({"sample": f"sample_{number:04d}", **artifact})
        steps["dnp"]["artifacts"]["dnp-tables"] = dnp
        contamination = steps["contamination"]["artifacts"]
        contamination["summary"] = self.table("steps/contamination/output/summary.txt", [
            {"individuo": f"table_{number:04d}", "informative_DNPs": "2", "mean_contamination": "0", "sd_contamination": "0"}
            for number in (1, 2)])
        contamination["contamination-tables"] = [self.table(f"steps/contamination/output/table{number}.txt", [
            {"pos1": str(position), "contamination": "0"} for position in (50, 230)]) for number in (1, 2)]
        cpi = steps["cpi"]["artifacts"]
        native = "Mothers0001-Fathers0002_DNPs"
        cpi["summary"] = self.table("steps/cpi/output/Summary_FetalFraction_CPI.csv", [{
            "Pair": native, "N_sites_mother": "0", "N_sites_father": "0",
            **dict.fromkeys(("Median_fetal_fraction_raw", "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI",
                             "Median_logCPI", "Mean_logCPI", "CPI_medianFF"), "NA"),
        }], delimiter=",")
        cpi["cpi-pairs"] = [{"pair": pair["id"], "native_pair": native, "mother": pair["mother"], "father": pair["father"],
                             "plot": self.artifact("steps/cpi/output/pair.pdf", "%PDF-1.7\n")}]
        cpi["combined-plot"] = self.artifact("steps/cpi/output/all.pdf", "%PDF-1.7\n")
        for number, counts in enumerate((((21, 0), (11, 10), (1, 20)), ((1, 20), (13, 8), (21, 0))), 1):
            name = f"snp_{number:04d}"
            step = steps[name]
            step["sample_mapping"] = {"sample": f"sample_{number:04d}", "mode": "bam"}
            step["artifacts"]["snp-tables"] = [{"sample": f"sample_{number:04d}", **self.table(f"steps/{name}/output/SNPcall_output.txt", [
                {"chr": "chrDnpSynthetic", "pos": str(position), "Reference": ref, "Alternative": alt,
                 "N_Reference": str(ref_count), "N_Alternative": str(alt_count), "N_Altro": "0", "total_count": "21", "ratio": str(ref_count / 21)}
                for (position, ref, alt), (ref_count, alt_count) in zip(((50, "A", "G"), (140, "T", "C"), (230, "G", "A")), counts)])}]
            step["preparation_exit_code"] = 0
            step["preparation_log"] = f"steps/{name}/preparation.log"
            self.artifact(step["preparation_log"], "samtools\n")
            step["artifacts"]["preparation"] = [
                {"kind": kind, **self.artifact(f"steps/{name}/work/{filename}", "intermediate\n")}
                for kind, filename in (("regions-bed", "snp_regions.bed"), ("pileup", "pileup.txt"))]

    def artifact(self, relative, text):
        path = self.workflow / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return {"path": relative, "sha256": check.sha256(path)}

    def table(self, relative, rows, delimiter="\t"):
        path = self.workflow / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rows)
        return {"path": relative, "sha256": check.sha256(path)}

    def verify(self):
        (self.run / "run.json").write_text(json.dumps(self.record), encoding="utf-8")
        (self.workflow / "workflow-state.json").write_text(json.dumps(self.state), encoding="utf-8")
        check.check_automatic_plan(self.run, self.fixture, self.manifest, self.image, self.sources)

    def test_complete_installed_plan_evidence_matches_expected_identity_and_numbers(self):
        self.verify()

    def test_successful_parent_does_not_hide_an_incomplete_scientific_step(self):
        self.state["steps"][-1]["status"] = "failed"
        with self.assertRaisesRegex(RuntimeError, "unsuccessful steps"):
            self.verify()

    def test_other_package_commit_or_runtime_cannot_satisfy_installed_check(self):
        self.record["source"]["release"]["source_git"]["commit"] = "9" * 40
        with self.assertRaisesRegex(RuntimeError, "tested package"):
            self.verify()
        self.record["source"]["release"]["source_git"]["commit"] = self.manifest["source_commit"]
        self.record["runtime"]["image_id"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(RuntimeError, "tested package"):
            self.verify()

    def test_changed_or_reassigned_snp_result_is_not_accepted(self):
        artifact = self.state["steps"][-1]["artifacts"]["snp-tables"][0]
        artifact["sample"] = "sample_0001"
        with self.assertRaisesRegex(RuntimeError, "SNP output mapping"):
            self.verify()
        artifact["sample"] = "sample_0002"
        path = self.workflow / artifact["path"]
        path.write_text(path.read_text().replace("\t13\t8\t", "\t12\t9\t"))
        artifact["sha256"] = check.sha256(path)
        with self.assertRaisesRegex(RuntimeError, "independent SAM oracle"):
            self.verify()

    def test_missing_or_replaced_artifact_fails_even_with_successful_status(self):
        artifact = self.state["steps"][-1]["artifacts"]["preparation"][0]
        path = self.workflow / artifact["path"]
        path.write_text("altered")
        with self.assertRaisesRegex(RuntimeError, "hash differs"):
            self.verify()
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
