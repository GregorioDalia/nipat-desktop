"""Execution boundaries for image-owned scientific workflows."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.mounts import InputMounts
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport, WslDockerTransport, _windows_path
from nipat.paths import ProjectLayout


IMAGE_ID = "sha256:" + "a" * 64


def engine_metadata():
    return {
        "schema_version": 1, "interface": "native-r-v1",
        "manifest": {"path": "scientific/SHA256SUMS", "sha256": "b" * 64},
        "workflows": {
            name: {"script": f"scientific/vendor/{name}/main.R", "sha256": "c" * 64}
            for name in ("dnp-call", "snp-call", "contamination", "cpi")
        },
        "workflow_interfaces": {"contamination": "contamination-v1", "snp-call": "snp-call-v1",
                                "dnp-call": "dnp-call-v1", "cpi": "cpi-v1"},
        "preparation": {
            "interface": "workflow-preparation-v1",
            "file_sha256": {name: "d" * 64 for name in (
                "engine/main.py", "lib/nipat_scientific/__init__.py",
                "lib/nipat_scientific/errors.py", "lib/nipat_scientific/panels.py",
                "lib/nipat_scientific/files.py", "lib/nipat_scientific/contamination.py",
                "lib/nipat_scientific/snp.py", "lib/nipat_scientific/dnp.py",
                "lib/nipat_scientific/cpi.py",
            )},
        },
    }


class BundledRunnerTests(unittest.TestCase):
    def setUp(self):
        # platform.platform() may spawn a process on Linux; keep that host probe
        # separate from the Docker subprocesses controlled by these tests.
        self.enterContext(patch("nipat.execution.tracking.platform.platform", return_value="test-host"))
        self.temp = tempfile.TemporaryDirectory(prefix="nipat bundled ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "client"
        self.project.mkdir()
        # A bundled workflow does not need any scientific file on the client.
        (self.project / "compose.yaml").write_text(
            "services:\n  scientific:\n    image: configured:custom\n", encoding="utf-8",
        )
        self.layout = ProjectLayout(self.project, self.root, self.root / "data",
                                    self.root / "runs", self.project / "compose.yaml")
        self.source = self.root / "source $VALUE, è.TSV"
        self.source.write_text("original input\n", encoding="utf-8")
        self.mounts = InputMounts(self.layout)
        self.mounts.bind_file(self.source, target="/workspace/inputs/sample_001.tsv")
        self.runner = DockerComposeRunner(self.layout, transport=DockerTransport())
        self.stdout = io.StringIO()

    def captured(self, description=None):
        return [
            "linux", '{"services":{"scientific":{"image":"configured:custom"}}}',
            json.dumps({"id": IMAGE_ID, "os": "linux", "architecture": "amd64"}),
            "R version fixture\nsamtools fixture",
            json.dumps(engine_metadata() if description is None else description),
        ]

    def process(self, code=0):
        process = MagicMock()
        process.stdout = io.StringIO("scientific output\n")
        process.wait.return_value = code
        process.poll.return_value = code
        return process

    def begin(self, name="bundled", workflow="contamination"):
        run = self.layout.new_run_dir(workflow, name)
        context = self.runner.record_run(
            run, workflow=workflow, inputs=[self.source], parameters={},
            mounts=self.mounts, bundled_workflow=workflow,
        )
        return run, context

    def test_doctor_verifies_the_image_without_host_scientific_sources_or_run(self):
        self.assertFalse((self.project / "scientific").exists())
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.shutil.which", return_value="docker",
        ), patch.object(self.runner, "_capture", side_effect=["Compose v2", *self.captured()]) as capture:
            self.runner.doctor(check_runtime=True)
        self.assertIsNone(self.runner._record)
        self.assertIsNone(self.runner._image_id)
        self.assertEqual(list(self.layout.runs_dir.iterdir()), [])
        self.assertIn("DNPcall, SNPcall, Contamination, CPI", self.stdout.getvalue())
        probes = [call.args[0] for call in capture.call_args_list if call.args[0][:2] == ["docker", "run"]]
        self.assertEqual(len(probes), 2)
        for command in probes:
            self.assertIn(IMAGE_ID, command)
            self.assertIn("--pull=never", command)
            self.assertIn("--read-only", command)
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertNotIn("--mount", command)
            self.assertNotIn("--volume", command)
            self.assertNotIn("-v", command)
        self.assertEqual(probes[-1][-4:], ["python3", "/opt/nipat/engine/main.py", "describe", "--json"])

    def test_doctor_rejects_each_missing_or_wrong_workflow_contract(self):
        for workflow in ("dnp-call", "snp-call", "contamination", "cpi"):
            for value in (None, "incompatible-v2"):
                description = engine_metadata()
                if value is None:
                    del description["workflow_interfaces"][workflow]
                else:
                    description["workflow_interfaces"][workflow] = value
                with self.subTest(workflow=workflow, value=value), redirect_stdout(self.stdout), patch(
                    "nipat.execution.runner.shutil.which", return_value="docker",
                ), patch.object(self.runner, "_capture", side_effect=["Compose v2", *self.captured(description)]):
                    with self.assertRaisesRegex(RuntimeExecutionError, "quattro workflow"):
                        self.runner.doctor(check_runtime=True)
                self.assertIsNone(self.runner._image_id)

    def test_doctor_rejects_incomplete_scientific_identity(self):
        description = engine_metadata()
        del description["preparation"]["file_sha256"]["lib/nipat_scientific/cpi.py"]
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.shutil.which", return_value="docker",
        ), patch.object(self.runner, "_capture", side_effect=["Compose v2", *self.captured(description)]):
            with self.assertRaisesRegex(RuntimeExecutionError, "metadati scientifici completi"):
                self.runner.doctor(check_runtime=True)
        self.assertIsNone(self.runner._image_id)

    def test_dry_run_doctor_rejects_diagnostics_without_starting_processes(self):
        self.runner.dry_run = True
        with patch("nipat.execution.runner.subprocess.run") as execute:
            with self.assertRaisesRegex(ValidationError, "rimuovere --dry-run"):
                self.runner.doctor(check_runtime=True)
        execute.assert_not_called()
        self.assertFalse(self.layout.runs_dir.exists())

    def test_isolated_service_has_only_selected_files_and_this_run(self):
        original = self.source.read_bytes()
        run, context = self.begin()
        with redirect_stdout(self.stdout), patch.object(
            self.runner, "_capture", side_effect=self.captured(),
        ) as capture, patch(
            "nipat.execution.runner.subprocess.Popen", return_value=self.process(),
        ) as popen:
            with context:
                self.runner.run(["python3", "/opt/nipat/engine/main.py", "execute",
                                 "contamination", "--request", "/workspace/request.json"])
        document = json.loads((run / "work/engine-compose.json").read_text(encoding="utf-8"))
        service = document["services"]["scientific"]
        self.assertEqual(service["image"], IMAGE_ID)
        self.assertTrue(service["read_only"])
        self.assertEqual(service["network_mode"], "none")
        self.assertIn("/tmp:rw,nosuid,nodev,size=128m", service["tmpfs"])
        self.assertEqual(service["environment"]["TMPDIR"], "/tmp")
        volumes = service["volumes"]
        self.assertEqual(len(volumes), 2)
        self.assertEqual({v["target"] for v in volumes}, {
            "/workspace/inputs/sample_001.tsv", str(self.layout.container_path(run)),
        })
        self.assertEqual([v["read_only"] for v in volumes], [True, False])
        self.assertTrue(all(v["bind"]["create_host_path"] is False for v in volumes))
        self.assertNotIn(str(self.project), {v["source"] for v in volumes})
        argv = popen.call_args.args[0]
        self.assertEqual([argv[i + 1] for i, arg in enumerate(argv) if arg == "-f"],
                         [str(run / "work/engine-compose.json")])
        self.assertIn("NIPAT_RUNTIME_IMAGE", popen.call_args.kwargs["env"])
        self.assertEqual(popen.call_args.kwargs["env"]["NIPAT_RUNTIME_IMAGE"], IMAGE_ID)
        self.assertEqual(capture.call_args_list[1].args[0][:4],
                         ["docker", "compose", "-f", str(self.layout.compose_file)])
        self.assertIn("configured:custom", capture.call_args_list[2].args[0])
        for check in capture.call_args_list[-2:]:
            probe = check.args[0]
            self.assertIn(IMAGE_ID, probe)
            self.assertIn("--read-only", probe)
            self.assertEqual(probe[probe.index("--network") + 1], "none")
            self.assertNotIn("--mount", probe)
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["runtime"]["engine"], engine_metadata())
        self.assertEqual(record["source"]["role"], "client")
        self.assertEqual(record["engine_verification"], "verified")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIsNone(self.runner._engine_compose_file)
        self.assertIsNone(self.runner._bundled_workflow)
        self.assertIsNone(self.runner._image_id)

    def test_missing_or_invalid_contract_fails_before_analysis_and_is_recorded(self):
        variants = []
        for key in ("workflow_interfaces", "preparation", "manifest", "workflows"):
            value = engine_metadata()
            del value[key]
            variants.append(value)
        value = engine_metadata()
        value["workflow_interfaces"]["contamination"] = "contamination-v2"
        variants.append(value)
        value = engine_metadata()
        value["preparation"]["file_sha256"]["engine/main.py"] = "invalid"
        variants.append(value)
        value = engine_metadata()
        value["preparation"]["file_sha256"]["lib/nipat_scientific/../escape.py"] = "e" * 64
        variants.append(value)
        value = engine_metadata()
        del value["workflows"]["cpi"]
        variants.append(value)
        variants.extend([None, [], "not an object"])
        for index, description in enumerate(variants):
            with self.subTest(index=index):
                answers = self.captured()
                answers[-1] = json.dumps(description)
                run, context = self.begin(f"invalid-{index}")
                with redirect_stdout(self.stdout), patch.object(
                    self.runner, "_capture", side_effect=answers,
                ), patch("nipat.execution.runner.subprocess.Popen") as popen:
                    with self.assertRaisesRegex(RuntimeExecutionError, "contratto Contamination"):
                        with context:
                            self.fail("An incompatible image must not enter the workflow.")
                popen.assert_not_called()
                record = json.loads((run / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["commands"], [])
                self.assertIsNone(self.runner._bundled_workflow)

    def test_callers_run_with_pinned_engine_without_client_scientific_sources(self):
        for workflow in ("snp-call", "dnp-call", "cpi"):
            with self.subTest(workflow=workflow):
                run, context = self.begin(f"{workflow}-bundled", workflow=workflow)
                with redirect_stdout(self.stdout), patch.object(
                    self.runner, "_capture", side_effect=self.captured(),
                ), patch("nipat.execution.runner.subprocess.Popen", return_value=self.process()) as popen:
                    with context:
                        self.runner.run(["python3", "/opt/nipat/engine/main.py", "execute",
                                         workflow, "--request", "/workspace/request.json"])
                self.assertFalse((self.project / "scientific").exists())
                record = json.loads((run / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(record["status"], "succeeded")
                self.assertEqual(record["bundled_workflow"], workflow)
                self.assertEqual(record["runtime"]["image_id"], IMAGE_ID)
                self.assertEqual(record["runtime"]["engine"]["workflow_interfaces"][workflow],
                                 f"{workflow}-v1")
                self.assertEqual(record["source"]["role"], "client")
                service = json.loads((run / "work/engine-compose.json").read_text(encoding="utf-8"))[
                    "services"]["scientific"]
                self.assertEqual(service["image"], IMAGE_ID)
                self.assertEqual(service["network_mode"], "none")
                self.assertTrue(service["read_only"])
                self.assertEqual({volume["target"] for volume in service["volumes"]}, {
                    "/workspace/inputs/sample_001.tsv", str(self.layout.container_path(run)),
                })
                self.assertEqual([volume["read_only"] for volume in service["volumes"]], [True, False])
                popen.assert_called_once()
                command = popen.call_args.args[0]
                self.assertEqual([command[i + 1] for i, arg in enumerate(command) if arg == "-f"],
                                 [str(run / "work/engine-compose.json")])

    def test_callers_require_their_own_contract_and_preparation_source(self):
        for workflow, module, label in (("snp-call", "snp", "SNPcall"),
                                        ("dnp-call", "dnp", "DNPcall"), ("cpi", "cpi", "CPI")):
            missing_interface = engine_metadata()
            del missing_interface["workflow_interfaces"][workflow]
            wrong_interface = engine_metadata()
            wrong_interface["workflow_interfaces"][workflow] = "contamination-v1"
            missing_source = engine_metadata()
            del missing_source["preparation"]["file_sha256"][f"lib/nipat_scientific/{module}.py"]
            for index, description in enumerate((missing_interface, wrong_interface, missing_source)):
                with self.subTest(workflow=workflow, index=index):
                    run, context = self.begin(f"{workflow}-incompatible-{index}", workflow=workflow)
                    with redirect_stdout(self.stdout), patch.object(
                        self.runner, "_capture", side_effect=self.captured(description),
                    ), patch("nipat.execution.runner.subprocess.Popen") as popen:
                        with self.assertRaisesRegex(RuntimeExecutionError,
                                                    f"contratto {label}.*{workflow}-v1"):
                            with context:
                                self.fail(f"An incompatible image must not execute {label}.")
                    popen.assert_not_called()
                    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
                    self.assertEqual(record["status"], "failed")
                    self.assertEqual(record["commands"], [])
                    self.assertFalse((run / "work/engine-compose.json").exists())

    def test_failed_engine_probe_is_actionable_and_tracked(self):
        answers = self.captured()
        answers[-1] = RuntimeExecutionError("python3: missing bundled entry point")
        run, context = self.begin("old-image")
        with redirect_stdout(self.stdout), patch.object(self.runner, "_capture", side_effect=answers):
            with self.assertRaisesRegex(RuntimeExecutionError, "motore scientifico incorporato"):
                with context:
                    self.fail("Old image must not reach the workflow.")
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["runtime"]["image_id"], IMAGE_ID)

    def test_failed_workflow_exit_code_is_propagated(self):
        run, context = self.begin("failure")
        with redirect_stdout(self.stdout), patch.object(
            self.runner, "_capture", side_effect=self.captured(),
        ), patch("nipat.execution.runner.subprocess.Popen", return_value=self.process(7)):
            with self.assertRaisesRegex(RuntimeExecutionError, "codice 7"):
                with context:
                    self.runner.run(["python3", "/opt/nipat/engine/main.py", "execute"])
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["commands"][0]["returncode"], 7)

    def test_interrupt_keeps_existing_named_container_cleanup(self):
        process = MagicMock()
        process.stdout.__iter__.side_effect = KeyboardInterrupt()
        process.poll.return_value = 130
        run, context = self.begin("cancelled")
        with redirect_stdout(self.stdout), patch.object(
            self.runner, "_capture", side_effect=self.captured(),
        ), patch("nipat.execution.runner.subprocess.Popen", return_value=process), patch.object(
            self.runner, "_stop_container", return_value={"status": "removed"},
        ) as stop:
            with self.assertRaises(KeyboardInterrupt):
                with context:
                    self.runner.run(["python3", "/opt/nipat/engine/main.py", "execute"])
        stop.assert_called_once()
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "interrupted")
        self.assertEqual(record["commands"][0]["container_cleanup"]["status"], "removed")

    def test_wsl_dry_run_translates_and_escapes_mounts_without_launching_processes(self):
        self.runner.dry_run = True
        self.runner._transport = WslDockerTransport("NIPAT-Test", dry_run=True)

        def windows_path(path):
            value = Path(path)
            if value.is_relative_to(self.root):
                return PureWindowsPath(r"D:\NIPAT test $ENV, è").joinpath(*value.relative_to(self.root).parts)
            return _windows_path(path)

        run, context = self.begin("planned")
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.transport._windows_path", side_effect=windows_path,
        ), patch("nipat.execution.transport._drive_type", return_value=3), patch(
            "nipat.execution.runner.subprocess.run",
        ) as execute, patch("nipat.execution.runner.subprocess.Popen") as popen:
            with context:
                self.runner.run(["python3", "/opt/nipat/engine/main.py", "execute"])
        execute.assert_not_called()
        popen.assert_not_called()
        document = json.loads((run / "work/engine-compose.json").read_text(encoding="utf-8"))
        service = document["services"]["scientific"]
        self.assertEqual(service["image"], "${NIPAT_RUNTIME_IMAGE:-nipat-scientific-runtime:0.6.0}")
        for volume in service["volumes"]:
            self.assertTrue(volume["source"].startswith("/mnt/d/NIPAT test $$ENV, è/"))
        self.assertIn("$$VALUE", service["volumes"][0]["source"])
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["engine_verification"], "not_run_dry_run")
        self.assertNotIn("engine", record["runtime"])
        argv = record["commands"][0]["argv"]
        self.assertEqual(argv[0], "wsl.exe")
        self.assertEqual([argv[i + 1] for i, arg in enumerate(argv) if arg == "-f"],
                         ["/mnt/d/NIPAT test $ENV, è/runs/planned/work/engine-compose.json"])


if __name__ == "__main__":
    unittest.main()
