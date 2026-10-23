#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orchestrator: JD spec -> match report -> tailored resume -> layout gate -> ledger.

Usage:
  python3 scripts/run_all.py --jd data/jd_ey.json --tag ey
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, capture=True):
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--max-mm", default="268")
    a = ap.parse_args()

    jd = json.load(open(os.path.join(ROOT, a.jd) if not os.path.isabs(a.jd) else a.jd,
                        encoding="utf-8"))
    tag = a.tag or re.sub(r"[^\w]+", "_", f"{jd.get('company','')}_{jd.get('role','')}")[:30]
    report = f"output/match_{tag}.md"
    resume = f"output/定制简历_{tag}.docx"

    print("① 证据匹配 ...")
    code, out = run([sys.executable, "scripts/match_evidence.py", "--jd", a.jd, "--out", report])
    print("  ", out.strip())
    if code != 0:
        return 1
    m = re.search(r"score=(\d+)", out)
    score = m.group(1) if m else ""

    print("② 生成简历 ...")
    code, out = run([sys.executable, "scripts/build_resume.py", "--jd", a.jd, "--out", resume])
    print("  ", out.strip().splitlines()[-1] if out.strip() else "")
    if code != 0:
        return 1

    print("③ 版式校验 ...")
    code, out = run([sys.executable, "scripts/check_layout.py", resume, "--max-mm", a.max_mm])
    print("  ", out.strip())
    mm = re.search(r"height=([\d.]+)mm", out)

    print("④ 写投递台账 ...")
    run([sys.executable, "scripts/ledger.py", "--jd", a.jd, "--resume", resume,
         "--score", score, "--layout-mm", mm.group(1) if mm else ""])

    print("\n产出:")
    for f in (report, resume, "data/applications.csv"):
        print("  -", f)
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
