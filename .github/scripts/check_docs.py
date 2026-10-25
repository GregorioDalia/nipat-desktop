"""Check repository-owned Markdown file links, heading anchors and HTML assets.

This is an offline check of the Markdown constructs used by this repository,
not a CommonMark renderer or an external-URL availability checker. Imported
vendor documents are not scanned; links into vendor files are still checked.
"""

import argparse
from html import unescape
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urlsplit


DOC_DIRECTORIES = ("docs", ".github", "engine", "scientific", "assets", "tests/fixtures")
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(")
REFERENCE = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(.*)$", re.MULTILINE)
REFERENCE_LINK = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
HTML_ATTRIBUTE = re.compile(r"\b(?:href|src|srcset)\s*=\s*([\"'])(.*?)\1", re.IGNORECASE)


def documentation_files(root):
    """Scan owned documentation, including historical notes and test fixtures."""
    files = set(root.glob("*.md"))
    for directory in DOC_DIRECTORIES:
        files.update((root / directory).rglob("*.md"))
    return sorted(path for path in files if "scientific/vendor/" not in path.relative_to(root).as_posix())


def without_fenced_code(text):
    """Blank fenced examples while preserving line numbers for diagnostics."""
    result = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            result.append("\n" if line.endswith("\n") else "")
        elif match:
            fence = match[1]
            result.append("\n" if line.endswith("\n") else "")
        else:
            result.append(line)
    return "".join(result)


def heading_anchors(text):
    text = without_fenced_code(text)
    anchors = set(re.findall(r"\b(?:id|name)=[\"']([^\"']+)[\"']", text))
    used = set()
    for line in text.splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", match[1])
        title = unescape(re.sub(r"<[^>]+>", "", title)).lower()
        slug = "".join(c for c in title if c in " -_" or unicodedata.category(c)[0] in "LNM")
        slug = slug.replace(" ", "-")
        anchor, suffix = slug, 0
        while anchor in used:
            suffix += 1
            anchor = f"{slug}-{suffix}"
        used.add(anchor)
        anchors.add(anchor)
    return anchors


def link_destination(value):
    value = value.strip()
    if value.startswith("<"):
        return value[1:].split(">", 1)[0]
    # Parentheses are permitted inside paths; a title follows whitespace.
    return re.split(r"\s+[\"']", value, maxsplit=1)[0].strip()


def local_links(text):
    """Yield (line, destination); preserve code in headings but ignore inline examples."""
    text = without_fenced_code(text)
    text = re.sub(r"(`+)(.*?)\1", lambda m: " " * len(m[0]), text)
    for match in INLINE_LINK.finditer(text):
        start, pos, depth = match.end(), match.end(), 1
        while pos < len(text) and depth:
            if text[pos] == "\\":
                pos += 2
                continue
            depth += (text[pos] == "(") - (text[pos] == ")")
            pos += 1
        if depth == 0:
            yield text.count("\n", 0, match.start()) + 1, link_destination(text[start:pos - 1])
    references = {match[1].casefold(): link_destination(match[2]) for match in REFERENCE.finditer(text)}
    for match in REFERENCE_LINK.finditer(text):
        key = (match[2] or match[1]).casefold()
        if key in references:
            yield text.count("\n", 0, match.start()) + 1, references[key]
    for match in HTML_ATTRIBUTE.finditer(text):
        yield text.count("\n", 0, match.start()) + 1, unescape(match[2])


def check_document(root, source, anchor_cache):
    errors = []
    text = source.read_text(encoding="utf-8")
    for line, destination in local_links(text):
        parsed = urlsplit(destination)
        if parsed.scheme or parsed.netloc:
            continue
        path = unquote(parsed.path)
        if not path:
            target = source
        elif path.startswith("/"):
            target = root / path.lstrip("/")
        else:
            target = source.parent / path
        target = target.resolve()
        label = f"{source.relative_to(root)}:{line}: {destination}"
        if not target.is_relative_to(root):
            errors.append(f"{label}: target outside repository")
        elif not target.exists():
            errors.append(f"{label}: missing file")
        elif parsed.fragment and target.suffix.lower() == ".md":
            if target not in anchor_cache:
                anchor_cache[target] = heading_anchors(target.read_text(encoding="utf-8"))
            if unquote(parsed.fragment) not in anchor_cache[target]:
                errors.append(f"{label}: missing heading anchor")
    return errors


def check_repository(root):
    root = root.resolve()
    files, anchors, errors = documentation_files(root), {}, []
    for source in files:
        errors.extend(check_document(root, source, anchors))
    return len(files), errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    count, errors = check_repository(args.root)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Documentation links verified: {count} Markdown files; no network requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
