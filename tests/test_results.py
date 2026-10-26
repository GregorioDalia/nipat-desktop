import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nipat.results import open_local_path, show_results


class FakeTerminal:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.lines = []
        self.menus = []

    def heading(self, text):
        self.lines.append(text)

    def message(self, text, kind="info"):
        self.lines.append(text)

    def menu(self, title, choices, default=None):
        self.menus.append(choices)
        return next(self.answers)


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name).resolve() / "run with spaces"
        self.run.mkdir()
        (self.run / "output").mkdir()
        (self.run / "execution.log").write_text("a scientific log\n", encoding="utf-8")
        self.metadata = {
            "schema_version": 1, "workflow": "dnp-call", "status": "succeeded",
            "started_at": "2026-10-21T15:00:00Z", "finished_at": "2026-10-21T15:01:00Z",
            "inputs": [{"path": "sample.bam"}, {"path": "reference.fa"}],
            "source": {"nipat_version": "0.4.1"},
        }
        self.save_metadata()

    def save_metadata(self):
        (self.run / "run.json").write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_success_opens_only_the_explicitly_selected_locations(self):
        ui, opener = FakeTerminal(["1", "3", "4", "0"]), Mock()
        show_results(ui, self.run, open_path=opener)
        self.assertEqual([call.args[0] for call in opener.call_args_list], [
            self.run / "output", self.run / "execution.log", self.run,
        ])
        self.assertIn("Esecuzione completata", ui.lines)
        self.assertIn(f"Log: {self.run / 'execution.log'}", ui.lines)
        self.assertEqual(sum("Richiesta di apertura inviata:" in line for line in ui.lines), 3)

    def test_dry_run_never_offers_or_opens_scientific_results(self):
        (self.run / "output" / "unexpected.txt").write_text("existing", encoding="utf-8")
        self.metadata["status"] = "planned"
        self.save_metadata()
        ui, opener = FakeTerminal(["1", "2", "0"]), Mock()
        show_results(ui, self.run, dry_run=True, open_path=opener)
        opener.assert_not_called()
        self.assertTrue(all("1" not in [choice[0] for choice in menu] for menu in ui.menus))
        self.assertIn("Esecuzione pianificata", ui.lines)
        self.assertNotIn("Esecuzione completata", ui.lines)
        self.assertNotIn("unexpected.txt", "\n".join(ui.lines))
        self.assertIn("Stato registrato: Pianificata (dry-run)", ui.lines)

    def test_summary_reads_real_metadata_and_bounds_file_inventory(self):
        output = self.run / "output" / "individual_outputs"
        output.mkdir()
        for number in range(20):
            (output / f"sample_{number:02d}.txt").write_text("result", encoding="utf-8")
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertIn("Workflow: dnp-call", ui.lines)
        self.assertIn("File di input registrati: 2", ui.lines)
        self.assertIn("Versione NIPAT: 0.4.1", ui.lines)
        file_lines = [line for line in ui.lines if line.startswith("  ")]
        self.assertEqual(len(file_lines), 12)
        self.assertIn("sample_00.txt", file_lines[0])
        self.assertTrue(any("Altri file disponibili" in line for line in ui.lines))

    def test_corrupt_or_missing_metadata_keeps_navigation_available(self):
        for content in ("not json", "[]", '{"schema_version": 9}', None):
            with self.subTest(content=content):
                path = self.run / "run.json"
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content, encoding="utf-8")
                ui, opener = FakeTerminal(["2", "4", "0"]), Mock()
                show_results(ui, self.run, open_path=opener)
                self.assertTrue(any("Metadati non consultabili" in line for line in ui.lines))
                opener.assert_called_once_with(self.run)

    def test_unavailable_desktop_opener_preserves_the_path_and_menu(self):
        ui = FakeTerminal(["1", "2", "0"])
        opener = Mock(side_effect=OSError("Desktop non disponibile"))
        show_results(ui, self.run, open_path=opener)
        self.assertTrue(any("Apertura non riuscita" in line and str(self.run / "output") in line
                            for line in ui.lines))
        self.assertIn("Workflow: dnp-call", ui.lines)

    def test_missing_output_or_log_is_not_an_available_action(self):
        (self.run / "output").rmdir()
        (self.run / "execution.log").unlink()
        ui, opener = FakeTerminal(["1", "3", "0"]), Mock()
        show_results(ui, self.run, open_path=opener)
        opener.assert_not_called()
        self.assertEqual([choice[0] for choice in ui.menus[0]], ["2", "4", "0"])

    def test_cancel_shortcuts_return_without_opening(self):
        for answer in (":annulla", ":indietro", "\x1b"):
            with self.subTest(answer=answer):
                opener = Mock()
                show_results(FakeTerminal([answer]), self.run, open_path=opener)
                opener.assert_not_called()

    def test_input_and_numerical_warnings_are_visible_before_opening_summary(self):
        work = self.run / "work"
        work.mkdir()
        (work / "input-validation.json").write_text(json.dumps({
            "schema_version": 1, "warnings": [{"code": "input.frequency_sum",
                "path": "/workspace/inputs/frequencies.tsv", "row": 2,
                "message": "Frequency interpretation requires domain review."}],
        }), encoding="utf-8")
        (work / "scientific-validation.json").write_text(json.dumps({
            "schema_version": 1, "quality_warnings": [{"code": "output.nonfinite",
                "file": "summary.csv", "row": 2, "column": "CPI", "value": "Inf",
                "message": "Non-finite scientific result; R value unchanged."}],
        }), encoding="utf-8")
        ui = FakeTerminal(["0"])
        show_results(ui, self.run)
        text = "\n".join(ui.lines)
        self.assertIn("Avvisi sui dati o sui risultati: 2", text)
        self.assertIn("input.frequency_sum", text)
        self.assertIn("output.nonfinite", text)
        self.assertIn("value=Inf", text)
        self.assertEqual(json.loads((self.run / "run.json").read_text())["status"], "succeeded")

    def test_invalid_warning_report_does_not_hide_results_navigation(self):
        work = self.run / "work"
        work.mkdir()
        (work / "input-validation.json").write_text('{"schema_version":1,"warnings":42}', encoding="utf-8")
        ui = FakeTerminal(["0"])
        show_results(ui, self.run)
        self.assertTrue(any("Avvisi di validazione non consultabili" in line for line in ui.lines))
        self.assertTrue(ui.menus)


    def prepare_workflow(self, *, status="succeeded", dnp="succeeded", contamination="succeeded"):
        self.metadata.update(workflow="dnp-contamination", status=status)
        self.save_metadata()
        root = self.run / "output" / "workflow"
        root.mkdir(exist_ok=True)
        state = {
            "schema_version": 1, "interface": "workflow-plan-execution-v1",
            "status": "cancelled" if status == "interrupted" else status,
            "steps": [
                {"id": "dnp", "workflow": "dnp-call", "status": dnp},
                {"id": "contamination", "workflow": "contamination", "status": contamination},
            ],
        }
        path = root / "workflow-state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return root, path, state

    def test_composed_summary_shows_both_steps_and_fixed_result_locations(self):
        root, path, state = self.prepare_workflow()
        for step in ("dnp", "contamination"):
            (root / "steps" / step / "output").mkdir(parents=True)
        state["steps"][0]["output_dir"] = str(self.run.parent / "outside")
        state["steps"][1]["log"] = "../../bad.cmd"
        path.write_text(json.dumps(state), encoding="utf-8")
        ui, opener = FakeTerminal(["2", "0"]), Mock()
        show_results(ui, self.run, open_path=opener)
        self.assertIn("Esecuzione completata", ui.lines)
        self.assertIn("  DNPcall: Completata", ui.lines)
        self.assertIn("  Contamination: Completata", ui.lines)
        text = "\n".join(ui.lines)
        self.assertIn(str(root / "steps" / "dnp" / "output"), text)
        self.assertIn(str(root / "steps" / "contamination" / "output"), text)
        self.assertNotIn("outside", text)
        self.assertNotIn("bad.cmd", text)
        opener.assert_not_called()

    def test_failed_or_cancelled_step_is_not_presented_as_completed(self):
        for status, dnp, expected in (("failed", "failed", "Esecuzione non riuscita"),
                                      ("interrupted", "cancelled", "Esecuzione interrotta")):
            with self.subTest(status=status):
                self.prepare_workflow(status=status, dnp=dnp, contamination="blocked")
                ui = FakeTerminal(["2", "0"])
                show_results(ui, self.run)
                self.assertIn(expected, ui.lines)
                self.assertNotIn("Esecuzione completata", ui.lines)
                self.assertIn("  Contamination: Non avviata: workflow arrestato", ui.lines)

    def test_failed_step_report_overrides_success_title_from_parent_record(self):
        _, path, state = self.prepare_workflow()
        state["status"] = "failed"
        state["steps"][0]["status"] = "failed"
        state["steps"][1]["status"] = "blocked"
        path.write_text(json.dumps(state), encoding="utf-8")
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertIn("Esecuzione non riuscita", ui.lines)
        self.assertNotIn("Esecuzione completata", ui.lines)

    def test_missing_or_malformed_step_state_keeps_navigation_available(self):
        _, path, good = self.prepare_workflow()
        malformed = [None, "not json", "[]", json.dumps({**good, "schema_version": True}),
                     json.dumps({**good, "steps": []}), json.dumps({**good, "status": []}),
                     json.dumps({**good, "steps": [good["steps"][0], good["steps"][0]]}),
                     json.dumps({**good, "steps": [{**good["steps"][0], "status": "failed"},
                                                    good["steps"][1]]})]
        for content in malformed:
            with self.subTest(content=content):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content, encoding="utf-8")
                ui, opener = FakeTerminal(["2", "4", "0"]), Mock()
                show_results(ui, self.run, open_path=opener)
                self.assertTrue(any("Stato dei passaggi non consultabile" in line for line in ui.lines))
                self.assertNotIn("Esecuzione completata", ui.lines)
                opener.assert_called_once_with(self.run)

    def test_step_metadata_read_is_bounded(self):
        _, path, _ = self.prepare_workflow()
        path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertTrue(any("supera il limite" in line for line in ui.lines))
        self.assertNotIn("Esecuzione completata", ui.lines)

    def test_symlinked_step_state_is_not_followed(self):
        _, path, state = self.prepare_workflow()
        external = self.run.parent / "external-state.json"
        external.write_text(json.dumps(state), encoding="utf-8")
        path.unlink()
        try:
            path.symlink_to(external)
        except (NotImplementedError, OSError):
            self.skipTest("Platform does not permit symbolic links")
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertTrue(any("Percorso collegato non consultabile" in line for line in ui.lines))
        self.assertNotIn("  DNPcall: Completata", ui.lines)

    def test_dry_run_does_not_read_or_claim_step_results(self):
        self.prepare_workflow()
        ui = FakeTerminal(["2", "0"])
        with patch("nipat.results._workflow_state") as read:
            show_results(ui, self.run, dry_run=True)
        read.assert_not_called()
        self.assertNotIn("Passaggi del workflow automatico:", ui.lines)
        self.assertIn("Esecuzione pianificata", ui.lines)


    def prepare_cpi_workflow(self, *, full=False):
        root, path, state = self.prepare_workflow()
        self.metadata["workflow"] = "dnp-contamination-cpi" if full else "dnp-cpi"
        self.metadata["parameters"] = {"pair_mapping": [{
            "pair_id": "FamilyA", "mother_sample_id": "sample_0001", "father_sample_id": "sample_0002",
            "mother_bam": "/external/maternal.bam", "father_bam": "/external/paternal.bam",
        }]}
        self.save_metadata()
        if not full:
            state["steps"] = state["steps"][:1]
        state["steps"].append({"id": "cpi", "workflow": "cpi", "status": "succeeded"})
        path.write_text(json.dumps(state), encoding="utf-8")
        return root, path, state

    def test_cpi_workflow_summaries_show_only_their_expected_steps_and_roles(self):
        for full in (False, True):
            with self.subTest(full=full):
                root, _, state = self.prepare_cpi_workflow(full=full)
                for step in state["steps"]:
                    (root / "steps" / step["id"] / "output").mkdir(parents=True, exist_ok=True)
                ui, opener = FakeTerminal(["2", "0"]), Mock()
                show_results(ui, self.run, open_path=opener)
                self.assertIn("Esecuzione completata", ui.lines)
                self.assertIn("  DNPcall: Completata", ui.lines)
                self.assertIn("  CPI: Completata", ui.lines)
                self.assertEqual("  Contamination: Completata" in ui.lines, full)
                self.assertIn("Coppie CPI registrate: 1", ui.lines)
                self.assertIn("  Coppia FamilyA", ui.lines)
                self.assertIn("    cfDNA materno (sample_0001): /external/maternal.bam", ui.lines)
                self.assertIn("    Campione paterno (sample_0002): /external/paternal.bam", ui.lines)
                self.assertTrue(any(str(root / "steps/cpi/output") in line for line in ui.lines))
                opener.assert_not_called()

    def test_cpi_missing_or_failed_step_cannot_receive_success_title(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                _, path, state = self.prepare_cpi_workflow(full=True)
                if missing:
                    state["steps"].pop()
                else:
                    state["status"] = "failed"
                    state["steps"][-1]["status"] = "failed"
                path.write_text(json.dumps(state), encoding="utf-8")
                ui = FakeTerminal(["2", "0"])
                show_results(ui, self.run)
                self.assertNotIn("Esecuzione completata", ui.lines)
                if missing:
                    self.assertTrue(any("Stato dei passaggi non consultabile" in line for line in ui.lines))
                else:
                    self.assertIn("  CPI: Non riuscita", ui.lines)

    def test_cpi_pair_mapping_is_bounded_and_never_opened_as_a_path(self):
        self.prepare_cpi_workflow()
        self.metadata["parameters"]["pair_mapping"] = [
            {"pair_id": f"Family{number}", "mother_sample_id": f"sample_{number}",
             "father_sample_id": "father", "mother_bam": "/outside/analysis.cmd",
             "father_bam": "/outside/father.bam"} for number in range(20)
        ]
        self.save_metadata()
        ui, opener = FakeTerminal(["2", "4", "0"]), Mock()
        show_results(ui, self.run, open_path=opener)
        self.assertEqual(sum(line.startswith("  Coppia ") for line in ui.lines), 12)
        self.assertIn("Coppie CPI registrate: 20", ui.lines)
        self.assertIn("Altre coppie disponibili in run.json.", ui.lines)
        opener.assert_called_once_with(self.run)

    def test_malformed_cpi_pair_mapping_does_not_hide_step_status(self):
        self.prepare_cpi_workflow()
        self.metadata["parameters"]["pair_mapping"] = [{"pair_id": "FamilyA", "mother_bam": []}]
        self.save_metadata()
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertIn("  CPI: Completata", ui.lines)
        self.assertIn("Associazioni delle coppie CPI non consultabili in run.json.", ui.lines)

    def prepare_snp_workflow(self, *, batch=False, mode="bam", count=2):
        root, path, state = self.prepare_workflow()
        if batch:
            self.metadata["workflow"] = "snp-batch"
            state["steps"] = []
        expected = [{"id": step["id"], "workflow": step["workflow"]} for step in state["steps"]]
        samples = []
        for number in range(1, count + 1):
            identifier = f"sample_{number:04d}"
            source = f"/inputs/{identifier}.bam" if mode == "bam" else f"/inputs/{identifier}.txt"
            samples.append({"sample_id": identifier, "original_path": f"/user/selected/{number}",
                            "container_path": source})
            expected.append({"id": f"snp_{number:04d}", "workflow": "snp-call",
                             "sample": identifier, "mode": mode})
            state["steps"].append({"id": f"snp_{number:04d}", "workflow": "snp-call", "status": "succeeded",
                                   "sample_mapping": {"sample": identifier, "mode": mode, "path": source},
                                   "artifacts": {"snp-tables": [{"sample": identifier, "path": "ignored.txt"}]}})
            (root / "steps" / f"snp_{number:04d}" / "output").mkdir(parents=True, exist_ok=True)
        self.metadata["parameters"] = {"expected_steps": expected, "sample_mapping": samples,
                                        **({"mode": mode} if batch else {"snp_panel": "/user/panel.tsv"})}
        self.save_metadata()
        path.write_text(json.dumps(state), encoding="utf-8")
        return root, path, state

    def test_snp_results_show_each_original_input_and_fixed_step_directory(self):
        for batch, mode in ((False, "bam"), (True, "bam"), (True, "pileup")):
            with self.subTest(batch=batch, mode=mode):
                root, _, _ = self.prepare_snp_workflow(batch=batch, mode=mode)
                ui, opener = FakeTerminal(["2", "0"]), Mock()
                show_results(ui, self.run, open_path=opener)
                self.assertIn("Esecuzione completata", ui.lines)
                self.assertIn(f"  SNPcall sample_0001 ({mode}): Completata", ui.lines)
                self.assertIn(f"  SNPcall sample_0002 ({mode}): Completata", ui.lines)
                self.assertIn("    Input: /user/selected/1", ui.lines)
                self.assertIn("    Input: /user/selected/2", ui.lines)
                self.assertTrue(any(str(root / "steps/snp_0002/output") in line for line in ui.lines))
                self.assertEqual("  DNPcall: Completata" in ui.lines, not batch)
                opener.assert_not_called()

    def test_snp_results_reject_missing_extra_or_wrong_sample_states(self):
        mutations = [lambda state: state["steps"].pop(),
                     lambda state: state["steps"].append(state["steps"][-1]),
                     lambda state: state["steps"][-1].update(id="../../outside"),
                     lambda state: state["steps"][-1]["sample_mapping"].update(mode="pileup"),
                     lambda state: state["steps"][-1]["sample_mapping"].update(path="/another/input.bam"),
                     lambda state: state["steps"][-1]["artifacts"]["snp-tables"][0].update(sample="sample_0001")]
        for mutate in mutations:
            _, path, state = self.prepare_snp_workflow()
            mutate(state)
            path.write_text(json.dumps(state), encoding="utf-8")
            ui = FakeTerminal(["2", "0"])
            show_results(ui, self.run)
            self.assertNotIn("Esecuzione completata", ui.lines)
            self.assertTrue(any("Stato dei passaggi non consultabile" in line for line in ui.lines))
            self.assertNotIn("../../outside", "\n".join(ui.lines))

    def test_snp_expected_mapping_cannot_supply_arbitrary_or_incomplete_step_ids(self):
        mutations = [lambda params: params.update(expected_steps=None),
                     lambda params: params["expected_steps"].pop(),
                     lambda params: params["expected_steps"][-1].update(id="../../outside"),
                     lambda params: params["expected_steps"][-1].update(workflow="cpi"),
                     lambda params: params["expected_steps"][-1].update(sample="sample_0001"),
                     lambda params: params["sample_mapping"][-1].update(sample_id="sample_0001"),
                     lambda params: params.update(sample_mapping=None),
                     lambda params: params.update(mode="unknown")]
        for mutate in mutations:
            self.prepare_snp_workflow(batch=True)
            mutate(self.metadata["parameters"])
            self.save_metadata()
            ui = FakeTerminal(["2", "0"])
            show_results(ui, self.run)
            self.assertNotIn("Esecuzione completata", ui.lines)
            self.assertTrue(any("Stato dei passaggi non consultabile" in line for line in ui.lines))
            self.assertNotIn("../../outside", "\n".join(ui.lines))

    def test_failed_snp_and_blocked_remaining_sample_are_visible(self):
        _, path, state = self.prepare_snp_workflow(batch=True)
        state["status"] = "failed"
        state["steps"][0].update(status="failed", artifacts={})
        state["steps"][1].update(status="blocked", artifacts={})
        state["steps"][1].pop("sample_mapping")
        path.write_text(json.dumps(state), encoding="utf-8")
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertIn("Esecuzione non riuscita", ui.lines)
        self.assertIn("  SNPcall sample_0001 (bam): Non riuscita", ui.lines)
        self.assertIn("  SNPcall sample_0002 (bam): Non avviata: workflow arrestato", ui.lines)

    def test_snp_summary_is_bounded_without_omitting_validation_of_later_steps(self):
        _, path, state = self.prepare_snp_workflow(batch=True, count=30)
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertEqual(sum(line.startswith("  SNPcall ") for line in ui.lines), 24)
        self.assertIn("Altri 6 passaggi disponibili in workflow-state.json.", ui.lines)
        state["steps"][-1]["artifacts"]["snp-tables"][0]["sample"] = "wrong"
        path.write_text(json.dumps(state), encoding="utf-8")
        ui = FakeTerminal(["2", "0"])
        show_results(ui, self.run)
        self.assertNotIn("Esecuzione completata", ui.lines)

    def test_legacy_parameters_null_or_list_do_not_crash_fixed_step_summary(self):
        for parameters in (None, []):
            self.prepare_workflow()
            self.metadata["parameters"] = parameters
            self.save_metadata()
            ui = FakeTerminal(["2", "0"])
            show_results(ui, self.run)
            self.assertIn("  DNPcall: Completata", ui.lines)
            self.assertIn("  Contamination: Completata", ui.lines)



class DesktopOpenerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()

    def test_windows_uses_shell_association_for_directory_without_shell_command(self):
        with patch("nipat.results.sys.platform", "win32"), \
                patch("nipat.results.os.startfile", create=True) as start, \
                patch("nipat.results.subprocess.Popen") as process:
            open_local_path(self.directory)
        start.assert_called_once_with(str(self.directory), "open")
        process.assert_not_called()

    def test_posix_directory_is_a_single_argument_and_shell_is_disabled(self):
        directory = self.directory / "results with spaces & characters"
        directory.mkdir()
        with patch("nipat.results.sys.platform", "linux"), \
                patch("nipat.results.subprocess.Popen") as process:
            open_local_path(directory)
        process.assert_called_once_with(
            ["xdg-open", str(directory)], shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def test_opening_arbitrary_files_is_rejected(self):
        script = self.directory / "analysis.cmd"
        script.write_text("echo should not execute", encoding="utf-8")
        with patch("nipat.results.subprocess.Popen") as process:
            with self.assertRaises(OSError):
                open_local_path(script)
        process.assert_not_called()

    def test_existing_execution_log_can_be_opened_on_macos(self):
        log = self.directory / "execution.log"
        log.write_text("log", encoding="utf-8")
        with patch("nipat.results.sys.platform", "darwin"), \
                patch("nipat.results.subprocess.Popen") as process:
            open_local_path(log)
        self.assertEqual(process.call_args.args[0], ["open", str(log)])


if __name__ == "__main__":
    unittest.main()
