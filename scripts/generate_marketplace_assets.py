#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Marketplace asset generator — stdlib-only pipeline for `assets/`.

Generated outputs (commit script + regenerated artifacts together;
never hand-edit the outputs):

  assets/icon-512.png        512x512 square icon derived from assets/logo.png
  assets/preview-doctor.svg  preview render of REAL `sumo-qa-doctor` output
  assets/preview-doctor.txt  captured (path-sanitised) doctor output — the
                             render's input; refresh via `capture` mode

Modes:
  icon     — decode assets/logo.png (8-bit RGB, non-interlaced), scale it
             onto a 512x512 paper-coloured canvas, write assets/icon-512.png
  capture  — run `sumo-qa-doctor`, sanitise machine-specific paths
             (home dir -> ~, repo dir name -> sumo-qa), write
             assets/preview-doctor.txt, then render the SVG from it so the
             two never drift. Machine-dependent by nature, so it is NEVER
             run implicitly — only when you ask for it.
  version  — update only the version in the committed doctor capture from
             pyproject.toml, then re-render the SVG. Deterministic release
             automation uses this after release-please bumps the version.
  render   — render assets/preview-doctor.txt to assets/preview-doctor.svg
             (deterministic: same capture in, same SVG out)
  all      — icon + render (no capture)

Brand constraints (sumo-qa visual identity): crimson #7A1F1F on paper
#FAF7F2, near-black ink, serif headings, monospace terminal text, no
emojis or pictograms. tests/test_marketplace_assets.py pins dimensions,
sanitisation, and the no-emoji rule.

No third-party dependencies — PNG decode/encode is done with zlib/struct.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"
LOGO = ASSETS / "logo.png"
ICON = ASSETS / "icon-512.png"
CAPTURE = ASSETS / "preview-doctor.txt"
PREVIEW = ASSETS / "preview-doctor.svg"

# Brand palette (see memory: editorial identity — no other hues).
PAPER = (0xFA, 0xF7, 0xF2)
PAPER_HEX = "#FAF7F2"
INK_HEX = "#1C1917"
MUTED_INK_HEX = "#5C554E"
CRIMSON_HEX = "#7A1F1F"

ICON_SIZE = 512
ICON_MARGIN = 16

