from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import tempfile
import unittest

from nipat_scientific.dnp import prepare_dnp
from nipat_scientific.errors import ValidationError


class DnpEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat_dnp_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.panel = self.inputs / "panel with spaces à.txt"
        self.panel.write_bytes(b"chr1 100 101 ac gt\r\nchr2 200 201 TA CG\r\n")
        self.reference = self.inputs / "genome.fa"
        self.reference.write_bytes(b">chr1\nACGT\n")
        Path(str(self.reference) + ".fai").write_bytes(b"chr1\t4\t6\t4\t5\n")
        self.bam = self.inputs / "sample_0001.bam"
        self.bam.write_bytes(b"BAM fixture\x00")
        self.run = self.root / "run with spaces = à"
        self.request = {
            "schema_version": 1, "workflow": "dnp-call", "panel": str(self.panel),
            "samples": [{"path": str(self.bam), "sample_id": "sample_0001"}],
            "reference": str(self.reference), "parallel": False,
            "work_dir": str(self.run / "work"), "out_dir": str(self.run / "output"),
        }

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): (
                ("symlink", str(path.readlink())) if path.is_symlink()
                else ("directory", None) if path.is_dir() else ("file", path.read_bytes())
            )
            for path in self.root.rglob("*")
        }

    def assert_rejected_without_writes(self, request):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            prepare_dnp(request)
        self.assertEqual(self.snapshot(), before)

    def test_prepares_native_arguments_and_preserves_original_inputs(self):
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        prepared = prepare_dnp(self.request)
        self.assertEqual(prepared.working_dir, self.run)
        self.assertEqual(prepared.native_arguments, [
            "--bamlist=work/bamlist.txt", "--DNPs=work/DNP_list.txt",
            "--out=output", f"--reference={self.reference.as_posix()}",
        ])
        self.assertEqual((self.run / "work/DNP_list.txt").read_bytes(),
                         b"chr1\t100\t101\tAC\tGT\nchr2\t200\t201\tTA\tCG\n")
        self.assertEqual((self.run / "work/bamlist.txt").read_bytes(),
                         (self.bam.as_posix() + "\n").encode())
        self.assertEqual({path: path.read_bytes() for path in self.inputs.iterdir()}, before)
        self.assertEqual({path.name for path in (self.run / "work").iterdir()},
                         {"DNP_list.txt", "bamlist.txt", "input-validation.json"})
        self.assertEqual(list((self.run / "output").iterdir()), [])
        self.assertFalse(any(path.is_symlink() for path in self.run.rglob("*")))

    def test_multiple_bams_keep_request_order_and_parallel_option(self):
        samples = []
        for number in range(1, 4):
            sample_id = f"sample_{number:04d}"
            path = self.inputs / f"{sample_id}.bam"
            path.write_bytes(f"BAM {number}".encode())
            samples.append({"path": str(path), "sample_id": sample_id})
        request = {**self.request, "samples": samples, "parallel": True}
        prepared = prepare_dnp(request)
        self.assertEqual(prepared.native_arguments[-1], "--parallel")
        self.assertEqual((self.run / "work/bamlist.txt").read_text().splitlines(),
                         [Path(sample["path"]).as_posix() for sample in samples])

    def test_safe_reference_alias_cannot_change_native_option_selection(self):
        # These are the actual unanchored regular expressions in upstream R.
        # Its parser takes the first matching argument, even for a partial flag.
        for suffix in ("--out", "--ou", "--bamlist", "--DNPs", "--reference"):
            reference = self.inputs / suffix / "genome.fa"
            reference.parent.mkdir()
            reference.write_bytes(self.reference.read_bytes())
            Path(str(reference) + ".fai").write_bytes(b"index")
            request = {**self.request, "reference": str(reference),
                       "work_dir": str(self.root / suffix / "work"),
                       "out_dir": str(self.root / suffix / "output")}
            with self.subTest(suffix=suffix):
                prepared = prepare_dnp(request)
                expected = {
                    "--bamlist*": "--bamlist=work/bamlist.txt",
                    "--DNPs*": "--DNPs=work/DNP_list.txt",
                    "--out*": "--out=output",
                    "--reference*": f"--reference={reference.as_posix()}",
                }
                for expression, argument in expected.items():
                    self.assertEqual(next(arg for arg in prepared.native_arguments
                                          if re.search(expression, arg)), argument)

    def test_bam_indexes_are_optional_and_existing_indexes_unchanged(self):
        for suffix in (".bam.bai", ".bai", ".bam.csi", ".csi"):
            (self.inputs / ("sample_0001" + suffix)).write_bytes(b"existing index")
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        prepare_dnp(self.request)
        self.assertEqual({path: path.read_bytes() for path in self.inputs.iterdir()}, before)

    def test_existing_empty_directories_and_request_metadata_are_allowed(self):
        (self.run / "work").mkdir(parents=True)
        (self.run / "output").mkdir()
        metadata = self.run / "work/engine-request.json"
        metadata.write_bytes(b"existing request metadata")
        prepare_dnp(self.request)
        self.assertEqual(metadata.read_bytes(), b"existing request metadata")

    def test_strict_schema_and_types_fail_before_any_writes(self):
        cases = [None, [], "request", {}, {**self.request, "extra": 1}]
        for field in self.request:
            cases.append({key: value for key, value in self.request.items() if key != field})
        for value in (True, False, "1", 1.0, 2, None):
            cases.append({**self.request, "schema_version": value})
        for value in (1, 0, "false", [], None):
            cases.append({**self.request, "parallel": value})
        for value in ("cpi", None, []):
            cases.append({**self.request, "workflow": value})
        for value in (None, [], {}, "sample", [None], [{}], [{"path": str(self.bam)}],
                      [{**self.request["samples"][0], "extra": True}]):
            cases.append({**self.request, "samples": value})
        for number, case in enumerate(cases):
            with self.subTest(number=number):
                self.assert_rejected_without_writes(case)

    def test_paths_must_be_absolute_strings_without_control_characters(self):
        for field in ("panel", "reference", "work_dir", "out_dir", "sample_path"):
            for value in (None, [], 1, "", "relative.txt", "\0", str(self.root) + "\n"):
                case = deepcopy(self.request)
                if field == "sample_path":
                    case["samples"][0]["path"] = value
                else:
                    case[field] = value
                with self.subTest(field=field, value=value):
                    self.assert_rejected_without_writes(case)

    def test_sample_alias_and_basename_must_match_sequential_identifiers(self):
        for sample_id in (None, 1, "A", "sample_0002", "sample_1", "sample_0001.bam"):
            request = deepcopy(self.request)
            request["samples"][0]["sample_id"] = sample_id
            with self.subTest(sample_id=sample_id):
                self.assert_rejected_without_writes(request)
        for number, filename in enumerate(("original.bam", "sample_0001.BAM", "sample_0002.bam")):
            # Windows resolves case-only aliases to the spelling of an existing
            # file. Isolate each fixture so .BAM cannot overwrite sample_0001.bam.
            directory = self.inputs / f"invalid_basename_{number}"
            directory.mkdir()
            path = directory / filename
            path.write_bytes(b"unaliasable sample")
            request = deepcopy(self.request)
            request["samples"][0]["path"] = str(path)
            with self.subTest(filename=filename):
                self.assert_rejected_without_writes(request)
        request = deepcopy(self.request)
        request["samples"].append(request["samples"][0].copy())
        self.assert_rejected_without_writes(request)

    def test_native_bam_and_reference_aliases_reject_shell_and_r_delimiters(self):
        for component in ("with space", "with=equals", "with$dollar", "with;semi", "with#hash",
                          "with'apostrophe", "with(unquoted)", "withàunicode"):
            unsafe = self.inputs / component
            unsafe.mkdir()
            bam = unsafe / "sample_0001.bam"
            bam.write_bytes(b"sample")
            reference = unsafe / "genome.fa"
            reference.write_bytes(self.reference.read_bytes())
            Path(str(reference) + ".fai").write_bytes(b"index")
            with self.subTest(component=component, field="bam"):
                case = deepcopy(self.request)
                case["samples"][0]["path"] = str(bam)
                self.assert_rejected_without_writes(case)
            with self.subTest(component=component, field="reference"):
                self.assert_rejected_without_writes({**self.request, "reference": str(reference)})

    def test_work_and_output_must_be_named_siblings(self):
        pairs = [(self.run / "other", self.run / "output"),
                 (self.run / "work", self.run / "other"),
                 (self.run / "work", self.run / "nested/output"),
                 (self.run / "work", self.run / "work/output"),
                 (self.run / "output/work", self.run / "output")]
        for work, output in pairs:
            with self.subTest(work=work, output=output):
                self.assert_rejected_without_writes({**self.request,
                    "work_dir": str(work), "out_dir": str(output)})

    def test_inputs_cannot_overlap_work_or_output(self):
        for name in ("work", "output"):
            location = self.root / "overlap" / name
            location.mkdir(parents=True)
            for field, filename, data in (("panel", "panel.txt", self.panel.read_bytes()),
                                          ("reference", "genome.fa", b">chr1\nAC\n"),
                                          ("bam", "sample_0001.bam", b"BAM")):
                source = location / filename
                source.write_bytes(data)
                Path(str(source) + ".fai").write_bytes(b"index")
                case = deepcopy(self.request)
                case.update(work_dir=str(location.parent / "work"),
                            out_dir=str(location.parent / "output"))
                if field == "bam":
                    case["samples"][0]["path"] = str(source)
                else:
                    case[field] = str(source)
                with self.subTest(directory=name, field=field):
                    self.assert_rejected_without_writes(case)

    def test_preexisting_staging_and_native_temporary_files_are_protected(self):
        for name in ("work/bamlist.txt", "work/DNP_list.txt", "mpileup.txt",
                     "bedfile_for_mpileup.bed", "output/previous.txt"):
            target = self.run / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"must remain unchanged")
            with self.subTest(name=name):
                self.assert_rejected_without_writes(self.request)
            target.unlink()

    def test_dangling_native_temporary_symlinks_are_protected(self):
        self.run.mkdir()
        for name in ("mpileup.txt", "bedfile_for_mpileup.bed", "work/bamlist.txt", "work/DNP_list.txt"):
            target = self.run / name
            target.parent.mkdir(exist_ok=True)
            try:
                target.symlink_to(self.root / "missing.txt")
            except (NotImplementedError, OSError):
                self.skipTest("Creating symbolic links is unavailable on this platform.")
            with self.subTest(name=name):
                self.assert_rejected_without_writes(self.request)
            target.unlink()

    def test_destination_files_are_rejected_without_writes(self):
        for destination in (self.run, self.run / "work", self.run / "output"):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"not a directory")
            with self.subTest(destination=destination):
                self.assert_rejected_without_writes(self.request)
            destination.unlink()

    def test_missing_inputs_or_reference_index_are_rejected_without_writes(self):
        paths = [self.panel, self.bam, self.reference, Path(str(self.reference) + ".fai")]
        for path in paths:
            original = path.read_bytes()
            path.unlink()
            with self.subTest(path=path):
                self.assert_rejected_without_writes(self.request)
            path.write_bytes(original)

    def test_invalid_panel_is_rejected_before_writes(self):
        for contents in (b"", b"chr1 100 102 AC GT\n", b"chr1 100 101 A G\n"):
            self.panel.write_bytes(contents)
            with self.subTest(contents=contents):
                self.assert_rejected_without_writes(self.request)

    def test_compressed_reference_requires_both_indexes(self):
        for extension in (".gz", ".bgz", ".bgzf"):
            reference = self.inputs / ("genome.fa" + extension)
            reference.write_bytes(b"compressed FASTA fixture")
            Path(str(reference) + ".fai").write_bytes(b"index")
            request = {**self.request, "reference": str(reference),
                       "work_dir": str(self.root / extension[1:] / "work"),
                       "out_dir": str(self.root / extension[1:] / "output")}
            with self.subTest(extension=extension):
                self.assert_rejected_without_writes(request)
                Path(str(reference) + ".gzi").write_bytes(b"compressed index")
                prepared = prepare_dnp(request)
                self.assertIn(f"--reference={reference.as_posix()}", prepared.native_arguments)


if __name__ == "__main__":
    unittest.main()
