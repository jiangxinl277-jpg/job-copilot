# -*- coding: utf-8 -*-
"""Shared python-docx helpers used by build_resume.py.

Only the primitives are kept here: paragraph factory, run styling, page setup
and a right-aligned tab stop. Layout content lives in data/profile.json so the
generator never hard-codes a person.
"""

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

LATIN = "Helvetica Neue"
EA = "PingFang SC"
BLACK = RGBColor(0x00, 0x00, 0x00)


def style_run(run, size=10.5, bold=False, italic=False, color=BLACK, ea=EA):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = LATIN
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), LATIN)
    rfonts.set(qn("w:hAnsi"), LATIN)
    rfonts.set(qn("w:eastAsia"), ea)
    return run


def para(container, space_before=0, space_after=2, line_spacing=1.10,
         left_indent=None, first_line_indent=None, align=None, line_pt=None):
    p = container.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = Pt(line_pt) if line_pt is not None else line_spacing
    if left_indent is not None:
        pf.left_indent = Cm(left_indent)
    if first_line_indent is not None:
        pf.first_line_indent = Cm(first_line_indent)
    if align is not None:
        pf.alignment = align
    return p


def right_tab(p, position_cm):
    p.paragraph_format.tab_stops.add_tab_stop(Cm(position_cm), WD_TAB_ALIGNMENT.RIGHT)
    return p


def set_doc_defaults(doc):
    normal = doc.styles["Normal"]
    normal.font.name = LATIN
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = BLACK
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), LATIN)
    rfonts.set(qn("w:hAnsi"), LATIN)
    rfonts.set(qn("w:eastAsia"), EA)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.10


def page_setup(doc, side=1.8, top=1.5, bottom=1.4):
    for section in doc.sections:
        section.left_margin = Cm(side)
        section.right_margin = Cm(side)
        section.top_margin = Cm(top)
        section.bottom_margin = Cm(bottom)
