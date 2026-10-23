#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch mode v3: candidate-derived gates and evidence-weighted matching.

What changed vs v1
  * cohort comes from the resume's graduation date (Sep–Dec → next year's 届),
    not a hard-coded "2026"
  * degree check uses the candidate's own degree; major is informational only
  * technical roles are no longer excluded — they are scored against the
    candidate's actual skills (SQL/Python/AI/数据 …)
  * keyword weights are multiplied by the candidate's evidence strength per
    capability tag, so two candidates get different rankings from the same table

Usage:
  python3 scripts/batch_score.py --excel data/jobs.xlsx \
      --resume data/resume_profile.json --out output/rank.xlsx --deep 6 --resumes 5
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from match_evidence import ALIASES, KW2TAG  # noqa: E402
import profile_meta  # noqa: E402

TODAY = datetime.date.today()
TARGET_CITIES = {"北京", "上海", "深圳", "杭州", "苏州"}

NODE = (os.environ.get("NODE_BIN") or shutil.which("node")
        or "/Users/jiangxinli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")

KW_WEIGHT = {
    "金融": 2.2, "银行": 2, "保险": 2.2, "资管": 2.2, "财务": 2.5,
    "会计": 2.5, "证券": 2.5, "基金": 2.5, "投资": 2,
    "审计": 3, "鉴证": 3, "底稿": 3, "勾稽": 3, "尽职调查": 3, "尽调": 3,
    "债券": 3, "固收": 3, "久期": 3, "凸性": 3, "利差": 2.5, "定价": 2.5,
    "估值": 3, "可比公司": 3, "DCF": 3, "并购": 3, "投行": 3, "资本市场": 2.5,
    "预算": 2.5, "预测": 2.5, "管理报表": 2.5, "财务分析": 3, "差异分析": 2.5,
    "授信": 3, "信贷": 3, "核保": 2.5, "信用分析": 3, "风险": 2, "风控": 2.5,
    "评级": 2.5, "资产质量": 2.5, "合规": 2, "反洗钱": 3, "AML": 3, "KYC": 3,
    "建模": 2.5, "模型": 1.5, "数据分析": 2.2, "SQL": 2.2, "Python": 2.5, "Java": 2,
    "C++": 2, "JavaScript": 2, "前端": 2.2, "后端": 2.2, "全栈": 2.2, "开发": 2,
    "软件": 1.8, "算法": 2.5, "机器学习": 2.5, "深度学习": 2.5, "测试": 1.8,
    "运维": 1.8, "嵌入式": 2.2, "Power Query": 2.2, "Power BI": 2, "Tableau": 2,
    "AI": 2, "人工智能": 2.2, "大模型": 2.3, "智能体": 2.3, "自动化": 1.8, "流程": 1,
    "客户": 1, "营销": 1, "财富": 1.5, "研究": 1.5, "管培": 1.2, "培训生": 1,
    "分析": 0.6, "数据": 0.8, "团队": 0.5, "沟通": 0.5, "报告": 0.6, "Excel": 1,
}

GENERIC_KEYWORDS = {
    "分析", "数据", "团队", "沟通", "报告", "流程", "客户", "研究",
    "优化", "管培", "培训生", "英语",
}

CORE_ROLE_WORDS = ["精算", "核保", "理赔", "承保", "再保", "清算", "托管",
                   "经纪", "投顾", "期货", "信托", "租赁", "保理", "外汇",
                   "交易员", "查勘", "量化", "算法", "Java", "Python", "C++",
                   "嵌入式", "前端", "后端", "机械", "电气", "化工", "护理",
                   "医师", "药学", "教师", "Infra", "Agent", "大模型", "训推",
                   "算子", "强化学习", "多模态", "机器学习", "深度学习"]

