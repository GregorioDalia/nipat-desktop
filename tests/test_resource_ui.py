from contextlib import nullcontext, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.cli import main
from nipat.execution.options import ExecutionOptions
from nipat.paths import ProjectLayout
from nipat.resource_ui import configure_resources, resource_lines
from nipat.wizard_forms import Cancelled


class FakeUI:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.lines, self.menus = [], []

    def heading(self, text):
        self.lines.append(text)

    def message(self, text, kind="info"):
        self.lines.append(text)

    def menu(self, title, choices, default="0"):
        self.menus.append((title, choices, default))
        return next(self.answers)

    def prompt(self, title, default=""):
        return next(self.answers)


def manager(backend="wsl", running=True):
    result = Mock()
    result.snapshot.return_value = {
        "backend": backend, "host": {"memory_mib": 32768, "cpus": 16},
        "runtime": {"configured": {"memory_mib": 4096, "cpus": 2},
                    "effective": {"memory_mib": 3700, "cpus": 2}, "running": running},
        "container": {"memory_mib": 2048, "cpus": 1}, "warnings": [],
    }
    result.preview.return_value.as_dict.return_value = {
        "backend": backend, "config_path": "/user/.wslconfig", "before": {"memory_mib": 4096, "cpus": 2},
        "after": {"memory_mib": 8192, "cpus": 4}, "warnings": ["Impatto globale WSL2"],
        "affected_running": ["Ubuntu", "NIPAT"] if running else [],
    }
    result.apply.return_value = {"backup": "/user/.wslconfig.backup", "status": "saved-restart-required", "warnings": []}
    return result


class ResourceUITests(unittest.TestCase):
    def test_wsl_save_and_restart_are_separate_explicit_choices(self):
        backend = manager()
        ui = FakeUI(["2", "8", "4", "1", "0", "0"])
        configure_resources(ui, None, ExecutionOptions(), manager=backend)
        backend.preview.assert_called_once_with(memory_mib=8192, cpus=4)
        backend.apply.assert_called_once_with(backend.preview.return_value, confirmed=True, restart_confirmed=False)
        text = "\n".join(ui.lines)
        self.assertIn("Ubuntu, NIPAT", text)
        self.assertIn("Riavvio da completare", text)
        self.assertIn("Backup:", text)
        self.assertIn("non aumenta", text)
        self.assertTrue(all(default == "0" for _, _, default in ui.menus))

    def test_wsl_restart_occurs_only_after_second_confirmation(self):
        backend = manager()
        configure_resources(FakeUI(["2", "8", "4", "1", "1", "0"]), None,
                            ExecutionOptions(), manager=backend)
        backend.apply.assert_called_once_with(backend.preview.return_value, confirmed=True, restart_confirmed=True)

    def test_lima_restart_refusal_cancels_configuration(self):
        backend = manager("lima")
        configure_resources(FakeUI(["2", "8", "4", "1", "0", "0"]), None,
                            ExecutionOptions(), manager=backend)
        backend.apply.assert_not_called()

    def test_cancel_after_preview_does_not_apply(self):
        backend = manager()
        configure_resources(FakeUI(["2", "8", "4", "0", "0"]), None,
                            ExecutionOptions(), manager=backend)
        backend.apply.assert_not_called()
        with self.assertRaises(Cancelled):
            configure_resources(FakeUI([":annulla"]), None, ExecutionOptions(), manager=backend)

    def test_linux_has_no_virtual_machine_editor_and_explains_container_scope(self):
        backend = manager("native")
        ui = FakeUI(["0"])
        configure_resources(ui, None, ExecutionOptions(), manager=backend)
        self.assertNotIn("2", [choice[0] for choice in ui.menus[0][1]])
        backend.preview.assert_not_called()
        self.assertIn("soltanto i limiti delle proprie analisi", "\n".join(ui.lines))

    def test_stopped_runtime_is_not_presented_as_effectively_reconfigured(self):
        data = manager(running=False).snapshot()
        data["runtime"]["effective"] = {"memory_mib": None, "cpus": None}
        self.assertIn("L'ambiente è fermo", "\n".join(resource_lines(data)))


class ResourceCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.layout = ProjectLayout(root, root, root / "data", root / "runs", root / "compose.yaml")
        self.backend = manager()

    def invoke(self, arguments):
        output = io.StringIO()
        with patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
             patch("nipat.cli.activity_session", return_value=nullcontext()), \
             patch("nipat.resources.ResourceManager.from_environment", return_value=self.backend), \
             patch("nipat.cli.DockerComposeRunner") as runner, redirect_stdout(output):
            code = main(arguments)
        runner.assert_not_called()
        return code, json.loads(output.getvalue())

    def test_inspection_and_preview_never_apply_or_instantiate_analysis_runner(self):
        code, report = self.invoke(["resources", "inspect", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(report["snapshot"]["backend"], "wsl")
        self.backend.preview.assert_not_called()
        code, report = self.invoke(["resources", "configure", "--memory-mib", "8192", "--vm-cpus", "4", "--json"])
        self.assertEqual(report["result"]["status"], "preview-only")
        self.backend.apply.assert_not_called()

    def test_mutation_requires_explicit_flags_and_dry_run_cannot_apply(self):
        arguments = ["resources", "configure", "--memory-mib", "8192", "--vm-cpus", "4"]
        for flags in (["--apply"], ["--restart"], ["--yes"]):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments + flags)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--dry-run"] + arguments + ["--apply", "--yes"])
        self.backend.apply.assert_not_called()
        self.invoke(arguments + ["--apply", "--yes", "--restart", "--json"])
        self.backend.apply.assert_called_once_with(self.backend.preview.return_value, confirmed=True, restart_confirmed=True)


if __name__ == "__main__":
    unittest.main()
