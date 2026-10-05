"""Build a CBDT color bitmap font from emoji PNGs (used for Apple-style emoji in the panel).

    python tools/build_emoji_font.py <png_dir> <out.ttf> <codepoint-files...>

PNG names: emoji-datasource style, e.g. 1f680.png, 2699-fe0f.png. Only single-codepoint
emoji (optionally followed by U+FE0F) are included; FE0F/ZWJ map to an empty glyph so
"⚙️" renders as the ⚙ bitmap. Requires fontTools.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import C_B_D_T_, C_B_L_C_
from fontTools.ttLib.tables.BitmapGlyphMetrics import SmallGlyphMetrics
from fontTools.ttLib.tables.E_B_L_C_ import BitmapSizeTable, SbitLineMetrics

UPM = 2048
PPEM = 109  # bitmaps are 64px; strike ppem chosen so that the image ~ fits the em like Noto (136px/109ppem)
ASCENT, DESCENT = 1900, -500


def png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


def build(png_dir: Path, out: Path, names: list[str], family: str = "Apple Emoji VK") -> None:
    glyphs: list[tuple[int, str, bytes]] = []
    for name in names:
        parts = [p for p in name.split("-") if p != "fe0f"]
        if len(parts) != 1:
            continue
        cp = int(parts[0], 16)
        data = (png_dir / f"{name}.png").read_bytes()
        glyphs.append((cp, f"u{cp:04X}", data))
    glyphs.sort()
    order = [".notdef", "space", "zerowidth"] + [g[1] for g in glyphs]

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    cmap = {0x20: "space", 0xFE0F: "zerowidth", 0x200D: "zerowidth", 0xFE0E: "zerowidth"}
    cmap.update({cp: gname for cp, gname, _ in glyphs})
    fb.setupCharacterMap(cmap)
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({g: empty for g in order})
    advance = int(UPM * 1.275)
    metrics = {g: (advance, 0) for g in order}
    metrics["zerowidth"] = (0, 0)
    metrics["space"] = (UPM // 3, 0)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, usWinAscent=ASCENT, usWinDescent=-DESCENT)
    fb.setupPost()
    font = fb.font

    # ---- CBDT / CBLC
    cbdt = newTable("CBDT")
    cbdt.version = 3.0
    strike_data = {}
    first = order.index(glyphs[0][1])
    for _, gname, data in glyphs:
        w, h = png_size(data)
        bitmap = C_B_D_T_.cbdt_bitmap_format_17(b"", font)
        m = SmallGlyphMetrics()
        m.height, m.width = h, w
        m.BearingX = 0
        m.BearingY = int(h * 0.86)
        m.Advance = int(w * 1.0)
        bitmap.metrics = m
        bitmap.imageData = data
        strike_data[gname] = bitmap
    cbdt.strikeData = [strike_data]
    font["CBDT"] = cbdt

    cblc = newTable("CBLC")
    cblc.version = 3.0
    size = BitmapSizeTable()
    for attr in ("hori", "vert"):
        line = SbitLineMetrics()
        px0 = png_size(glyphs[0][2])[0]
        line.ascender, line.descender = round(px0 * 0.81), -round(px0 * 0.19)
        line.widthMax = px0
        for k in ("caretSlopeNumerator", "caretSlopeDenominator", "caretOffset", "minOriginSB",
                  "minAdvanceSB", "maxBeforeBL", "minAfterBL", "pad1", "pad2"):
            setattr(line, k, 0)
        line.caretSlopeNumerator, line.caretSlopeDenominator = 0, 0
        setattr(size, attr, line)
    size.colorRef = 0
    size.startGlyphIndex = first
    size.endGlyphIndex = len(order) - 1
    px = png_size(glyphs[0][2])[0]
    size.ppemX = size.ppemY = round(px / 1.185)  # bitmaps drawn at ~1.18em, close to native emoji size
    size.bitDepth = 32
    size.flags = 1
    index = C_B_L_C_.cblc_index_sub_table_1(b"", font) if hasattr(C_B_L_C_, "cblc_index_sub_table_1") else None
    if index is None:
        from fontTools.ttLib.tables.E_B_L_C_ import eblc_index_sub_table_1 as index_cls
        index = index_cls(b"", font)
    index.indexFormat = 1
    index.imageFormat = 17
    index.firstGlyphIndex = first
    index.lastGlyphIndex = len(order) - 1
    index.names = [g[1] for g in glyphs]
    size.indexSubTables = [index]
    cblc.strikes = [C_B_L_C_.Strike() if hasattr(C_B_L_C_, "Strike") else _strike(size)]
    if hasattr(cblc.strikes[0], "bitmapSizeTable"):
        cblc.strikes[0].bitmapSizeTable = size
        cblc.strikes[0].indexSubTables = [index]
    font["CBLC"] = cblc
    font.save(out)


def _strike(size):  # pragma: no cover - compatibility shim
    from fontTools.ttLib.tables.E_B_L_C_ import Strike

    s = Strike()
    s.bitmapSizeTable = size
    return s


if __name__ == "__main__":
    png_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    if len(sys.argv) > 3:  # explicit list of names (file with one name per line)
        names = [n.strip() for n in Path(sys.argv[3]).read_text().split() if n.strip()]
    else:
        names = [p.stem for p in sorted(png_dir.glob("*.png"))]
    build(png_dir, out, names)
    print(f"{out}: {len(names)} emoji, {out.stat().st_size // 1024} KB")
