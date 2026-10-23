#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a one-page tailored resume from profile.json + a JD spec.

The point of this script is *stable output*: it renders, measures the page with
real font metrics, and if the page is too tall it drops the lowest-scoring
bullet and renders again — so whatever JD comes in, the result is one A4 page.

Usage:
  python3 scripts/build_resume.py --profile data/profile.json \
      --jd data/jd.json --out output/resume.docx
"""

import argparse
import json
import os
import sys
from copy import deepcopy

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lib(name):
    """Prefer the self-contained copy under lib/, fall back to the workspace build/."""
    local = os.path.join(ROOT, "lib", name)
    if os.path.exists(local):
        return local
    return os.path.join(ROOT, "..", "build", name)

import importlib.util

spec = importlib.util.spec_from_file_location(
    "build_docs", _lib("build_docs.py")
)
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)

spec_qa = importlib.util.spec_from_file_location(
    "qa_fit", _lib("qa_fit.py")
)
qa = importlib.util.module_from_spec(spec_qa)
spec_qa.loader.exec_module(qa)

PHOTO = os.path.join(ROOT, "assets", "photo_1inch.jpg")
if not os.path.exists(PHOTO):
    PHOTO = os.path.join(ROOT, "..", "resume_assets", "photo_1inch.jpg")
GREY = RGBColor(0x40, 0x40, 0x40)
BODY = 10.0
LEAD = 13.2

# JD 关键词 → 能力标签权重
FOCUS = {
    "audit": ["审计", "鉴证", "底稿", "勾稽", "内控", "尽职调查", "尽调"],
    "consulting": ["咨询", "顾问", "项目", "方案", "转型", "客户"],
    "ib": ["投行", "并购", "交易", "IPO", "估值", "资本市场"],
    "fp_and_a": ["财务分析", "预算", "预测", "管理报表", "FP&A", "财务管培"],
    "credit": ["授信", "信贷", "贷款", "核保", "客户经理"],
    "risk": ["风险", "风控", "合规", "资产质量"],
    "fixed_income": ["固收", "债券", "久期", "利率", "利差"],
    "ai": ["AI", "大模型", "智能体", "自动化", "数字化"],
    "client": ["客户", "财富", "营销", "渠道"],
}

TAG_ALIAS = {"analysis": "fp_and_a", "reporting": "fp_and_a", "close": "audit",
             "valuation": "ib", "research": "ib", "process": "ai",
             "data": "ai", "communication": "consulting", "leadership": "consulting"}


def weights_from_jd(jd):
    text = " ".join(str(v) for v in jd.values())
    w = {}
    for tag, kws in FOCUS.items():
        n = sum(text.count(k) for k in kws)
        if n:
            w[tag] = 1.0 + min(n, 5) * 0.4
    return w or {"fp_and_a": 1.0}


def score(item, w):
    s = 0.0
    for t in item.get("tags", []):
        key = TAG_ALIAS.get(t, t)
        s += w.get(key, 0) + (0.2 if t in ("modelling", "fixed_income") else 0)
    return s


def rule(p, color="808080", size=6):
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    bdr.append(bottom)
    ppr.append(bdr)


def sec(doc, text, space_before=4.0):
    p = bd.para(doc, space_before=space_before, space_after=1.4, line_pt=13)
    p.paragraph_format.keep_with_next = True
    bd.style_run(p.add_run(text), size=10.5, bold=True)
    rule(p)
    return p


def entry(doc, org, role, date, space_before=2.8):
    p = bd.para(doc, space_before=space_before, space_after=0.6, line_pt=12.4)
    p.paragraph_format.keep_with_next = True
    bd.right_tab(p, 17.9)
    bd.style_run(p.add_run(org), size=10, bold=True)
    if role:
        bd.style_run(p.add_run("　" + role), size=9.5, bold=True)
    bd.style_run(p.add_run("\t" + date), size=9.0, color=GREY)
    return p


def bul(doc, label, text, indent=0.48):
    p = bd.para(doc, space_after=0.5, line_pt=LEAD, left_indent=indent,
                first_line_indent=-indent)
    p.paragraph_format.keep_together = True
    bd.style_run(p.add_run("•  "), size=BODY)
    if label:
        bd.style_run(p.add_run(label + "："), size=BODY, bold=True)
    bd.style_run(p.add_run(text), size=BODY)
    return p


def no_borders(table):
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "none")
        node.set(qn("w:sz"), "0")
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), "auto")
        borders.append(node)
    tblpr.append(borders)
    mar = OxmlElement("w:tblCellMar")
    for tag in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{tag}")
        node.set(qn("w:w"), "0")
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tblpr.append(mar)


def header(doc, profile, jd):
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    no_borders(table)
    left, right = table.rows[0].cells
    left.width, right.width = Cm(13.6), Cm(3.6)
    left.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    right.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    p = left.paragraphs[0]
    p.paragraph_format.space_after = Pt(1.6)
    p.paragraph_format.line_spacing = Pt(21)
    bd.style_run(p.add_run(profile["name"]), size=17, bold=True)
    bd.style_run(p.add_run("   " + profile["name_en"]), size=9.6, color=GREY)

    for text, bold, color, after in [
        (f"电话 {profile['phone']}　｜　邮箱 {profile['email']}", False, GREY, 0.5),
        (jd.get("intent_line") or f"求职意向：{profile['default_intent']}", True, bd.BLACK, 0.5),
        (jd.get("avail_line") or profile["available"], False, GREY, 0.5),
    ]:
        q = left.add_paragraph()
        q.paragraph_format.space_before = Pt(0)
        q.paragraph_format.space_after = Pt(after)
        q.paragraph_format.line_spacing = Pt(12.4)
        bd.style_run(q.add_run(text), size=9.0, bold=bold, color=color)

    pic = right.paragraphs[0]
    pic.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pic.paragraph_format.space_after = Pt(0)
    if os.path.exists(PHOTO):
        pic.add_run().add_picture(PHOTO, width=Cm(2.1))
    return table


def render(profile, jd, out, n_first=5, n_second=4, n_proj=4):
    w = weights_from_jd(jd)
    exps = deepcopy(profile["experiences"])
    picks = []
    for i, e in enumerate(exps):
        ranked = sorted(e["bullets"], key=lambda b: -score(b, w))
        k = n_first if i == 0 else n_second
        chosen = ranked[:k]
        # 按匹配度排序：与 JD 最相关的条目放最前
        picks.append((e, chosen))
    projs = sorted(profile["projects"], key=lambda p: -score(p, w))[:n_proj]
    projs = projs  # 保留匹配度排序

    doc = Document()
    bd.set_doc_defaults(doc)
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.top_margin, s.bottom_margin = Cm(1.2), Cm(1.1)
        s.left_margin, s.right_margin = Cm(1.55), Cm(1.55)
    header(doc, profile, jd)

    ed = profile["education"]
    sec(doc, "教育经历", space_before=3.4)
    entry(doc, ed["school"], f"{ed['degree']}（GPA {ed['gpa']}）",
          f"{ed['start']} - {ed['end']}", space_before=0.4)
    bul(doc, "主修课程", ed["courses"])
    bul(doc, "荣誉", ed["honors"])

    sec(doc, "实习经历")
    for e, bullets in picks:
        entry(doc, e["org"], f"{e['role']}　{e['city']}",
              f"{e['start']} - {e['end']}", space_before=0.4 if e is exps[0] else 4.0)
        for b in bullets:
            bul(doc, b["label"], b["text"])

    sec(doc, "项目经历")
    for i, p in enumerate(projs):
        entry(doc, p["title"], p["role"], f"{p['start']} - {p['end']}",
              space_before=0.4 if i == 0 else 2.8)
        bul(doc, None, p["text"])

    sec(doc, "技能、证书与语言")
    bul(doc, "财务与数据", profile["skills"]["financial"])
    bul(doc, "工具与 AI", profile["skills"]["data"])
    bul(doc, "证书与语言", profile["skills"]["certs"])

    doc.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(ROOT, "data", "profile.json"))
    ap.add_argument("--jd", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-mm", type=float, default=268.0)
    a = ap.parse_args()

    profile = json.load(open(a.profile, encoding="utf-8"))
    jd = json.load(open(a.jd, encoding="utf-8"))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    n_first, n_second, n_proj = 5, 4, 4
    for attempt in range(6):
        render(profile, jd, a.out, n_first, n_second, n_proj)
        h = qa.estimate(a.out, usable_mm=274.0, quiet=True)
        print(f"attempt {attempt + 1}: {n_first}/{n_second}/{n_proj} -> {h:.1f}mm")
        if h <= a.max_mm:
            break
        if n_proj > 3:
            n_proj -= 1
        elif n_first > 4:
            n_first -= 1
        elif n_second > 3:
            n_second -= 1
        else:
            break
    print("written:", a.out)


if __name__ == "__main__":
    main()