# 岗位方向只用于判断"简历里有没有可迁移证据"；没有证据时封顶而不是删除。
ROLE_FAMILIES = {
    "finance": {
        "markers": ("金融", "银行", "证券", "基金", "保险", "风控", "信贷", "授信",
                    "审计", "会计", "财务", "投资", "估值", "固收", "债券", "精算",
                    "核保", "理赔", "信托", "租赁", "资管", "财富"),
        "tags": {"finance", "fp_and_a", "credit", "risk", "audit", "accounting",
                 "valuation", "fixed_income", "pricing", "reporting", "securities",
                 "asset_mgmt", "investment", "compliance"},
    },
    "technology": {
        "markers": ("开发", "软件", "算法", "前端", "后端", "全栈", "测试", "运维",
                    "IT", "Java", "Python", "C++", "JavaScript", "嵌入式", "AI",
                    "人工智能", "大数据", "数据分析", "数据工程", "数据治理",
                    "数据科学", "网络安全"),
        "tags": {"programming", "data", "ai", "ml", "algorithm", "qa", "devops",
                 "embedded"},
    },
    "engineering": {
        "markers": ("机械", "电气", "工艺", "结构", "土木", "化工", "材料", "设备",
                    "检修", "集控", "硬件", "制造", "施工", "测绘"),
        "tags": {"engineering_mech", "engineering_elec", "engineering_process",
                 "chemical", "materials", "civil", "hardware", "embedded"},
    },
    "healthcare": {
        "markers": ("医师", "护理", "药学", "医学", "临床", "康复", "检验"),
        "tags": {"medical", "nursing", "pharmacy"},
    },
    "education": {
        "markers": ("教师", "教研", "讲师", "课程", "教学"),
        "tags": {"education"},
    },
    "legal": {
        "markers": ("法务", "律师", "法律", "知识产权", "合规审核"),
        "tags": {"legal"},
    },
    "hr": {
        "markers": ("招聘", "人力资源", "HRBP", "薪酬", "员工关系"),
        "tags": {"hr"},
    },
    "compliance": {
        "markers": ("合规", "纪检", "反洗钱"),
        "tags": {"compliance"},
    },
    "business": {
        "markers": ("管理培训生", "管培", "咨询", "商业分析", "项目管理", "产品经理",
                    "运营", "市场", "营销", "销售", "采购", "供应链"),
        "tags": {"consulting", "analysis", "research", "client", "communication",
                 "leadership", "process", "supply_chain"},
    },
}

SPECIALIST_FAMILIES = {"technology", "engineering", "healthcare", "education", "legal", "hr"}

MAJOR_FAMILIES = {
    "金融": {"金融", "经济", "管理", "会计", "统计", "数学", "数据"},
    "会计": {"会计", "金融", "经济", "管理"},
    "经济": {"经济", "金融", "管理", "统计", "数学"},
    "统计": {"统计", "数学", "数据", "经济", "金融"},
    "数学": {"数学", "统计", "数据", "经济", "金融"},
    "计算机": {"计算机", "数据", "电子"},
    "数据": {"数据", "统计", "数学", "计算机", "经济", "金融"},
    "管理": {"管理", "金融", "经济", "会计"},
    "法学": {"法学"},
    "工程": {"工程", "电子"},
    "电子": {"电子", "工程", "计算机"},
}

COLUMN_HINTS = {
    "company": ["公司名称", "公司", "企业"],
    "role": ["招聘岗位", "岗位", "职位"],
    "city": ["工作地点", "地点", "城市"],
    "edu": ["学历要求", "学历"],
    "grade": ["届次", "毕业届次"],
    "deadline": ["截止时间", "截止"],
    "apply": ["投递链接", "投递"],
    "notice": ["公告链接", "公告"],
    "major": ["专业要求", "专业"],
    "note": ["备注", "说明"],
    "industry": ["行业分类", "行业"],
    "nature": ["企业性质", "性质"],
}


def detect_columns(header):
    idx = {}
    for key, hints in COLUMN_HINTS.items():
        for i, h in enumerate(header):
            if h and any(hint in str(h).strip() for hint in hints):
                idx[key] = i
                break
    return idx


def load_resume(path):
    """Accept a parsed resume (has .text) or a structured profile.json."""
    d = json.load(open(path, encoding="utf-8"))
    if "text" in d:
        return d
    parts = [d.get("name", ""), d.get("default_intent", "")]
    ed = d.get("education", {})
    if isinstance(ed, dict):
        parts += [str(v) for v in ed.values() if isinstance(v, (str, int, float))]
    for e in d.get("experiences", []):
        parts += [e.get("org", ""), e.get("role", "")]
        parts += [b.get("text", "") for b in e.get("bullets", [])]
    for p in d.get("projects", []):
        parts += [p.get("title", ""), p.get("text", "")]
    sk = d.get("skills", {})
    parts += list(sk.values()) if isinstance(sk, dict) else [str(sk)]
    d["text"] = "\n".join(x for x in parts if x)
    tags = set()
    for e in d.get("experiences", []):
        for b in e.get("bullets", []):
            tags.update(b.get("tags", []))
    for p in d.get("projects", []):
        tags.update(p.get("tags", []))
    d["tags"] = sorted(tags)
    return d


