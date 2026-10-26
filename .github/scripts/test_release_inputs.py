import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("release_inputs", Path(__file__).with_name("release_inputs.py"))
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseInputTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
