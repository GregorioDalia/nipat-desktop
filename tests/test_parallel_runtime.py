"""Exercise the client-to-container execution policy and per-step environment."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.errors import RuntimeExecutionError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout
from nipat_scientific.parallel import THREAD_LIMITS, execution_environment
from test_bundled_runner import engine_metadata


class ParallelRuntimeTests(unittest.TestCase):
    def test_client_passes_policy_into_owned_container_not_host_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            run = root / "runs" / "one"
            (run / "work").mkdir(parents=True)
            layout = ProjectLayout(root, root, root / "data", root / "runs", root / "compose.yaml")
            options = ExecutionOptions(execution_mode="serial", max_workers=3,
                                       dnp_block_mib=16, dnp_block_loci=20,
                                       cpus=2.5, memory_mb=6000)
            runner = DockerComposeRunner(layout, transport=DockerTransport(), options=options)
            runner._record = Mock(run_dir=run, data={})
            with patch.dict(os.environ, {"NIPAT_MAX_WORKERS": "100", "NIPAT_DNP_BLOCK_BYTES": "1"}):
                runner._write_engine_compose("sha256:" + "a" * 64)
                self.assertEqual(os.environ["NIPAT_MAX_WORKERS"], "100")
            service = json.loads((run / "work/engine-compose.json").read_text())["services"]["scientific"]
            environment = service["environment"]
            self.assertEqual(environment["NIPAT_EXECUTION_MODE"], "serial")
            self.assertEqual(environment["NIPAT_MAX_WORKERS"], "3")
            self.assertEqual(environment["NIPAT_DNP_BLOCK_BYTES"], str(16 * 1024**2))
            self.assertEqual(environment["NIPAT_DNP_BLOCK_LOCI"], "20")
            self.assertEqual(environment["NIPAT_CPU_LIMIT"], "2.5")
            self.assertEqual(environment["NIPAT_MEMORY_LIMIT_MIB"], "6000")
            self.assertEqual(service["mem_limit"], 6000 * 1024**2)
            self.assertTrue(all(environment[name] == "1" for name in THREAD_LIMITS))

    def test_old_runtime_is_rejected_instead_of_silently_ignoring_parallel_settings(self):
        for change in ("capability", "module", "workflow", "serial"):
            with self.subTest(change=change):
                metadata = copy.deepcopy(engine_metadata())
                if change == "capability":
                    del metadata["parallel_execution"]
                elif change == "module":
                    del metadata["preparation"]["file_sha256"]["lib/nipat_scientific/parallel.R"]
                elif change == "workflow":
                    metadata["parallel_execution"]["workflows"].remove("snp-call")
                else:
                    metadata["parallel_execution"]["modes"] = ["auto"]
                with self.assertRaisesRegex(RuntimeExecutionError, "nipat-parallel-v1"):
                    DockerComposeRunner._validate_engine_description(metadata)

    def test_scoped_thread_limits_and_diagnostics_survive_error_without_environment_leak(self):
        inherited = {name: "16" for name in THREAD_LIMITS}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "NIPAT_PARALLEL_LOG_DIR": "old", **inherited,
        }):
            work = Path(temporary) / "work"
            with self.assertRaisesRegex(ValueError, "test"):
                with execution_environment(work) as directory:
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(os.environ["NIPAT_PARALLEL_LOG_DIR"], str(work / "parallel"))
                    self.assertTrue(all(os.environ[name] == "1" for name in THREAD_LIMITS))
                    raise ValueError("test")
            self.assertEqual(os.environ["NIPAT_PARALLEL_LOG_DIR"], "old")
            self.assertTrue(all(os.environ[name] == value for name, value in inherited.items()))

    def test_native_thread_limits_need_no_work_directory_and_preserve_diagnostics(self):
        with patch.dict(os.environ, {"NIPAT_PARALLEL_LOG_DIR": "existing", "VROOM_THREADS": "8"}):
            with execution_environment() as directory:
                self.assertIsNone(directory)
                self.assertEqual(os.environ["NIPAT_PARALLEL_LOG_DIR"], "existing")
                self.assertTrue(all(os.environ[name] == "1" for name in THREAD_LIMITS))
            self.assertEqual(os.environ["VROOM_THREADS"], "8")
            self.assertEqual(os.environ["NIPAT_PARALLEL_LOG_DIR"], "existing")


if __name__ == "__main__":
    unittest.main()
