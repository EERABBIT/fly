#!/usr/bin/env python3
"""Strip WeChat UI junk from downloaded articles into docs_clean/, mirroring the docs/ tree.

Three fixes, in order:
  1. cut everything from the trailing "预览时标签不可点" marker onward (WeChat chrome)
  2. rejoin text the extractor split at WeChat's inline <span> boundaries -- numbers and
     English words ended up on their own lines, e.g. "包括 / CJ-1000 / 现实中工作人员..."
  3. collapse the 打赏 triple-repeat and any other verbatim consecutive duplicate

Originals under docs/ are never modified.
"""
import os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # fly/
SRC = os.path.join(BASE, "docs")
DST = os.path.join(BASE, "docs_clean")

CUT = "预览时标签不可点"          # identical trailing block in all files
RULE = re.compile(r"^-{5,}$")     # the ---- separator before the 个股 section
FRAG = re.compile(r"^[A-Za-z0-9\-\.%/+]{1,12}$")   # "CJ-1000", "PE30", "155", "-60%", "21"
PUNCT = re.compile(r"^[，。、？！：；~）（\.]{1,3}$")  # stray punctuation on its own line
CJK = re.compile(r"[一-鿿]")


def rejoin(lines):
    """Merge span-split fragments back into the surrounding sentence.

    A fragment line glues to the previous line; the following line then continues that
    same sentence, so it glues on too. Blank lines between them are artifacts, not
    paragraph breaks -- real paragraph breaks never have a bare fragment on one side.
    """
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if RULE.match(s) or s.startswith("#"):
            out.append(s)
            continue
        # Look past artifact blanks to the last real line before deciding.
        k = len(out) - 1
        while k >= 0 and not out[k].strip():
            k -= 1
        prev = out[k].strip() if k >= 0 else ""
        prev_prose = bool(CJK.search(prev))
        glue = False
        if prev_prose and (FRAG.match(s) or PUNCT.match(s)):
            glue = True                      # fragment trailing prose
        elif prev and prev_prose and CJK.search(s) and re.search(r"[A-Za-z0-9%\-\.]$", prev):
            glue = True                      # prose continuing after a glued fragment
        if glue:
            del out[k + 1:]                  # drop the artifact blanks
            out[k] = out[k].rstrip() + s
            continue
        out.append(s)
    return out


def dedupe(lines):
    """Drop a substantial line that repeats the nearest preceding non-blank line."""
    out, last = [], None
    for ln in lines:
        s = ln.strip()
        if s and len(s) > 20 and s == last:
            continue
        if s:
            last = s
        out.append(ln)
    return out


def clean(text):
    lines = text.split("\n")
    if CUT in text:
        lines = lines[:next(i for i, l in enumerate(lines) if CUT in l)]
    lines = dedupe(rejoin(lines))
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return body.strip() + "\n"


def main():
    n = 0
    for root, _, files in os.walk(SRC):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            src = os.path.join(root, fn)
            dst = os.path.join(DST, os.path.relpath(src, SRC))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding="utf-8") as f:
                out = clean(f.read())
            with open(dst, "w", encoding="utf-8") as f:
                f.write(out)
            n += 1
    print(f"cleaned: {n}")


if __name__ == "__main__":
    main()