def parse_deadline(v):
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月]?(\d{1,2})?", str(v or ""))
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            return None
    return None


def norm(v):
    return str(v or "").strip()


def resume_views(resume):
    """Return evidence, skills and full text separately."""
    sections = resume.get("sections") or {}
    if sections:
        evidence = "\n".join(sections.get("experience", []) + sections.get("projects", []))
        skills = "\n".join(sections.get("skills", []))
    else:
        evidence_parts, skill_parts = [], []
        for e in resume.get("experiences", []):
            evidence_parts.extend(b.get("text", "") for b in e.get("bullets", []))
        for p in resume.get("projects", []):
            evidence_parts.append(p.get("text", ""))
        skills_obj = resume.get("skills", {})
        if isinstance(skills_obj, dict):
            skill_parts.extend(str(v) for v in skills_obj.values())
        elif isinstance(skills_obj, list):
            skill_parts.extend(str(v) for v in skills_obj)
        evidence, skills = "\n".join(evidence_parts), "\n".join(skill_parts)
    return evidence, skills, resume.get("text", "")


def keyword_factor(keyword, meta):
    """Candidate-aware multiplier; generic words stay deliberately weak."""
    tags = KW2TAG.get(keyword, [])
    strength = max([meta["strength"].get(t, 0.0) for t in tags] or [0.0])
    if keyword in GENERIC_KEYWORDS:
        return 0.55 + min(strength, 2.0) * 0.10
    return 0.75 + min(strength, 2.5) * 0.30


def marker_present(marker, text):
    """Avoid short Latin markers matching inside unrelated English words."""
    if marker.isascii():
        return re.search(
            r"(?<![A-Za-z])" + re.escape(marker) + r"(?![A-Za-z])",
            text,
            flags=re.I,
        ) is not None
    return marker in text


def job_family_fit(role, meta):
    """Detect whether the resume has evidence for the role family.

    This never excludes a row. A stated specialist direction with no matching
    evidence is capped later, so the job still remains visible for review.
    """
    matched = []
    for family, cfg in ROLE_FAMILIES.items():
        if any(marker_present(marker, role) for marker in cfg["markers"]):
            evidence = max([meta["strength"].get(t, 0.0) for t in cfg["tags"]] or [0.0])
            matched.append((family, evidence))
    return matched


def role_segments(role):
    """Split a role cell only at top-level separators.

    Commas inside parentheses usually list a practice area or specialization;
    they must not become standalone role names.
    """
    parts, buf, depth = [], [], 0
    pairs = {"(": ")", "（": "）"}
    for char in role:
        if char in pairs:
            depth += 1
        elif char in pairs.values() and depth:
            depth -= 1
        if char in ",，;；、\n" and depth == 0:
            if "".join(buf).strip():
                parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def segment_support(segment, meta):
    """A specialist segment needs specialist evidence, even with a finance label.

    For example, "授薪律师（金融证券）" is still a legal role. The finance word
    describes the practice area and must not make a finance resume look like a
    direct match.
    """
    families = job_family_fit(segment, meta)
    named = {name for name, strength in families if strength > 0}
    specialists = {name for name, strength in families if name in SPECIALIST_FAMILIES}
    if specialists and not (specialists & named):
        return False
    return bool(named)


