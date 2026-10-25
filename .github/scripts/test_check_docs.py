"""Regression checks for broken documentation paths and section references."""

from pathlib import Path
import tempfile
import unittest

from check_docs import check_repository, heading_anchors


class DocumentationLinksTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, contents=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_removed_guide_and_renamed_section_fail(self):
        self.write("README.md", "[Guide](docs/removed.md)\n[Section](docs/guide.md#old-name)\n")
        self.write("docs/guide.md", "# New name\n")
        count, errors = check_repository(self.root)
        self.assertEqual(count, 2)
        self.assertEqual(len(errors), 2)
        self.assertIn("missing file", errors[0])
        self.assertIn("missing heading anchor", errors[1])

    def test_local_assets_encoded_paths_and_reference_links(self):
        self.write("README.md", '[Guide](docs/with%20space.md#modalità)\n<img src="assets/logo.svg">\n[License][lic]\n[lic]: LICENSE\n')
        self.write("docs/with space.md", "# Modalità\n[Root](/README.md)\n")
        self.write("assets/logo.svg", "<svg/>")
        self.write("LICENSE", "license")
        self.assertEqual(check_repository(self.root)[1], [])
        (self.root / "assets/logo.svg").unlink()
        self.assertIn("missing file", check_repository(self.root)[1][0])

    def test_examples_and_external_urls_do_not_trigger_io(self):
        self.write("README.md", """# Guide
[External](https://example.invalid/absent#section)
[Email](mailto:test@example.invalid)
`[example](absent.md)`
```markdown
[example](absent.md)
```
~~~~
[example](absent.md)
~~~~
""")
        self.assertEqual(check_repository(self.root)[1], [])

    def test_same_document_duplicate_headings_unicode_and_explicit_anchor(self):
        self.write("README.md", """# Installazione
## Modalità: `input`
## Modalità: `input`
<a id="specifico"></a>
[First](#modalità-input) [Second](#modalità-input-1) [Explicit](#specifico)
""")
        self.assertEqual(check_repository(self.root)[1], [])
        self.assertEqual(heading_anchors("# Uso\n# Uso\n# Uso-1\n"), {"uso", "uso-1", "uso-1-1"})

    def test_vendor_sources_excluded_but_owned_links_to_vendor_checked(self):
        self.write("scientific/vendor/tool/README.md", "[upstream](missing.md)")
        self.write("docs/archive/note.md", "[license](../../scientific/vendor/tool/LICENSE)")
        self.write("scientific/vendor/tool/LICENSE", "license")
        self.assertEqual(check_repository(self.root), (1, []))
        (self.root / "scientific/vendor/tool/LICENSE").unlink()
        self.assertIn("missing file", check_repository(self.root)[1][0])

    def test_local_link_cannot_escape_repository(self):
        self.write("README.md", "[outside](../../external.md)")
        self.assertIn("outside repository", check_repository(self.root)[1][0])


if __name__ == "__main__":
    unittest.main()
