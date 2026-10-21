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
            "source": {"nipat_version": "0.4.0"},
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
        self.assertIn("Versione NIPAT: 0.4.0", ui.lines)
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
