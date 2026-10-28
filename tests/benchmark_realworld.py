"""Real-world check: the UN Arabic UDHR PDF (OHCHR copy, made with MS Word).

    python tests/benchmark_realworld.py        (downloads ~200 KB once)

There is no clean ground truth for this PDF, so the metric is "share of
extracted Arabic words that exist in the reference vocabulary" (the corpus
text published with the PDF by Aalto University, extracted with pdftotext and
checked by hand).  Reversed or split words fall out of the vocabulary.
Note the reference itself was made with pdftotext, which favours pdftotext;
several of Waraq's "misses" are words the reference splits (e.g. "قد ًا").
"""
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waraq.core.arabic import normalize_presentation  # noqa: E402
from waraq.core.extract import extract_pages  # noqa: E402

CACHE = ROOT / "tests" / "_fixtures" / "realworld"
PDF_URL = "https://research.ics.aalto.fi/cog/data/udhr/pdf/arz.pdf"
TXT_URL = "https://research.ics.aalto.fi/cog/data/udhr/txt/arz.txt"
H = {chr(c) for c in range(0x064B, 0x0653)} | {"\u0670", "\u0640"}


def get(url, name):
    p = CACHE / name
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        p.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return p


def words(t):
    t = "".join(c for c in normalize_presentation(t) if c not in H)
    return re.findall(r"[\u0621-\u064A]+", t)


def norm(w):
    return w.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")


def main():
    pdf = str(get(PDF_URL, "udhr_ar.pdf"))
    ref = {norm(w) for w in words(get(TXT_URL, "udhr_ar.txt").read_text(encoding="utf-8"))}
    from pypdf import PdfReader
    from pdfminer.high_level import extract_text
    outs = {
        "Waraq": "\n".join(b.text for p in extract_pages(pdf) for b in p.blocks),
        "pypdf": "\n".join(p.extract_text() or "" for p in PdfReader(pdf).pages),
        "pdfminer.six": extract_text(pdf),
    }
    try:
        outs["pdftotext"] = subprocess.run(["pdftotext", "-enc", "UTF-8", pdf, "-"], capture_output=True,
                                           text=True).stdout
    except FileNotFoundError:
        pass
    print("| tool | Arabic words | in reference vocabulary |\n|---|---|---|")
    for k, v in outs.items():
        ws = words(v)
        print(f"| {k} | {len(ws)} | {sum(norm(w) in ref for w in ws) / max(len(ws), 1):.1%} |")


if __name__ == "__main__":
    main()
