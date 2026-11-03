"""Resource edits are opt-in, scoped, backed up and independent of run limits."""

import base64
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.execution.transport import DockerTransport, WslDockerTransport
from nipat.resources import (
    ResourceManager, _decode_output, _lima_configuration, _memory_mib, _resource_lock,
    analysis_session, host_resources, suggested_resources, wsl_configuration,
)


HOST = {"memory_mib": 32768, "cpus": 12}


class ResourceConfigurationTests(unittest.TestCase):
    def test_wsl_preserves_bom_comments_unknown_keys_and_other_sections(self):
        text = "# existing settings\r\n[wsl2]\r\n  MEMORY = 4GB  # analysis\r\nprocessors=2\r\nkernel=C:\\Users\\u\\kernel\r\n[experimental]\r\nautoMemoryReclaim=gradual\r\n"
        original = b"\xff\xfe" + text.encode("utf-16-le")
        before, changed = wsl_configuration(original, memory_mib=8192, cpus=4)
        self.assertEqual(before, {"memory_mib": 4096, "cpus": 2})
        self.assertEqual(changed, b"\xff\xfe" + text.replace("4GB", "8192MB").replace("processors=2", "processors=4").encode("utf-16-le"))

    def test_missing_keys_insert_only_in_wsl2_not_other_section(self):
        before, changed = wsl_configuration(b"[wsl2]\nswap=2GB\n[experimental]\nfoo=yes", memory_mib=6144, cpus=3)
        self.assertEqual(before, {"memory_mib": None, "cpus": None})
        self.assertEqual(changed, b"[wsl2]\nmemory=6144MB\nprocessors=3\nswap=2GB\n[experimental]\nfoo=yes")

    def test_missing_section_preserves_original_final_line(self):
        _, changed = wsl_configuration(b"# note\n[experimental]\nfoo=bar", memory_mib=2048, cpus=1)
        self.assertEqual(changed, b"# note\n[experimental]\nfoo=bar\n\n[wsl2]\nmemory=2048MB\nprocessors=1\n")

    def test_missing_keys_after_section_without_final_newline(self):
        _, changed = wsl_configuration(b"[wsl2]", memory_mib=2048, cpus=1)
        self.assertEqual(changed, b"[wsl2]\nmemory=2048MB\nprocessors=1\n")

    def test_ambiguous_existing_wsl_configuration_is_never_rewritten(self):
        for original in (b"[wsl2]\nmemory=4GB\nMemory=8GB\n", b"[wsl2]\n[wsl2]\n"):
            with self.subTest(original=original), self.assertRaises(ValidationError):
                wsl_configuration(original, memory_mib=8192, cpus=4)

    def test_unsupported_encoding_refuses_modification(self):
        with self.assertRaises(ValidationError):
            wsl_configuration(b"# \xe8\n[wsl2]\n", memory_mib=1024, cpus=2)

    def test_lima_json_and_yaml_resource_parsing(self):
        expected = {"memory_mib": 6144, "cpus": 3}
        self.assertEqual(_lima_configuration(b'{"memory":"6GiB","cpus":3}'), expected)
        self.assertEqual(_lima_configuration(b"memory: '6GiB' # note\ncpus: 3\nparam:\n  unrelated: value\n"), expected)
        with self.assertRaises(ValidationError):
            _lima_configuration(b"cpus: 2\ncpus: 4\nmemory: 4GiB\n")

    def test_utf16_wsl_console_output_is_decoded(self):
        self.assertEqual(_decode_output("Ubuntu\r\nNIPAT\r\n".encode("utf-16-le")), "Ubuntu\r\nNIPAT\r\n")

    def test_unrepresentable_memory_is_unavailable_instead_of_crashing(self):
        self.assertIsNone(_memory_mib("9" * 400 + "TB"))

    def test_suggestions_leave_memory_for_host_and_do_not_predict_run(self):
        self.assertEqual(suggested_resources(HOST), {"memory_mib": 8192, "cpus": 4})
        self.assertEqual(suggested_resources({"memory_mib": 4096, "cpus": 2}), {"memory_mib": 2048, "cpus": 1})
        self.assertEqual(suggested_resources({}), {"memory_mib": None, "cpus": None})

    def test_host_probe_reports_positive_physical_values_when_available(self):
        result = host_resources()
        self.assertTrue(result["memory_mib"] is None or result["memory_mib"] > 0)
        self.assertTrue(result["cpus"] is None or result["cpus"] > 0)


class WslResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.config = self.home / ".wslconfig"
        self.original = b"# user configuration\r\n[wsl2]\r\nmemory=4GB\r\nprocessors=2\r\n# retain\r\n[experimental]\r\nnetworkingMode=mirrored\r\n"
        self.config.write_bytes(self.original)
        self.manager = ResourceManager(WslDockerTransport("NIPAT-Desktop"), home=self.home)
        self.host_patch = patch("nipat.resources.host_resources", return_value=HOST)
        self.host_patch.start()
        self.addCleanup(self.host_patch.stop)
        self.running_patch = patch.object(self.manager, "_running", return_value=("NIPAT-Desktop", "Ubuntu"))
        self.running = self.running_patch.start()
        self.addCleanup(self.running_patch.stop)
        self.idle_patch = patch.object(self.manager, "_assert_idle")
        self.idle = self.idle_patch.start()
        self.addCleanup(self.idle_patch.stop)

    def test_preview_performs_no_write_and_exposes_global_scope(self):
        preview = self.manager.preview(8192, 4)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(preview.after, {"memory_mib": 8192, "cpus": 4})
        self.assertEqual(preview.affected_running, ("NIPAT-Desktop", "Ubuntu"))
        self.assertIn("tutte le distribuzioni", " ".join(preview.warnings))
        self.assertNotIn("replacement", preview.as_dict())

    def test_no_confirmation_means_no_write_or_backup(self):
        preview = self.manager.preview(8192, 4)
        with self.assertRaisesRegex(ValidationError, "conferma"):
            self.manager.apply(preview, confirmed=False)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse((self.home / ".nipat").exists())

    def test_save_creates_exact_backup_and_does_not_restart(self):
        preview = self.manager.preview(8192, 4)
        with patch.object(self.manager, "_wsl") as execute:
            result = self.manager.apply(preview, confirmed=True)
        execute.assert_not_called()
        self.assertEqual(result["status"], "saved-restart-required")
        self.assertEqual(wsl_configuration(self.config.read_bytes())[0], preview.after)
        backup = json.loads(Path(result["backup"]).read_text())
        self.assertTrue(backup["existed"])
        self.assertEqual(base64.b64decode(backup["content_base64"]), self.original)

    def test_new_file_backup_records_absence(self):
        self.config.unlink()
        preview = self.manager.preview(2048, 1)
        result = self.manager.apply(preview, confirmed=True)
        backup = json.loads(Path(result["backup"]).read_text())
        self.assertFalse(backup["existed"])
        self.assertIsNone(backup["content_base64"])

    def test_external_change_after_preview_is_preserved(self):
        preview = self.manager.preview(8192, 4)
        changed = self.original + b"# changed externally\r\n"
        self.config.write_bytes(changed)
        with self.assertRaisesRegex(ValidationError, "cambiata"):
            self.manager.apply(preview, confirmed=True)
        self.assertEqual(self.config.read_bytes(), changed)

    def test_external_change_during_idle_check_is_preserved(self):
        preview = self.manager.preview(8192, 4)
        changed = self.original + b"# concurrent edit\r\n"
        self.idle.side_effect = lambda: self.config.write_bytes(changed)
        with self.assertRaisesRegex(ValidationError, "cambiata"):
            self.manager.apply(preview, confirmed=True)
        self.assertEqual(self.config.read_bytes(), changed)

    def test_external_change_after_backup_is_preserved(self):
        preview = self.manager.preview(8192, 4)
        changed = self.original + b"# concurrent backup edit\r\n"
        backup = self.manager._backup
        def create_and_edit(path, contents):
            result = backup(path, contents)
            self.config.write_bytes(changed)
            return result
        with patch.object(self.manager, "_backup", side_effect=create_and_edit):
            with self.assertRaisesRegex(ValidationError, "cambiata"):
                self.manager.apply(preview, confirmed=True)
        self.assertEqual(self.config.read_bytes(), changed)

    @unittest.skipUnless(os.name == "posix", "Symlink creation without Windows developer mode")
    def test_symlink_configuration_is_never_read_or_modified(self):
        target = self.home / "other-config"
        target.write_bytes(self.original)
        self.config.unlink()
        self.config.symlink_to(target)
        with self.assertRaisesRegex(ValidationError, "collegamento"):
            self.manager.preview(8192, 4)
        self.assertEqual(target.read_bytes(), self.original)

    def test_global_restart_requires_same_previewed_instances(self):
        preview = self.manager.preview(8192, 4)
        self.running.return_value = ("NIPAT-Desktop", "Ubuntu", "Other")
        with patch.object(self.manager, "_wsl") as execute:
            with self.assertRaisesRegex(ValidationError, "VM attive"):
                self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        execute.assert_not_called()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restart_rechecks_instances_immediately_before_shutdown(self):
        preview = self.manager.preview(8192, 4)
        self.running.side_effect = [("NIPAT-Desktop", "Ubuntu"), ("NIPAT-Desktop", "Ubuntu", "Other")]
        with patch.object(self.manager, "_wsl") as execute:
            result = self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        execute.assert_not_called()
        self.assertEqual(result["status"], "saved-restart-required")
        self.assertTrue(result["warnings"])

    def test_restart_starts_only_nipat_and_verifies_actual_resources(self):
        preview = self.manager.preview(8192, 4)
        with patch.object(self.manager, "_wsl", return_value="") as execute, patch.object(self.manager, "_effective", return_value={"memory_mib": 7900, "cpus": 4}):
            result = self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(execute.call_args_list[0].args[0], ["--shutdown"])
        self.assertEqual(execute.call_args_list[1].args[0][:3], ["--distribution", "NIPAT-Desktop", "--user"])
        self.assertNotIn("Ubuntu", str(execute.call_args_list))

    def test_restart_failure_is_not_reported_as_applied(self):
        preview = self.manager.preview(8192, 4)
        with patch.object(self.manager, "_wsl", side_effect=RuntimeExecutionError("failure")):
            result = self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        self.assertEqual(result["status"], "verification-required")
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertEqual(wsl_configuration(self.config.read_bytes())[0], preview.after)

    def test_live_container_blocks_before_configuration_write(self):
        preview = self.manager.preview(8192, 4)
        self.idle.side_effect = RuntimeExecutionError("analisi attive")
        with self.assertRaises(RuntimeExecutionError):
            self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_snapshot_distinguishes_actual_vm_from_container_cap(self):
        with patch.object(self.manager, "_effective", return_value={"memory_mib": 3800, "cpus": 2}):
            snapshot = self.manager.snapshot(ExecutionOptions(memory_mb=8192))
        self.assertEqual(snapshot["host"], HOST)
        self.assertEqual(snapshot["runtime"]["configured"]["memory_mib"], 4096)
        self.assertEqual(snapshot["runtime"]["effective"]["memory_mib"], 3800)
        self.assertEqual(snapshot["container"]["memory_mib"], 8192)
        self.assertTrue(any("non aumenta" in item for item in snapshot["warnings"]))

    def test_stopped_wsl_snapshot_does_not_start_or_query_guest(self):
        self.running.return_value = ("Ubuntu",)
        with patch.object(self.manager, "_effective") as effective:
            snapshot = self.manager.snapshot()
        effective.assert_not_called()
        self.assertFalse(snapshot["runtime"]["running"])
        self.assertIsNone(snapshot["runtime"]["effective"]["memory_mib"])

    def test_invalid_requests_do_not_touch_file(self):
        for memory, cpus in ((True, 2), (1000, 0), (32768, 4), (1024, 13), (-1, 2)):
            with self.subTest(memory=memory, cpus=cpus), self.assertRaises(ValidationError):
                self.manager.preview(memory, cpus)
        self.assertEqual(self.config.read_bytes(), self.original)


class LimaResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.instance = self.home / "instance"
        self.instance.mkdir()
        self.config = self.instance / "lima.yaml"
        self.original = {"memory": "4GiB", "cpus": 2, "param": {"NipatOwner": "owner"}, "mounts": [{"location": "/Users"}]}
        self.config.write_text(json.dumps(self.original))
        self.runtime = SimpleNamespace(instance_dir=self.instance, project=self.home,
                                       _assert_owned=Mock(), _host_check=Mock(), lock=nullcontext,
                                       host_prefix=lambda: ["limactl"], _run=Mock(side_effect=self.execute))
        self.manager = ResourceManager(SimpleNamespace(backend="lima", runtime=self.runtime), home=self.home)
        self.patch_host = patch("nipat.resources.host_resources", return_value=HOST)
        self.patch_host.start()
        self.addCleanup(self.patch_host.stop)
        self.patch_manifest = patch("nipat.macos_runtime.read_manifest", return_value={})
        self.patch_manifest.start()
        self.addCleanup(self.patch_manifest.stop)
        self.patch_idle = patch.object(self.manager, "_assert_idle")
        self.patch_idle.start()
        self.addCleanup(self.patch_idle.stop)

    def execute(self, argv, **kwargs):
        from nipat.macos_runtime import INSTANCE
        if "list" in argv:
            return json.dumps({"name": INSTANCE, "status": "Running"})
        if "edit" in argv:
            document = json.loads(self.config.read_text())
            document.update(cpus=int(argv[argv.index("--cpus") + 1]), memory=argv[argv.index("--memory") + 1] + "GiB")
            self.config.write_text(json.dumps(document))
        return ""

    def test_running_lima_requires_restart_confirmation(self):
        preview = self.manager.preview(8192, 4)
        with self.assertRaisesRegex(ValidationError, "confermare"):
            self.manager.apply(preview, confirmed=True)
        self.assertEqual(json.loads(self.config.read_text()), self.original)

    def test_owned_lima_edit_keeps_other_settings_and_backup(self):
        preview = self.manager.preview(8192, 4)
        with patch.object(self.manager, "_effective", return_value={"memory_mib": 7900, "cpus": 4}):
            result = self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        changed = json.loads(self.config.read_text())
        self.assertEqual(changed["param"], self.original["param"])
        self.assertEqual(changed["mounts"], self.original["mounts"])
        self.assertEqual(result["status"], "applied")
        self.assertTrue(Path(result["backup"]).is_file())
        arguments = [call.args[0] for call in self.runtime._run.call_args_list]
        self.assertLess(next(i for i, argv in enumerate(arguments) if "stop" in argv), next(i for i, argv in enumerate(arguments) if "edit" in argv))

    def test_unsuccessful_lima_edit_restores_exact_configuration(self):
        preview = self.manager.preview(8192, 4)
        raw = self.config.read_bytes()
        execute = self.execute
        def broken(argv, **kwargs):
            if "edit" in argv:
                self.config.write_text("broken configuration")
                raise RuntimeExecutionError("failed edit")
            return execute(argv, **kwargs)
        self.runtime._run.side_effect = broken
        with self.assertRaises(RuntimeExecutionError):
            self.manager.apply(preview, confirmed=True, restart_confirmed=True)
        self.assertEqual(self.config.read_bytes(), raw)


