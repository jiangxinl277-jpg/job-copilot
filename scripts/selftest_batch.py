#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression checks for candidate-derived cohort, major and job scoring."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import batch_score  # noqa: E402
import profile_meta  # noqa: E402


def resume(text, experience, skills="", projects=None):
    return {
        "text": text,
        "sections": {
            "education": [text.splitlines()[0]],
            "experience": experience,
            "projects": projects or [],
            "skills": [skills] if skills else [],
        },
    }


FINANCE = resume(
    "2026年6月毕业 金融学 本科\n财务分析与预算",
    ["在实习中完成预算、估值、财务分析和风险评估。"],
    "Excel、债券定价",
)

TECH = resume(
    "2027年6月毕业 计算机科学 本科\nJava Python 后端开发",
    ["使用 Java 与 Python 完成后端开发、数据库和算法项目。"],
    "Java、Python、SQL",
)


def main():
    fmeta = profile_meta.meta_from_profile(FINANCE)
    tmeta = profile_meta.meta_from_profile(TECH)
    checks = []

    checks.append(("按毕业年月推届别", fmeta["graduation"] == "2026-06" and fmeta["cohort"] == 2026))
    checks.append(("不同毕业年得到不同届别", tmeta["cohort"] == 2027))
    checks.append(("9–12月归下一年届", profile_meta.cohort_of((2026, 12)) == 2027))
    checks.append(("明确届别优先", profile_meta.cohort_of((2027, 6), {
        "text": "预计2027年6月毕业，2026届",
        "sections": {"education": ["预计2027年6月毕业，2026届"]},
    }) == 2026))
    english_meta = profile_meta.meta_from_profile({
        "text": "Bachelor of Science in Finance\nExpected graduation: May 2028",
        "sections": {
            "education": ["Bachelor of Science in Finance", "Expected graduation: May 2028"],
            "experience": [],
            "projects": [],
            "skills": [],
        },
    })
    checks.append(("英文毕业月份", english_meta["graduation"] == "2028-05" and english_meta["cohort"] == 2028))
    checks.append(("英文届别/学位", profile_meta.cohort_of((2027, 6), {
        "text": "Class of 2027",
        "sections": {"education": ["Class of 2027"]},
    }) == 2027 and english_meta["degree"] == "本科"))
    checks.append(("未来项目日期不覆盖教育日期", profile_meta.meta_from_profile({
        "text": "2026年6月毕业 金融学\nAI项目 2027年10月",
        "sections": {
            "education": ["2026年6月毕业 金融学"],
            "experience": ["AI项目 2027年10月"],
            "projects": [],
            "skills": [],
        },
    })["cohort"] == 2026))

    checks.append(("专业不匹配只提示", batch_score.major_relation(fmeta, "机械工程") == "不匹配（仅提示）"))
    checks.append(("相关专业识别", batch_score.major_relation(fmeta, "经济、金融、会计") == "相关（仅提示）"))

    finance_job, *_ = batch_score.score_job("财务分析、预算、估值", FINANCE, fmeta)
    tech_job, *_ = batch_score.score_job("财务分析、预算、估值", TECH, tmeta)
    checks.append(("动态权重区分候选人", finance_job > tech_job))

    tech_score, tech_kws, tech_hits, _, _ = batch_score.score_job("Java 后端 开发 Python", TECH, tmeta)
    checks.append(("技术岗进入打分", bool(tech_kws) and tech_score > 0 and bool(tech_hits)))

    generic, *_ = batch_score.score_job("数据分析", FINANCE, fmeta)
    checks.append(("单个泛词不能满分", generic <= 20))

    capped, cap_note, _ = batch_score.apply_role_adjustments(80, "机械工程师", FINANCE, fmeta)
    checks.append(("方向不匹配封顶不排除", capped == 35 and "不排除" in cap_note))
    checks.append(("技术方向无简历证据只低分", batch_score.apply_role_adjustments(
        80, "Java开发工程师", FINANCE, fmeta
    )[0] == 35))
    checks.append(("专业领域词不能冒充法律证据", not batch_score.segment_support(
        "授薪律师（金融证券）", fmeta
    )))
    checks.append(("混合岗位保留可投子岗位", any(
        batch_score.segment_support(segment, fmeta)
        for segment in ["机械工程师", "财务毕业培训生"]
    )))

    failed = 0
    for label, ok in checks:
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
    print(f"\n{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