# ---------------------------------------------------------------------------
# PNG decode (subset: 8-bit RGB, non-interlaced — exactly what logo.png is)
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _read_png_rgb(path: Path) -> tuple[int, int, bytearray]:
    """Return (width, height, flat RGB bytearray) for an 8-bit RGB PNG."""
    blob = path.read_bytes()
    if blob[:8] != _PNG_SIGNATURE:
        raise ValueError(f"{path} is not a PNG")
    pos = 8
    width = height = 0
    idat = bytearray()
    while pos < len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        ctype = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", data)
            if (bit_depth, color_type, interlace) != (8, 2, 0):
                raise ValueError(
                    f"{path}: only 8-bit RGB non-interlaced PNG supported "
                    f"(got depth={bit_depth} color={color_type} interlace={interlace})"
                )
        elif ctype == b"IDAT":
            idat.extend(data)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    stride = 3 * width
    pixels = bytearray(stride * height)
    prev = bytearray(stride)
    for row in range(height):
        offset = row * (stride + 1)
        filter_type = raw[offset]
        cur = bytearray(raw[offset + 1 : offset + 1 + stride])
        if filter_type == 1:  # Sub
            for i in range(3, stride):
                cur[i] = (cur[i] + cur[i - 3]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = cur[i - 3] if i >= 3 else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                a = cur[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                cur[i] = (cur[i] + pred) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"{path}: unsupported PNG filter {filter_type}")
        pixels[row * stride : (row + 1) * stride] = cur
        prev = cur
    return width, height, pixels


def _write_png_rgb(path: Path, width: int, height: int, pixels: bytearray) -> None:
    stride = 3 * width
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 per row — simple and deterministic
        raw.extend(pixels[row * stride : (row + 1) * stride])

    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    path.write_bytes(
        _PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def _box_downsample(src_w: int, src_h: int, src: bytearray, dst_w: int, dst_h: int) -> bytearray:
    """Area-average downsample — smooth result without any dependency."""
    dst = bytearray(3 * dst_w * dst_h)
    for ty in range(dst_h):
        sy0 = ty * src_h // dst_h
        sy1 = max((ty + 1) * src_h // dst_h, sy0 + 1)
        for tx in range(dst_w):
            sx0 = tx * src_w // dst_w
            sx1 = max((tx + 1) * src_w // dst_w, sx0 + 1)
            r = g = b = 0
            count = (sy1 - sy0) * (sx1 - sx0)
            for sy in range(sy0, sy1):
                base = 3 * (sy * src_w + sx0)
                for _ in range(sx0, sx1):
                    r += src[base]
                    g += src[base + 1]
                    b += src[base + 2]
                    base += 3
            di = 3 * (ty * dst_w + tx)
            dst[di] = r // count
            dst[di + 1] = g // count
            dst[di + 2] = b // count
    return dst


def generate_icon() -> None:
    """512x512 icon: logo scaled to fit, white remapped to brand paper.

    Per-channel multiply maps the logo's white background exactly onto the
    paper colour (255 -> 250/247/242) while leaving the near-black mark and
    crimson belt visually unchanged — so the scaled logo blends seamlessly
    into the square canvas instead of sitting in a white box.
    """
    src_w, src_h, src = _read_png_rgb(LOGO)
    drawable = ICON_SIZE - 2 * ICON_MARGIN
    scale = min(drawable / src_w, drawable / src_h)
    dst_w = max(1, round(src_w * scale))
    dst_h = max(1, round(src_h * scale))
    scaled = _box_downsample(src_w, src_h, src, dst_w, dst_h)
    for i in range(0, len(scaled), 3):
        scaled[i] = scaled[i] * PAPER[0] // 255
        scaled[i + 1] = scaled[i + 1] * PAPER[1] // 255
        scaled[i + 2] = scaled[i + 2] * PAPER[2] // 255

    canvas = bytearray(bytes(PAPER) * (ICON_SIZE * ICON_SIZE))
    x0 = (ICON_SIZE - dst_w) // 2
    y0 = (ICON_SIZE - dst_h) // 2
    for row in range(dst_h):
        di = 3 * ((y0 + row) * ICON_SIZE + x0)
        si = 3 * row * dst_w
        canvas[di : di + 3 * dst_w] = scaled[si : si + 3 * dst_w]
    _write_png_rgb(ICON, ICON_SIZE, ICON_SIZE, canvas)
    print(f"wrote {ICON.relative_to(REPO_ROOT)} ({ICON_SIZE}x{ICON_SIZE})")


# ---------------------------------------------------------------------------
# Doctor capture (machine-dependent — explicit mode only)
# ---------------------------------------------------------------------------


def capture_doctor() -> None:
    """Run the real `sumo-qa-doctor` and store a path-sanitised capture.

    Sanitisation is privacy-only — the check lines, statuses, and fix
    commands are the tool's real output. Rules: the user's home directory
    becomes `~`, and the checkout's directory name becomes `sumo-qa` (so
    clone-naming conventions don't leak into the marketing asset).
    """
    result = subprocess.run(
        [sys.executable, "-m", "sumo_qa.doctor"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    text = result.stdout
    if not text.strip():
        raise RuntimeError(f"sumo-qa-doctor produced no stdout (stderr: {result.stderr!r})")
    home = str(Path.home())
    text = text.replace(str(REPO_ROOT), "~/" + "sumo-qa")
    text = text.replace(home, "~")
    text = text.replace(REPO_ROOT.name, "sumo-qa")
    CAPTURE.write_text(text, encoding="utf-8")
    print(f"wrote {CAPTURE.relative_to(REPO_ROOT)} ({len(text.splitlines())} lines)")


def sync_capture_version() -> None:
    """Update the captured doctor version from canonical project metadata."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*$\n(.*?)(?=^\[|\Z)", pyproject)
    if project is None:
        raise ValueError("pyproject.toml has no [project] table")
    version = re.search(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', project.group(1))
    if version is None:
        raise ValueError("pyproject.toml [project] table has no X.Y.Z version")

    lines = CAPTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines:
        raise ValueError(f"{CAPTURE} is empty")
    lines[0], replacements = re.subn(
        r"(sumo-qa )\d+\.\d+\.\d+",
        rf"\g<1>{version.group(1)}",
        lines[0],
        count=1,
    )
    if replacements != 1:
        raise ValueError(f"{CAPTURE} first line has no sumo-qa X.Y.Z version")
    CAPTURE.write_text("".join(lines), encoding="utf-8")
    print(f"updated {CAPTURE.relative_to(REPO_ROOT)} to {version.group(1)}")


# ---------------------------------------------------------------------------
# Preview render (deterministic: capture text -> SVG)
# ---------------------------------------------------------------------------

_PREVIEW_WIDTH = 1200
_MARGIN = 56
_WRAP_COLS = 104
_LINE_HEIGHT = 24
_BODY_FONT_SIZE = 14.5
_SERIF = "Georgia, 'Times New Roman', serif"
_MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"


def _wrap(line: str, cols: int) -> list[str]:
    if len(line) <= cols:
        return [line]
    indent = " " * 8
    words = line.split(" ")
    out: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}" if cur else word
        if len(candidate) > cols and cur:
            out.append(cur)
            cur = indent + word
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _line_style(line: str) -> tuple[str, str]:
    """(fill, font-weight) for one rendered output line."""
    stripped = line.lstrip()
    if stripped.startswith("[FAIL]") or stripped.startswith("[WARN]"):
        return CRIMSON_HEX, "bold"
    if stripped.startswith("Fix:"):
        return CRIMSON_HEX, "normal"
    if stripped.startswith("Summary:"):
        return INK_HEX, "bold"
    if stripped.startswith("[OK]"):
        return MUTED_INK_HEX, "normal"
    return INK_HEX, "normal"


def render_preview() -> None:
    raw_lines = CAPTURE.read_text(encoding="utf-8").splitlines()
    wrapped: list[str] = []
    for line in raw_lines:
        wrapped.extend(_wrap(line, _WRAP_COLS))

    header_h = 148
    prompt_h = _LINE_HEIGHT + 14
    footer_h = 78
    body_h = len(wrapped) * _LINE_HEIGHT
    total_h = header_h + prompt_h + body_h + footer_h

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_PREVIEW_WIDTH}" '
        f'height="{total_h}" viewBox="0 0 {_PREVIEW_WIDTH} {total_h}">'
    )
    parts.append(f'<rect width="{_PREVIEW_WIDTH}" height="{total_h}" fill="{PAPER_HEX}"/>')
    parts.append(f'<rect width="{_PREVIEW_WIDTH}" height="6" fill="{CRIMSON_HEX}"/>')
    parts.append(
        f'<text x="{_MARGIN}" y="78" font-family="{_SERIF}" font-size="40" '
        f'font-weight="bold" fill="{INK_HEX}">Sumo QA</text>'
    )
    parts.append(
        f'<text x="{_PREVIEW_WIDTH - _MARGIN}" y="78" text-anchor="end" '
        f'font-family="{_SERIF}" font-size="19" font-style="italic" '
        f'fill="{CRIMSON_HEX}">sumo-qa-doctor &#8212; one read-only command to verify any host setup</text>'
    )
    parts.append(
        f'<line x1="{_MARGIN}" y1="104" x2="{_PREVIEW_WIDTH - _MARGIN}" y2="104" '
        f'stroke="{INK_HEX}" stroke-width="1" stroke-opacity="0.35"/>'
    )
    parts.append(
        f'<text x="{_MARGIN}" y="{header_h}" xml:space="preserve" font-family="{_MONO}" '
        f'font-size="{_BODY_FONT_SIZE}" font-weight="bold" fill="{INK_HEX}">$ sumo-qa-doctor</text>'
    )
    y = header_h + prompt_h
    for line in wrapped:
        fill, weight = _line_style(line)
        weight_attr = f' font-weight="{weight}"' if weight != "normal" else ""
        parts.append(
            f'<text x="{_MARGIN}" y="{y}" xml:space="preserve" font-family="{_MONO}" '
            f'font-size="{_BODY_FONT_SIZE}" fill="{fill}"{weight_attr}>{escape(line)}</text>'
        )
        y += _LINE_HEIGHT
    footer_rule_y = y + 14
    parts.append(
        f'<line x1="{_MARGIN}" y1="{footer_rule_y}" x2="{_PREVIEW_WIDTH - _MARGIN}" '
        f'y2="{footer_rule_y}" stroke="{INK_HEX}" stroke-width="1" stroke-opacity="0.35"/>'
    )
    parts.append(
        f'<text x="{_MARGIN}" y="{footer_rule_y + 36}" font-family="{_SERIF}" '
        f'font-size="17" font-style="italic" fill="{INK_HEX}">Real output &#8212; every '
        f"failure ships the exact command that fixes it.</text>"
    )
    parts.append(
        f'<text x="{_PREVIEW_WIDTH - _MARGIN}" y="{footer_rule_y + 36}" text-anchor="end" '
        f'font-family="{_SERIF}" font-size="17" fill="{MUTED_INK_HEX}">github.com/sumithr/sumo-qa</text>'
    )
    parts.append("</svg>")
    PREVIEW.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {PREVIEW.relative_to(REPO_ROOT)} ({_PREVIEW_WIDTH}x{total_h})")


_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0xFE00, 0xFE0F),
    (0x2190, 0x21FF),
)


def _assert_no_pictograms(text: str, label: str) -> None:
    for ch in text:
        cp = ord(ch)
        for lo, hi in _EMOJI_RANGES:
            if lo <= cp <= hi:
                raise ValueError(f"{label} contains pictogram U+{cp:04X} — brand bans emojis")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/generate_marketplace_assets.py",
        description="Generate marketplace assets (icon + doctor preview) from canonical inputs.",
    )
    parser.add_argument(
        "mode", choices=("icon", "capture", "version", "render", "all"), default="all"
    )
    args = parser.parse_args(argv)
    if args.mode in ("icon", "all"):
        generate_icon()
    if args.mode == "capture":
        capture_doctor()
        _assert_no_pictograms(CAPTURE.read_text(encoding="utf-8"), str(CAPTURE))
        # Re-render immediately: the SVG is deterministic from the capture,
        # so this keeps the documented `capture` refresh from leaving a
        # stale preview-doctor.svg behind.
        render_preview()
        _assert_no_pictograms(PREVIEW.read_text(encoding="utf-8"), str(PREVIEW))
    if args.mode == "version":
        sync_capture_version()
        render_preview()
        _assert_no_pictograms(CAPTURE.read_text(encoding="utf-8"), str(CAPTURE))
        _assert_no_pictograms(PREVIEW.read_text(encoding="utf-8"), str(PREVIEW))
    if args.mode in ("render", "all"):
        render_preview()
        _assert_no_pictograms(PREVIEW.read_text(encoding="utf-8"), str(PREVIEW))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
