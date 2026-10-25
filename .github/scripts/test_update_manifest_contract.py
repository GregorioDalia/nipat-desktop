"""Exercise the publication-to-client contract with exact, local HTTP fixtures."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from nipat.updates import API, WEB, UpdateClient

SPEC = importlib.util.spec_from_file_location("update_publisher", Path(__file__).with_name("publish_windows_release.py"))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class Response(io.BytesIO):
    def __init__(self, url, contents):
        super().__init__(contents)
        self.url = url
        self.headers = {"Content-Length": str(len(contents))}

    def geturl(self):
        return self.url


class PublishedUpdateContract(unittest.TestCase):
    def test_accepted_pair_is_discoverable_downloadable_and_channel_filtered(self):
        for channel in ("testing", "stable"):
            with self.subTest(channel=channel):
                self.check_published_pair(channel)

    def check_published_pair(self, channel):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit = "c" * 40
            version, tag = "0.6.1", "v0.6.1"
            manifest = {"version": version, "release_tag": tag, "source_commit": commit}
            pair = {"version": version, "source_commit": commit}
            for system, name in (("windows", "NIPAT-Setup.exe"),
                                 ("linux", "nipat-desktop_0.6.1_amd64.deb")):
                path = root / name
                path.write_bytes(b"fixture bytes for verified " + system.encode())
                pair[system] = {"file": name, "sha256": publisher.sha256(path)}
            document = publisher.write_update_manifest(root, manifest, pair, channel)
            release_url = f"{WEB}/releases/tag/{tag}"
            payloads = {}
            assets = []
            for name in ("update-manifest.json", "NIPAT-Setup.exe", "nipat-desktop_0.6.1_amd64.deb"):
                content = (root / name).read_bytes()
                url = f"{WEB}/releases/download/{tag}/{name}"
                payloads[url] = content
                assets.append({"name": name, "state": "uploaded", "size": len(content),
                               "browser_download_url": url,
                               "digest": "sha256:" + hashlib.sha256(content).hexdigest()})
            release = {"tag_name": tag, "draft": False, "prerelease": channel == "testing",
                       "published_at": "2026-10-25T12:00:00Z", "html_url": release_url, "assets": assets}
            payloads[f"{API}/releases?per_page=100&page=1"] = json.dumps([release]).encode()
            payloads[f"{API}/git/ref/tags/{tag}"] = json.dumps({
                "ref": "refs/tags/" + tag, "object": {"type": "commit", "sha": commit},
            }).encode()
            requests = []

            def open_fixture(request, timeout):
                requests.append(request.full_url)
                return Response(request.full_url, payloads[request.full_url])

            client = UpdateClient(opener=open_fixture)
            for platform, system in (("windows-x86_64", "windows"), ("linux-x86_64", "linux")):
                check = client.check("0.6.0", "testing", platform)
                self.assertEqual(check.status, "available", check.message)
                self.assertEqual(check.offer.source_commit, commit)
                self.assertEqual(check.offer.asset.sha256, pair[system]["sha256"])
                package = client.download(check.offer, root / "cache" / platform / version)
                self.assertEqual(package.read_bytes(), (root / pair[system]["file"]).read_bytes())
                self.assertEqual(check.offer.release_notes_url, document["release_notes_url"])
            stable = client.check("0.6.0", "stable", "windows-x86_64")
            if channel == "stable":
                self.assertEqual(stable.status, "available", stable.message)
                self.assertEqual(stable.offer.channel, "stable")
            else:
                self.assertIsNone(stable.offer)
            self.assertIsNone(client.check("0.6.2", "testing", "windows-x86_64").offer)
            self.assertTrue(all(url.startswith((API + "/", WEB + "/releases/")) for url in requests))


if __name__ == "__main__":
    unittest.main()