def score_job(job_text, resume, meta):
    """Evidence-weighted coverage of the job's capability vocabulary.

    Weight = keyword specificity × candidate evidence strength. The coverage
    confidence prevents a single generic word from producing 100/100.
    """
    evidence, skills_text, full_text = resume_views(resume)
    candidates = [k for k in KW2TAG if k and k in job_text]
    candidates.sort(
        key=lambda k: (
            -(KW_WEIGHT.get(k, 1.0) * keyword_factor(k, meta)),
            -job_text.count(k),
            -len(k),
        )
    )
    kws = candidates[:18]
    hits, weaks, gaps = [], [], []
    got = total = 0.0
    for k in kws:
        aliases = ALIASES.get(k, [k])
        if any(a and a in evidence for a in aliases):
            status, factor = "hit", 1.0
        elif any(a and a in skills_text for a in aliases):
            status, factor = "weak", 0.5
        else:
            tags = KW2TAG.get(k, [])
            strength = max([meta["strength"].get(t, 0.0) for t in tags] or [0.0])
            if strength >= 0.45:
                status, factor = "weak", 0.35
            else:
                status, factor = "gap", 0.0
        # Fall back to full text only after evidence/skills checks fail. This
        # keeps an incidental mention from being treated as strong proof.
        if status == "gap" and any(a and a in full_text for a in aliases):
            status, factor = "weak", 0.25
        w = KW_WEIGHT.get(k, 1.0) * keyword_factor(k, meta)
        total += w
        got += w * factor
        (hits if status == "hit" else weaks if status == "weak" else gaps).append(k)
    confidence = min(1.0, total / 10.0) if total else 0.0
    score = round(got / total * 100 * confidence) if total else 0
    return score, kws, hits, weaks, gaps


def major_relation(meta, major_req):
    """Return an informational label only; never gate or change the score."""
    req = norm(major_req)
    candidate = meta.get("major")
    candidate_majors = meta.get("majors") or ([candidate] if candidate else [])
    if not req or req in {"/", "不限", "专业不限"} or "专业不限" in req:
        return "不限"
    if not candidate_majors:
        return "简历未识别"
    related = set()
    for m in candidate_majors:
        related.add(m)
        related.update(MAJOR_FAMILIES.get(m, set()))
    if any(m in req for m in related):
        return "相关（仅提示）"
    return "不匹配（仅提示）"


