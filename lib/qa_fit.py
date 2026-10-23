# -*- coding: utf-8 -*-
"""Estimate how tall a built resume DOCX is, using real font metrics.

The builder sets *exact* line spacing in points, so vertical space is
deterministic in Word; only the number of wrapped lines is uncertain. This
script wraps each paragraph greedily with PingFang metrics and sums:

    lines * exact line spacing + space_before + space_after

which is close enough to tell whether a page will overflow.

Usage:  python3 build/qa_fit.py <docx> [--usable-mm 274]
"""

import sys

from docx import Document
from docx.shared import Length
from PIL import ImageFont

PINGFANG = "/System/Library/Fonts/PingFang.ttc"
MM_PER_PT = 25.4 / 72


def font_for(size_pt):
    return ImageFont.truetype(PINGFANG, int(round(size_pt * 10)))


def text_width_pt(text, size_pt):
    """Width of ``text`` in points at ``size_pt``."""
    font = font_for(size_pt)
    return font.getlength(text) / 10.0


def is_cjk(ch):
    code = ord(ch)
    return (0x4E00 <= code <= 0x9FFF) or (0x3000 <= code <= 0x303F) or \
           (0xFF00 <= code <= 0xFFEF) or code in (0x2018, 0x2019, 0x201C, 0x201D,
                                                  0x2014, 0x2013, 0x00B1, 0x00D7)


NO_LINE_START = set("，。、；：？！）》】」』%,.;:?!)]}\u201d\u2019")


def wrap(text, size_pt, width_pt):
    """Greedy wrap; CJK breaks anywhere, Latin words break at spaces."""
    if not text:
        return 1
    lines, cur, cur_w = 1, "", 0.0
    token = ""

    def flush_token():
        nonlocal cur, cur_w, lines, token
        if not token:
            return
        w = text_width_pt(token, size_pt)
        if cur_w + w > width_pt and cur:
            lines += 1
            cur, cur_w = "", 0.0
        cur += token
        cur_w += w
        token = ""

    for ch in text:
        if is_cjk(ch):
            flush_token()
            w = text_width_pt(ch, size_pt)
            if cur_w + w > width_pt and cur:
                # avoid starting a line with closing punctuation
                if ch in NO_LINE_START and cur:
                    cur += ch
                    cur_w += w
                    lines += 1
                    cur, cur_w = "", 0.0
                    continue
                lines += 1
                cur, cur_w = "", 0.0
            cur += ch
            cur_w += w
        elif ch == " ":
            token += ch
            flush_token()
        else:
            token += ch
    flush_token()
    return lines


def para_height_mm(p, width_mm):
    text = p.text
    sizes = [r.font.size.pt for r in p.runs if r.font.size is not None]
    size = max(sizes) if sizes else 10.0
    pf = p.paragraph_format
    lead = pf.line_spacing
    lead_pt = lead.pt if isinstance(lead, Length) else (size * 1.35)
    indent = pf.left_indent.pt if pf.left_indent is not None else 0.0
    avail = (width_mm - indent * MM_PER_PT) / MM_PER_PT
    last_line_width = text_width_pt(text, size)
    if last_line_width <= avail:
        lines = 1
    else:
        lines = wrap(text, size, avail)
    sb = pf.space_before.pt if pf.space_before is not None else 0.0
    sa = pf.space_after.pt if pf.space_after is not None else 0.0
    return (lines * lead_pt + sb + sa) * MM_PER_PT, lines


def estimate(path, usable_mm=274.0, width_mm=176.0, quiet=False):
    doc = Document(path)
    total = 0.0
    rows = []
    for p in doc.paragraphs:
        h, lines = para_height_mm(p, width_mm)
        total += h
        if p.text.strip():
            rows.append((lines, h, p.text.strip()[:46]))
    # header table: photo 22mm wide -> 31.4mm tall, or the text block if taller
    for t in doc.tables:
        cell_h = 0.0
        for cell in t.rows[0].cells:
            for p in cell.paragraphs:
                h, _ = para_height_mm(p, 120.0)
                cell_h += h
        total += max(31.4, cell_h)
    if not quiet:
        for lines, h, text in rows:
            print(f"{lines:>2} 行 {h:6.1f}mm  {text}")
    print(f"\n估算总高: {total:.1f}mm / 可用 {usable_mm:.0f}mm "
          f"({'FIT' if total <= usable_mm else 'OVERFLOW'} {total - usable_mm:+.1f}mm)")
    return total


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    usable = 274.0
    for a in sys.argv[1:]:
        if a.startswith("--usable-mm"):
            usable = float(a.split("=")[1]) if "=" in a else usable
    estimate(args[0], usable_mm=usable)
