"""Installed CPIN parameter and bounded-curve checks, with no pytest dependency."""

import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest

import test_native_r_edge_cases as native
from native_r_helpers import NATIVE_R_AVAILABLE, NATIVE_R_REASON


@unittest.skipUnless(NATIVE_R_AVAILABLE, NATIVE_R_REASON)
class NativeCPINParameterTests(unittest.TestCase):
    def execute(self, root, marker, settings=None, options=(), huge_support=False):
        inputs = root / "inputs"
        shutil.copytree(native.ROOT / "tests/fixtures/cpin" / marker, inputs)
        if huge_support:
            child = inputs / "ChildC1.txt"
            before = child.read_text()
            after = before.replace("100\t0\t0\t100", "1000000000\t0\t0\t1000000000")
            self.assertNotEqual(before, after, "The large-support fixture must actually change")
            child.write_text(after)
        original = {path.name: path.read_bytes() for path in inputs.iterdir()}
        process, output = native.NativeREdgeCases.run_native(
            self, root, "cpin", inputs, native_options=options, settings=settings)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(original, {path.name: path.read_bytes() for path in inputs.iterdir()})
        document = json.loads((output / "scientific-settings.json").read_text())
        self.assertEqual(document["workflow"], "cpin")
        self.assertEqual(document["constants"]["ploidy"]["value"], 2)
        for name, value in (settings or {}).items():
            self.assertEqual(document["parameters"][name], value)
        return output, document

    def test_parameter_effects_are_observed_in_native_snp_and_dnp_results(self):
        variants = (
            ({"min_child_reads": 1}, [3, 4]),
            ({"min_child_reads": 101}, [0, 0]),
            ({"other_fraction_max": .11}, [3, 4]),
            ({"heterozygous_max": .7}, [3, 4]),
            ({"site_selection": "other_allele"}, [2]),
            ({"site_selection": "all"}, [3]),
        )
        for marker in ("SNP", "DNP"):
            for settings, counts in variants:
                with self.subTest(marker=marker, settings=settings), tempfile.TemporaryDirectory() as temporary:
                    output, _ = self.execute(Path(temporary), marker, settings=settings)
                    rows = native.table(output / "Summary_Postnatal_CPI.txt")
                    self.assertEqual([int(row["N_sites"]) for row in rows], counts)
                    self.assertEqual({row["Marker_type"] for row in rows}, {marker})
                    if counts == [0, 0]:
                        self.assertTrue(all(row["CPI"] == row["Log10_CPI"] == "NA" for row in rows))
                        self.assertTrue(all(not native.table(path) for path in (output / "curves").iterdir()))

    def test_custom_mismatch_constants_change_the_scientific_formula(self):
        for marker in ("SNP", "DNP"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                epsilon = .02
                output, _ = self.execute(Path(temporary), marker,
                                         settings={f"err_const_{marker.lower()}": epsilon})
                rows = native.table(output / "Summary_Postnatal_CPI.txt")
                for row, expected in zip(rows, (1.25 * epsilon / .4, 1.25 * epsilon / .4 / .6), strict=True):
                    self.assertTrue(math.isclose(float(row["CPI"]), expected, rel_tol=1e-12))
                    self.assertTrue(math.isclose(float(row["Log10_CPI"]), math.log10(expected), rel_tol=1e-12))
                    self.assertEqual(float(row["Error_constant"]), epsilon)

    def test_native_cli_overrides_are_recorded_and_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, document = self.execute(Path(temporary), "SNP", options=(
                "--min_child_reads", "3", "--err_const_snp", ".02", "--site_selection", "all"))
            self.assertEqual(document["parameters"]["min_child_reads"], 3)
            self.assertEqual(document["parameters"]["err_const_snp"], .02)
            self.assertEqual(document["parameters"]["site_selection"], "all")
            rows = native.table(output / "Summary_Postnatal_CPI.txt")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Analysis"], "all_compatible_sites")
            self.assertEqual(rows[0]["Min_child_reads"], "3")
            self.assertTrue(math.isclose(float(rows[0]["CPI"]), 1.25 * .02 / .4 / .6, rel_tol=1e-12))

    def test_billion_read_support_uses_two_intervals_with_exact_endpoints(self):
        for marker in ("SNP", "DNP"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                output, _ = self.execute(Path(temporary), marker, huge_support=True)
                curve = native.table(next((output / "curves").glob("*all_compatible*")))
                self.assertEqual(len(curve), 2)
                self.assertEqual(int(curve[0]["Min_child_reads"]), 2)
                self.assertEqual(int(curve[0]["Through_min_child_reads"]), 50)
                self.assertEqual(int(curve[1]["Min_child_reads"]), 51)
                self.assertEqual(float(curve[1]["Through_min_child_reads"]), 1_000_000_000)
                self.assertEqual(int(curve[1]["N_sites"]), 1)
                self.assertTrue(math.isclose(float(curve[1]["Log10_CPI"]), math.log10(1 / .6), rel_tol=1e-12))


if __name__ == "__main__":
    unittest.main()
