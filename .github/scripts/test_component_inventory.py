import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("component_inventory", Path(__file__).with_name("component_inventory.py"))
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class ComponentInventoryTests(unittest.TestCase):
    def test_inventory_binds_source_scientific_image_and_exact_wsl_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "component-inventory.json"
            provenance = {"apt_packages": {"docker-ce": "29.9.1", "python3": "3.11"},
                          "component_sha256": "d" * 64}
            manifest = {"source_commit": "a" * 40, "runtime_image": "sha256:" + "b" * 64,
                        "rootfs_provenance": {**provenance, "rootfs_image_id": "sha256:" + "e" * 64}}
            value = {"schema_version": 1, "source_commit": "a" * 40,
                     "scientific": {"image_id": "sha256:" + "b" * 64, "apt_packages_tsv": "python3\t3.12\n",
                                    "r_packages_tsv": "Package\tVersion\tLicense\nbase\t4.4.2\tPart of R\n",
                                    "samtools_version": "samtools 1.21"},
                     "wsl": {"image_id": "sha256:" + "c" * 64,
                             "apt_packages_tsv": "docker-ce\t29.9.1\npython3\t3.11\n",
                             "component_provenance": provenance}, "scope": "inventory"}
            path.write_text(json.dumps(value))
            self.assertEqual(inventory.verify(path, manifest)["file"], path.name)
            for change in ("source", "image", "packages", "provenance", "empty-r", "escaped-tsv", "malformed-apt"):
                broken = copy.deepcopy(value)
                if change == "source":
                    broken["source_commit"] = "f" * 40
                elif change == "image":
                    broken["scientific"]["image_id"] = "sha256:" + "f" * 64
                elif change == "packages":
                    broken["wsl"]["apt_packages_tsv"] = "docker-ce\t0.1\n"
                elif change == "provenance":
                    broken["wsl"]["component_provenance"]["component_sha256"] = "f" * 64
                elif change == "empty-r":
                    broken["scientific"]["r_packages_tsv"] = ""
                elif change == "escaped-tsv":
                    broken["scientific"]["r_packages_tsv"] = broken["scientific"]["r_packages_tsv"].replace("\t", "\\t")
                else:
                    broken["scientific"]["apt_packages_tsv"] = "python3 3.12\n"
                path.write_text(json.dumps(broken))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    inventory.verify(path, manifest)

    def test_read_only_inventory_probe_has_temporary_space_for_r(self):
        with patch.object(inventory.subprocess, "check_output", return_value="value") as probe:
            self.assertEqual(inventory.run("image", "Rscript", "-e", "installed.packages()"), "value")
        command = probe.call_args.args[0]
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--tmpfs") + 1], "/tmp:rw,noexec,nosuid,size=256m")
        self.assertEqual(command[command.index("--env") + 1], "TMPDIR=/tmp")


if __name__ == "__main__":
    unittest.main()
