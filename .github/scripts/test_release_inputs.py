import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("release_inputs", Path(__file__).with_name("release_inputs.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseInputTests(unittest.TestCase):
    def metadata_request(self, url, token):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"id": 123}')
        with patch.dict(release.os.environ, {"GH_TOKEN": token}), \
                patch.object(release.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(release.fetch_json(url), {"id": 123})
        return opener.open.call_args.args[0]

    def test_optional_token_is_scoped_to_own_release_metadata(self):
        prefix = f"https://api.github.com/repos/{release.REPOSITORY}/releases/"
        for suffix in ("latest", "tags/v0.7.2", "tags/v0.8.10rc1"):
            with self.subTest(metadata=suffix):
                request = self.metadata_request(prefix + suffix, "test-token")
                self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
                self.assertNotIn("Authorization", request.headers)
        for url in (
            prefix + "assets/123", prefix + "tags/v0.7.2?redirect=1", prefix + "latest#fragment",
            "https://api.github.com/repos/anchore/syft/releases/latest",
            "https://api.github.com/repos/GregorioDalia/other/releases/latest",
            f"https://github.com/{release.REPOSITORY}/releases/download/v0.7.2/installer-manifest.json",
            "https://release-assets.githubusercontent.com/download",
        ):
            with self.subTest(unauthenticated=url):
                self.assertFalse(self.metadata_request(url, "test-token").has_header("Authorization"))
        self.assertFalse(self.metadata_request(prefix + "latest", "").has_header("Authorization"))

    def test_metadata_token_is_not_forwarded_on_any_approved_redirect(self):
        request = self.metadata_request(
            f"https://api.github.com/repos/{release.REPOSITORY}/releases/latest", "test-token")
        for destination in (
            f"https://api.github.com/repos/{release.REPOSITORY}/releases/tags/v0.7.2",
            f"https://github.com/{release.REPOSITORY}/releases/download/v0.7.2/installer-manifest.json",
            "https://release-assets.githubusercontent.com/download",
        ):
            with self.subTest(destination=destination):
                redirected = release.RestrictedRedirect().redirect_request(
                    request, None, 302, "Found", {}, destination)
                self.assertFalse(redirected.has_header("Authorization"))
                self.assertEqual(redirected.get_header("Accept"), "application/vnd.github+json")

    def test_asset_download_does_not_add_metadata_token(self):
        url = f"https://github.com/{release.REPOSITORY}/releases/download/v0.7.2/asset"
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"asset")
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(release.os.environ, {"GH_TOKEN": "test-token"}), \
                patch.object(release.urllib.request, "build_opener", return_value=opener):
            target = Path(temporary) / "asset"
            release.checked_download(url, target, hashlib.sha256(b"asset").hexdigest(), 5)
            self.assertEqual(target.read_bytes(), b"asset")
        opener.open.assert_called_once_with(url, timeout=120)

    def test_download_hosts_are_https_exact_and_without_credentials(self):
        for url in ("https://github.com/example", "https://release-assets.githubusercontent.com/download"):
            self.assertTrue(release.allowed_url(url))
        for url in ("http://github.com/x", "https://github.com.evil.test/x", "https://example.com/x",
                    "https://user:secret@github.com/x", "https://github.com:123/x", "file:///tmp/x"):
            with self.subTest(url=url):
                self.assertFalse(release.allowed_url(url))

    def test_verified_download_is_atomic_and_failed_bytes_do_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset"
            path.write_bytes(b"previous")
            for data, digest, size, valid in (
                (b"new", hashlib.sha256(b"new").hexdigest(), 3, True),
                (b"bad", hashlib.sha256(b"new").hexdigest(), 3, False),
                (b"long", hashlib.sha256(b"long").hexdigest(), 3, False),
                (b"x", hashlib.sha256(b"x").hexdigest(), 3, False),
            ):
                before = path.read_bytes()
                opener = Mock()
                opener.open.return_value = io.BytesIO(data)
                with patch.object(release.urllib.request, "build_opener", return_value=opener):
                    if valid:
                        release.checked_download("https://github.com/example", path, digest, size)
                        self.assertEqual(path.read_bytes(), data)
                    else:
                        with self.assertRaises(ValueError):
                            release.checked_download("https://github.com/example", path, digest, size)
                        self.assertEqual(path.read_bytes(), before)
                self.assertFalse(path.with_name("asset.partial").exists())

    def test_redirect_to_external_host_is_rejected_before_opening(self):
        with self.assertRaises(ValueError):
            release.RestrictedRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test/file")

    def test_pinned_072_upgrade_input_records_source_and_exact_github_digest(self):
        tag = "v0.7.2"
        source = "5bc05e00c7e231f7f3d501ace91131dae3bd1458"
        deb_name = "nipat-desktop_0.7.2_amd64.deb"
        deb_hash = "e623897ffa46698250b1ee32216b1ab392607b6f7e3082a1932a164ef4992675"
        manifest = json.dumps({"version": "0.7.2", "release_tag": tag, "source_commit": source}).encode()
        records = [{"name": "installer-manifest.json", "size": len(manifest),
                    "digest": "sha256:" + hashlib.sha256(manifest).hexdigest()},
                   {"name": deb_name, "size": 603740352, "digest": "sha256:" + deb_hash}]
        for item in records:
            item["browser_download_url"] = f"https://github.com/{release.REPOSITORY}/releases/download/{tag}/{item['name']}"
        metadata = {"draft": False, "tag_name": tag, "id": 123, "assets": records}
        calls = []
        def download(url, path, digest, size):
            calls.append((url, digest, size))
            path.write_bytes(manifest if path.name == "installer-manifest.json" else b"fixture; downloader tested separately")
            return path
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(release, "fetch_json", return_value=metadata) as fetch, \
                    patch.object(release, "checked_download", side_effect=download):
                paths = release.release_inputs(tag, ["deb"], root)
            fetch.assert_called_once_with(f"https://api.github.com/repos/{release.REPOSITORY}/releases/tags/v0.7.2")
            self.assertEqual(paths["deb"].name, deb_name)
            self.assertEqual(calls[-1][1:], (deb_hash, 603740352))
            provenance = json.loads((root / "release-inputs.json").read_text())
            self.assertEqual(provenance["source_commit"], source)
            self.assertEqual(provenance["files"]["deb"]["sha256"], deb_hash)
            records[-1]["name"] = "nipat-desktop_0.7.1_amd64.deb"
            with patch.object(release, "fetch_json", return_value=metadata), \
                    patch.object(release, "checked_download", side_effect=download), \
                    self.assertRaisesRegex(ValueError, "matching the requested"):
                release.release_inputs(tag, ["deb"], root)


if __name__ == "__main__":
    unittest.main()
