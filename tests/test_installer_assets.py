"""Exercise trust metadata, selective staging, and lossless asset exports."""

import copy
import gzip
import hashlib
import io
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nipat import __version__


SPEC = importlib.util.spec_from_file_location(
    "installer_assets", Path(__file__).resolve().parents[1]
    / "scripts" / "build_windows_installer_assets.py",
)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
PROVENANCE_SPEC = importlib.util.spec_from_file_location(
    "runtime_provenance", Path(__file__).resolve().parents[1]
    / "installer" / "runtime" / "write-provenance.py",
)
provenance = importlib.util.module_from_spec(PROVENANCE_SPEC)
PROVENANCE_SPEC.loader.exec_module(provenance)

COMMIT = "a" * 40
SCIENTIFIC = "sha256:" + "b" * 64
ROOTFS = "sha256:" + "c" * 64


class InstallerAssetTests(unittest.TestCase):
    def test_repository_release_versions_agree(self):
        # Packaging spans Python, PowerShell and Inno Setup. Catch a version
        # bump that the installer would reject before exporting large assets.
        project = Path(__file__).resolve().parents[1]
        version = assets.checked_version(project)
        self.assertEqual(__version__, version)
        bootstrap = (project / "installer/windows/bootstrap-common.ps1").read_text(encoding="utf-8")
        guard = re.search(r"\$manifest\.version -ne '([^']+)'", bootstrap)
        self.assertIsNotNone(guard, "Expected an explicit supported installer version")
        self.assertEqual(guard.group(1), version)
        setup = (project / "installer/windows/NIPAT.iss").read_text(encoding="utf-8")
        self.assertIn('#include StageDir + "\\install-profile.iss"', setup)
        definition = assets.installation_profile_include(dict(
            self.manifest, version=version, release_tag=f"v{version}",
            assets={key: dict(value, url=value["url"].replace("v0.5.0a1", f"v{version}"))
                    for key, value in self.manifest["assets"].items()},
        ))
        self.assertIn(f'#define NipatVersion "{version}"', definition)
        self.assertEqual(assets.installation_profile(project), assets.EXPECTED_INSTALLATION_PROFILE)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "pyproject.toml").write_text(
            '[project]\nversion = "0.5.0a1"\n', encoding="utf-8",
        )
        (self.project / "README.md").write_text("Approved source\n", encoding="utf-8")
        (self.project / "distribution-files.txt").write_text(
            "distribution-files.txt\npyproject.toml\nREADME.md\ninstaller/windows/install-profile.json\n", encoding="utf-8",
        )
        profile = self.project / assets.PROFILE_PATH
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps(assets.EXPECTED_INSTALLATION_PROFILE), encoding="utf-8")
        (self.project / "private-local.txt").write_text("not selected", encoding="utf-8")
        self.rootfs = self.root / "rootfs.tar.gz"
        self.scientific = self.root / "scientific.tar.gz"
        self.rootfs.write_bytes(gzip.compress(b"rootfs fixture", mtime=0))
        self.scientific.write_bytes(gzip.compress(b"scientific fixture", mtime=0))
        self.provenance = {
            "schema_version": 1, "vendor": "nipat-desktop", "source_commit": COMMIT,
            "base_image": "debian@sha256:" + "d" * 64,
        }
        self.manifest = assets.make_manifest(
            self.project, source_commit=COMMIT, runtime_image=SCIENTIFIC,
            rootfs=self.rootfs, scientific_image=self.scientific,
            rootfs_provenance=self.provenance,
        )
        self.manifest_path = self.root / assets.MANIFEST_NAME
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.python_archive = self.root / "python.zip"
        self.python_archive.write_bytes(b"python archive fixture")

    def test_manifest_identifies_exact_sources_and_assets(self):
        assets.validate_manifest(self.manifest)
        self.assertEqual(self.manifest["installation_profile"], assets.EXPECTED_INSTALLATION_PROFILE)
        self.assertEqual(self.manifest["source_commit"], COMMIT)
        self.assertEqual(self.manifest["runtime_image"], SCIENTIFIC)
        self.assertEqual(set(self.manifest["source_sha256"]), {
            "distribution-files.txt", "pyproject.toml", "README.md", "installer/windows/install-profile.json",
        })
        for key, path in [("rootfs", self.rootfs), ("scientific_image", self.scientific)]:
            entry = self.manifest["assets"][key]
            self.assertEqual(entry["sha256"], assets.bundle.sha256_file(path))
            self.assertEqual(entry["size"], path.stat().st_size)
            self.assertEqual(entry["url"],
                             "https://github.com/GregorioDalia/nipat-desktop/releases/"
                             f"download/v0.5.0a1/{path.name}")

    def test_manifest_rejects_foreign_or_ambiguous_installation_profile(self):
        mutations = {
            "channel": "stable",
            "app_dir_name": "NIPAT",
            "data_dir_name": "NIPAT",
            "display_name": "NIPAT",
            "distro_prefix": "NIPAT-Runtime-",
            "resume_key": "NIPAT-ResumeSetup",
            "mutex_prefix": "Local\\NIPAT-Setup-",
            "app_id": "5C0FD852-ED53-4F4B-92D2-64B784E7F9B3",
            "schema_version": True,
        }
        for key, value in mutations.items():
            manifest = copy.deepcopy(self.manifest)
            manifest["installation_profile"][key] = value
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "Profilo"):
                assets.validate_manifest(manifest)
        for value in (None, {}, {**assets.EXPECTED_INSTALLATION_PROFILE, "other": "field"}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Profilo"):
                assets.validate_manifest(dict(self.manifest, installation_profile=value))

    def test_historical_manifest_is_verifiable_but_cannot_stage_a_new_wsl_installer(self):
        historical = copy.deepcopy(self.manifest)
        historical.pop("installation_profile")
        historical["version"] = "0.4.1"
        historical["release_tag"] = "v0.4.1"
        for entry in historical["assets"].values():
            entry["url"] = entry["url"].replace("v0.5.0a1", "v0.4.1")
        assets.validate_manifest(historical)
        assets.verify_runtime_assets(historical, self.root)
        for builder in (assets.runtime_assets_include, assets.installation_profile_include):
            with self.subTest(builder=builder.__name__), self.assertRaisesRegex(ValueError, "Profilo"):
                builder(historical)
        self.manifest_path.write_text(json.dumps(historical), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Profilo"):
            assets.stage_app(self.project, self.manifest_path, self.root / "stage", self.python_archive)
        self.assertFalse((self.root / "stage").exists())
        historical["installation_profile"] = {"channel": "stable"}
        with self.assertRaisesRegex(ValueError, "Profilo"):
            assets.validate_manifest(historical)

    def test_manifest_rejects_source_profile_with_stable_destination(self):
        profile_path = self.project / assets.PROFILE_PATH
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["data_dir_name"] = "NIPAT"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Profilo"):
            assets.make_manifest(
                self.project, source_commit=COMMIT, runtime_image=SCIENTIFIC,
                rootfs=self.rootfs, scientific_image=self.scientific,
                rootfs_provenance=self.provenance,
            )

    def test_profile_include_carries_only_verified_candidate_identity(self):
        include = assets.installation_profile_include(self.manifest)
        definitions = dict(re.findall(r'^#define (\w+) "([^\"]+)"$', include, re.MULTILINE))
        self.assertEqual(definitions, {
            "NipatVersion": "0.5.0a1",
            "NipatAppId": "{{9E27D451-67B5-4D28-B388-A41CFE2F7D05}",
            "NipatDisplayName": "NIPAT 0.5 Preview",
            "NipatAppDirectory": "NIPAT-0.5-Preview",
            "NipatDataDirectory": "NIPAT-0.5-Preview",
            "NipatResumeKey": "NIPAT-05-Preview-ResumeSetup",
        })
        bad = copy.deepcopy(self.manifest)
        bad["installation_profile"]["display_name"] += '\"\n#define Injected "1'
        with self.assertRaisesRegex(ValueError, "Profilo"):
            assets.installation_profile_include(bad)

    def test_setup_validates_selected_paths_before_copying_and_preserves_channel(self):
        setup = (Path(__file__).resolve().parents[1] / "installer/windows/NIPAT.iss").read_text(encoding="utf-8")
        self.assertIn("DisableDirPage=no", setup)
        self.assertIn("UsePreviousAppDir=yes", setup)
        self.assertIn("UsePreviousGroup=no", setup)
        guard = setup.split("function PrepareToInstall(var NeedsRestart: Boolean): String;", 1)[1]
        guard = guard.split("function InitializeUninstall", 1)[0]
        self.assertIn("NipatValidateSelection", guard)
        self.assertIn("NipatValidateWithSharedRules", guard)
        self.assertIn("WizardGroupValue, '{#NipatDisplayName}'", guard)
        self.assertIn("validate-install-layout.ps1", setup)
        self.assertIn("'{#NipatResumeKey}'", setup)
        self.assertNotIn("'NIPAT-ResumeSetup'", setup)

    def test_manifest_and_stage_accept_noncanonical_project_root(self):
        prior_directory = Path.cwd()
        try:
            os.chdir(self.root)
            manifest = assets.make_manifest(
                Path("project"), source_commit=COMMIT, runtime_image=SCIENTIFIC,
                rootfs=self.rootfs, scientific_image=self.scientific,
                rootfs_provenance=self.provenance,
            )
            self.assertEqual(manifest["source_sha256"], self.manifest["source_sha256"])
            with patch.object(assets.bundle, "require_python_archive"):
                app = assets.stage_app(Path("project"), self.manifest_path,
                                       self.root / "relative-stage", self.python_archive)
            self.assertTrue((app / "README.md").is_file())
        finally:
            os.chdir(prior_directory)

    def test_manifest_rejects_provenance_from_another_source(self):
        provenance = dict(self.provenance, source_commit="e" * 40)
        with self.assertRaisesRegex(ValueError, "provenienza"):
            assets.make_manifest(
                self.project, source_commit=COMMIT, runtime_image=SCIENTIFIC,
                rootfs=self.rootfs, scientific_image=self.scientific,
                rootfs_provenance=provenance,
            )

    def test_engine_notices_match_installed_version_and_record_exact_bytes(self):
        payloads = (b"license fixture", b"notice fixture")
        with patch.object(provenance.urllib.request, "urlopen", side_effect=[
            io.BytesIO(content) for content in payloads
        ]) as request:
            record = provenance.collect_engine_notices(
                "Docker version 29.9.1, build dfc520d", self.root / "engine-docs",
            )
        self.assertEqual(record["source_tag"], "docker-v29.9.1")
        self.assertEqual([call.args[0] for call in request.call_args_list], [
            "https://raw.githubusercontent.com/moby/moby/docker-v29.9.1/LICENSE",
            "https://raw.githubusercontent.com/moby/moby/docker-v29.9.1/NOTICE",
        ])
        for entry, content in zip(record["files"], payloads):
            self.assertEqual(Path(entry["path"]).read_bytes(), content)
            self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())

    def test_engine_notices_fail_clearly_when_version_or_upstream_is_unavailable(self):
        with self.assertRaisesRegex(ValueError, "Cannot identify"):
            provenance.collect_engine_notices("unknown", self.root / "engine-docs")
        with patch.object(provenance.urllib.request, "urlopen", side_effect=OSError("not found")):
            with self.assertRaisesRegex(ValueError, "Cannot preserve.*docker-v29.9.1/LICENSE"):
                provenance.collect_engine_notices(
                    "Docker version 29.9.1, build dfc520d", self.root / "engine-docs",
                )

    def test_asset_rejects_empty_uncompressed_and_oversized_files(self):
        path = self.root / "invalid.tar.gz"
        for content in (b"", b"not gzip"):
            path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                assets.asset_metadata(path, "v0.4.1")
        with patch.object(assets, "MAX_ASSET_BYTES", self.rootfs.stat().st_size):
            with self.assertRaisesRegex(ValueError, "2 GiB"):
                assets.asset_metadata(self.rootfs, "v0.4.1")

    def test_manifest_rejects_untrusted_or_invalid_download_metadata(self):
        mutations = [
            ("url", "https://other.example/rootfs.tar.gz"),
            ("file", "../rootfs.tar.gz"),
            ("sha256", "b" * 63),
            ("size", 2 * 1024**3),
            ("size", True),
        ]
        for key, value in mutations:
            manifest = copy.deepcopy(self.manifest)
            manifest["assets"]["rootfs"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                assets.validate_manifest(manifest)
        for key, value in [("source_commit", "main"), ("runtime_image", "latest"),
                           ("release_tag", "v0.5.0")]:
            manifest = dict(self.manifest, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                assets.validate_manifest(manifest)

    def test_stage_copies_only_verified_allowlist_and_embedded_manifest(self):
        with patch.object(assets.bundle, "require_python_archive") as verify_python:
            app = assets.stage_app(self.project, self.manifest_path,
                                   self.root / "stage", self.python_archive)
        verify_python.assert_called_once_with(self.python_archive)
        self.assertFalse((app / "private-local.txt").exists())
        self.assertEqual((app / "README.md").read_text(), "Approved source\n")
        self.assertEqual((app / ".distribution" / assets.MANIFEST_NAME).read_bytes(),
                         self.manifest_path.read_bytes())
        release = json.loads((app / "release.json").read_text())
        self.assertEqual(release["source_git"]["commit"], COMMIT)
        self.assertEqual(release["runtime"]["image_id"], SCIENTIFIC)

    def application_stage(self):
        stage = self.root / "application-stage"
        with patch.object(assets.bundle, "require_python_archive"):
            app = assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        (app / "NIPAT.exe").write_bytes(b"tested launcher fixture")
        (app / "installer/windows/EnableWsl.exe").write_bytes(b"elevation helper fixture")
        return stage, app

    def test_application_inventory_covers_sources_and_compiled_components(self):
        stage, app = self.application_stage()
        with patch.object(assets.bundle, "require_python_archive"):
            inventory = assets.write_application_payload(stage)
            self.assertEqual(assets.verify_application_payload(stage), inventory)
        record = json.loads(inventory.read_text())
        self.assertEqual(record["source_commit"], COMMIT)
        self.assertEqual(record["installation_channel"], "preview-0.5")
        entries = {entry["path"]: entry["sha256"] for entry in record["files"]}
        self.assertEqual(set(entries), {p.relative_to(app).as_posix() for p in app.rglob("*")
                                       if p.is_file() and p != inventory})
        for relative, digest in entries.items():
            self.assertEqual(digest, assets.bundle.sha256_file(app / relative))
        (app / "NIPAT.exe").write_bytes(b"unexpected replacement")
        with patch.object(assets.bundle, "require_python_archive"), self.assertRaisesRegex(ValueError, "inventario"):
            assets.verify_application_payload(stage)

    def test_inventory_refuses_changed_source_missing_binary_and_unlisted_file(self):
        stage, app = self.application_stage()
        source = app / "README.md"
        original = source.read_bytes()
        source.write_bytes(b"changed after trusted staging")
        with self.assertRaisesRegex(ValueError, "Sorgente modificato"):
            assets.write_application_payload(stage)
        source.write_bytes(original)
        binary = app / "NIPAT.exe"
        binary.unlink()
        with self.assertRaisesRegex(ValueError, "payload non corrisponde"):
            assets.write_application_payload(stage)
        binary.write_bytes(b"fixture")
        private = app / "private.txt"
        private.write_text("must not ship")
        with self.assertRaisesRegex(ValueError, "payload non corrisponde"):
            assets.write_application_payload(stage)
        self.assertFalse((app / ".distribution" / assets.APPLICATION_FILES_NAME).exists())

    def test_inventory_rejects_windows_aliases_and_links(self):
        stage, app = self.application_stage()
        for name in ("extra.", "extra:stream", "nul.txt"):
            if os.name == "nt":
                continue  # Windows itself prevents creation of these test paths.
            path = app / name
            path.write_text("fixture")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "non sicuro"):
                assets.write_application_payload(stage)
            path.unlink()
        if os.name != "nt":
            path = app / "linked"
            path.symlink_to(app / "README.md")
            with self.assertRaisesRegex(ValueError, "collegamento"):
                assets.write_application_payload(stage)

    def test_inventory_requires_the_verified_python_archive(self):
        stage, app = self.application_stage()
        with self.assertRaises(ValueError):
            assets.write_application_payload(stage)
        self.assertFalse((app / ".distribution" / assets.APPLICATION_FILES_NAME).exists())

    def test_stage_embeds_exact_archives_directly_into_persistent_cache(self):
        stage = self.root / "stage"
        with patch.object(assets.bundle, "require_python_archive"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        include = stage / assets.RUNTIME_INCLUDE_NAME
        recipe = include.read_text(encoding="utf-8")
        lines = [line for line in recipe.splitlines() if line.startswith("Source:")]
        self.assertEqual(len(lines), 2)
        self.assertNotIn(str(self.root), recipe)
        self.assertFalse(list(stage.rglob("*.tar.gz")), "Staging must not duplicate the large archives")
        for line, key in zip(lines, ("rootfs", "scientific_image")):
            fields = dict(re.findall(r'(\w+): "([^"]*)"', line))
            entry = self.manifest["assets"][key]
            self.assertEqual(fields["Source"], "{#RuntimeAssetsDir}\\" + entry["file"])
            self.assertEqual(fields["DestDir"], "{code:GetNipatCacheDir}")
            self.assertEqual(fields["DestName"], entry["sha256"] + "-" + entry["file"])
            self.assertEqual(fields["Hash"], entry["sha256"])
            flags = line.rsplit("Flags: ", 1)[1].split()
            self.assertEqual(set(flags), {"ignoreversion", "uninsneveruninstall", "nocompression", "solidbreak"})
        self.assertEqual(assets.verify_embedded_inputs(self.manifest_path, stage, self.root), include)

    def test_manifest_rejects_runtime_names_that_collide_on_windows(self):
        for name in ("rootfs.tar.gz", "ROOTFS.tar.gz"):
            manifest = copy.deepcopy(self.manifest)
            manifest["assets"]["scientific_image"]["file"] = name
            manifest["assets"]["scientific_image"]["url"] = manifest["assets"]["rootfs"]["url"].rsplit("/", 1)[0] + "/" + name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "distinti"):
                assets.validate_manifest(manifest)

    def test_stage_rejects_missing_or_altered_runtime_before_creating_output(self):
        original = self.rootfs.read_bytes()
        stage = self.root / "stage"
        for mode in ("missing", "altered"):
            if mode == "missing":
                self.rootfs.unlink()
            else:
                self.rootfs.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
            self.assertFalse(stage.exists())
            self.rootfs.write_bytes(original)

    def test_precompile_rejects_payload_changes_after_staging(self):
        stage = self.root / "stage"
        with patch.object(assets.bundle, "require_python_archive"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        original = self.scientific.read_bytes()
        self.scientific.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, "diverso dal manifest"):
            assets.verify_embedded_inputs(self.manifest_path, stage, self.root)

    def test_precompile_rejects_modified_recipe_or_embedded_manifest(self):
        stage = self.root / "stage"
        with patch.object(assets.bundle, "require_python_archive"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        include = stage / assets.RUNTIME_INCLUDE_NAME
        original = include.read_text(encoding="utf-8")
        include.write_text(original.replace("nocompression", "external"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "istruzioni"):
            assets.verify_embedded_inputs(self.manifest_path, stage, self.root)
        include.write_text(original, encoding="utf-8")
        embedded_manifest = stage / "app" / ".distribution" / assets.MANIFEST_NAME
        embedded_manifest.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest incorporato"):
            assets.verify_embedded_inputs(self.manifest_path, stage, self.root)

    def test_precompile_rejects_altered_identity_include_or_profile(self):
        stage = self.root / "stage"
        with patch.object(assets.bundle, "require_python_archive"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        include = stage / assets.PROFILE_INCLUDE_NAME
        original = include.read_text(encoding="utf-8")
        include.write_text(original.replace("NIPAT-0.5-Preview", "NIPAT"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "profilo Inno"):
            assets.verify_embedded_inputs(self.manifest_path, stage, self.root)
        include.write_text(original, encoding="utf-8")
        profile = stage / "app" / assets.PROFILE_PATH
        profile.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Profilo"):
            assets.verify_embedded_inputs(self.manifest_path, stage, self.root)

    def test_precompile_cli_uses_downloaded_assets_without_python_download(self):
        stage = self.root / "stage"
        with patch.object(assets.bundle, "require_python_archive"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        result = subprocess.run([
            sys.executable, str(Path(assets.__file__)), "verify-embedded",
            "--manifest", str(self.manifest_path), "--stage-dir", str(stage),
            "--assets-dir", str(self.root),
        ], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), str(stage / assets.RUNTIME_INCLUDE_NAME))

    def test_stage_rejects_modified_sources_before_creating_output(self):
        (self.project / "README.md").write_text("changed", encoding="utf-8")
        stage = self.root / "stage"
        with self.assertRaisesRegex(ValueError, "sorgenti"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        self.assertFalse(stage.exists())

    def test_stage_never_overwrites_existing_destination(self):
        stage = self.root / "stage"
        stage.mkdir()
        sentinel = stage / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with patch.object(assets.bundle, "require_python_archive"):
            with self.assertRaises(FileExistsError):
                assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_streamed_export_is_lossless_and_preserves_existing_target(self):
        target = self.root / "export.tar.gz"
        command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'payload' * 1024)"]
        assets.gzip_export(command, target)
        self.assertEqual(gzip.decompress(target.read_bytes()), b"payload" * 1024)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            assets.gzip_export(command, target)
        self.assertEqual(target.read_bytes(), before)

    def test_failed_export_removes_only_new_partial_asset(self):
        target = self.root / "failure.tar.gz"
        command = [sys.executable, "-c",
                   "import sys; sys.stdout.write('partial'); sys.stderr.write('failure'); sys.exit(3)"]
        with self.assertRaisesRegex(RuntimeError, "failure"):
            assets.gzip_export(command, target)
        self.assertFalse(target.exists())

    def test_image_inspection_rejects_wrong_architecture(self):
        details = {"Id": SCIENTIFIC, "Os": "linux", "Architecture": "arm64"}
        with patch.object(assets.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps([details]), "")):
            with self.assertRaisesRegex(ValueError, "amd64"):
                assets.inspect_image("image:mutable-tag")

    def test_export_uses_immutable_ids_and_never_starts_exported_container(self):
        identifier = "f" * 64
        commands = []
        exported = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:2] == ["docker", "create"]:
                output = identifier
            elif command[:2] == ["docker", "run"]:
                output = json.dumps(self.provenance)
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0, output, "")

        def export(command, destination):
            exported.append(command)
            destination.write_bytes(gzip.compress(b"export fixture", mtime=0))

        with patch.object(assets.bundle, "git_source", return_value={"commit": COMMIT, "dirty": False}), \
             patch.object(assets, "inspect_image", side_effect=[{"Id": SCIENTIFIC}, {"Id": ROOTFS}]), \
             patch.object(assets.subprocess, "run", side_effect=run), \
             patch.object(assets, "gzip_export", side_effect=export):
            output = assets.export_assets(
                self.project, self.root / "assets", source_commit=COMMIT,
                scientific_reference="scientific:tag", rootfs_reference="rootfs:tag",
            )
        self.assertEqual(exported, [["docker", "image", "save", SCIENTIFIC],
                                    ["docker", "container", "export", identifier]])
        self.assertIn(["docker", "create", ROOTFS], commands)
        self.assertIn(["docker", "container", "rm", "--force", identifier], commands)
        self.assertFalse(any("start" in command for command in commands))
        manifest = json.loads(output.read_text())
        self.assertEqual(manifest["rootfs_provenance"]["rootfs_image_id"], ROOTFS)
        assets.validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
