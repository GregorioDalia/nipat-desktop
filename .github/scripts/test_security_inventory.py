import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("security_inventory", Path(__file__).with_name("security_inventory.py"))
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)


def docker_tar():
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w") as archive:
        data = b'[{"Config":"config.json","RepoTags":[],"Layers":[]}]'
        member = tarfile.TarInfo("manifest.json")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return content.getvalue()


class ScientificScanInputTests(unittest.TestCase):
    def test_real_gzip_is_unwrapped_as_plain_tar_without_extracting_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "published.tar.gz"
            raw = docker_tar()
            compressed = gzip.compress(raw)
            source.write_bytes(compressed)
            with security.scientific_scan_tar(source, root) as target:
                self.assertEqual(target.read_bytes(), raw)
                with tarfile.open(target, "r:") as archive:
                    self.assertEqual(archive.getnames(), ["manifest.json"])
                self.assertFalse((target.parent / "manifest.json").exists())
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), compressed)
            self.assertEqual(list(root.iterdir()), [source])

    def test_corrupt_truncated_empty_or_oversized_gzip_is_rejected_and_removed(self):
        compressed = gzip.compress(docker_tar())
        corrupt = compressed[:-8] + bytes([compressed[-8] ^ 1]) + compressed[-7:]
        for data, maximum in ((corrupt, 20000), (compressed[:-4], 20000),
                              (gzip.compress(b""), 20000), (compressed, 10)):
            with self.subTest(data=data[:8], maximum=maximum), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "published.tar.gz"
                source.write_bytes(data)
                with self.assertRaises((OSError, EOFError, ValueError)):
                    with security.scientific_scan_tar(source, root, maximum=maximum):
                        self.fail("Invalid scan input must never reach the scanner")
                self.assertEqual(list(root.iterdir()), [source])
                self.assertEqual(source.read_bytes(), data)

    def test_disk_reserve_and_scanner_failure_remove_temporary_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "published.tar.gz"
            source.write_bytes(gzip.compress(docker_tar()))
            with patch.object(security.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(ValueError, "free space"):
                    with security.scientific_scan_tar(source, root):
                        self.fail("The scanner cannot run without temporary space")
            with self.assertRaisesRegex(RuntimeError, "scanner failed"):
                with security.scientific_scan_tar(source, root) as target:
                    self.assertTrue(target.is_file())
                    raise RuntimeError("scanner failed")
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [source])

    def test_report_passes_plain_tar_to_syft_and_preserves_published_identity(self):
        for fail_scanner in (False, True):
            with self.subTest(fail_scanner=fail_scanner), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "report"
                raw = docker_tar()
                compressed = gzip.compress(raw)
                expected_hash = hashlib.sha256(compressed).hexdigest()
                scanned = []

                def fetch_inputs(tag, kinds, destination):
                    destination.mkdir()
                    scientific = destination / "scientific.tar.gz"
                    scientific.write_bytes(compressed)
                    rootfs = destination / "rootfs.tar.gz"
                    rootfs.write_bytes(b"rootfs fixture")
                    (destination / "release-inputs.json").write_text(json.dumps({
                        "tag": "v0.7.2", "files": {"scientific_image": {"sha256": expected_hash}},
                    }))
                    return {"rootfs": rootfs, "scientific_image": scientific}

                def scanner(command, destination):
                    if command[0] == "syft" and command[1].startswith("docker-archive:"):
                        target = Path(command[1].removeprefix("docker-archive:"))
                        scanned.append(target)
                        self.assertEqual(target.read_bytes(), raw)
                        if fail_scanner:
                            raise subprocess.CalledProcessError(1, command)
                    destination.write_text(json.dumps({"matches": [], "descriptor": {"db": {}}}))

                with patch.object(security.release, "release_inputs", side_effect=fetch_inputs), \
                        patch.object(security, "install_tool", side_effect=lambda name, _: Path(name)), \
                        patch.object(security, "run_to_file", side_effect=scanner), \
                        patch.object(security.subprocess, "run") as docker, \
                        patch("sys.argv", ["security_inventory.py", "--output-dir", str(output)]):
                    if fail_scanner:
                        with self.assertRaises(subprocess.CalledProcessError):
                            security.main()
                    else:
                        security.main()
                summary = json.loads((output / "security-summary.json").read_text())
                self.assertEqual(summary["status"], "failed" if fail_scanner else "completed")
                self.assertEqual(summary["release"]["files"]["scientific_image"]["sha256"], expected_hash)
                self.assertEqual(set(summary["archives"]), set() if fail_scanner else {"scientific", "wsl"})
                self.assertEqual((output / "inputs/scientific.tar.gz").read_bytes(), compressed)
                self.assertEqual(len(scanned), 1)
                self.assertFalse(scanned[0].exists())
                self.assertEqual(list(output.glob("scan-input-*")), [])
                self.assertEqual(docker.call_args_list[-1].args[0][:3], ["docker", "image", "rm"])


if __name__ == "__main__":
    unittest.main()