def apply_role_adjustments(score, role, resume, meta):
    """Penalise unsupported specialist requirements without excluding rows."""
    _, _, full_text = resume_views(resume)
    core_missing = [w for w in CORE_ROLE_WORDS if w.lower() in role.lower()
                    and w.lower() not in full_text.lower()]
    if core_missing:
        score = max(0, score - min(36, 12 * len(core_missing)))

    families = job_family_fit(role, meta)
    named = [name for name, strength in families if strength > 0]
    supported = any(segment_support(segment, meta) for segment in role_segments(role))
    if families and not supported:
        # Domain mismatch is a score ceiling, not an exclusion rule. Mixed
        # rows remain visible because any matched family removes the cap.
        score = min(score, 35)
        note = "岗位方向无直接简历证据（封顶35，不排除）"
    elif named:
        note = "有可迁移证据：" + "、".join(named)
    else:
        note = "未识别专门方向"
    return score, note, core_missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--resume", default=os.path.join(ROOT, "data", "resume_profile.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "岗位匹配排名.xlsx"))
    ap.add_argument("--deep", type=int, default=0)
    ap.add_argument("--resumes", type=int, default=0)
    ap.add_argument("--top", type=int, default=200)
    a = ap.parse_args()

    resume = load_resume(a.resume)
    meta = profile_meta.meta_from_profile(resume)
    print(json.dumps({k: meta[k] for k in ("graduation", "cohort", "degree", "major")}, ensure_ascii=False))

    wb = openpyxl.load_workbook(a.excel, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    col = detect_columns([str(c or "") for c in rows[0]])
    if "company" not in col or "role" not in col:
        print("cannot detect 公司/岗位 columns", file=sys.stderr)
        return 2

    ranked, excluded = [], []
    for r in rows[1:]:
        if not r or not r[col["company"]]:
            continue
        g = lambda k: norm(r[col[k]]) if k in col and col[k] < len(r) else ""
        company, role = g("company"), g("role")
        city, edu, grade = g("city"), g("edu"), g("grade")
        ddl_raw = g("deadline")
        ddl = parse_deadline(ddl_raw)
        major_req = g("major")
        # Major requirements are handled as an informational field. Mixing a
        # long list of majors into the capability text would let an unrelated
        # engineering row borrow words such as "数据" or "Python".
        job_text = " ".join([role, g("note"), g("industry")])

        reason = ""
        years = {int(y) for y in re.findall(r"20\d{2}", grade)}
        if meta["cohort"] and years and meta["cohort"] not in years:
            reason = f"届次不符（你是 {meta['cohort']} 届）"
        elif meta["degree"] and edu and meta["degree"] not in edu:
            reason = f"学历不符（你是{meta['degree']}）"
        elif ddl and ddl < TODAY:
            reason = f"已过期（{ddl}）"
        if reason:
            excluded.append({"company": company, "role": role, "city": city,
                             "deadline": ddl_raw, "reason": reason})
            continue

        score, kws, hits, weaks, gaps = score_job(job_text, resume, meta)
        if not kws:
            excluded.append({"company": company, "role": role, "city": city,
                             "deadline": ddl_raw, "reason": "岗位文本无可用关键词"})
            continue

        # A table row is not a verified JD. Reserve 96–100 for jobs whose full
        # detail page was retrieved and passed the quality gate.
        score = min(score, 95)
        major_fit = major_relation(meta, major_req)
        score, role_fit, core_missing = apply_role_adjustments(score, role, resume, meta)

        city_hit = bool({c.strip() for c in city.replace("，", ",").split(",")} & TARGET_CITIES)
        ranked.append({
            "company": company, "role": role, "city": city, "edu": edu, "grade": grade,
            "deadline": ddl_raw, "deadline_date": ddl.isoformat() if ddl else "",
            "score": score, "kws": kws, "hits": hits, "weaks": weaks, "gaps": gaps,
            "major_fit": major_fit, "major_req": major_req,
            "role_fit": role_fit, "core_missing": core_missing,
            "city_hit": city_hit, "apply": g("apply"), "notice": g("notice"),
            "job_text": job_text, "deep": False,
        })

    ranked.sort(key=lambda r: (-r["score"], r["deadline_date"] or "9999"))
    ranked = ranked[: a.top]

    if a.deep:
        fetched = 0
        for idx, r in enumerate(ranked):
            if fetched >= a.deep:
                break
            url = r["apply"] if r["apply"].startswith("http") else (
                r["notice"] if r["notice"].startswith("http") else "")
            if not url:
                continue
            outdir = os.path.join(ROOT, "data", "raw", "deep", f"{idx:03d}")
            os.makedirs(outdir, exist_ok=True)
            if not any(f.endswith(".txt") for f in os.listdir(outdir)):
                subprocess.run([NODE, os.path.join(ROOT, "scripts", "fetch_page.js"),
                                "--out", outdir, "--wait", "7000", url],
                               capture_output=True, text=True)
            txts = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".txt")]
            if not txts:
                continue
            jd = open(txts[0], encoding="utf-8", errors="ignore").read()
            signals = sum(1 for w in ("职责", "要求", "任职", "岗位", "工作内容", "资格") if w in jd)
            if len(jd) > 500 and signals >= 2 and not (jd.count("首页") >= 1 and len(jd) < 700):
                r["job_text"] += " " + jd
                s2, r["kws"], r["hits"], r["weaks"], r["gaps"] = score_job(r["job_text"], resume, meta)
                r["score"], r["role_fit"], r["core_missing"] = apply_role_adjustments(
                    s2, r["role"], resume, meta
                )
                r["deep"] = True
                fetched += 1
        ranked.sort(key=lambda r: (-r["score"], r["deadline_date"] or "9999"))

    if a.resumes:
        for i, r in enumerate(ranked[: a.resumes], 1):
            jd = {"company": r["company"], "role": r["role"], "url": r["apply"] or r["notice"],
                  "chars": len(r["job_text"]), "quality": "deep" if r["deep"] else "table",
                  "education": [meta["degree"]] if meta["degree"] else [],
                  "cities": [c.strip() for c in r["city"].replace("，", ",").split(",") if c.strip()],
                  "deadline": r["deadline"], "keywords": {k: 1 for k in r["kws"]},
                  "intent_line": f"求职意向：{r['role'][:24]}（{r['company']}）"}
            jp = os.path.join(ROOT, "data", f"jd_batch_{i:02d}.json")
            open(jp, "w", encoding="utf-8").write(json.dumps(jd, ensure_ascii=False, indent=1))
            safe = lambda s: re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", s)[:16].strip("_")
            out_docx = os.path.join(ROOT, "output", f"{i:02d}_{safe(r['company'])}_{safe(r['role'])}.docx")
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_resume.py"),
                            "--jd", jp, "--out", out_docx], capture_output=True, text=True)
            r["resume"] = os.path.basename(out_docx)

    out_wb = openpyxl.Workbook()
    ws1 = out_wb.active
    ws1.title = "建议投递排名"
    cols = ["排名", "匹配分", "公司", "岗位", "地点", "城市匹配", "届次(岗位)", "届次匹配",
            "学历(岗位)", "学历匹配", "专业相关", "岗位方向证据", "核心缺口", "截止",
            "命中关键词", "弱证据", "缺口", "JD已核实", "建议", "投递链接",
            "公告链接", "定制简历"]
    ws1.append(cols)
    for i, r in enumerate(ranked, 1):
        advice = "优先投" if r["score"] >= 70 else "可投" if r["score"] >= 50 else "备选"
        ws1.append([i, r["score"], r["company"], r["role"], r["city"],
                    "是" if r["city_hit"] else "否", r["grade"],
                    f"是（{meta['cohort']}届）" if meta["cohort"] else "未识别",
                    r["edu"], f"是（{meta['degree']}）" if meta["degree"] else "未识别",
                    r["major_fit"], r["role_fit"], "、".join(r["core_missing"]),
                    r["deadline"], "、".join(r["hits"]), "、".join(r["weaks"]),
                    "、".join(r["gaps"]), "是" if r["deep"] else "否", advice,
                    r["apply"], r["notice"], r.get("resume", "")])
    for c in ws1[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center", vertical="center")
    widths = [6, 7, 22, 40, 16, 8, 18, 12, 14, 12, 15, 28, 18, 12,
              24, 20, 18, 8, 14, 38, 38, 26]
    for i, w in enumerate(widths, 1):
        ws1.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for row in ws1.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
        if isinstance(row[1].value, int) and row[1].value >= 70:
            for c in row:
                c.fill = PatternFill("solid", fgColor="FFF2CC")
    ws1.freeze_panes = "A2"
    ws1.auto_filter.ref = ws1.dimensions

    ws2 = out_wb.create_sheet("已排除")
    ws2.append(["公司", "岗位", "地点", "截止", "排除原因"])
    for r in excluded:
        ws2.append([r["company"], r["role"], r["city"], r["deadline"], r["reason"]])
    for c in ws2[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="7F7F7F")

    ws3 = out_wb.create_sheet("说明")
    for line in [
        ["项", "说明"],
        ["简历来源", resume.get("source", a.resume)],
        ["毕业时间", meta["graduation"] or "未识别"],
        ["届次（推算）", f"{meta['cohort']} 届" if meta["cohort"] else "未识别"],
        ["学历", meta["degree"] or "未识别"],
        ["专业", meta["major"] or "未识别"],
        ["届次规则", "毕业月份 ≥ 9 月归入下一年届（2025-12 / 2026-01 → 2026 届）"],
        ["岗位总数", len(rows) - 1],
        ["进入排名", len(ranked)],
        ["已排除", len(excluded)],
        ["硬过滤", "身份条件：本人届次、本人学历；过期或无可用关键词的岗位也会排除"],
        ["专业", "只做提示，不设门槛，也不改匹配分"],
        ["技术岗", "不排除；开发、算法、数据等岗位与金融岗位使用同一套证据打分"],
        ["岗位方向", "简历完全无对应方向证据时封顶 35，仍保留供人工查看"],
        ["词权重", "关键词基础权重 × 该能力在简历经历/项目中的证据强度"],
        ["泛词处理", "分析、数据、团队、沟通等泛词降权且限制动态放大"],
        ["覆盖折扣", "岗位可用关键词总权重不足 10 时按比例打折"],
        ["注意", "岗位字段常含多个职位，投前点开链接核对"],
    ]:
        ws3.append(line)
    ws3.column_dimensions["A"].width = 16
    ws3.column_dimensions["B"].width = 100
    for c in ws3[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    out_wb.save(a.out)
    print(f"ranked={len(ranked)} excluded={len(excluded)} -> {a.out}")
    for r in ranked[:8]:
        print(f"  {r['score']:>3} | {r['company'][:14]:14s} | {r['role'][:28]:28s} | "
              f"{r['city'][:10]:10s} | {r['deadline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
