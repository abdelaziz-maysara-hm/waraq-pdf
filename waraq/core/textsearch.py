"""Arabic-aware search and text selection on top of PDFium text pages.

Matching ignores harakat/tatweel, Arabic presentation forms (NFKC),
alef/hamza variants and ى/ي, ة/ه; English is case-insensitive.  Text that
was stored in *visual* order (common with old Arabic PDFs) is found too by
also searching for the reversed query.
"""
from __future__ import annotations

import unicodedata
from typing import List, Optional, Tuple

from .arabic import has_arabic, visual_to_logical

_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
                       "\u0640": None})


def normalize(text: str, loose: bool = True) -> Tuple[str, List[int]]:
    """Return (normalised text, map from normalised index -> source index)."""
    out: List[str] = []
    idx: List[int] = []
    for i, ch in enumerate(text):
        n = unicodedata.normalize("NFKC", ch)
        for c in n:
            if unicodedata.category(c) == "Mn" or c == "\u0640":
                continue
            if loose:
                c = c.translate(_ALEF)
                if not c:
                    continue
                c = c.lower()
            if c in "\r\n\t\u00a0":
                c = " "
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def find_all(page_text: str, query: str, loose: bool = True) -> List[Tuple[int, int]]:
    """Character ranges (start, count) in ``page_text`` that match ``query``."""
    q, _ = normalize(query.strip(), loose)
    q = " ".join(q.split())
    if not q:
        return []
    t, idx = normalize(page_text, loose)
    # collapse runs of spaces in the page text, keeping the index map
    t2, idx2 = [], []
    prev_space = False
    for c, i in zip(t, idx):
        if c == " ":
            if prev_space:
                continue
            prev_space = True
        else:
            prev_space = False
        t2.append(c)
        idx2.append(i)
    t = "".join(t2)
    needles = [q]
    if has_arabic(q):
        needles.append(q[::-1])
    hits = set()
    for nd in needles:
        start = 0
        while True:
            k = t.find(nd, start)
            if k < 0:
                break
            a = idx2[k]
            b = idx2[k + len(nd) - 1]
            hits.add((min(a, b), abs(b - a) + 1))
            start = k + 1
    return sorted(hits)


def range_rects(textpage, start: int, count: int):
    """PDF-space rects (l, b, r, t) covering a character range."""
    n = textpage.count_rects(start, count)
    return [textpage.get_rect(i) for i in range(n)]


def page_text(textpage) -> str:
    n = textpage.count_chars()
    return textpage.get_text_range(0, n) if n > 0 else ""


def char_at(textpage, x: float, y: float, tol: float = 6.0) -> int:
    """Index of the character at PDF point (x, y), or -1."""
    try:
        i = textpage.get_index(x, y, tol, tol)
    except Exception:
        return -1
    return -1 if i is None else int(i)


def nearest_char(textpage, x: float, y: float) -> int:
    """Closest character to (x, y) (for drag selection that starts in white space)."""
    i = char_at(textpage, x, y, 4.0)
    if i >= 0:
        return i
    best, bd = -1, None
    n = textpage.count_chars()
    for k in range(n):
        try:
            l, b, r, t = textpage.get_charbox(k)
        except Exception:
            continue
        if r - l <= 0 and t - b <= 0:
            continue
        dx = 0 if l <= x <= r else min(abs(x - l), abs(x - r))
        dy = 0 if b <= y <= t else min(abs(y - b), abs(y - t))
        d = dx * dx + dy * dy * 4
        if bd is None or d < bd:
            best, bd = k, d
    return best


def readable(text: str) -> str:
    """Make copied text logical Unicode (fixes visual-order presentation-form Arabic)."""
    if not any(0xFB50 <= ord(c) <= 0xFEFF for c in text):
        return text.replace("\r\n", "\n")
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(visual_to_logical(ln) if has_arabic(ln) else ln for ln in lines)


def line_at(textpage, x: float, y: float) -> Optional[Tuple[int, int]]:
    """(start, count) of the text line under (x, y) - used by 'edit text'."""
    i = char_at(textpage, x, y, 3.0)
    if i < 0:
        return None
    text = page_text(textpage)
    a = i
    while a > 0 and text[a - 1] not in "\r\n":
        a -= 1
    b = i
    while b < len(text) - 1 and text[b + 1] not in "\r\n":
        b += 1
    return a, b - a + 1
