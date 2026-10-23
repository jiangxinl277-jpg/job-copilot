#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn a fetched/pasted JD into a structured spec (jd.json).

Heuristic on purpose: no LLM key needed, deterministic, and it flags pages that
did not really yield a JD (SPA shells, login walls) instead of pretending.
"""

import argparse
import datetime
import json
import re

CITIES = ["北京", "上海", "深圳", "杭州", "苏州", "广州", "南京", "成都", "武汉",
          "香港", "新加坡", "伦敦", "纽约"]
# 抽取词表与匹配表同源，避免"抽得到但匹配不了"或反过来的漂移
try:
    from match_evidence import KW2TAG as _KW2TAG
    KW = sorted(_KW2TAG.keys(), key=len, reverse=True)
except Exception:  # 单文件运行时兜底
    KW = ["审计", "咨询", "交易", "估值", "尽调", "风险", "风控", "合规", "债券", "固收", "久期", "预算", "预测", "客户", "数据", "AI", "管培", "英语"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True, help="fetched .txt or pasted JD")
    ap.add_argument("--out", required=True)
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--url", default="")
    a = ap.parse_args()

    raw = open(a.text, encoding="utf-8", errors="ignore").read()
    text = re.sub(r"[ \t]+", " ", raw)
    chars = len(text.strip())

    edu = [x for x in ("本科", "硕士", "博士") if x in text]
    cities = [c for c in CITIES if c in text]
    dates = re.findall(r"(20\d{2})[-/.年](\d{1,2})[-/.月]?(\d{1,2})?", text)
    deadline = ""
    for y, m, d in dates[:6]:
        if int(y) >= 2026:
            deadline = f"{y}-{int(m):02d}" + (f"-{int(d):02d}" if d else "")
            break
    hits = {k: text.count(k) for k in KW if text.count(k)}
    hits = dict(sorted(hits.items(), key=lambda kv: -kv[1])[:10])

    signal = sum(1 for w in ("职责", "要求", "任职", "岗位", "工作内容", "资格") if w in text)
    if chars >= 800 and signal >= 2:
        quality = "ok"
    elif chars >= 500 and signal >= 1:
        quality = "thin"
    else:
        quality = "needs_paste"

    company = a.company or ""
    role = a.role or ""
    intent = ""
    if role:
        intent = f"求职意向：{role}" + (f"（{company}）" if company else "")

    jd = {
        "company": company,
        "role": role,
        "url": a.url,
        "chars": chars,
        "quality": quality,
        "signal_terms": signal,
        "education": edu,
        "cities": cities,
        "deadline": deadline,
        "keywords": hits,
        "intent_line": intent,
        "source_text": a.text,
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    json.dump(jd, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: jd[k] for k in ("chars", "quality", "education", "cities",
                                        "deadline", "keywords")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
