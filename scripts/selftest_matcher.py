#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for the keyword table.

Each case is (keyword, expected status). Run after editing KW2TAG / ALIASES:
  python3 scripts/selftest_matcher.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from match_evidence import classify, evidence_items  # noqa: E402

CASES = [
    ("客户", "hit"),      # 某全国性银行 · 客户与市场洞察
    ("债券", "hit"),      # 固定收益项目
    ("久期", "hit"),
    ("模型", "hit"),
    ("智能体", "hit"),
    ("审计", "weak"),     # 只有勾稽/关账，没有审计项目
    ("尽职调查", "weak"),  # 能力相近，但没有 FDD 经历
    ("咨询", "gap"),      # 没有咨询经历（"客户咨询记录"不算）
    ("Excel", "weak"),    # 只在技能区
    ("反洗钱", "gap"),
]


def main():
    profile = json.load(open(os.path.join(ROOT, "data", "profile.json"), encoding="utf-8"))
    items = evidence_items(profile)
    skills = " ".join(profile["skills"].values())

    failed = 0
    for kw, expected in CASES:
        got, where = classify(kw, items, skills)
        ok = got == expected
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {kw:6s} expected={expected:5s} got={got:5s}  {where}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
