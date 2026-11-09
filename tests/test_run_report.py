import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nipat.run_report import sample_rows, write_run_report


class RunReportTests(unittest.TestCase):
    def parallel_events(self, directory, *, label="dnp-blocks", workers=3):
        directory.mkdir(parents=True)
        base = {"schema_version": 1, "interface": "nipat-parallel-v1",
                "label": label, "coordinator_pid": 8, "workers": workers}
        (directory / "worker-8.jsonl").write_text(json.dumps({**base, "event": "plan"}) + "\n")
        for pid, index, start, finish in ((23, 1, 10, 15), (24, 2, 11, 14), (25, 3, 16, 20)):
            (directory / f"worker-{pid}.jsonl").write_text("\n".join(json.dumps({
                **base, "pid": pid, "task_index": index, "event": event, "observed_at_unix": when,
            }) for event, when in (("task-start", start), ("task-end", finish))) + "\n")

    def test_modern_execution_settings_replace_legacy_flag_and_distinguish_observed_tasks(self):
        self.metadata["execution_options"] = {"execution_mode": "auto", "max_workers": 4,
            "dnp_block_mib": 32, "dnp_block_loci": 64, "performance_diagnostics": False}
        self.parallel_events(self.root / "work/parallel")
        self.save()
        write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("Automatica", page)
        self.assertIn("Dimensione obiettivo dei blocchi DNP (MiB)</pre></td><td><pre>32", page)
        self.assertIn("Massimo di loci per blocco DNP</pre></td><td><pre>64", page)
        self.assertNotIn("Opzione parallela del codice storico", page)
        self.assertNotIn("Elaborazione parallela", page)
        self.assertIn("dnp-blocks</pre></td><td><pre>3</pre></td><td><pre>2", page)
        self.assertIn("non misurano il numero di core", page)
        self.assertNotIn("Diagnostica delle prestazioni", page)

    def test_compound_run_reports_acquisition_and_r_separately(self):
        self.metadata["execution_options"] = {"execution_mode": "serial", "max_workers": 4,
                                             "dnp_block_mib": 32, "dnp_block_loci": 64}
        work = self.root / "output/workflow/steps/dnp/work"
        self.parallel_events(work / "parallel", workers=3)
        (work / "dnp-pileup.json").write_text(json.dumps({"status": "succeeded",
            "strategy": "indexed-chromosomes", "parallel": {"workers": 4, "tasks": 22,
                "observed_max_processes": 4, "reason": "indexed-compatible-contigs"}}))
        self.save()
        write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("Seriale", page)
        self.assertIn("dnp-blocks</pre></td><td><pre>3</pre></td><td><pre>2", page)
        self.assertIn("indexed-chromosomes</pre></td><td><pre>4</pre></td><td><pre>4", page)
        self.assertIn("Massimo di processi samtools osservati", page)
        self.assertIn("valori di fasi diverse non vanno sommati", page)

    def test_incomplete_worker_events_only_establish_lower_bound(self):
        self.parallel_events(self.root / "work/parallel")
        with (self.root / "work/parallel/worker-25.jsonl").open("a") as handle:
            handle.write('{"event":')
        self.save()
        write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("Almeno 2 (eventi incompleti)", page)
        self.assertIn("osservazioni mostrate possono essere incomplete", page)

    def test_worker_evidence_budget_prevents_unbounded_read_and_no_concurrency_is_invented(self):
        self.metadata["execution_options"] = {"execution_mode": "auto"}
        self.parallel_events(self.root / "work/parallel")
        self.save()
        with mock.patch("nipat.run_report._MAX_PARALLEL_BYTES", 8):
            write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("Decisioni e attività dei processi non disponibili", page)
        self.assertNotIn("Task simultanei osservati", page)
        self.assertIn("supera i limiti del resoconto", page)

    def test_parallel_evidence_does_not_follow_linked_work_directory(self):
        self.metadata["execution_options"] = {"execution_mode": "auto"}
        elsewhere = self.root / "elsewhere"
        self.parallel_events(elsewhere / "parallel", label="SECRET_LABEL")
        try:
            (self.root / "work").symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symbolic links is unavailable on this platform")
        self.save()
        write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertNotIn("SECRET_LABEL", page)
        self.assertIn("Decisioni e attività dei processi non disponibili", page)

    def test_historical_parallel_flag_is_not_reinterpreted_as_modern_execution_policy(self):
        self.save()
        write_run_report(self.root)
        page = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("Opzione parallela del codice storico</pre></td><td><pre>No", page)
        self.assertNotIn("Modalità e blocchi richiesti", page)
        self.assertNotIn("Parallelismo effettivamente registrato", page)

    def test_optional_performance_report_separates_memory_meanings_and_partial_phases(self):
        self.metadata["execution_options"] = {"performance_diagnostics": True}
        engine = self.root / "performance" / "engine"
        engine.mkdir(parents=True)
        (engine.parent / "summary.json").write_text(json.dumps({
            "status": "completed", "sample_count": 5,
            "sampled_maxima": {"memory_cache_adjusted_bytes": 2 * 1024 * 1024},
        }), encoding="utf-8")
        (engine / "summary.json").write_text(json.dumps({
            "status": "partial", "samples": 10,
            "sampled_memory_max_bytes": 3 * 1024 * 1024,
            "observed_kernel_memory_peak_bytes": None,
        }), encoding="utf-8")
        (engine / "phases.jsonl").write_text(json.dumps({
            "event": "end", "phase": "R <script>", "workflow": "dnp-call",
            "duration_seconds": 1.25, "outcome": "returned",
        }) + '\n{"event":', encoding="utf-8")
        self.save()
        write_run_report(self.root)
        html = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertIn("2.00 MiB", html)
        self.assertIn("3.00 MiB", html)
        self.assertIn("Non disponibile", html)
        self.assertIn("cache inattiva sottratta", html)
        self.assertIn("R &lt;script&gt;", html)
        self.assertIn("1.25", html)
        self.assertIn("performance/engine/phases.jsonl", html)

    def test_unrequested_or_linked_performance_is_not_read(self):
        self.save()
        write_run_report(self.root)
        html = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertNotIn("Diagnostica delle prestazioni", html)
        (self.root / "run-report.html").unlink()
        (self.root / "sample-map.tsv").unlink()
        self.metadata["execution_options"] = {"performance_diagnostics": True}
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "summary.json").write_text('{"status":"SECRET_STATUS"}', encoding="utf-8")
        try:
            (self.root / "performance").symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            return
        self.save()
        write_run_report(self.root)
        html = (self.root / "run-report.html").read_text(encoding="utf-8")
        self.assertNotIn("SECRET_STATUS", html)
        self.assertNotIn("href='performance/", html)
        self.assertIn("resoconto non disponibile", html)

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
