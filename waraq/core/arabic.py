"""Arabic text helpers (no GUI imports).

Two directions are handled here:

* ``visual_units_to_logical`` turns text that was pulled out of a PDF in
  *visual* order (left-to-right on the page, usually with Arabic
  presentation-form letters) back into normal *logical* Unicode that Word,
  search engines and copy/paste understand.
* ``shape_for_display`` does the opposite (logical -> shaped visual) for
  drawing Arabic with engines that cannot shape text themselves
  (ReportLab, Tk on Linux).

The visual->logical step is an inverse of the Unicode Bidirectional
Algorithm for the common cases found in real documents: Arabic runs,
numbers (kept left-to-right), embedded Latin words/phrases, punctuation and
mirrored brackets.  Perfect inversion is impossible in general (several
logical strings can produce the same visual line), so ambiguous cases are
resolved toward the most natural reading.
"""
from __future__ import annotations

import unicodedata
from typing import Iterable, List, Optional, Sequence

# --------------------------------------------------------------------------
# character classes
# --------------------------------------------------------------------------
_MIRROR = {
    "(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{",
    "<": ">", ">": "<", "«": "»", "»": "«", "‹": "›", "›": "‹",
}
_KEEP_LIGATURES = {"\ufdfa", "\ufdfb", "\ufdfc", "\ufdfd"}  # ﷺ ﷻ ﷼ ﷽

# digits / number separators
_NUM_SEP = set(",.:/\u060c\u066b\u066c")  # comma, dot, colon, slash, Arabic comma, decimal, thousands
_NUM_ES = set("+-")


def is_arabic_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x0600 <= o <= 0x06FF
        or 0x0750 <= o <= 0x077F
        or 0x08A0 <= o <= 0x08FF
        or 0xFB50 <= o <= 0xFDFF
        or 0xFE70 <= o <= 0xFEFF
    )


def has_arabic(text: str) -> bool:
    return any(is_arabic_char(c) for c in text)


def is_mark(ch: str) -> bool:
    """Combining marks (harakat, shadda, superscript alef, ...)."""
    if not ch:
        return False
    return unicodedata.category(ch) in ("Mn", "Me")


def char_kind(ch: str) -> str:
    """Return 'R', 'L', 'D' (digit), 'M' (mark) or 'N' (neutral)."""
    if is_mark(ch):
        return "M"
    b = unicodedata.bidirectional(ch)
    if b in ("R", "AL"):
        return "R"
    if b == "L":
        return "L"
    if b in ("EN", "AN"):
        return "D"
    return "N"


def unit_kind(unit: str) -> str:
    kinds = [char_kind(c) for c in unit]
    for k in kinds:
        if k in ("R", "L"):
            return k
    if "D" in kinds:
        return "D"
    return "N"


# --------------------------------------------------------------------------
# presentation forms -> standard letters
# --------------------------------------------------------------------------
def normalize_presentation(text: str) -> str:
    """Map Arabic presentation forms (FB50-FDFF, FE70-FEFF) to base letters.

    ``ﻻ`` becomes ``لا`` (logical order), ``ﺑ`` becomes ``ب`` and so on.
    A few honorific ligatures (ﷺ ﷽) are kept because expanding them changes
    the meaning of the document text.
    """
    out = []
    for ch in text:
        o = ord(ch)
        if ch in _KEEP_LIGATURES:
            out.append(ch)
        elif 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            n = unicodedata.normalize("NFKC", ch)
            if 0xFE70 <= o <= 0xFE7F:
                # isolated / medial mark forms decompose to " " + mark or tatweel + mark
                n = n.lstrip(" ").replace("\u0640", "") or n
            out.append(n)
        else:
            out.append(ch)
    return "".join(out)


# --------------------------------------------------------------------------
# visual -> logical
# --------------------------------------------------------------------------
def group_marks(chars: Sequence[str], marks_before_base: bool = False) -> List[str]:
    """Attach combining marks to the letter they belong to.

    Reversed strings (e.g. produced by a bidi ``get_display``) put a mark
    *before* its base letter; geometric extraction usually yields it after.
    """
    units: List[str] = []
    pending = ""
    for ch in chars:
        if all(is_mark(c) for c in ch) and ch:
            if marks_before_base:
                pending += ch
            elif units:
                units[-1] += ch
            else:
                pending += ch
        else:
            units.append(ch + pending[::-1] if pending else ch)
            pending = ""
    if pending:
        units.append(pending)
    return units


