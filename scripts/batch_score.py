#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch mode: job table (Excel) + parsed resume -> ranked application list.

Steps
  1. read the Excel and auto-detect the columns (公司/岗位/地点/学历/届次/截止/链接)
  2. hard filters: 本科可投、2026 届可投、截止未过
  3. score each job: keyword hit / weak / gap against the parsed resume
  4. optional --deep N: fetch the JD URL for the top N and re-score with it
  5. optional --resumes N: generate tailored resumes for the top N
  6. write output/岗位匹配排名.xlsx with 排名 / 排除 / 说明 sheets

Usage:
  python3 scripts/batch_score.py --excel data/jobs.xlsx \
      --resume data/resume_profile.json --out output/岗位匹配排名.xlsx \
      --deep 10 --resumes 5
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

# node 可能不在 PATH 里（Codex 运行时把 node 放在自己的目录）
NODE = (os.environ.get("NODE_BIN") or shutil.which("node")
        or "/Users/jiangxinli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")

from match_evidence import ALIASES, KW2TAG  # noqa: E402

TODAY = datetime.date.today()
TARGET_CITIES = {"北京", "上海", "深圳", "杭州", "苏州"}

# 目标域：行业列/企业性质优先；岗位名里只认"金融机构 + 财务职能"的硬词
DOMAIN_KW = ["银行", "证券", "基金", "保险", "资管", "期货", "信托", "租赁",
             "审计", "会计师事务所", "咨询", "财务", "会计", "税务", "投行",
             "固收", "债券", "金融", "精算", "风控", "合规", "风险管理", "量化"]

# 岗位核心词：JD 里有、简历里没有，说明这条岗的主线能力缺失，要扣分
CORE_ROLE_WORDS = ["精算", "核保", "理赔", "承保", "再保", "清算", "托管",
                   "经纪", "投顾", "客户经理", "期货", "信托", "租赁", "保理",
                   "外汇", "交易员", "量化", "算法", "查勘"]

# 纯技术岗：除非同时出现金融/数据/风控字样，否则不是目标域
TECH_ROLE_WORDS = ["工程师", "开发", "研发", "算法", "架构", "运维"]

