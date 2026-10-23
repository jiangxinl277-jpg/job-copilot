#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 5: verify a generated DOCX still fits one A4 page.

Wraps the calibrated page-height estimator (build/qa_fit.py). Exit code:
  0 = fits, 1 = overflow (so it can gate the pipeline / CI).
"""

import argparse
import contextlib
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

local = os.path.join(ROOT, "lib", "qa_fit.py")
QA_PATH = local if os.path.exists(local) else os.path.join(ROOT, "..", "build", "qa_fit.py")

spec = importlib.util.spec_from_file_location(
    "qa_fit", QA_PATH
)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--max-mm", type=float, default=268.0)
    ap.add_argument("--usable-mm", type=float, default=274.0)
    ap.add_argument("--width-mm", type=float, default=176.0)
    a = ap.parse_args()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        h = qa.estimate(a.docx, usable_mm=a.usable_mm, width_mm=a.width_mm, quiet=True)
    ok = h <= a.max_mm
    print(f"{'PASS' if ok else 'FAIL'}  {os.path.basename(a.docx)}  "
          f"height={h:.1f}mm  limit={a.max_mm:.0f}mm  margin={a.max_mm - h:+.1f}mm")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