class _Tok:
    __slots__ = ("kind", "units")

    def __init__(self, kind: str, units: List[str]):
        self.kind = kind  # 'R' (single unit), 'L', 'D' (atomic LTR), 'N' (single neutral)
        self.units = units

    def text(self) -> str:
        return "".join(self.units)


def _tokenize(units: Sequence[str]) -> List[_Tok]:
    """Split visual units into tokens; numbers become atomic tokens."""
    kinds = [unit_kind(u) for u in units]
    toks: List[_Tok] = []
    i, n = 0, len(units)
    while i < n:
        k = kinds[i]
        if k == "D":
            j = i + 1
            while j < n:
                if kinds[j] == "D":
                    j += 1
                elif (
                    j + 1 < n
                    and kinds[j + 1] == "D"
                    and units[j] in _NUM_SEP
                ):
                    j += 2
                else:
                    break
            toks.append(_Tok("D", list(units[i:j])))
            i = j
        else:
            toks.append(_Tok(k, [units[i]]))
            i += 1
    return toks


def _guess_base(toks: List[_Tok]) -> str:
    strong = [t for t in toks if t.kind in ("R", "L")]
    if not strong:
        return "L"
    nr = sum(1 for t in strong if t.kind == "R")
    nl = len(strong) - nr
    left, right = strong[0].kind, strong[-1].kind
    if left == "R" and right == "R":
        return "R"
    if left == "L" and right == "L":
        return "L" if nl >= nr * 0.5 or nr == 0 else "R"
    if left == "R" and right == "L":
        return "L"
    # left L, right R  (e.g. "Word ابحرم") -> ambiguous, use majority
    return "R" if nr >= nl else "L"


def _ltr_runs_in_rtl(toks: List[_Tok]) -> List[_Tok]:
    """Merge L-runs (with numbers and inner neutrals) into atomic tokens."""
    out: List[_Tok] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].kind != "L":
            out.append(toks[i])
            i += 1
            continue
        # grammar:  L (N* (L|D))*   -- plus a trailing ET-like char glued to a number
        j = i + 1
        end = j
        while j < n:
            k = j
            while k < n and toks[k].kind == "N":
                k += 1
            if k < n and toks[k].kind in ("L", "D"):
                j = k + 1
                end = j
            else:
                break
        # a number written "50%" inside an English phrase
        if end < n and toks[end - 1].kind == "D" and toks[end].kind == "N" and toks[end].text() in "%\u066a°":
            end += 1
        units: List[str] = []
        for t in toks[i:end]:
            units.extend(t.units)
        out.append(_Tok("L", units))
        i = end
    return out


def _rtl_runs_in_ltr(toks: List[_Tok], mirror: bool = True) -> List[Optional[_Tok]]:
    out: List[_Tok] = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        starts = t.kind == "R"
        if t.kind == "D":
            # number immediately left of an Arabic run (through neutrals) belongs to it
            k = i + 1
            while k < n and toks[k].kind == "N":
                k += 1
            prev_l = any(x.kind == "L" for x in toks[max(0, i - 2):i]) and (i == 0 or toks[i - 1].kind != "R")
            starts = k < n and toks[k].kind == "R" and not prev_l
        if not starts:
            out.append(t)
            i += 1
            continue
        j = i + 1
        end = j
        while j < n:
            k = j
            while k < n and toks[k].kind == "N":
                k += 1
            if k < n and toks[k].kind in ("R", "D"):
                j = k + 1
                end = j
            else:
                break
        run = toks[i:end]
        units: List[str] = []
        for x in reversed(run):
            if x.kind == "D":
                units.extend(x.units)
            else:
                units.extend((_mirror(u) if mirror else u) for u in reversed(x.units))
        out.append(_Tok("RR", units))  # already logical
        i = end
    return out


