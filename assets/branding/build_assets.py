"""Regenerate NIPAT vector and raster branding with Pillow 12.3.0.

The SVGs and raster icons share the geometry below. This developer utility is
not used when building or running NIPAT; generated assets are versioned.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
NAVY = "#142D4E"
TEAL = "#48D6C5"
WHITE = "#FFFFFF"
# Parallel strokes refer to paired sequence data; the main silhouette is N.
STROKES = [
    ([(72, 184), (72, 72), (184, 184), (184, 72)], WHITE, 22),
    ([(105, 72), (184, 151)], TEAL, 10),
]
# Outline lettering avoids font installation and substitution in SVG viewers.
GLYPHS = [
    "M0 78V0H13L45 55V0H59V78H46L14 23V78Z",  # N
    "M0 0H14V78H0Z",  # I
    "M0 78V0H31C49 0 59 9 59 25C59 42 49 51 31 51H14V78ZM14 13V38H30C40 38 45 34 45 25C45 17 40 13 30 13Z",  # P
    "M0 78L27 0H43L70 78H55L49 59H21L15 78ZM25 46H45L35 15Z",  # A
    "M0 0H62V14H38V78H24V14H0Z",  # T
]
GLYPH_X = [0, 78, 111, 184, 264]


def icon_markup() -> str:
    strokes = "\n".join(
        f'  <polyline points="{" ".join(f"{x},{y}" for x, y in points)}" '
        f'fill="none" stroke="{color}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        for points, color, width in STROKES
    )
    return f'  <rect x="8" y="8" width="240" height="240" rx="48" fill="{NAVY}"/>\n{strokes}'


def svg_document(body: str, viewbox: str, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" role="img" '
            f'aria-label="{label}">\n<title>{label}</title>\n{body}\n</svg>\n')


def raster_icon(size: int) -> Image.Image:
    scale = 4 * size / 256
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(tuple(round(v * scale) for v in (8, 8, 248, 248)),
                           radius=round(48 * scale), fill=NAVY)
    for points, color, width in STROKES:
        scaled = [(round(x * scale), round(y * scale)) for x, y in points]
        stroke = round(width * scale)
        draw.line(scaled, fill=color, width=stroke, joint="curve")
        radius = stroke / 2
        for x, y in scaled:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    (ROOT / "nipat-symbol.svg").write_text(
        svg_document(icon_markup(), "0 0 256 256", "NIPAT"), encoding="utf-8")
    for name, color in (("nipat-logo.svg", NAVY), ("nipat-logo-dark.svg", WHITE)):
        lettering = "\n".join(
            f'<path transform="translate({x} 0)" d="{path}"/>'
            for x, path in zip(GLYPH_X, GLYPHS)
        )
        body = (f'<g transform="scale(0.625)">\n{icon_markup()}\n</g>\n'
                f'<g transform="translate(194 41)" fill="{color}" fill-rule="evenodd">\n'
                f'{lettering}\n</g>')
        (ROOT / name).write_text(svg_document(body, "0 0 536 160", "NIPAT"), encoding="utf-8")
    raster_icon(512).save(ROOT / "nipat-icon.png", optimize=False, compress_level=9)
    # PNG-backed ICO frames retain their independently rendered small-size detail.
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    frames = []
    for size in sizes:
        buffer = io.BytesIO()
        raster_icon(size).save(buffer, format="PNG", optimize=False, compress_level=9)
        frames.append(buffer.getvalue())
    import struct
    offset = 6 + 16 * len(sizes)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, payload in zip(sizes, frames):
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                     1, 32, len(payload), offset))
        offset += len(payload)
    (ROOT / "nipat-icon.ico").write_bytes(bytes(directory) + b"".join(frames))


if __name__ == "__main__":
    main()
