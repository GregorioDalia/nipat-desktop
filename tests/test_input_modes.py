import json
import shutil
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from nipat.adapters.panels import read_position_panel
from nipat.errors import ValidationError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.records = []

    def run(self, command, *, working_dir=None):
        self.calls.append(list(map(str, command)))

    def record_run(self, run_dir, **kwargs):
        self.records.append(kwargs)
        return nullcontext()


class InputModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        project = root / "project"
        project.mkdir()
        self.external = root / "dati esterni $ ,= à"
        self.external.mkdir()
        self.layout = ProjectLayout(project, root, root / "data", root / "results",
                                    project / "compose.yaml")
        self.runner = RecordingRunner()
        self.workflows = Workflows(self.layout, self.runner)

    def write(self, name, content):
        path = self.external / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def cpi_args(self):
        source = FIXTURES / "cpi"
        folder = self.external / "campioni CPI"
        shutil.copytree(source / "samples", folder)
        popfreq = self.external / "frequenze $ ,=.tsv"
        shutil.copy2(source / "pop_allFreq.txt", popfreq)
        return dict(input_dir=folder, popfreq=popfreq,
                    pairs="Informative:Informative,NoSites:NoSites",
                    mother_prefix="Mother", father_prefix="Father")

    def test_snp_existing_external_pileup_skips_mpileup_and_reference(self):
        panel = self.write("SNP list.tsv", "pos\tref\talt\nchr1:1\tA\tC\n")
        pileup = self.write("pileup $ ,=.txt", "chr1\t1\tA\t1\t.\tI\tread1\n")
        before = pileup.read_bytes()
        run = self.workflows.snp_call(pileup=pileup, panel=panel)
        self.assertEqual(len(self.runner.calls), 1)
        command = self.runner.calls[0]
        self.assertEqual(command[:4],
                         ["python3", "/opt/nipat/engine/main.py", "execute", "snp-call"])
        request = json.loads((run / "work/engine-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request, {
            "schema_version": 1, "workflow": "snp-call", "mode": "pileup",
            "panel": "/workspace/inputs/snp-list.tsv",
            "pileup": "/workspace/inputs/snp-pileup.txt", "bam": None, "reference": None,
            "work_dir": str(self.layout.container_path(run / "work")),
            "out_dir": str(self.layout.container_path(run / "output")),
        })
        self.assertEqual(command[-1], str(self.layout.container_path(run / "work/engine-request.json")))
        self.assertEqual(self.runner.records[0]["bundled_workflow"], "snp-call")
        self.assertFalse((run / "work/snp_regions.bed").exists())
        self.assertFalse((run / "work/pileup.txt").exists())
        self.assertEqual(pileup.read_bytes(), before)
        mappings = self.runner.records[0]["mounts"].mappings
        self.assertTrue(all(item["read_only"] for item in mappings))
        self.assertEqual(
            {item["host_path"] for item in mappings},
            {str(panel.resolve()), str(pileup.resolve())},
        )

    def test_snp_rejects_six_column_pileup_before_creating_run(self):
        panel = self.write("SNP.tsv", "pos\tref\talt\nchr1:100\tA\tC\n")
        pileup = self.write("six.txt", "chr1\t100\tA\t1\t.\tI\n")
        with self.assertRaisesRegex(ValidationError, "7 colonne"):
            self.workflows.snp_call(pileup=pileup, panel=panel)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_snp_accepts_columns_after_the_seventh_qname_column(self):
        panel = self.write("SNP.tsv", "pos\tref\talt\nchr1:100\tA\tC\n")
        pileup = self.write("extra.txt", "chr1\t100\tA\t1\t.\tI\tread1\toptional\n")
        self.workflows.snp_call(pileup=pileup, panel=panel)
        self.assertEqual(len(self.runner.calls), 1)

    def test_snp_bam_without_optional_bam_index_delegates_preparation_to_engine(self):
        panel = self.write("SNP.tsv", "pos\tref\talt\nchr1:100\tA\tC\n")
        bam = self.write("sample.bam", "fixture")
        reference = self.write("genome.fa", ">chr1\nACGT\n")
        self.write("genome.fa.fai", "chr1\t4\t6\t4\t5\n")
        before = {path: path.read_bytes() for path in self.external.iterdir()}
        run = self.workflows.snp_call(bam=bam, reference=reference, panel=panel)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0][:4],
                         ["python3", "/opt/nipat/engine/main.py", "execute", "snp-call"])
        request = json.loads((run / "work/engine-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["mode"], "bam")
        self.assertEqual(request["bam"], "/workspace/inputs/bam/sample.bam")
        self.assertEqual(request["reference"], "/workspace/inputs/reference/genome.fa")
        self.assertIsNone(request["pileup"])
        self.assertFalse((run / "work/snp_regions.bed").exists())
        self.assertFalse((run / "work/pileup.txt").exists())
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        self.assertEqual(self.runner.records[0]["bundled_workflow"], "snp-call")
        mappings = self.runner.records[0]["mounts"].mappings
        self.assertTrue(all(item["read_only"] for item in mappings))
        self.assertEqual(len(mappings), 4)
        self.assertEqual(self.runner.records[0]["parameters"]["bam"], str(bam.resolve()))

    def test_snp_compressed_reference_and_optional_indexes_keep_adjacent_safe_aliases(self):
        panel = self.write("SNP.tsv", "pos\tref\talt\nchr1:100\tA\tC\n")
        bam = self.write("sample $ ,=.bam", "fixture")
        self.write("sample $ ,=.bai", "index")
        self.write("sample $ ,=.bam.csi", "index")
        reference = self.write("genome $ ,=.fa.bgz", "compressed fixture")
        self.write("genome $ ,=.fa.bgz.fai", "chr1\t4\t6\t4\t5\n")
        self.write("genome $ ,=.fa.bgz.gzi", "index")
        run = self.workflows.snp_call(bam=bam, reference=reference, panel=panel)
        request = json.loads((run / "work/engine-request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["reference"], "/workspace/inputs/reference/genome.fa.gz")
        mappings = self.runner.records[0]["mounts"].mappings
        self.assertEqual({item["container_path"] for item in mappings}, {
            "/workspace/inputs/snp-list.tsv", "/workspace/inputs/bam/sample.bam",
            "/workspace/inputs/bam/sample.bam.bai", "/workspace/inputs/bam/sample.bam.csi",
            "/workspace/inputs/reference/genome.fa.gz",
            "/workspace/inputs/reference/genome.fa.gz.fai",
            "/workspace/inputs/reference/genome.fa.gz.gzi",
        })
        self.assertTrue(all(item["read_only"] for item in mappings))

    def test_contamination_recursive_folder_excludes_panel_and_preserves_inputs(self):
        folder = self.external / "recursive"
        shutil.copytree(FIXTURES / "contamination" / "samples", folder / "nested")
        panel = folder / "panel.txt"
        panel.write_text("pos2\tannotation\tchr\tpos1\n101\tX\tchr1\t100\n", encoding="utf-8")
        (folder / "ignored.csv").write_text("not a table", encoding="utf-8")
        before = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
        run = self.workflows.contamination(input_dir=folder, panel=panel)
        request = json.loads((run / "work" / "engine-request.json").read_text(encoding="utf-8"))
        self.assertEqual({sample["name"] for sample in request["samples"]},
                         {"NoRatio.txt", "WithRatio.txt", "NoSites.txt"})
        self.assertEqual(self.runner.records[0]["bundled_workflow"], "contamination")
        self.assertEqual(len(self.runner.records[0]["mounts"].mappings), 4)
        self.assertFalse((run / "work" / "DNPpanel.txt").exists())
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_coordinate_panels_accept_native_order_and_nonadjacent_positions(self):
        for name, text in (
            ("native.tsv", "pos2\tchr\tpos1\n105\tchr1\t100\n"),
            ("three.txt", "chr1\t100\t105\n"),
            ("legacy.txt", "chr1 100 105 AA CC\n"),
        ):
            with self.subTest(name=name):
                record = read_position_panel(self.write(name, text))[0]
                self.assertEqual((record.chromosome, record.pos1, record.pos2), ("chr1", 100, 105))

    def cpi_request(self, run):
        return json.loads((run / "work/engine-request.json").read_text(encoding="utf-8"))

    def test_cpi_all_delegates_to_engine_with_zero_error_and_no_host_staging(self):
        args = self.cpi_args()
        run = self.workflows.cpi(**args, err_const=0)
        command = self.runner.calls[0]
        self.assertEqual(command, [
            "python3", "/opt/nipat/engine/main.py", "execute", "cpi", "--request",
            str(self.layout.container_path(run / "work/engine-request.json")),
        ])
        self.assertEqual(self.cpi_request(run), {
            "schema_version": 1, "workflow": "cpi", "samples": [
                {"path": f"/workspace/inputs/cpi/sample_{number:04d}.txt", "name": name}
                for number, name in enumerate(("MotherInformative.txt", "FatherInformative.txt",
                                               "MotherNoSites.txt", "FatherNoSites.txt"), 1)
            ],
            "pairs": args["pairs"], "mother_prefix": "Mother", "father_prefix": "Father",
            "popfreq": "/workspace/inputs/population.tsv", "cutoff_mode": "all",
            "cutoffs": [], "err_const": 0,
            "work_dir": str(self.layout.container_path(run / "work")),
            "out_dir": str(self.layout.container_path(run / "output")),
        })
        self.assertEqual(self.runner.records[0]["parameters"]["cutoffs"], [])
        self.assertEqual(self.runner.records[0]["bundled_workflow"], "cpi")
        self.assertEqual({path.name for path in (run / "work").iterdir()}, {"engine-request.json"})
        self.assertEqual(self.runner.calls, [command])

    def test_cpi_single_panel_is_original_readonly_mount_not_client_normalized_file(self):
        args = self.cpi_args()
        panel = self.write("single panel $ ,= è.tsv", "pos2\tchr\tpos1\n101\tchr1\t100\n")
        before = panel.read_bytes()
        run = self.workflows.cpi(**args, panel=panel, err_const=0.125)
        request = self.cpi_request(run)
        self.assertEqual(request["cutoff_mode"], "panel")
        self.assertEqual(request["cutoffs"], [{"label": "", "path": "/workspace/inputs/cpi-cutoffs/panel_001.tsv"}])
        self.assertEqual(request["err_const"], 0.125)
        self.assertFalse((run / "work/DNPpanel.txt").exists())
        self.assertEqual(panel.read_bytes(), before)
        mappings = self.runner.records[0]["mounts"].mappings
        self.assertTrue(all(item["read_only"] for item in mappings))
        self.assertIn({"host_path": str(panel.resolve()), "container_path": request["cutoffs"][0]["path"],
                       "read_only": True}, mappings)

    def test_cpi_multiple_panels_use_safe_paths_keep_labels_and_originals(self):
        args = self.cpi_args()
        first = self.write("cutoff one $ ,=.tsv", "chr\tpos1\tpos2\nchr1\t100\t101\n")
        second = self.write("cutoff two.tsv", "chr1\t200\t201\tAA\tCC\n")
        original = first.read_bytes()
        run = self.workflows.cpi(**args, cutoffs=[("Full panel", first), ("Second", second)])
        request = self.cpi_request(run)
        self.assertEqual(request["cutoff_mode"], "named")
        self.assertEqual(request["cutoffs"], [
            {"label": "Full panel", "path": "/workspace/inputs/cpi-cutoffs/panel_001.tsv"},
            {"label": "Second", "path": "/workspace/inputs/cpi-cutoffs/panel_002.tsv"},
        ])
        self.assertFalse((run / "work/cutoff_001.tsv").exists())
        self.assertFalse((run / "work/cutoff_002.tsv").exists())
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(self.runner.records[0]["parameters"]["cutoffs"][0]["path"], str(first.resolve()))

    def test_cpi_native_map_and_alias_match_expected_mapping(self):
        args = self.cpi_args()
        panel = self.write("native.tsv", "chr\tpos1\tpos2\nchr1\t100\t101\n")
        # Native syntax uses commas as separators, so use a path without commas.
        simple = self.layout.project_dir / "native.tsv"
        shutil.copy2(panel, simple)
        run = self.workflows.cpi(**args, cutoff_map=f"Native={simple}")
        self.assertEqual(self.cpi_request(run)["cutoffs"], [
            {"label": "Native", "path": "/workspace/inputs/cpi-cutoffs/panel_001.tsv"},
        ])

    def test_cpi_bare_native_cutoff_map_preserves_filename_as_label(self):
        args = self.cpi_args()
        panel = self.layout.project_dir / "native.tsv"
        panel.write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        run = self.workflows.cpi(**args, cutoff_map=str(panel))
        self.assertEqual(self.cpi_request(run)["cutoff_mode"], "named")
        self.assertEqual(self.cpi_request(run)["cutoffs"][0]["label"], str(panel))

    def test_cpi_pair_whitespace_is_normalized_and_selected_files_only_are_mounted(self):
        args = self.cpi_args()
        args["pairs"] = " Informative : Informative "
        run = self.workflows.cpi(**args)
        record = self.runner.records[0]
        self.assertEqual(record["parameters"]["pairs"], "Informative:Informative")
        mounted = {Path(item["host_path"]).name for item in record["mounts"].mappings}
        self.assertEqual(mounted, {"MotherInformative.txt", "FatherInformative.txt", "frequenze $ ,=.tsv"})
        self.assertEqual(self.cpi_request(run)["pairs"], "Informative:Informative")

    def test_cpi_shared_parent_is_selected_once_and_pair_order_is_preserved(self):
        args = self.cpi_args()
        args["pairs"] = " Informative : NoSites , Informative : Informative "
        run = self.workflows.cpi(**args)
        request = self.cpi_request(run)
        self.assertEqual(request["pairs"], "Informative:NoSites,Informative:Informative")
        self.assertEqual([sample["name"] for sample in request["samples"]],
                         ["MotherInformative.txt", "FatherNoSites.txt", "FatherInformative.txt"])
        self.assertEqual(len(self.runner.records[0]["inputs"]), 4)
        self.assertEqual(len(self.runner.records[0]["mounts"].mappings), 4)

    def test_cpi_empty_and_custom_prefixes_preserve_filenames_and_bytes(self):
        args = self.cpi_args()
        original_dir = args["input_dir"]
        for source, target in (("MotherInformative.txt", "Informative.txt"),
                               ("FatherInformative.txt", "--Padre è $= Informative.txt")):
            shutil.copyfile(original_dir / source, original_dir / target)
        args.update(pairs="Informative:Informative", mother_prefix="", father_prefix="--Padre è $= ")
        before = {path: path.read_bytes() for path in original_dir.iterdir()}
        run = self.workflows.cpi(**args)
        request = self.cpi_request(run)
        self.assertEqual((request["mother_prefix"], request["father_prefix"]), ("", "--Padre è $= "))
        self.assertEqual([sample["name"] for sample in request["samples"]],
                         ["Informative.txt", "--Padre è $= Informative.txt"])
        self.assertEqual({path: path.read_bytes() for path in original_dir.iterdir()}, before)

    def test_cpi_identical_sample_for_both_roles_has_one_selected_file(self):
        args = self.cpi_args()
        args.update(pairs="Informative:Informative", father_prefix="Mother")
        run = self.workflows.cpi(**args)
        self.assertEqual([sample["name"] for sample in self.cpi_request(run)["samples"]],
                         ["MotherInformative.txt"])
        self.assertEqual(len(self.runner.records[0]["mounts"].mappings), 2)

    def test_cpi_rejects_duplicate_pairs_and_cutoff_labels_before_run(self):
        args = self.cpi_args()
        panel = self.write("panel.tsv", "chr\tpos1\tpos2\nchr1\t100\t101\n")
        with self.assertRaisesRegex(ValidationError, "Coppia CPI duplicata"):
            self.workflows.cpi(**{**args, "pairs": "Informative:Informative, Informative:Informative"})
        with self.assertRaisesRegex(ValidationError, "Etichetta cutoff duplicata"):
            self.workflows.cpi(**args, cutoffs=[("A", panel), ("A", panel)])
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_cpi_rejects_ambiguous_output_or_sample_names_before_run(self):
        args = self.cpi_args()
        for pairs in ("A-FatherB:C,A:B-FatherC", "Informative:Informative,informative:NoSites"):
            with self.subTest(pairs=pairs), self.assertRaises(ValidationError):
                self.workflows.cpi(**{**args, "pairs": pairs})
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_cpi_rejects_nonfinite_negative_or_boolean_error_before_run(self):
        args = self.cpi_args()
        for value in (-1, float("inf"), float("nan"), 10 ** 1000, True, False, "0.2", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "costante di errore"):
                self.workflows.cpi(**args, err_const=value)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_cpi_rejects_incompatible_or_empty_cutoff_modes_before_run(self):
        args = self.cpi_args()
        panel = self.write("panel.tsv", "chr\tpos1\tpos2\nchr1\t100\t101\n")
        for options in ({"panel": panel, "cutoffs": [("Full", panel)]},
                        {"cutoffs": []}, {"cutoff_map": ""}, {"cutoff_map": "Full="},
                        {"cutoffs": [("bad,label", panel)]}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                self.workflows.cpi(**args, **options)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_cpi_rejects_missing_or_malformed_tables_before_run(self):
        args = self.cpi_args()
        source = args["input_dir"] / "MotherInformative.txt"
        original = source.read_bytes()
        source.unlink()
        with self.assertRaises(ValidationError):
            self.workflows.cpi(**args)
        source.write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.workflows.cpi(**args)
        source.write_bytes(original)
        args["popfreq"].write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.workflows.cpi(**args)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())


if __name__ == "__main__":
    unittest.main()
