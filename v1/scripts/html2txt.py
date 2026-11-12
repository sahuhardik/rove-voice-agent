#!/usr/bin/env python3
"""Crude HTML -> text for reading saved pages. Usage: html2txt.py FILE [FILE...]"""
import html
import re
import sys


def to_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        s = fh.read()
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"(?s)<[^>]+>", "\n", s)
    s = html.unescape(s)
    seen_blank = False
    out = []
    for line in s.split("\n"):
        line = " ".join(line.split())
        if not line:
            seen_blank = True
            continue
        if seen_blank and out:
            out.append("")
        seen_blank = False
        out.append(line)
    return "\n".join(out)


for p in sys.argv[1:]:
    print("=" * 20, p, "=" * 20)
    print(to_text(p))
