#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive candidate metadata from a resume instead of hard-coding it.

All values are computed from the candidate's own material:

  graduation   the latest end date found in the education block
  cohort       explicit "20xx 届" when present; otherwise 中国校招口径：
               毕业月份 >= 9 月算下一年（2025-12 / 2026-01 → 2026 届）
  degree       本科 / 硕士 / 博士（取最高）
  major(s)     从教育经历抽取，只作为说明信息，不参与硬过滤
  strength     {tag: evidence score} 由经历/项目 bullet + 技能区提及决定

Works with both data/profile.json (structured) and a parsed resume JSON.
"""

import json
import re

DEGREES = ["博士", "硕士", "研究生", "本科", "学士"]
MAJOR_ALIASES = {
    "金融": ["金融学", "金融工程", "经济与金融", "金融科技", "投资学"],
    "会计": ["会计学", "会计", "财务管理", "审计学"],
    "经济": ["经济学", "经济统计", "国际经济与贸易", "财政学", "税务"],
    "统计": ["统计学", "应用统计", "数据科学"],
    "数学": ["数学", "应用数学"],
    "计算机": ["计算机", "软件工程", "信息安全", "人工智能", "网络工程"],
    "数据": ["数据科学", "大数据", "信息管理", "商业分析"],
    "管理": ["工商管理", "管理学", "管理科学", "市场营销", "人力资源"],
    "法学": ["法学", "法律"],
    "工程": ["工程管理", "机械", "电气", "土木", "化学工程", "材料"],
    "电子": ["电子信息", "电子工程", "通信工程", "自动化"],
    "物理": ["物理学", "应用物理"],
    "化学": ["化学", "应用化学"],
    "医学": ["医学", "临床", "护理", "药学"],
    "英语": ["英语", "外国语言文学", "翻译"],
}
EDU_MARKERS = ("大学", "学院", "本科", "硕士", "博士", "研究生", "学士",
               "graduat", "university", "college", "bachelor", "master")
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _text(profile):
    if profile.get("text"):
        return profile["text"]
    parts = [profile.get("name", ""), profile.get("default_intent", "")]
    ed = profile.get("education", {})
    if isinstance(ed, dict):
        parts += [str(v) for v in ed.values() if isinstance(v, (str, int, float))]
    for e in profile.get("experiences", []):
        parts += [e.get("org", ""), e.get("role", "")]
        parts += [b.get("text", "") for b in e.get("bullets", [])]
    for p in profile.get("projects", []):
        parts += [p.get("title", ""), p.get("text", "")]
    sk = profile.get("skills", {})
    parts += list(sk.values()) if isinstance(sk, dict) else [str(sk)]
    return "\n".join(parts)


def _education_text(profile):
    ed = profile.get("education", {})
    if isinstance(ed, dict) and ed:
        return " ".join(str(v) for v in ed.values() if isinstance(v, (str, int, float)))
    if isinstance(ed, list) and ed:
        return " ".join(str(v) for v in ed if isinstance(v, (str, int, float)))
    sec = profile.get("sections", {}).get("education")
    if sec:
        return " ".join(sec)
    # 未结构化的简历：截取教育标题后的相邻行，避免把未来实习/项目日期
    # 误当成毕业时间。
    lines = [l.strip() for l in _text(profile).splitlines() if l.strip()]
    hits = [i for i, line in enumerate(lines)
            if any(m.lower() in line.lower() for m in EDU_MARKERS)]
    if hits:
        keep = set()
        for i in hits:
            keep.update(range(max(0, i - 1), min(len(lines), i + 3)))
        return "\n".join(lines[i] for i in sorted(keep))
    return _text(profile)


def _explicit_cohort(text):
    years = [int(y) for y in re.findall(r"(20\d{2})\s*届", text)]
    years += [int(y) for y in re.findall(r"(?:class\s+of|cohort)\s*(20\d{2})", text, flags=re.I)]
    return max(years) if years else None


def graduation(profile):
    """Latest graduation end date in the education block.

    A date range such as 2020.08–2025.12 uses the end, not the start.
    Year-only phrases such as "预计2026年毕业" fall back to June.
    """
    for source in (_education_text(profile), _text(profile)):
        precise, fallback = [], []
        for m in re.finditer(
                r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*月?"
                r"\s*(?:-|–|—|至|到|~)\s*"
                r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*月?",
                source):
            y, mo = int(m.group(3)), int(m.group(4))
            if 1 <= mo <= 12:
                precise.append((y, mo))
        for y, m in re.findall(r"(20\d{2})\s*[年./-]\s*(\d{1,2})", source):
            if 1 <= int(m) <= 12:
                precise.append((int(y), int(m)))
        for y in re.findall(r"(20\d{2})\s*年?\s*(?:预计|预期)?\s*毕业", source):
            fallback.append((int(y), 6))
        for month, y in re.findall(
                r"\b(" + "|".join(MONTHS) + r")[a-z]*\s*,?\s*(20\d{2})\b",
                source, flags=re.I):
            precise.append((int(y), MONTHS[month[:3].lower()]))
        for y in re.findall(
                r"\b(?:graduat(?:ion|ing)|class\s+of)\D{0,12}(20\d{2})\b",
                source, flags=re.I):
            fallback.append((int(y), 6))
        if precise:
            return max(precise)
        if fallback:
            return max(fallback)
    return None


def cohort_of(grad, profile=None):
    """中国校招口径：9–12 月毕业归入下一年届。"""
    explicit = (
        _explicit_cohort(_education_text(profile)) or
        _explicit_cohort(_text(profile))
    ) if profile else None
    if explicit:
        return explicit
    if not grad:
        return None
    y, m = grad
    return y + 1 if m >= 9 else y


def degree(profile):
    text = _education_text(profile) + " " + _text(profile)
    lower = text.lower()
    if any(x in lower for x in ("ph.d", "phd", "doctor of")):
        return "博士"
    if any(x in lower for x in ("master of", "master's", "msc", "m.sc", "mba")):
        return "硕士"
    if any(x in lower for x in ("bachelor of", "bachelor's", "b.sc", "b.a.")):
        return "本科"
    for d in DEGREES:
        if d in text:
            return {"博士": "博士", "硕士": "硕士", "研究生": "硕士",
                    "本科": "本科", "学士": "本科"}[d]
    return None


def major(profile):
    edu = _education_text(profile)
    found = []
    for canonical, aliases in MAJOR_ALIASES.items():
        if any(alias.lower() in edu.lower() for alias in aliases + [canonical]):
            found.append(canonical)
    return found[0] if found else None


def majors(profile):
    edu = _education_text(profile)
    return [
        canonical for canonical, aliases in MAJOR_ALIASES.items()
        if any(alias.lower() in edu.lower() for alias in aliases + [canonical])
    ]


def _evidence_lines(profile):
    sections = profile.get("sections") or {}
    if sections:
        return list(sections.get("experience", [])) + list(sections.get("projects", []))
    lines = []
    for e in profile.get("experiences", []):
        lines.extend(b.get("text", "") for b in e.get("bullets", []))
    for p in profile.get("projects", []):
        lines.append(p.get("text", ""))
    return [line for line in lines if line]


def _skills_text(profile):
    skills = profile.get("skills", {})
    if isinstance(skills, dict):
        return " ".join(str(v) for v in skills.values())
    if isinstance(skills, list):
        return " ".join(str(v) for v in skills)
    sections = profile.get("sections") or {}
    return " ".join(sections.get("skills", []))


def tag_strength(profile):
    """Capability evidence score derived from the submitted resume.

    Structured profiles use bullet/project tags. Parsed resumes are scanned
    section by section: experience/project evidence counts more than a skill
    list mention, and generic keywords do not receive a large multiplier.
    """
    counts = {}
    for e in profile.get("experiences", []):
        for b in e.get("bullets", []):
            for t in b.get("tags", []):
                counts[t] = counts.get(t, 0) + 1
    for p in profile.get("projects", []):
        for t in p.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    try:
        from match_evidence import KW2TAG
    except Exception:
        KW2TAG = {}

    skills = _skills_text(profile)
    skill_tags = set()
    for kw, tags in KW2TAG.items():
        if kw in skills:
            skill_tags.update(tags)

    # Parsed resume: count each capability at most once per evidence line.
    # Structured profiles already carry explicit bullet tags; do not add the
    # same evidence a second time from raw keyword occurrence.
    if not counts:
        for line in _evidence_lines(profile):
            matched_tags = set()
            for kw, tags in KW2TAG.items():
                if kw in line:
                    matched_tags.update(tags)
            for t in matched_tags:
                counts[t] = counts.get(t, 0) + 1

    if counts:
        return {
            t: round(min(2.8, 0.8 + 0.45 * n + (0.15 if t in skill_tags else 0.0)), 2)
            for t, n in counts.items()
        } | {
            t: 0.45 for t in skill_tags if t not in counts
        }

    return {
        t: round(min(2.5, 0.35 + 0.35 * n + (0.15 if t in skill_tags else 0.0)), 2)
        for t, n in counts.items()
    } | {
        t: 0.45 for t in skill_tags if t not in counts
    }


def describe(path):
    profile = json.load(open(path, encoding="utf-8"))
    return meta_from_profile(profile)


def meta_from_profile(profile):
    grad = graduation(profile)
    candidate_majors = majors(profile)
    return {
        "graduation": f"{grad[0]}-{grad[1]:02d}" if grad else None,
        "cohort": cohort_of(grad, profile),
        "degree": degree(profile),
        "major": candidate_majors[0] if candidate_majors else None,
        "majors": candidate_majors,
        "strength": tag_strength(profile),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(describe(sys.argv[1]), ensure_ascii=False, indent=1))
