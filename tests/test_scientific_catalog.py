"""Catalog provenance, interface coverage and read-only bilingual consultation."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nipat.catalog_ui import catalog_lines, show_catalog
from nipat.cli import build_parser, main
from nipat.terminal import Terminal
from nipat_scientific.catalog import (
    CatalogError, WORKFLOWS, load_catalog, validate_catalog, verify_review_dependencies,
)


ROOT = Path(__file__).resolve().parents[1]


class ScientificCatalogTests(unittest.TestCase):
    def copy_review_sources(self, document, root, *, engine_bundle=False):
        paths = {document["source"]["path"]} | {
            item["evidence"]["path"] for item in document["preparation_settings"]
        } | {
            dependency["path"] for item in document["preparation_settings"]
            for dependency in item["evidence"].get("dependencies", [])
        }
        for relative in paths:
            if engine_bundle and (relative.startswith("src/nipat/")
                                  or relative == "docker/scientific-runtime/Dockerfile"):
                continue
            target = relative
            if engine_bundle and relative.startswith("src/nipat_scientific/"):
                target = "lib/" + relative.removeprefix("src/")
            destination = root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)

    def test_all_reviews_match_exact_sources_and_cover_every_line(self):
        catalog = load_catalog(source_root=ROOT)
        self.assertEqual(set(catalog["workflows"]), set(WORKFLOWS))
        self.assertEqual(sum(item["source"]["line_count"]
                             for item in catalog["workflows"].values()), 1790)

    def test_all_preparation_evidence_matches_the_full_source_checkout(self):
        for workflow, document in load_catalog()["workflows"].items():
            with self.subTest(workflow=workflow):
                verify_review_dependencies(document, ROOT, require_all=True)

    def test_samtools_profiles_match_pinned_build_version_and_require_build_review(self):
        dockerfile = "docker/scientific-runtime/Dockerfile"
        version = re.search(r"^ARG SAMTOOLS_VERSION=(\S+)$", (ROOT / dockerfile).read_text(), re.M)[1]
        for workflow in ("dnp-call", "snp-call"):
            document = load_catalog(workflow)["workflows"][workflow]
            profile = next(item for item in document["preparation_settings"]
                           if item["id"] == "mpileup_inherited_defaults")
            self.assertEqual(profile["value"]["samtools_version"], version)
            self.assertIn(dockerfile, {item["path"] for item in profile["evidence"]["dependencies"]})
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.copy_review_sources(document, root)
                path = root / dockerfile
                path.write_text(path.read_text().replace("SAMTOOLS_VERSION=1.21", "SAMTOOLS_VERSION=1.22"))
                with self.assertRaisesRegex(CatalogError, "stale.*Dockerfile"):
                    verify_review_dependencies(document, root)

    def test_declared_r_options_have_catalog_entries(self):
        catalog = load_catalog(source_root=ROOT)["workflows"]
        for workflow, document in catalog.items():
            source = (ROOT / document["source"]["path"]).read_text(encoding="utf-8")
            names = {name for item in document["public_parameters"] for name in item["r_names"]}
            if workflow == "cpi":
                declared = set(re.findall(r'parser\$add_argument\("(--[a-z_]+)"', source))
                self.assertEqual(names, declared)
            elif workflow == "dnp-call":
                declared = set(re.findall(r'"(--[A-Za-z]+)\*?"', source[:source.index("# read the df")]))
                self.assertEqual(names, declared)
            elif workflow == "snp-call":
                self.assertTrue({"--pileup", "--snplist", "--out"}.issubset(names))
                for name in ("--pileup", "--snplist", "--out"):
                    self.assertIn(f'"{name}"', source)
            else:
                positional = {item["position"]: item["r_names"][0]
                              for item in document["public_parameters"]}
                for number, name in positional.items():
                    self.assertRegex(source, rf'{re.escape(name)}\s*<-\s*args\[{number}\]')
                self.assertEqual(set(positional), {1, 2, 3})

    def test_mapped_cli_flags_exist_and_no_public_parameter_is_silently_missing(self):
        parser = build_parser()
        global_flags = {flag for action in parser._actions for flag in action.option_strings}
        subparsers = next(action for action in parser._actions if hasattr(action, "choices")
                          and isinstance(action.choices, dict))
        for workflow, document in load_catalog()["workflows"].items():
            flags = global_flags | {flag for action in subparsers.choices[workflow]._actions
                                    for flag in action.option_strings}
            for entry in document["public_parameters"]:
                with self.subTest(workflow=workflow, parameter=entry["id"]):
                    self.assertNotEqual(entry["nipat"]["mapping"], "missing")
                    self.assertTrue(set(entry["nipat"]["cli"]).issubset(flags))

    def test_changed_r_requires_a_new_review_even_if_still_valid_r(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_review_sources(document, root)
            destination = root / document["source"]["path"]
            validate_catalog(document, source_root=root)
            destination.write_bytes(destination.read_bytes() + b"\n# New source revision\n")
            with self.assertRaisesRegex(CatalogError, "stale"):
                validate_catalog(document, source_root=root)

    def test_changed_preparation_source_requires_a_new_review(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_review_sources(document, root)
            destination = root / "src/nipat_scientific/snp.py"
            destination.write_bytes(destination.read_bytes() + b"\n# New adapter revision\n")
            with self.assertRaisesRegex(CatalogError, "stale.*snp.py"):
                validate_catalog(document, source_root=root)

    def test_evidence_line_range_must_exist_in_the_verified_source(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        document["preparation_settings"][0]["evidence"]["source_lines"] = [999999, 1000000]
        with self.assertRaisesRegex(CatalogError, "line range"):
            validate_catalog(document, source_root=ROOT)

    def test_engine_layout_checks_mapped_dependencies_and_excludes_absent_host_sources(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_review_sources(document, root, engine_bundle=True)
            validate_catalog(document, source_root=root)
            with self.assertRaisesRegex(CatalogError, "Cannot read catalog evidence:"):
                verify_review_dependencies(document, root, require_all=True)
            adapter = root / "lib/nipat_scientific/snp.py"
            adapter.write_bytes(adapter.read_bytes() + b"\n# Changed bundled adapter\n")
            with self.assertRaisesRegex(CatalogError, "stale.*snp.py"):
                validate_catalog(document, source_root=root)
            adapter.unlink()
            with self.assertRaisesRegex(CatalogError, "Cannot read catalog evidence.*snp.py"):
                validate_catalog(document, source_root=root)

    def test_missing_checkout_host_evidence_is_not_skipped(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_review_sources(document, root)
            (root / "src/nipat/preferences.py").unlink()
            with self.assertRaisesRegex(CatalogError, "Cannot read catalog evidence: src/nipat/"):
                validate_catalog(document, source_root=root)

    def test_evidence_requires_hash_and_normalized_relative_paths(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        mutations = (
            lambda evidence: evidence.pop("sha256"),
            lambda evidence: evidence.update(sha256="invalid"),
            lambda evidence: evidence.update(path="../source.py"),
            lambda evidence: evidence.update(path="/source.py"),
            lambda evidence: evidence.update(path="src/./source.py"),
            lambda evidence: evidence.update(path="src//source.py"),
            lambda evidence: evidence.update(path="src\\source.py"),
            lambda evidence: evidence.update(path="C:/source.py"),
        )
        for mutation in mutations:
            selected = copy.deepcopy(document)
            mutation(selected["preparation_settings"][0]["evidence"])
            with self.assertRaises(CatalogError):
                validate_catalog(selected)

    def test_missing_translations_and_incomplete_coverage_fail(self):
        document = load_catalog("snp-call")["workflows"]["snp-call"]
        mutations = (
            lambda item: item["fixed_settings"][0]["description"].pop("en"),
            lambda item: item["audit_sections"].pop(),
            lambda item: item["audit_sections"][0].update(start=2),
            lambda item: item["fixed_settings"][0].update(source_lines=[1, 9999]),
            lambda item: item["fixed_settings"].append(copy.deepcopy(item["fixed_settings"][0])),
        )
        for mutation in mutations:
            selected = copy.deepcopy(document)
            mutation(selected)
            with self.assertRaises(CatalogError):
                validate_catalog(selected)

    def test_language_changes_only_presentation(self):
        catalog = load_catalog("cpi")
        before = copy.deepcopy(catalog)
        italian = "\n".join(catalog_lines(catalog, language="it"))
        english = "\n".join(catalog_lines(catalog, language="en"))
        self.assertIn("Regole interne R", italian)
        self.assertIn("Internal R rules", english)
        self.assertNotEqual(italian, english)
        self.assertEqual(catalog, before)
        for language in (italian, english):
            self.assertIn("--err_const", language)
            self.assertIn(catalog["workflows"]["cpi"]["source"]["sha256"], language)

    def test_cli_json_does_not_initialize_runtime_or_create_directories(self):
        with patch("nipat.cli.ProjectLayout.discover") as layout, patch(
            "nipat.cli.DockerComposeRunner"
        ) as runner, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["parameters", "cpi", "--json"]), 0)
        layout.assert_not_called()
        runner.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(set(result["workflows"]), {"cpi"})
        self.assertEqual(result["interface"], "scientific-catalog-v1")

    def test_cli_json_preserves_bilingual_text_with_ascii_stdout(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONIOENCODING"] = "ascii"
        result = subprocess.run(
            [sys.executable, "-m", "nipat", "parameters", "--json"],
            cwd=ROOT, env=environment, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("ascii", errors="replace"))
        actual = json.loads(result.stdout.decode("ascii"))
        self.assertEqual(actual, load_catalog())

    def test_menu_can_consult_english_rules_and_return_without_analysis(self):
        answers = iter(["l", "2", "2", "0", "0"])
        messages = []
        show_catalog(Terminal(read=lambda _: next(answers), write=messages.append))
        self.assertIn("Internal R rules", "\n".join(messages))
        self.assertIn("snp-call", "\n".join(messages))

    def test_catalog_reads_do_not_share_mutable_state(self):
        first = load_catalog("cpi")
        first["workflows"]["cpi"]["public_parameters"].clear()
        self.assertTrue(load_catalog("cpi")["workflows"]["cpi"]["public_parameters"])


if __name__ == "__main__":
    unittest.main()
