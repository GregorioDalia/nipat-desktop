import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualification_evidence.py"))
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


class QualificationEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "synthetic"
        self.source.mkdir()
        (self.source / "result.csv").write_text("expected,actual\n0.602,0.602\n", encoding="utf-8")
        (self.source / "command.log").write_text("/private/runner/fixture.txt: PASS\n", encoding="utf-8")
        (self.source / "sample.bam").write_bytes(b"not published")
        self.installer_set = {"version": "0.7.2", "source_commit": "a" * 40,
                              "installer_manifest_sha256": "b" * 64,
                              "windows": {"sha256": "c" * 64}, "linux": {"sha256": "d" * 64}}
        self.output = self.root / "output"
        self.descriptor = qualification.build(self.output, self.installer_set, {"science": self.source},
                                               {"/private/runner": "${CI_WORKSPACE}"})

    def write_descriptor(self, value):
        (self.output / qualification.DESCRIPTOR).write_text(json.dumps(value), encoding="utf-8")

    def test_round_trip_retains_numeric_evidence_without_binary_inputs_or_host_roots(self):
        qualification.verify(self.output, self.installer_set)
        with zipfile.ZipFile(self.output / qualification.ARCHIVE) as handle:
            self.assertEqual(set(handle.namelist()), {"science/result.csv", "science/command.log"})
            self.assertIn(b"${CI_WORKSPACE}/fixture.txt", handle.read("science/command.log"))
            self.assertIn(b"0.602,0.602", handle.read("science/result.csv"))

    def test_rejects_source_package_substitution_and_false_scope(self):
        for key, value in (("source_commit", "e" * 40), ("windows_installer_sha256", "e" * 64),
                           ("linux_installer_sha256", "e" * 64), ("synthetic_only", False)):
            changed = copy.deepcopy(self.descriptor)
            changed[key] = value
            self.write_descriptor(changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                qualification.verify(self.output, self.installer_set)

    def test_rejects_modified_archive_even_with_same_length(self):
        path = self.output / qualification.ARCHIVE
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "bytes mismatch"):
            qualification.verify(self.output, self.installer_set)

    def test_rejects_unsafe_duplicate_oversized_or_missing_member_descriptors(self):
        for change in ("escape", "duplicate", "oversized", "missing", "wrong_hash"):
            changed = copy.deepcopy(self.descriptor)
            if change == "escape":
                changed["entries"][0]["path"] = "../escape"
            elif change == "duplicate":
                changed["entries"].append(changed["entries"][0])
            elif change == "oversized":
                changed["entries"][0]["size"] = qualification.MAX_FILE + 1
            elif change == "missing":
                changed["entries"].pop()
            else:
                changed["entries"][0]["sha256"] = "0" * 64
            self.write_descriptor(changed)
            with self.subTest(change=change), self.assertRaises(ValueError):
                qualification.verify(self.output, self.installer_set)

    def test_rejects_extra_zip_members_even_after_archive_hash_is_updated(self):
        archive = self.output / qualification.ARCHIVE
        with zipfile.ZipFile(archive, "a") as handle:
            handle.writestr("unreviewed.txt", "injected")
        self.descriptor["archive"].update(size=archive.stat().st_size,
                                          sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        self.write_descriptor(self.descriptor)
        with self.assertRaisesRegex(ValueError, "entries differ"):
            qualification.verify(self.output, self.installer_set)


if __name__ == "__main__":
    unittest.main()