def _mirror(u: str) -> str:
    return _MIRROR.get(u, u)


def _bracket_score(text: str) -> int:
    """Lower is better: count closing brackets that appear before an opener."""
    pairs = {")": "(", "]": "[", "}": "{", "»": "«", ">": "<"}
    opens = set(pairs.values())
    depth = {o: 0 for o in opens}
    bad = 0
    for ch in text:
        if ch in opens:
            depth[ch] += 1
        elif ch in pairs:
            o = pairs[ch]
            if depth[o] == 0:
                bad += 1
            else:
                depth[o] -= 1
    return bad + sum(depth.values())


def visual_units_to_logical(units: Sequence[str], base: Optional[str] = None,
                            marks_before_base: bool = False, mirror: Optional[bool] = None) -> str:
    """See module docstring.  ``mirror=None`` picks automatically.

    Some producers store the *mirrored* bracket character for brackets
    inside Arabic text (what you see), others store the original one (what
    was typed).  With ``mirror=None`` both readings are tried and the one
    with balanced brackets wins.
    """
    if mirror is None:
        a = _v2l(units, base, marks_before_base, True)
        if not any(c in _MIRROR for c in a):
            return a
        b = _v2l(units, base, marks_before_base, False)
        return b if _bracket_score(b) < _bracket_score(a) else a
    return _v2l(units, base, marks_before_base, mirror)


def _v2l(units: Sequence[str], base: Optional[str], marks_before_base: bool, mirror: bool) -> str:
    """Convert one line of visual-order units to a logical string.

    ``units`` are left-to-right glyph texts (a unit may contain several
    characters, e.g. a ligature already in logical order).  Presentation
    forms must already be normalised.
    """
    units = [u for u in units if u != ""]
    if not units:
        return ""
    units = group_marks(units, marks_before_base)
    toks = _tokenize(units)
    if not any(t.kind == "R" for t in toks):
        return "".join(units)
    base = base or _guess_base(toks)
    if base == "R":
        toks = _ltr_runs_in_rtl(toks)
        parts: List[str] = []
        for t in reversed(toks):
            if t.kind in ("L", "D"):
                parts.append(t.text())
            else:
                parts.append("".join((_mirror(u) if mirror else u) for u in reversed(t.units)))
        return "".join(parts)
    toks2 = _rtl_runs_in_ltr(toks, mirror)
    return "".join(t.text() for t in toks2)


def visual_to_logical(text: str, base: Optional[str] = None) -> str:
    """Convenience wrapper: visual string (one line) -> logical string."""
    text = normalize_presentation(text)
    return visual_units_to_logical(list(text), base=base, marks_before_base=True)


# --------------------------------------------------------------------------
# logical -> shaped visual (for drawing)
# --------------------------------------------------------------------------
def shape_for_display(text: str, base_dir: Optional[str] = None) -> str:
    """Reshape Arabic letters and reorder for engines without shaping."""
    if not has_arabic(text):
        return text
    get_display = _get_display()
    reshaper = _reshaper()

    lines = []
    for line in text.split("\n"):
        if has_arabic(line):
            line = get_display(reshaper.reshape(line), base_dir=base_dir)
        lines.append(line)
    return "\n".join(lines)


_RESHAPER = None


def _reshaper():
    global _RESHAPER
    if _RESHAPER is None:
        import arabic_reshaper

        _RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False,
                                                                  "support_ligatures": True})
    return _RESHAPER


def _get_display():
    """python-bidi's pure-Python algorithm mirrors brackets; the Rust one does not."""
    try:
        from bidi.algorithm import get_display  # type: ignore
    except Exception:  # pragma: no cover
        from bidi import get_display  # type: ignore
    return get_display


def char_error_rate(ref: str, hyp: str) -> float:
    """Levenshtein distance / len(ref) (used by tests and the OCR report)."""
    a, b = ref, hyp
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] / len(a)


def squash_ws(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "is_arabic_char", "has_arabic", "normalize_presentation", "visual_to_logical",
    "visual_units_to_logical", "shape_for_display", "char_error_rate", "squash_ws",
]
