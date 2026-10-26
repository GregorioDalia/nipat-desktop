from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.cpi import normalize_pairs, prepare_cpi
from nipat_scientific.errors import ValidationError


class CpiEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat CPI engine ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / "original inputs ,= è"
        self.inputs.mkdir()
        self.panel = self.inputs / "panel ,=.tsv"
        self.panel.write_bytes(b"chr\tpos1\tpos2\r\nchr1\t100\t101\r\nchr1\t200\t201\r\n")
        self.popfreq = self.inputs / "population ,=.tsv"
        self.popfreq.write_bytes(b"chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\r\nchr1\t100\t101\t0,8\t0,2\r\n")
        self.sample_bytes = b"chr pos1 pos2 REF ALT N_REF N_ALT N_Other total_count\r\nchr1 100 101 AC GT 98 2 0 100\r\n"
        samples = []
        for number, name in enumerate(("MotherA.txt", "FatherB.txt", "FatherC.txt")):
            path = self.inputs / f"alias_{number:04d}.txt"
            path.write_bytes(self.sample_bytes)
            samples.append({"path": str(path), "name": name})
        self.run = self.root / "run è"
        self.request = {
            "schema_version": 1, "workflow": "cpi", "samples": samples,
            "pairs": " A : B , A:C ", "mother_prefix": "Mother", "father_prefix": "Father",
            "popfreq": str(self.popfreq), "cutoff_mode": "all", "cutoffs": [],
            "err_const": 0.0000892303778101497, "work_dir": str(self.run / "work"),
            "out_dir": str(self.run / "output"),
        }

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            ("symlink", str(path.readlink())) if path.is_symlink()
            else ("directory", None) if path.is_dir() else ("file", path.read_bytes())
        ) for path in self.root.rglob("*")}

    def reject(self, request):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            prepare_cpi(request)
        self.assertEqual(self.snapshot(), before)

    def panel_request(self):
        return {**self.request, "cutoff_mode": "panel",
                "cutoffs": [{"label": "", "path": str(self.panel)}]}

    def test_all_stages_reused_samples_once_without_modifying_any_input(self):
        before = {path: path.read_bytes() for path in self.inputs.iterdir()}
        argv = prepare_cpi(self.request)
        self.assertEqual(argv, [
            "--pileup_dir", str(self.run / "work/inputs"), "--out_dir", str(self.run / "output"),
            "--pairs=A:B,A:C", "--mother_prefix=Mother", "--father_prefix=Father",
            "--popfreq", str(self.popfreq), "--err_const", str(self.request["err_const"]),
        ])
        staged = self.run / "work/inputs"
        self.assertEqual({path.name for path in staged.iterdir()}, {"MotherA.txt", "FatherB.txt", "FatherC.txt"})
        self.assertTrue(all(path.read_bytes() == self.sample_bytes for path in staged.iterdir()))
        self.assertEqual({path: path.read_bytes() for path in self.inputs.iterdir()}, before)
        self.assertEqual({path.name for path in (self.run / "work").iterdir()}, {"inputs", "input-validation.json"})
        self.assertEqual(list((self.run / "output").iterdir()), [])

    def test_single_panel_preserves_native_path_label_and_normalization(self):
        original = self.panel.read_bytes()
        argv = prepare_cpi(self.panel_request())
        normalized = self.run / "work/DNPpanel.txt"
        self.assertEqual(argv[-1], f"--cutoff_map={normalized}")
        self.assertEqual(normalized.read_text(encoding="utf-8"),
                         "n°DNP\tchr\tpos1\tpos2\nDNP001\tchr1\t100\t101\nDNP002\tchr1\t200\t201\n")
        self.assertEqual(self.panel.read_bytes(), original)

    def test_named_cutoffs_keep_order_and_labels_with_spaces_unicode_and_hyphen(self):
        request = {**self.request, "cutoff_mode": "named", "cutoffs": [
            {"label": " -First è ", "path": str(self.panel)},
            {"label": "Second", "path": str(self.panel)},
        ]}
        argv = prepare_cpi(request)
        self.assertEqual(argv[-1], f"--cutoff_map=-First è={self.run / 'work/cutoff_001.tsv'},"
                         f"Second={self.run / 'work/cutoff_002.tsv'}")
        self.assertEqual((self.run / "work/cutoff_001.tsv").read_bytes(),
                         (self.run / "work/cutoff_002.tsv").read_bytes())

    def test_prefixes_can_be_empty_or_start_with_a_hyphen(self):
        request = deepcopy(self.request)
        request.update(pairs="A:B", mother_prefix="", father_prefix="--father=è", err_const=0)
        request["samples"] = [
            {**request["samples"][0], "name": "A.txt"},
            {**request["samples"][1], "name": "--father=èB.txt"},
        ]
        argv = prepare_cpi(request)
        self.assertIn("--mother_prefix=", argv)
        self.assertIn("--father_prefix=--father=è", argv)
        self.assertEqual(argv[-1], "0")
        self.assertTrue((self.run / "work/inputs/--father=èB.txt").is_file())

    def test_exact_shared_mother_father_filename_is_allowed(self):
        request = deepcopy(self.request)
        request.update(pairs="A:A", mother_prefix="", father_prefix="")
        request["samples"] = [{**request["samples"][0], "name": "A.txt"}]
        prepare_cpi(request)
        self.assertEqual([p.name for p in (self.run / "work/inputs").iterdir()], ["A.txt"])

    def test_schema_types_and_error_constant_reject_before_writes(self):
        cases = [None, [], "request", {}, {**self.request, "extra": 1}]
        for field in self.request:
            cases.append({key: value for key, value in self.request.items() if key != field})
        for value in (True, False, "1", 1.0, 2, None):
            cases.append({**self.request, "schema_version": value})
        for value in (True, False, "0.1", None, [], -1, math.nan, math.inf, -math.inf, 10**1000):
            cases.append({**self.request, "err_const": value})
        for value in ("dnp-call", [], None):
            cases.append({**self.request, "workflow": value})
        for value in (None, [], {}, "sample", [None], [{}]):
            cases.append({**self.request, "samples": value})
        for number, request in enumerate(cases):
            with self.subTest(number=number):
                self.reject(request)

    def test_invalid_pairs_prefixes_and_output_collisions_reject_before_writes(self):
        for pairs in (None, [], "", "A", "A:", ":B", "A:B:C", "A:B,", "A:B, A:B",
                      "A/B:C", "A:B\\C", "A\nB:C", "A-FatherB:C,A:B-FatherC"):
            with self.subTest(pairs=pairs):
                self.reject({**self.request, "pairs": pairs})
        for field in ("mother_prefix", "father_prefix"):
            for value in (None, [], 1, "../", "x\\y", "x\ny", "x\x7fy"):
                with self.subTest(field=field, value=value):
                    self.reject({**self.request, field: value})
        # Both output names and required sample names must be unambiguous on Windows.
        with self.assertRaises(ValidationError):
            normalize_pairs("A:B,a:b", "", "")

    def test_missing_extra_duplicate_or_misnamed_sample_rejects_before_writes(self):
        cases = []
        for samples in (self.request["samples"][:2], self.request["samples"] * 2,
                        [*self.request["samples"], {"name": "Unexpected.txt", "path": str(self.panel)}]):
            cases.append({**self.request, "samples": samples})
        for value in (None, [], "", "../A.txt", "Mothera.txt", "MotherA.TXT"):
            case = deepcopy(self.request)
            case["samples"][0]["name"] = value
            cases.append(case)
        case = deepcopy(self.request)
        case["samples"][0]["extra"] = True
        cases.append(case)
        for number, case in enumerate(cases):
            with self.subTest(number=number):
                self.reject(case)

    def test_cutoff_mode_shape_labels_and_duplicates_reject_before_writes(self):
        valid = {"label": "First", "path": str(self.panel)}
        cases = [(None, []), ([], []), ("other", []), ("all", [valid]), ("panel", []),
                 ("panel", [valid]), ("panel", [valid, valid]), ("named", []), ("named", None),
                 ("named", [{}]), ("named", [{**valid, "extra": 1}]), ("named", [valid, valid])]
        for label in (None, [], "", "A=B", "A,B", "A\nB", "A\x7fB"):
            cases.append(("named", [{**valid, "label": label}]))
        for mode, cutoffs in cases:
            with self.subTest(mode=mode, cutoffs=cutoffs):
                self.reject({**self.request, "cutoff_mode": mode, "cutoffs": cutoffs})

    def test_paths_require_absolute_strings_without_control_characters(self):
        for field in ("popfreq", "work_dir", "out_dir", "sample_path", "panel_path"):
            for value in (None, [], 1, "", "relative.txt", str(self.root) + "\0"):
                case = deepcopy(self.panel_request())
                if field == "sample_path":
                    case["samples"][0]["path"] = value
                elif field == "panel_path":
                    case["cutoffs"][0]["path"] = value
                else:
                    case[field] = value
                with self.subTest(field=field, value=value):
                    self.reject(case)

    def test_missing_and_malformed_sources_reject_before_writes(self):
        paths = [self.popfreq, self.panel, Path(self.request["samples"][0]["path"])]
        for path in paths:
            original = path.read_bytes()
            for contents in (None, b"", b"wrong columns\n"):
                if contents is None:
                    path.unlink()
                else:
                    path.write_bytes(contents)
                with self.subTest(path=path, contents=contents):
                    self.reject(self.panel_request())
            path.write_bytes(original)

    def test_work_output_overlap_and_sources_inside_destinations_reject(self):
        for work, output in ((self.run, self.run), (self.run, self.run / "output"),
                             (self.run / "work", self.run)):
            self.reject({**self.request, "work_dir": str(work), "out_dir": str(output)})
        for name in ("work", "output"):
            location = self.run / name
            location.mkdir(parents=True, exist_ok=True)
            for field in ("popfreq", "sample_path", "panel_path"):
                case = deepcopy(self.panel_request())
                original = self.popfreq if field == "popfreq" else self.panel if field == "panel_path" else Path(case["samples"][0]["path"])
                target = location / original.name
                target.write_bytes(original.read_bytes())
                if field == "popfreq":
                    case[field] = str(target)
                elif field == "sample_path":
                    case["samples"][0]["path"] = str(target)
                else:
                    case["cutoffs"][0]["path"] = str(target)
                with self.subTest(directory=name, field=field):
                    self.reject(case)
                target.unlink()

    def test_preexisting_staging_outputs_and_destination_files_are_preserved(self):
        for name in ("work/inputs", "work/DNPpanel.txt", "output/previous.txt"):
            target = self.run / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"preserve")
            self.reject(self.panel_request())
            target.unlink()
        for name in ("work", "output"):
            target = self.run / name
            target.rmdir()
            target.write_bytes(b"preserve")
            self.reject(self.request)
            target.unlink()

    def test_dangling_staging_symlinks_are_not_overwritten(self):
        for name in ("inputs", "DNPpanel.txt"):
            target = self.run / "work" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.symlink_to(self.root / "missing")
            except (NotImplementedError, OSError):
                self.skipTest("Creating symbolic links is unavailable on this platform.")
            self.reject(self.panel_request())
            target.unlink()

    def test_existing_request_metadata_is_preserved(self):
        (self.run / "work").mkdir(parents=True)
        metadata = self.run / "work/engine-request.json"
        metadata.write_bytes(b"request metadata")
        prepare_cpi(self.request)
        self.assertEqual(metadata.read_bytes(), b"request metadata")

    def test_unrepresentable_cutoff_paths_reject_but_all_mode_remains_valid(self):
        for name in ("comma,run", "equal=run"):
            paths = {"work_dir": str(self.root / name / "work"), "out_dir": str(self.root / name / "output")}
            with self.subTest(name=name):
                self.reject({**self.panel_request(), **paths})
                argv = prepare_cpi({**self.request, **paths})
                self.assertFalse(any(value.startswith("--cutoff_map") for value in argv))


if __name__ == "__main__":
    unittest.main()
