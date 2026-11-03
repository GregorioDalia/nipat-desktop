import csv
import json
from pathlib import Path
import tempfile
import unittest

from nipat.run_report import sample_rows, write_run_report


class RunReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.metadata = {
            "schema_version": 1, "run_name": "Prova <&>", "workflow": "dnp-call", "status": "failed",
            "error": "Comando terminato con codice 137; causa non confermata",
            "source": {"nipat_version": "0.8.2"},
            "parameters": {"parallel": False, "sample_mapping": [
                {"sample_id": "sample_0001", "original_path": r'C:\ricerca\mamma <&> è.bam',
                 "container_path": "/workspace/inputs/bams/sample_0001.bam"},
                {"sample_id": "sample_0002", "original_path": "/input/=SUM(A1).bam"},
            ]},
            "resource_snapshot": {
                "backend": "wsl", "host": {"memory_mib": 32768, "cpus": 16},
                "runtime": {"configured": {"memory_mib": 8192, "cpus": 4},
                            "effective": {"memory_mib": 7800, "cpus": 4}},
                "container": {"memory_mib": 4096, "cpus": 2}, "warnings": [],
            },
            "commands": [{"container_diagnostics": {"diagnosis": {
                "kind": "exit-137-unconfirmed", "message": "Causa del codice 137 non confermata."}}}],
        }

    def save(self):
        (self.root / "run.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_failed_run_keeps_readable_names_status_resources_and_diagnosis(self):
        self.save()
        report = write_run_report(self.root)
        html = (self.root / report["summary"]).read_text(encoding="utf-8")
        self.assertIn("Non riuscita", html)
        self.assertIn("mamma &lt;&amp;&gt; è.bam", html)
        self.assertNotIn("mamma <&>", html)
        self.assertIn("sample_0001", html)
        self.assertIn("32 GiB", html)
        self.assertIn("8 GiB", html)
        self.assertIn("4 GiB", html)
        self.assertIn("Causa del codice 137 non confermata.", html)
        self.assertIn("default-src 'none'", html)
        with (self.root / report["sample_map"]).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(rows[0]["original_name"], "mamma <&> è.bam")
        self.assertEqual(rows[1]["original_name"], "'=SUM(A1).bam")
        self.assertIn("=SUM(A1).bam", html)

    def test_existing_files_and_linked_metadata_are_not_replaced_or_followed(self):
        self.save()
        (self.root / "sample-map.tsv").write_text("existing evidence")
        with self.assertRaises(FileExistsError):
            write_run_report(self.root)
        self.assertEqual((self.root / "sample-map.tsv").read_text(), "existing evidence")
        self.assertFalse((self.root / "run-report.html").exists())
        (self.root / "sample-map.tsv").unlink()
        (self.root / "run.json").rename(self.root / "elsewhere.json")
        (self.root / "run.json").symlink_to(self.root / "elsewhere.json")
        with self.assertRaises(ValueError):
            write_run_report(self.root)

    def test_workflow_report_links_only_owned_presentation_and_records_phase_failures(self):
        self.save()
        workflow = self.root / "output/workflow"
        (workflow / "presentation").mkdir(parents=True)
        (workflow / "presentation/index.html").write_text("presentation")
        (workflow / "workflow-state.json").write_text(json.dumps({"steps": [
            {"id": "dnp", "workflow": "dnp-call", "status": "succeeded"},
            {"id": "cpi", "workflow": "cpi", "status": "blocked"},
        ]}))
        write_run_report(self.root)
        html = (self.root / "run-report.html").read_text()
        self.assertIn("output/workflow/presentation/index.html", html)
        self.assertIn("Non avviata", html)

    def test_legacy_metadata_remains_readable_and_has_no_invented_sample_identity(self):
        self.metadata["parameters"] = {"bam": "/old/one.bam"}
        self.metadata["status"] = "planned"
        self.save()
        self.assertEqual(sample_rows(self.metadata), [])
        write_run_report(self.root)
        html = (self.root / "run-report.html").read_text()
        self.assertIn("Pianificata: analisi non eseguita", html)
        self.assertIn("non registra una corrispondenza", html)


if __name__ == "__main__":
    unittest.main()
