#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 6: append a row to the application ledger (data/applications.csv)."""

import argparse
import csv
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "applications.csv")
HEADER = ["date", "company", "role", "city", "deadline", "match_score",
          "resume", "layout_mm", "channel", "status", "notes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--resume", default="")
    ap.add_argument("--score", default="")
    ap.add_argument("--layout-mm", default="")
    ap.add_argument("--channel", default="官网")
    ap.add_argument("--status", default="已定制")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()

    jd = json.load(open(a.jd, encoding="utf-8"))
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow([
            datetime.date.today().isoformat(),
            jd.get("company", ""),
            jd.get("role", ""),
            "/".join(jd.get("cities", [])),
            jd.get("deadline", ""),
            a.score,
            os.path.basename(a.resume) if a.resume else "",
            a.layout_mm,
            a.channel,
            a.status,
            a.notes,
        ])
    print("ledger:", LEDGER)


if __name__ == "__main__":
    main()
