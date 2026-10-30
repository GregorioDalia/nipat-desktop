"""Client-side Lima selection and isolated child interpreter bootstrapping."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nipat.errors import ValidationError
from nipat.execution.transport import DockerTransport, LimaDockerTransport


@unittest.skipUnless(os.name == "posix", "Lima transport targets POSIX hosts")
class LimaTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nl-", dir="/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.project = self.home / "application"
        self.project.mkdir()
        self.environment = {
            "NIPAT_BACKEND": "lima", "NIPAT_PROJECT_DIR": str(self.project),
            "NIPAT_WORKSPACE_DIR": str(self.home / "Library/Application Support/NIPAT-Experimental08"),
            "NIPAT_LIMA_EXECUTABLE": str(self.home / "bundle/lima/bin/limactl"),
            "LIMA_HOME": str(self.home / ".nipat08/lima"),
        }
        self.enterContext(patch.dict(os.environ, self.environment, clear=True))
        self.enterContext(patch("nipat.macos_runtime.Path.home", return_value=self.home))

    def test_backend_selection_requires_explicit_private_home(self):
        transport = DockerTransport.from_environment(dry_run=True)
        self.assertIsInstance(transport, LimaDockerTransport)
        self.assertTrue(transport.dry_run)
        self.assertEqual(transport.metadata["lima_instance"], "nipat08")
        with patch.dict(os.environ, {"LIMA_HOME": str(self.home / ".lima")}):
            with self.assertRaisesRegex(ValidationError, "LIMA_HOME"):
                DockerTransport.from_environment()

    def test_shell_and_inherited_contexts_cannot_be_forwarded(self):
        transport = DockerTransport.from_environment()
        with self.assertRaises(ValidationError):
            transport.command(["sh", "-c", "echo bad"], {})
        command = transport.command(["docker", "compose", "version"], {
            "DOCKER_CONTEXT": "unrelated", "DOCKER_HOST": "tcp://example:2375", "SSH": "evil",
            "NIPAT_RUNTIME_IMAGE": "sha256:" + "a" * 64,
        })
        self.assertFalse(any("unrelated" in item or "example:" in item or "evil" in item for item in command))
        self.assertIn("SSH=/usr/bin/ssh", command)
        self.assertIn("unix:///var/run/docker.sock", command)
        self.assertEqual(command[-2:], ["compose", "version"])

    def test_prepare_command_bootstraps_src_with_isolated_python(self):
        package = self.project / "src/nipat"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "macos_runtime.py").write_text("import sys; print('fixture:' + ','.join(sys.argv[1:]))")
        transport = DockerTransport.from_environment()
        command = transport.ensure_command()
        self.assertEqual(command[0], sys.executable)
        self.assertIn("-I", command)
        result = subprocess.run(command, cwd=self.home, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "fixture:ensure")


if __name__ == "__main__":
    unittest.main()
