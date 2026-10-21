import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish_windows_release.py"))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
COMMIT = "a" * 40


class ReleaseGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.setup = self.root / "setup"
        self.runtime = self.root / "runtime"
        self.setup.mkdir()
        self.runtime.mkdir()
        self.sources = {"distribution-files.txt": b"distribution-files.txt\nREADME.md\n", "README.md": b"approved\n"}
        self.manifest = {
            "schema_version": 1, "version": "0.3.0a1", "release_tag": "v0.3.0a1", "source_commit": COMMIT,
            "rootfs_provenance": {"source_commit": COMMIT},
            "source_sha256": {n: hashlib.sha256(b).hexdigest() for n, b in self.sources.items()}, "assets": {},
        }
        (self.setup / "NIPAT-Setup.exe").write_bytes(b"installer fixture")
        for key, stem in (("rootfs", "nipat-wsl-rootfs"), ("scientific_image", "nipat-scientific-runtime")):
            name = f"{stem}-0.3.0a1-amd64.tar.gz"
            path = self.runtime / name
            path.write_bytes(key.encode())
            self.manifest["assets"][key] = {"file": name, "size": path.stat().st_size, "sha256": publisher.sha256(path),
                "url": f"https://github.com/{publisher.REPO}/releases/download/v0.3.0a1/{name}"}
        self.write_manifests()

    def write_manifests(self):
        data = json.dumps(self.manifest).encode()
        for folder in (self.setup, self.runtime):
            (folder / publisher.MANIFEST).write_bytes(data)
        for folder, names in ((self.setup, ["NIPAT-Setup.exe"]), (self.runtime,
            [publisher.MANIFEST] + [a["file"] for a in self.manifest["assets"].values()])):
            (folder / "SHA256SUMS").write_text("".join(f"{publisher.sha256(folder/n)}  {n}\n" for n in names))

    def prepare(self):
        return publisher.prepare_assets(self.setup, self.runtime, self.root / "release", COMMIT,
                                        read_source=lambda commit, name: self.sources[name])

    def test_combines_both_checksum_lists_without_losing_exe(self):
        self.prepare()
        result = publisher.checksums(self.root / "release/SHA256SUMS")
        self.assertEqual(len(result), 4)
        self.assertIn("NIPAT-Setup.exe", result)
        self.assertEqual(len(list((self.root / "release").iterdir())), 5)

    def test_rejects_corrupt_asset_before_staging(self):
        asset = self.manifest["assets"]["scientific_image"]["file"]
        (self.runtime / asset).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
            self.prepare()
        self.assertFalse((self.root / "release").exists())

    def test_rejects_wrong_exe_checksum(self):
        (self.setup / "NIPAT-Setup.exe").write_bytes(b"different exe")
        with self.assertRaisesRegex(ValueError, "Installer checksum"):
            self.prepare()

    def test_rejects_mixed_build_manifests(self):
        (self.runtime / publisher.MANIFEST).write_text("{}")
        with self.assertRaisesRegex(ValueError, "manifests differ"):
            self.prepare()

    def test_rejects_changed_source_and_missing_source_entry(self):
        self.sources["README.md"] = b"different source"
        with self.assertRaisesRegex(ValueError, "Source hash mismatch"):
            self.prepare()
        del self.manifest["source_sha256"]["README.md"]
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "source list"):
            self.prepare()

    def test_rejects_wrong_rootfs_provenance(self):
        self.manifest["rootfs_provenance"]["source_commit"] = "b" * 40
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "Rootfs source mismatch"):
            self.prepare()

    def test_build_must_be_successful_same_source_and_not_from_a_fork(self):
        run = {"id": 123, "head_sha": COMMIT, "status": "completed", "conclusion": "success", "event": "push",
               "path": ".github/workflows/windows-installer.yml", "repository": {"full_name": publisher.REPO},
               "head_repository": {"full_name": publisher.REPO}}
        publisher.validate_run(run, COMMIT, 123)
        for key, value in (("head_sha", "b" * 40), ("conclusion", "failure"), ("event", "pull_request"),
                           ("head_repository", {"full_name": "someone/fork"})):
            altered = copy.deepcopy(run)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.validate_run(altered, COMMIT, 123)

    def test_resume_requires_matching_draft_and_uploaded_digests(self):
        path = self.setup / "NIPAT-Setup.exe"
        files = {path.name: path}
        release = {"draft": True, "prerelease": True, "target_commitish": COMMIT,
                   "tag_name": "v0.3.0a1", "body": "notes", "assets": []}
        publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes", complete=True)
        release["assets"] = [{"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                              "digest": f"sha256:{publisher.sha256(path)}"}]
        publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes", complete=True)
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "integrity"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")
        release["draft"] = False
        with self.assertRaisesRegex(ValueError, "not a draft"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")


if __name__ == "__main__":
    unittest.main()