# 词权重：越具体的金融能力词越重，泛词只作辅助
KW_WEIGHT = {
    "审计": 3, "鉴证": 3, "底稿": 3, "勾稽": 3, "尽职调查": 3, "尽调": 3,
    "债券": 3, "固收": 3, "久期": 3, "凸性": 3, "利差": 2.5, "定价": 2.5,
    "估值": 3, "可比公司": 3, "DCF": 3, "并购": 3, "投行": 3, "资本市场": 2.5,
    "预算": 2.5, "预测": 2.5, "管理报表": 2.5, "财务分析": 3, "差异分析": 2.5,
    "授信": 3, "信贷": 3, "核保": 2.5, "信用分析": 3, "风险": 2, "风控": 2.5,
    "评级": 2.5, "资产质量": 2.5, "合规": 2, "反洗钱": 3, "AML": 3, "KYC": 3,
    "建模": 2.5, "模型": 1.5, "数据分析": 2, "SQL": 2, "AI": 1.5, "智能体": 2,
    "自动化": 1.5, "流程": 1, "客户": 1, "营销": 1, "财富": 1.5, "研究": 1.5,
    "分析": 0.6, "数据": 0.8, "团队": 0.5, "沟通": 0.5, "报告": 0.6, "Excel": 1,
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
            if not h:
                continue
            hs = str(h).strip()
            if any(hint in hs for hint in hints):
                idx[key] = i
                break
    return idx


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


def load_resume(path):
    """Accept either a parsed resume (has .text) or a structured profile.json."""
    d = json.load(open(path, encoding="utf-8"))
    if "text" in d:
        return d
    parts = [d.get("name", ""), d.get("default_intent", "")]
    ed = d.get("education", {})
    if isinstance(ed, dict):
        parts += [ed.get("school", ""), ed.get("degree", ""),
                  ed.get("courses", ""), ed.get("honors", "")]
    for e in d.get("experiences", []):
        parts += [e.get("org", ""), e.get("role", "")]
        for b in e.get("bullets", []):
            parts += [b.get("label", ""), b.get("text", "")]
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


def classify_text(kw, resume_text, resume_tags):
    aliases = ALIASES.get(kw, [kw])
    if any(a and a in resume_text for a in aliases):
        return "hit"
    if set(KW2TAG.get(kw, [])) & set(resume_tags):
        return "weak"
    return "gap"


def score_job(job_text, resume):
    kws = [k for k in KW2TAG if k in job_text][:14]
    hits, weaks, gaps = [], [], []
    got, total_w = 0.0, 0.0
    for k in kws:
        s = classify_text(k, resume["text"], resume["tags"])
        (hits if s == "hit" else weaks if s == "weak" else gaps).append(k)
        w = KW_WEIGHT.get(k, 1.0)
        total_w += w
        got += w * (1.0 if s == "hit" else 0.5 if s == "weak" else 0.0)
    # 覆盖度折扣：可匹配关键词的总权重不足 8，说明这条岗位信息太薄，
    # 不允许它拿高分（否则"只有数据一个词"的研发岗也会 100 分）
    confidence = min(1.0, total_w / 8.0)
    score = round(got / total_w * 100 * confidence) if total_w else 0
    return score, kws, hits, weaks, gaps


def apply_penalties(score, role, tier, resume_text):
    """核心词缺口 / 非金融行业 / 技术混合岗的扣分，主流程与深度重算都要用。"""
    core_missing = [w for w in CORE_ROLE_WORDS if w in role and w not in resume_text]
    if core_missing:
        score = max(0, score - min(40, 12 * len(core_missing)))
    if tier.startswith("B"):
        score = max(0, score - 15)
    tech_heavy = any(k in role for k in TECH_ROLE_WORDS) and not any(
        k in role for k in ["财务", "审计", "会计", "税务", "资金", "风控",
                            "合规", "投资", "金融", "管培", "培训生", "储备"])
    if tech_heavy:
        score = min(score, 55)
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--resume", default=os.path.join(ROOT, "data", "resume_profile.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "岗位匹配排名.xlsx"))
    ap.add_argument("--deep", type=int, default=0, help="fetch JD for top N rows with URLs")
    ap.add_argument("--resumes", type=int, default=0, help="build resumes for top N")
    ap.add_argument("--top", type=int, default=200)
    a = ap.parse_args()

    resume = load_resume(a.resume)
    wb = openpyxl.load_workbook(a.excel, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c or "") for c in rows[0]]
    col = detect_columns(header)
    if "company" not in col or "role" not in col:
        print("cannot detect 公司/岗位 columns; header =", header[:12], file=sys.stderr)
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
        link_apply, link_notice = g("apply"), g("notice")
        job_text = " ".join([role, g("major"), g("note")])

        reason = ""
        industry, nature = g("industry"), g("nature")
        tier_a = ("金融" in industry) or (nature == "银行")
        finance_role = any(k in role for k in ["财务", "审计", "会计", "税务", "资金",
                                               "风控", "合规", "投资管理", "管培",
                                               "培训生", "储备", "金融"])
        engineering = any(k in role for k in ["技术员", "检修", "研发", "工艺", "模具",
                                              "地质", "采矿", "化工", "机械", "电气",
                                              "焊接", "数控", "试验员", "测量员"])
        tech_only = any(k in role for k in TECH_ROLE_WORDS) and not any(
            k in role for k in ["数据分析", "分析师", "金融科技", "风控", "合规",
                                "财务", "产品经理", "量化"])
        tier = "A 金融业" if tier_a else ("B 非金融·财务岗" if finance_role else "")
        if "2026" not in grade and grade:
            reason = "非 2026 届"
        elif edu and "本科" not in edu:
            reason = "学历不符（需硕士+）"
        elif ddl and ddl < TODAY:
            reason = f"已过期（{ddl}）"
        elif not tier:
            reason = "非金融/财务目标域"
        elif tech_only or (engineering and not tier_a):
            reason = "纯技术岗（开发/算法），非目标域"
        if reason:
            excluded.append({"company": company, "role": role, "city": city, "deadline": ddl_raw, "reason": reason})
            continue

        score, kws, hits, weaks, gaps = score_job(job_text, resume)
        if len(hits) + len(weaks) < 2:
            score = min(score, 30)  # 证据太薄，别让它排到前面
        score = apply_penalties(score, role, tier, resume["text"])
        city_hit = bool({c.strip() for c in city.replace("，", ",").split(",")} & TARGET_CITIES)
        ranked.append({
            "company": company, "role": role, "city": city, "edu": edu, "grade": grade,
            "deadline": ddl_raw, "deadline_date": ddl.isoformat() if ddl else "",
            "score": score, "kws": kws, "hits": hits, "weaks": weaks, "gaps": gaps,
            "tier": tier,
            "city_hit": city_hit, "apply": link_apply, "notice": link_notice,
            "job_text": job_text, "deep": False,
        })

    ranked.sort(key=lambda r: (-r["score"], r["deadline_date"] or "9999"))
    ranked = ranked[: a.top]

    # 可选：对前 N 个有 URL 的岗位抓 JD 并重算
    if a.deep:
        fetched = 0
        for idx, r in enumerate(ranked):
            if fetched >= a.deep:
                break
            url = r["apply"] if r["apply"].startswith("http") else (r["notice"] if r["notice"].startswith("http") else "")
            if not url:
                continue
            # 每个岗位独立目录：抓取失败时绝不继承上一个岗位的 JD
            outdir = os.path.join(ROOT, "data", "raw", "deep", f"{idx:03d}")
            os.makedirs(outdir, exist_ok=True)
            if not any(f.endswith(".txt") for f in os.listdir(outdir)):
                subprocess.run([NODE, os.path.join(ROOT, "scripts", "fetch_page.js"),
                                "--out", outdir, "--wait", "7000", url], capture_output=True, text=True)
            txts = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".txt")]
            if txts:
                jd = open(txts[0], encoding="utf-8", errors="ignore").read()
                # 质量闸门：门户导航/登录页不算 JD
                signals = sum(1 for w in ("职责", "要求", "任职", "岗位", "工作内容", "资格") if w in jd)
                nav_only = jd.count("首页") >= 1 and len(jd) < 700
                if len(jd) > 500 and signals >= 2 and not nav_only:
                    r["job_text"] = r["job_text"] + " " + jd
                    s2, r["kws"], r["hits"], r["weaks"], r["gaps"] = score_job(r["job_text"], resume)
                    r["score"] = apply_penalties(s2, r["role"], r["tier"], resume["text"])
                    r["deep"] = True
                    fetched += 1
        ranked.sort(key=lambda r: (-r["score"], r["deadline_date"] or "9999"))

    # 可选：为前 N 个岗位生成定制简历
    if a.resumes:
        for i, r in enumerate(ranked[: a.resumes], 1):
            jd = {
                "company": r["company"], "role": r["role"], "url": r["apply"] or r["notice"],
                "chars": len(r["job_text"]), "quality": "deep" if r["deep"] else "table",
                "education": ["本科"] if "本科" in r["edu"] else [],
                "cities": [c.strip() for c in r["city"].replace("，", ",").split(",") if c.strip()],
                "deadline": r["deadline"], "keywords": {k: 1 for k in r["kws"]},
                "intent_line": f"求职意向：{r['role'][:24]}（{r['company']}）",
            }
            jd_path = os.path.join(ROOT, "data", f"jd_batch_{i:02d}.json")
            open(jd_path, "w", encoding="utf-8").write(json.dumps(jd, ensure_ascii=False, indent=1))
            safe = lambda s: re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", s)[:16].strip("_")
            out_docx = os.path.join(ROOT, "output", f"{i:02d}_{safe(r['company'])}_{safe(r['role'])}.docx")
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_resume.py"),
                            "--jd", jd_path, "--out", out_docx], capture_output=True, text=True)
            r["resume"] = os.path.basename(out_docx)

    # 写 Excel
    out_wb = openpyxl.Workbook()
    ws1 = out_wb.active
    ws1.title = "建议投递排名"
    cols = ["排名", "匹配分", "公司", "岗位", "地点", "城市匹配", "届次", "学历", "截止",
            "命中关键词", "弱证据", "缺口", "JD已核实", "建议", "投递链接", "公告链接", "定制简历"]
    ws1.append(cols)
    for i, r in enumerate(ranked, 1):
        advice = "优先投" if r["score"] >= 70 else "可投" if r["score"] >= 50 else "备选"
        if not r["city_hit"] and r["city"]:
            advice += "（城市不在志愿内）"
        ws1.append([i, r["score"], r["company"], r["role"], r["city"],
                    "是" if r["city_hit"] else "否", r["grade"], r["edu"], r["deadline"],
                    "、".join(r["hits"]), "、".join(r["weaks"]), "、".join(r["gaps"]),
                    "是" if r["deep"] else "否", advice, r["apply"], r["notice"], r.get("resume", "")])
    for c in ws1[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center", vertical="center")
    widths = [6, 7, 22, 40, 16, 8, 18, 14, 12, 24, 20, 18, 8, 16, 38, 38, 26]
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
        ["简历来源", resume.get("source", "")],
        ["岗位总数", len(rows) - 1],
        ["进入排名", len(ranked)],
        ["已排除", len(excluded)],
        ["硬过滤", "学历含本科；届次含 2026（若有）；截止未过（或尽快/长期）"],
        ["打分", "岗位文本里的关键词 × 简历证据：强命中 1 分、弱证据 0.5 分，折算百分制"],
        ["深度核实", f"对前 {a.deep} 个有链接的岗位抓取 JD 后重算"],
        ["注意", "岗位字段常含多个职位，投前点开链接核对；分数用于排序，不替代人工判断"],
    ]:
        ws3.append(line)
    ws3.column_dimensions["A"].width = 14
    ws3.column_dimensions["B"].width = 100
    for c in ws3[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    out_wb.save(a.out)
    print(f"ranked={len(ranked)} excluded={len(excluded)} -> {a.out}")
    for r in ranked[:8]:
        print(f"  {r['score']:>3} | {r['company'][:14]:14s} | {r['role'][:30]:30s} | {r['city'][:10]} | {r['deadline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
