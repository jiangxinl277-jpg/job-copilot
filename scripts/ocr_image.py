#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 1 (OCR backend): screenshot / photo -> text via macOS Vision (PyObjC).

Why PyObjC: this machine's swiftc cannot build against the installed SDK
(compiler 6.0.3.1.10 vs SDK 6.0.3.1.5), so the Swift helper is not usable.
The Vision engine itself is fine; PyObjC calls the same framework offline.

Setup (once):
  uv venv .venv --python <python3.12>
  uv pip install --python .venv/bin/python pyobjc-framework-Vision pyobjc-framework-Quartz

Usage:
  python3 scripts/ocr_image.py --out data/raw shot1.png shot2.jpg
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = os.path.join(ROOT, ".venv", "bin", "python")
HELPER = os.path.join(ROOT, "scripts", "ocr_vision_py.py")


def pick_python():
    if os.path.exists(VENV_PY):
        return VENV_PY
    try:
        import Vision  # noqa: F401
        return sys.executable
    except Exception:
        raise RuntimeError(
            "Vision bindings not found. Run:\n"
            "  uv venv .venv --python <python3.12>\n"
            "  uv pip install --python .venv/bin/python pyobjc-framework-Vision pyobjc-framework-Quartz"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--langs", nargs="*", default=["zh-Hans", "en-US"])
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    py = pick_python()
    results = []

    for img in a.images:
        if not os.path.exists(img):
            results.append({"image": img, "ok": False, "error": "not found"})
            continue
        r = subprocess.run([py, HELPER, img] + a.langs, capture_output=True, text=True)
        text = (r.stdout or "").strip()
        slug = os.path.splitext(os.path.basename(img))[0]
        slug = "".join(c if (c.isalnum() or c in "-_") else "_" for c in slug)[:60]
        txt_path = os.path.join(a.out, f"ocr_{slug}.txt")
        open(txt_path, "w", encoding="utf-8").write(text)
        meta = {
            "image": img,
            "text": txt_path,
            "chars": len(text),
            "lines": len(text.splitlines()),
            "backend": "macos-vision-pyobjc",
            "langs": a.langs,
            "ok": r.returncode == 0 and len(text) > 20,
        }
        open(os.path.join(a.out, f"ocr_{slug}.json"), "w", encoding="utf-8").write(
            json.dumps(meta, ensure_ascii=False, indent=1)
        )
        results.append(meta)

    print(json.dumps(results, ensure_ascii=False, indent=1))
    if not all(x.get("ok") for x in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
