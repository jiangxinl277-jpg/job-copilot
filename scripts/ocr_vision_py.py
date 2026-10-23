#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vision OCR via PyObjC (run with the skill venv: .venv/bin/python).

Prints recognized lines in reading order (top-to-bottom, left-to-right).
Usage: .venv/bin/python scripts/ocr_vision_py.py <image> [lang...]
"""

import sys

import Quartz
import Vision
from Foundation import NSURL


def main():
    if len(sys.argv) < 2:
        print("usage: ocr_vision_py.py <image> [lang...]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    langs = sys.argv[2:] or ["zh-Hans", "en-US"]

    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if not src:
        print(f"cannot open image: {path}", file=sys.stderr)
        return 3
    image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # 0 = accurate
    request.setRecognitionLanguages_(langs)
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        print(f"vision failed: {err}", file=sys.stderr)
        return 4

    observations = list(request.results() or [])
    # Vision 的坐标原点在左下角：midY 越大越靠上
    observations.sort(key=lambda o: (-round(o.boundingBox().origin.y, 2), o.boundingBox().origin.x))
    for obs in observations:
        candidates = obs.topCandidates_(1)
        if candidates and len(candidates) > 0:
            print(candidates[0].string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