class NativeResourceTests(unittest.TestCase):
    def test_native_has_no_vm_edit(self):
        manager = ResourceManager(DockerTransport())
        with self.assertRaisesRegex(ValidationError, "Ubuntu"):
            manager.preview(4096, 2)

    def test_native_snapshot_uses_local_engine_and_preserves_unknowns(self):
        manager = ResourceManager(DockerTransport())
        with patch("nipat.resources._run", side_effect=RuntimeExecutionError("engine unavailable")) as run:
            snapshot = manager.snapshot()
        self.assertEqual(run.call_args.args[0][:3], ["docker", "--host", "unix:///var/run/docker.sock"])
        self.assertIsNone(snapshot["runtime"]["effective"]["memory_mib"])
        self.assertTrue(snapshot["warnings"])

    def test_analysis_lock_is_nested_and_excludes_resource_change(self):
        with tempfile.TemporaryDirectory() as temporary, patch("nipat.resources.Path.home", return_value=Path(temporary)), patch.dict(os.environ, {"NIPAT_BACKEND": "native"}):
            with analysis_session(), analysis_session():
                with self.assertRaises(RuntimeExecutionError):
                    with _resource_lock(Path(temporary), "native", exclusive=True):
                        self.fail("Resource mutation entered during analysis")
            with _resource_lock(Path(temporary), "native", exclusive=True):
                with self.assertRaises(RuntimeExecutionError):
                    with analysis_session():
                        self.fail("Analysis entered during resource mutation")

    def test_native_os_lock_excludes_other_process_resource_change(self):
        script = """import sys
from pathlib import Path
from nipat.resources import _resource_lock
from nipat.errors import RuntimeExecutionError
try:
    with _resource_lock(Path(sys.argv[1]), 'native', exclusive=sys.argv[2]=='exclusive'):
        print('acquired')
except RuntimeExecutionError:
    print('blocked')
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        with tempfile.TemporaryDirectory() as temporary:
            with _resource_lock(Path(temporary), "native", exclusive=False):
                shared = subprocess.run([sys.executable, "-c", script, temporary, "shared"],
                                        capture_output=True, text=True, env=environment, timeout=15)
                exclusive = subprocess.run([sys.executable, "-c", script, temporary, "exclusive"],
                                           capture_output=True, text=True, env=environment, timeout=15)
            unlocked = subprocess.run([sys.executable, "-c", script, temporary, "exclusive"],
                                      capture_output=True, text=True, env=environment, timeout=15)
        for result in (shared, exclusive, unlocked):
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shared.stdout.strip(), "acquired")
        self.assertEqual(exclusive.stdout.strip(), "blocked")
        self.assertEqual(unlocked.stdout.strip(), "acquired")

    def test_orphan_running_nipat_container_prevents_resource_changes(self):
        manager = ResourceManager(DockerTransport())
        with patch.object(manager, "_docker", side_effect=["", "nipat-run-orphan"]):
            with self.assertRaisesRegex(RuntimeExecutionError, "container NIPAT attivi"):
                manager._assert_idle()


if __name__ == "__main__":
    unittest.main()
