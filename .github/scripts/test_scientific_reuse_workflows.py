"""Scientific reuse may replace seven checks, never final package qualification."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
FALLBACK = "steps.scientific_reuse.outputs.reused != 'true'"
CHECKS = {
    "Verify bundled scientific scripts without host sources": ("scripts/verify_engine_package.py",),
    "Verify original sample labels and unchanged scientific results": ("scripts/verify_presentation.py",),
    "Scientific regression and input-mode checks": ("python -m nipat doctor --runtime", "python -m nipat self-test"),
    "Verify optional performance evidence and unchanged DNP results": ("scripts/verify_performance.py",),
    "Verify native scientific edge cases and settings in the installed image": ("/qualification/.github/scripts/check_native_r.py",),
    "Verify updated CPI Contamination and CPIN models": ("scripts/verify_five_modules.py", '--output "$TMPDIR/artifacts" --full'),
    "Compare scientific cores with immutable versioned references": ("scripts/verify_r_equivalence.py",),
}


def jobs(workflow):
    return dict(re.findall(r"^  ([a-z][a-z-]+):\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
                           workflow, re.MULTILINE | re.DOTALL))


def steps(job):
    return dict(re.findall(r"^      - name: ([^\n]+)\n(.*?)(?=^      - name:|\Z)",
                           job, re.MULTILINE | re.DOTALL))


class ScientificReuseWorkflows(unittest.TestCase):
    def setUp(self):
        self.ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.installer = (ROOT / ".github/workflows/windows-installer.yml").read_text()
        self.producer = jobs(self.ci)["scientific"]
        self.runtime = jobs(self.installer)["linux-runtime"]

    def assert_blocking(self, step):
        self.assertNotIn("continue-on-error:", step)
        self.assertIn(re.findall(r"(?m)^        if: (.+)$", step), ([], ["success()"], ["${{ success() }}"]))

    def test_producer_seals_and_uploads_only_after_all_seven_checks_succeed(self):
        producer = steps(self.producer)
        seal_name = "Seal successful scientific qualification for exact-image reuse"
        upload_name = "Retain reusable scientific qualification"
        for name, commands in CHECKS.items():
            with self.subTest(check=name):
                self.assert_blocking(producer[name])
                for command in commands:
                    self.assertIn(command, producer[name])
                self.assertLess(self.producer.index(name), self.producer.index(seal_name))
        self.assert_blocking(producer[seal_name])
        self.assertIn("id: scientific_qualification", producer[seal_name])
        self.assertIn('scientific_reuse.py seal', producer[seal_name])
        self.assertIn('--image "$NIPAT_RUNTIME_IMAGE" --output-dir build/scientific-qualification', producer[seal_name])
        self.assertIn("source_tree=$(git rev-parse 'HEAD^{tree}')", producer[seal_name])
        self.assertIn('>> "$GITHUB_OUTPUT"', producer[seal_name])
        self.assertLess(self.producer.index(seal_name), self.producer.index(upload_name))
        upload = producer[upload_name]
        self.assert_blocking(upload)
        self.assertIn("actions/upload-artifact@", upload)
        self.assertIn("name: nipat-scientific-qualification-${{ github.run_attempt }}-"
                      "${{ steps.scientific_qualification.outputs.source_tree }}", upload)
        self.assertIn("path: build/scientific-qualification/", upload)
        self.assertIn("if-no-files-found: error", upload)
        # Failure diagnostics remain separate and cannot masquerade as reusable evidence.
        diagnostics = producer["Retain scientific diagnostics"]
        self.assertIn("if: always()", diagnostics)
        self.assertIn("name: nipat-ci-scientific-logs", diagnostics)

    def test_restore_checks_the_built_image_before_any_reusable_gate(self):
        runtime = steps(self.runtime)
        build_name = "Build scientific runtime using the dependency cache"
        restore_name = "Restore verified CI qualification for the exact source and image"
        build, restore = runtime[build_name], runtime[restore_name]
        self.assert_blocking(build)
        self.assertIn("file: docker/scientific-runtime/Dockerfile", build)
        self.assertIn("load: true", build)
        self.assertLess(self.runtime.index(build_name), self.runtime.index(restore_name))
        self.assert_blocking(restore)
        self.assertIn("id: scientific_reuse", restore)
        self.assertIn("GH_TOKEN: ${{ github.token }}", restore)
        self.assertIn("scientific_reuse.py restore", restore)
        self.assertIn('--image "$NIPAT_RUNTIME_IMAGE" --output-dir build/scientific-reuse', restore)
        self.assertIn('--runner-temp "$RUNNER_TEMP" --output "$GITHUB_OUTPUT"', restore)
        for name in CHECKS:
            self.assertLess(self.runtime.index(restore_name), self.runtime.index(name))

    def test_only_explicit_verified_reuse_can_skip_exactly_the_seven_gates(self):
        runtime = steps(self.runtime)
        conditional = {name for name, step in runtime.items()
                       if "steps.scientific_reuse.outputs.reused" in step}
        self.assertEqual(conditional, set(CHECKS))
        for name, commands in CHECKS.items():
            with self.subTest(check=name):
                step = runtime[name]
                # != true keeps missing, empty and false outputs on the full-check path.
                self.assertEqual(re.findall(r"(?m)^        if: (.+)$", step), [FALLBACK])
                self.assertNotIn("continue-on-error:", step)
                for command in commands:
                    self.assertIn(command, step)
        header = self.runtime.split("    steps:", 1)[0]
        self.assertNotRegex(header, r"(?m)^    if:")

    def test_reuse_cannot_skip_export_or_execution_of_the_shipped_runtime(self):
        runtime = steps(self.runtime)
        for name in (
            "Preflight scientific evidence before building installers",
            "Build dedicated WSL filesystem from pinned dependencies",
            "Check daemon startup in isolated Linux container",
            "Export pinned assets and trusted installer manifest",
            "Record the description from the exact scientific image",
            "Import the exact selected rootfs archive for qualification",
            "Record resolved component inventories",
            "Load and execute exported image in the shipped engine",
        ):
            with self.subTest(step=name):
                self.assert_blocking(runtime[name])
        export = runtime["Export pinned assets and trusted installer manifest"]
        self.assertIn('--source-commit "$(git rev-parse HEAD)"', export)
        shipped = runtime["Load and execute exported image in the shipped engine"]
        for argument in ("test-runtime-image.ps1", "-ManifestPath build/assets/installer-manifest.json",
                         "-AssetDirectory build/assets", "-RootfsImage nipat-wsl-rootfs:exported-test"):
            self.assertIn(argument, shipped)

    def test_final_installer_binding_and_evidence_collection_are_not_conditional_on_reuse(self):
        installer_jobs = jobs(self.installer)
        for name in ("windows-installer", "linux-installer", "macos-installer", "installer-required"):
            self.assertNotIn("scientific_reuse", installer_jobs[name])
        final = steps(installer_jobs["installer-required"])
        binding = final["Bind all four packages to exact source and scientific archive"]
        bundle = final["Preserve bounded synthetic qualification evidence for accepted releases"]
        self.assert_blocking(binding)
        self.assert_blocking(bundle)
        self.assertIn("verify_installer_set.py", binding)
        self.assertIn('--source-commit "$(git rev-parse HEAD)"', binding)
        self.assertIn("--macos-arm64-dir build/macos-arm64 --macos-x86-64-dir build/macos-x86_64", binding)
        self.assertIn("--installer-set build/verified-installers/installer-set-check.json", bundle)
        self.assertNotIn("--preflight", bundle)
        labels = re.findall(r"--source ([a-z0-9-]+) ", bundle)
        self.assertCountEqual(labels, ("scientific", "windows-client", "installed-linux", "windows-package",
                                      "linux-package", "components", "macos-arm64-package", "macos-x86-64-package",
                                      "synthetic-fixtures"))

    def test_origin_is_preflighted_and_retained_in_the_final_scientific_artifact(self):
        runtime = steps(self.runtime)
        self.assertIn("--source scientific-origin build/scientific-reuse",
                      runtime["Preflight scientific evidence before building installers"])
        retained = runtime["Retain regression logs and metadata"]
        self.assertIn("name: nipat-scientific-check-logs", retained)
        self.assertIn("build/scientific-reuse/reuse.json", retained)
        final = steps(jobs(self.installer)["installer-required"])
        self.assertIn("name: nipat-scientific-check-logs", final["Download synthetic scientific diagnostics"])
        self.assertIn("path: build/evidence/scientific", final["Download synthetic scientific diagnostics"])
        self.assertIn("--source scientific build/evidence/scientific",
                      final["Preserve bounded synthetic qualification evidence for accepted releases"])

    def test_restore_has_only_read_actions_permission_and_no_publication_rights(self):
        header = self.runtime.split("    steps:", 1)[0]
        self.assertRegex(header, r"(?m)^    permissions:\n      contents: read\n      actions: read$")
        self.assertNotRegex(self.installer, r"(?m)^\s+(contents|actions): write$")
        self.assertNotRegex(self.ci, r"(?m)^\s+(contents|actions): write$")


if __name__ == "__main__":
    unittest.main()
