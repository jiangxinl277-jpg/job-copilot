#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 3: match a structured JD against the structured profile.

Judgement rules (deliberately strict, so the score means something):
  hit  - the keyword (or an alias) actually appears in an experience/project
  weak - no literal match, but a related capability tag exists (claim without
         the exact evidence), or it only appears in the skills block
  gap  - nothing in the profile supports it

Score = (hits + 0.5 * weak) / total keywords * 100.
"""

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# JD 关键词 -> 能力标签（与 profile.json 的 tags 对齐）
KW2TAG = {
    # 关账 / 审计 / 内控
    "关账": ["close"], "结账": ["close"], "月结": ["close"], "对账": ["close", "audit"],
    "勾稽": ["audit", "close"], "底稿": ["audit"], "审计": ["audit"], "鉴证": ["audit"],
    "内控": ["audit", "compliance"], "穿行测试": ["audit"], "抽样": ["audit"],
    "尽职调查": ["audit", "ib"], "尽调": ["audit", "ib"], "FDD": ["audit", "ib"],
    # 财务计划与分析
    "预算": ["fp_and_a"], "预测": ["fp_and_a"], "滚动预测": ["fp_and_a"],
    "预实": ["fp_and_a"], "预算与实际": ["fp_and_a"], "管理报表": ["reporting", "fp_and_a"],
    "财务分析": ["fp_and_a"], "经营分析": ["fp_and_a"], "差异分析": ["analysis", "fp_and_a"],
    "成本分析": ["analysis"], "费用管控": ["fp_and_a"], "供应商": ["process", "fp_and_a"],
    # 分析与建模
    "分析": ["analysis"], "归因": ["analysis"], "敏感性": ["analysis"], "情景": ["analysis"],
    "建模": ["modelling"], "模型": ["modelling"], "三表": ["modelling"], "DCF": ["modelling", "valuation"],
    "可比公司": ["valuation"], "估值": ["valuation", "ib"],
    # 投行 / 交易
    "投行": ["ib"], "并购": ["ib"], "IPO": ["ib"], "资本市场": ["ib"], "交易": ["ib"],
    "重组": ["ib"], "融资": ["ib"],
    "咨询": ["consulting"], "顾问": ["consulting"],
    # 研究与行业
    "研究": ["research"], "行业研究": ["research"], "报告": ["research", "communication"],
    # 信贷 / 风险 / 合规
    "授信": ["credit"], "信贷": ["credit"], "贷款": ["credit"], "核保": ["credit"],
    "信用分析": ["credit", "risk"], "DTI": ["credit"], "LTV": ["credit"],
    "风险": ["risk"], "风控": ["risk"], "评级": ["risk"], "资产质量": ["risk"],
    "逾期": ["risk"], "合规": ["compliance"],
    # 反洗钱 / KYC 是独立能力，不能靠"合规"标签蹭到
    "反洗钱": [], "AML": [], "KYC": [],
    # 定价 / 固收
    "定价": ["pricing"], "利差": ["pricing", "fixed_income"], "盈亏平衡": ["pricing"],
    "固收": ["fixed_income"], "债券": ["fixed_income"], "久期": ["fixed_income"],
    "凸性": ["fixed_income"], "利率": ["fixed_income"], "YTM": ["fixed_income"],
    # 客户 / 数据 / AI / 流程
    "客户": ["client"], "营销": ["client"], "财富": ["client"], "渠道": ["client"],
    "数据": ["data"], "数据分析": ["data", "analysis"], "SQL": ["data"], "清洗": ["data"],
    "AI": ["ai"], "人工智能": ["ai"], "大模型": ["ai"], "智能体": ["ai"],
    "自动化": ["process", "ai"], "流程": ["process"], "优化": ["process"],
    "沟通": ["communication"], "汇报": ["communication"], "跨部门": ["communication"],
    "领导": ["leadership"], "统筹": ["leadership"], "团队": ["leadership"],
    "英语": [],
}

# 同义词：用于在经历文本里做"真命中"检索
ALIASES = {
    "关账": ["关账", "结账", "月结"], "结账": ["结账", "关账"], "月结": ["月结", "关账"],
    "勾稽": ["勾稽", "跨表", "核对"], "底稿": ["底稿"], "审计": ["审计"],
    "尽调": ["尽调", "尽调", "尽职调查"], "尽职调查": ["尽职调查", "尽调"],
    "预算": ["预算"], "预测": ["预测"], "滚动预测": ["滚动预测", "预测"],
    "预实": ["预实", "预算 / 实际", "预算/实际"],
    "管理报表": ["管理报表", "报表"], "财务分析": ["财务分析", "差异"],
    "分析": ["分析", "归因"], "建模": ["建模", "模型"], "模型": ["模型", "建模"],
    "估值": ["估值"], "可比公司": ["可比公司"], "DCF": ["DCF"],
    "交易": ["交易"], "并购": ["并购"], "投行": ["投行"],
    "研究": ["研究", "洞察"], "授信": ["授信"], "信贷": ["信贷", "贷款"],
    "核保": ["核保", "授信"], "风险": ["风险"], "风控": ["风控", "风险"],
    "评级": ["评级"], "合规": ["合规"], "定价": ["定价"], "利差": ["利差"],
    "固收": ["固收", "债券"], "债券": ["债券"], "久期": ["久期"], "利率": ["利率"],
    # 短词容易被"客户咨询记录"这类文本误命中，收紧成词组
    "咨询": ["咨询顾问", "咨询项目", "管理咨询", "咨询服务", "咨询方案"],
    "顾问": ["顾问"],
    "客户": ["客户"], "数据": ["数据"], "数据分析": ["数据分析"],
    "AI": ["ChatGPT", "Gemini", "AI", "MCP"], "智能体": ["智能体", "MCP", "Skills"],
    "自动化": ["自动化", "Power Query", "重构"], "流程": ["流程"],
    "沟通": ["沟通", "汇报"], "团队": ["小组", "团队", "统筹"],
}


def evidence_items(profile):
    items = []
    for e in profile["experiences"]:
        for b in e["bullets"]:
            items.append({"where": f"{e['org']} · {b['label']}", "text": b["text"], "tags": set(b["tags"])})
    for p in profile["projects"]:
        items.append({"where": p["title"], "text": p["text"], "tags": set(p["tags"])})
    return items


def classify(kw, items, skills_text):
    aliases = ALIASES.get(kw, [kw])
    # 1) 文本里真的出现 -> 强命中
    for it in items:
        if any(a and a in it["text"] for a in aliases):
            return "hit", it["where"]
    # 2) 只有能力标签重叠 -> 弱证据
    tags = set(KW2TAG.get(kw, []))
    if tags:
        for it in items:
            if it["tags"] & tags:
                return "weak", f"{it['where']}（相关能力，未出现该词）"
    # 3) 只在技能区出现 -> 弱证据
    if any(a and a in skills_text for a in aliases):
        return "weak", "仅在技能区出现"
    return "gap", "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(ROOT, "data", "profile.json"))
    ap.add_argument("--jd", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    profile = json.load(open(a.profile, encoding="utf-8"))
    jd = json.load(open(a.jd, encoding="utf-8"))
    skills_text = " ".join(profile["skills"].values())
    items = evidence_items(profile)

    rows = []
    count = {"hit": 0, "weak": 0, "gap": 0}
    for kw, n in sorted(jd.get("keywords", {}).items(), key=lambda kv: -kv[1]):
        status, where = classify(kw, items, skills_text)
        count[status] += 1
        rows.append((kw, n, status, where))

    total = max(sum(count.values()), 1)
    score = round((count["hit"] + 0.5 * count["weak"]) / total * 100)

    md = [f"# 岗位匹配报告：{jd.get('company','')} {jd.get('role','')}".strip(), "",
          f"- JD 文本量：{jd.get('chars','?')} 字符（质量：{jd.get('quality','?')}）",
          f"- 关键词：**{count['hit']}** 强命中 / {count['weak']} 弱证据 / {count['gap']} 缺口",
          f"- 匹配分：**{score} / 100**（强命中 1 分，弱证据 0.5 分）", ""]
    if jd.get("cities"):
        overlap = [c for c in jd["cities"] if c in ("上海", "深圳", "北京", "杭州", "苏州")]
        md.append(f"- JD 城市：{'、'.join(jd['cities'])}；与目标城市重合：{'、'.join(overlap) or '无'}")
    if jd.get("education"):
        md.append(f"- 学历：{'、'.join(jd['education'])}；本人本科" + ("（满足）" if "本科" in jd["education"] else ""))
    if jd.get("deadline"):
        md.append(f"- 截止：{jd['deadline']}")
    md += ["", "| 关键词 | 出现 | 判定 | 证据 / 原因 |", "| --- | --- | --- | --- |"]
    label = {"hit": "✅ 强命中", "weak": "⚠️ 弱证据", "gap": "❌ 缺口"}
    order = {"hit": 0, "weak": 1, "gap": 2}
    for kw, n, status, where in sorted(rows, key=lambda r: (order[r[2]], -r[1])):
        md.append(f"| {kw} | {n} | {label[status]} | {where} |")

    md += ["", "## 建议", ""]
    gaps = [r[0] for r in rows if r[2] == "gap"]
    weaks = [r[0] for r in rows if r[2] == "weak"]
    if gaps:
        md.append(f"- **别硬讲**：{'、'.join(gaps)} —— JD 提到但简历无对应经历。")
    if weaks:
        md.append(f"- **补证据**：{'、'.join(weaks)} —— 有能力标签但没出现原词，面试要准备具体例子。")
    md.append("- 生成简历时按强命中权重重排 bullet，缺口词不会被放大。")

    open(a.out, "w", encoding="utf-8").write("\n".join(md))
    print(f"score={score} hit={count['hit']} weak={count['weak']} gap={count['gap']} -> {a.out}")


if __name__ == "__main__":
    main()
