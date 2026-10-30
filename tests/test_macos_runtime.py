"""Lima lifecycle boundaries; real VM evidence is a separate macOS job."""

import copy
from contextlib import redirect_stdout
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.macos_runtime import (
    CHANNEL, INSTANCE, LIMA_VERSION, LimaRuntime, _write_json, file_sha256,
    loaded_image_id, read_manifest,
)
from test_bundled_runner import engine_metadata


SOURCE_ID = "sha256:" + "a" * 64
LOADED_ID = "sha256:" + "b" * 64


@unittest.skipUnless(os.name == "posix", "Lima lifecycle is exercised on Linux/macOS hosts")
class MacRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nm-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.project = self.home / "App with spaces" / "app"
        self.project.mkdir(parents=True)
        self.executable = self.home / "lima" / "bin" / "limactl"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_text("fixture")
        self.workspace = self.home / "Library" / "Application Support" / "NIPAT-Experimental08"
        self.runtime = LimaRuntime(self.project, self.workspace, self.executable, home=self.home)
        self.archive = self.project / ".distribution" / "assets" / "runtime.tar.gz"
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(b"verified fixture archive")
        self.manifest = {
            "schema_version": 1, "channel": CHANNEL, "version": "0.8.0a1", "source_commit": "c" * 40,
            "architecture": "x86_64", "lima_version": LIMA_VERSION, "runtime_image": SOURCE_ID,
            "scientific_asset": {"name": self.archive.name, "sha256": file_sha256(self.archive)},
            "engine_description": engine_metadata(),
        }
        _write_json(self.project / ".distribution" / "macos-manifest.json", self.manifest)
        self.owner = {"channel": CHANNEL, "instance": INSTANCE, "lima_home": str(self.runtime.lima_home),
                      "token": "d" * 32, "mounts": self.runtime.default_mounts()}

    def owned_vm(self):
        _write_json(self.runtime.owner_path, self.owner)
        self.runtime.instance_dir.mkdir(parents=True)
        (self.runtime.instance_dir / "lima.yaml").write_text(
            "param:\n  NipatOwner: " + self.owner["token"] + "\n", encoding="utf-8",
        )

    def ready_state(self):
        state = {**self.runtime._bindings(self.manifest), "phase": "ready", "runtime_image": LOADED_ID}
        _write_json(self.runtime.state_path, state)
        return state

    def test_manifest_rejects_stable_channel_path_traversal_or_partial_contract(self):
        self.assertEqual(read_manifest(self.project), self.manifest)
        mutations = [
            lambda m: m.update(channel="desktop"),
            lambda m: m.update(runtime_image="arbitrary:latest"),
            lambda m: m["scientific_asset"].update(name="../runtime.tar.gz"),
            lambda m: m.update(engine_description={}),
            lambda m: m.update(lima_version="latest"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(self.manifest)
                mutate(value)
                _write_json(self.project / ".distribution" / "macos-manifest.json", value)
                with self.assertRaises((ValidationError, RuntimeExecutionError)):
                    read_manifest(self.project)

    def test_load_receipt_does_not_guess_from_existing_images_or_tags(self):
        self.assertEqual(loaded_image_id("Loading layer\nLoaded image ID: " + LOADED_ID), LOADED_ID)
        for output in ("", "Loaded image: latest", "Loaded image ID: sha256:123", "Loaded image ID: "
                       + LOADED_ID + "\nLoaded image ID: " + SOURCE_ID,
                       "Loaded image ID: " + LOADED_ID + "\nError unpacking image"):
            with self.subTest(output=output), self.assertRaises(RuntimeExecutionError):
                loaded_image_id(output)

    def test_native_architectures_share_same_amd64_scientific_image(self):
        for arch in ("arm64", "x86_64"):
            manifest = dict(self.manifest, architecture=arch)
            config = self.runtime.template(manifest, self.owner)
            self.assertEqual(config["vmType"], "vz")
            self.assertEqual(config["arch"], "aarch64" if arch == "arm64" else "x86_64")
            self.assertEqual(config["vmOpts"]["vz"]["rosetta"], {"enabled": arch == "arm64", "binfmt": arch == "arm64"})
            self.assertEqual(len(config["images"]), 1)
            self.assertRegex(config["images"][0]["digest"], r"^sha256:[a-f0-9]{64}$")
            self.assertIn("24.04", config["images"][0]["location"])
            self.assertNotIn("curl", config["provision"][0]["script"])
            self.assertIn("$PARAM_NipatOwner", config["provision"][0]["script"])
            self.assertFalse(config["ssh"]["forwardAgent"])

    def test_owned_config_accepts_original_json_and_lima_yaml(self):
        self.owned_vm()
        self.assertEqual(self.runtime._assert_owned(), self.owner)
        _write_json(self.runtime.instance_dir / "lima.yaml", self.runtime.template(self.manifest, self.owner))
        self.assertEqual(self.runtime._assert_owned(), self.owner)

    def test_does_not_adopt_an_existing_unowned_vm(self):
        self.runtime.instance_dir.mkdir(parents=True)
        (self.runtime.instance_dir / "keep").write_text("unrelated")
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run") as execute:
            with self.assertRaisesRegex(ValidationError, "non gestita"):
                self.runtime.prepare()
        execute.assert_not_called()
        self.assertFalse(self.runtime.owner_path.exists())
        self.assertEqual((self.runtime.instance_dir / "keep").read_text(), "unrelated")

    def test_remove_rejects_forged_ownership_and_preserves_analyses(self):
        self.owned_vm()
        self.ready_state()
        data = self.workspace / "data" / "keep.bam"
        data.parent.mkdir(parents=True)
        data.write_text("original")
        (self.runtime.instance_dir / "lima.yaml").write_text("param:\n  NipatOwner: foreign\n")
        with patch.object(self.runtime, "_run") as execute:
            with self.assertRaises(ValidationError):
                self.runtime.remove_runtime()
            execute.assert_not_called()
        (self.runtime.instance_dir / "lima.yaml").write_text("param:\n  NipatOwner: " + self.owner["token"] + "\n")
        with patch.object(self.runtime, "_run", return_value="") as execute:
            self.runtime.remove_runtime()
            self.assertEqual(execute.call_args.args[0][-3:], ["delete", "--force", INSTANCE])
        self.assertEqual(data.read_text(), "original")
        self.assertFalse(self.runtime.state_path.exists())
        self.assertFalse(self.runtime.owner_path.exists())

    def test_checksum_failure_prevents_any_image_load(self):
        self.owned_vm()
        self.archive.write_bytes(b"tampered archive")
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run", return_value="") as execute:
            with self.assertRaisesRegex(ValidationError, "checksum"):
                self.runtime.prepare()
        self.assertFalse(any("load" in call.args[0] for call in execute.call_args_list))
        self.assertEqual(json.loads(self.runtime.state_path.read_text())["phase"], "failed")

    def test_verified_import_accepts_local_id_only_with_exact_contract(self):
        self.owned_vm()
        responses = ["started", "Loaded image ID: " + LOADED_ID,
                     LOADED_ID + " linux amd64", json.dumps(self.manifest["engine_description"])]
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run", side_effect=responses) as execute:
            state = self.runtime.prepare()
        self.assertEqual(state["runtime_image"], LOADED_ID)
        self.assertEqual(state["source_runtime_image"], SOURCE_ID)
        self.assertEqual(state["phase"], "ready")
        self.assertFalse(any("image" in call.args[0] and "ls" in call.args[0] for call in execute.call_args_list))

    def test_first_prepare_creates_only_owned_instance_and_survives_json_config(self):
        original = self.archive.read_bytes()

        def execute(argv, **kwargs):
            if "start" in argv:
                self.assertIn("--name=nipat08", argv)
                self.runtime.instance_dir.mkdir(parents=True)
                (self.runtime.instance_dir / "lima.yaml").write_bytes(Path(argv[-1]).read_bytes())
                return "started"
            if "load" in argv:
                return "Loaded image ID: " + LOADED_ID
            if "inspect" in argv:
                return LOADED_ID + " linux amd64"
            if "describe" in argv:
                return json.dumps(self.manifest["engine_description"])
            self.fail(f"Unexpected runtime command: {argv}")

        with redirect_stdout(io.StringIO()), patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run", side_effect=execute):
            state = self.runtime.prepare()
        self.assertEqual(state["phase"], "ready")
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertEqual(self.runtime._assert_owned()["instance"], INSTANCE)

    def test_first_boot_failure_records_diagnostic_and_can_be_retried(self):
        with redirect_stdout(io.StringIO()), patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run", side_effect=RuntimeExecutionError("download failed")):
            with self.assertRaisesRegex(RuntimeExecutionError, "download failed"):
                self.runtime.prepare()
        state = json.loads(self.runtime.state_path.read_text())
        self.assertEqual(state["phase"], "failed")
        self.assertIn("download failed", state["last_error"])
        self.assertTrue(self.runtime.owner_path.exists())

    def test_same_interface_different_science_is_rejected(self):
        altered = copy.deepcopy(self.manifest["engine_description"])
        altered["workflows"]["cpi"]["sha256"] = "f" * 64
        with patch.object(self.runtime, "_run", side_effect=[LOADED_ID + " linux amd64", json.dumps(altered)]):
            with self.assertRaisesRegex(RuntimeExecutionError, "non corrisponde"):
                self.runtime._verify_image(self.manifest, LOADED_ID)

    def test_repeated_prepare_reuses_verified_vm_without_import(self):
        self.owned_vm()
        state = self.ready_state()
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run", return_value="") as execute, patch.object(self.runtime, "_verify_image") as verify:
            self.assertEqual(self.runtime.prepare(), state)
        verify.assert_called_once_with(self.manifest, LOADED_ID)
        self.assertEqual(len(execute.call_args_list), 1)
        self.assertEqual(execute.call_args.args[0][-3:], ["start", "--tty=false", INSTANCE])

    def test_ensure_requires_correct_build_and_never_imports_or_creates(self):
        self.owned_vm()
        state = self.ready_state()
        state["source_commit"] = "e" * 40
        _write_json(self.runtime.state_path, state)
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run") as execute:
            with self.assertRaisesRegex(ValidationError, "altra build"):
                self.runtime.ensure()
        execute.assert_not_called()

    def test_concurrent_prepare_is_rejected_without_stealing_lock(self):
        with self.runtime.lock():
            with self.assertRaisesRegex(RuntimeExecutionError, "già in corso"):
                with self.runtime.lock(timeout=0):
                    self.fail("lock was stolen")

    def test_paths_preserve_spaces_and_special_characters_without_shell_commands(self):
        value = self.home / "Case $HOME; $(touch nope), è" / "sample.bam"
        with patch("nipat.macos_runtime.subprocess.run") as run:
            self.assertEqual(self.runtime.host_path(value), str(value))
            command = self.runtime.docker_command(["image", "load", "--input", str(value)])
        run.assert_not_called()
        self.assertEqual(command[-1], str(value))
        self.assertNotIn("sh", command)
        self.assertNotIn("-c", command)
        self.assertIn("LIMA_HOME=" + str(self.home / ".nipat08/lima"), command)
        self.assertIn("SSH=/usr/bin/ssh", command)
        self.assertIn("--workdir=/", command)
        self.assertIn("DOCKER_DEFAULT_PLATFORM=linux/amd64", command)

    def test_paths_outside_mounts_and_escaping_symlinks_are_rejected(self):
        outside = Path("/unshared/nipat/file.bam")
        with self.assertRaisesRegex(ValidationError, "non condivisa"):
            self.runtime.host_path(outside)
        link = self.home / "escape"
        link.symlink_to("/unshared")
        with self.assertRaises(ValidationError):
            self.runtime.host_path(link / "input.bam")
        for raw in ("", "/tmp/path\n", "/tmp/path\x00"):
            with self.assertRaises(ValidationError):
                self.runtime.host_path(raw)

    def test_first_setup_mounts_custom_root_but_never_whole_system(self):
        self.owned_vm()
        with patch.object(self.runtime, "_host_check"), patch.object(self.runtime, "_run") as execute:
            with self.assertRaisesRegex(ValidationError, "radice"):
                self.runtime.prepare([Path("/")])
        execute.assert_not_called()

    def test_host_check_rejects_foreign_lima_version_and_global_overrides(self):
        with patch("nipat.macos_runtime.sys.platform", "darwin"), patch("nipat.macos_runtime.platform.mac_ver", return_value=("14.7", (), "")), patch("nipat.macos_runtime.platform.machine", return_value="x86_64"), patch.object(self.runtime, "_run", return_value="limactl version 99.0.0"):
            with self.assertRaisesRegex(ValidationError, "versione Lima"):
                self.runtime._host_check(self.manifest)
        override = self.runtime.lima_home / "_config" / "override.yaml"
        override.parent.mkdir(parents=True)
        override.write_text("vmType: qemu")
        with patch("nipat.macos_runtime.sys.platform", "darwin"), patch("nipat.macos_runtime.platform.mac_ver", return_value=("14.7", (), "")), patch("nipat.macos_runtime.platform.machine", return_value="x86_64"), patch.object(self.runtime, "_run") as execute:
            with self.assertRaisesRegex(ValidationError, "Override"):
                self.runtime._host_check(self.manifest)
        execute.assert_not_called()

    def test_process_failure_is_logged_and_reported(self):
        failed = subprocess.CompletedProcess([], 7, "", "VZ not available")
        with patch("nipat.macos_runtime.subprocess.run", return_value=failed) as run:
            with self.assertRaisesRegex(RuntimeExecutionError, "VZ not available"):
                self.runtime._run(["limactl", "start", "nipat08"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("VZ not available", (self.runtime.directory / "setup.log").read_text())

    def test_real_runner_report_preserves_failed_step_evidence(self):
        source = Path(__file__).resolve().parents[1] / "scripts/verify_macos_runtime.py"
        spec = importlib.util.spec_from_file_location("verify_macos_runtime_fixture", source)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        app = self.home / "Fixture.app"
        resources = app / "Contents/Resources"
        (resources / "app/.distribution").mkdir(parents=True)
        (resources / "NIPAT.command").write_text("fixture")
        _write_json(resources / "app/.distribution/macos-manifest.json", self.manifest)
        self.ready_state()
        report_path = self.home / "evidence/report.json"
        with patch.object(verifier.sys, "platform", "darwin"), patch.object(verifier.Path, "home", return_value=self.home), patch.object(verifier.platform, "mac_ver", return_value=("14.7", (), "")), patch.object(verifier.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 7)]):
            report = verifier.verify(app, report_path)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][-1]["name"], "doctor")
        self.assertEqual(report["checks"][-1]["exit_code"], 7)
        self.assertEqual(json.loads(report_path.read_text()), report)
        self.assertTrue(self.runtime.state_path.exists())


if __name__ == "__main__":
    unittest.main()
