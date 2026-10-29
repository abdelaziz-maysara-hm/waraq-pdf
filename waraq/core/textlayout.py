"""Laying out (possibly Arabic) text for PDF appearance streams.

ReportLab cannot shape Arabic, so every line is word-wrapped in *logical*
order, then shaped and reordered with arabic-reshaper + python-bidi, and
finally drawn as runs; each character goes to the first font of the family
that has a glyph for it.
"""
from __future__ import annotations

import io
from typing import List, Optional, Sequence, Tuple

from .arabic import has_arabic, is_arabic_char, shape_for_display
from .fonts import register_family

Color = Tuple[float, float, float]


def _font_maps(family: str):
    from reportlab.pdfbase import pdfmetrics

    names = register_family(family)
    maps = []
    for n in names:
        f = pdfmetrics.getFont(n)
        maps.append((n, f.face.charToGlyph))
    return maps


def runs(visual: str, family: str) -> List[Tuple[str, str]]:
    """Split a visual (already shaped) line into (font name, text) runs."""
    maps = _font_maps(family)
    out: List[Tuple[str, str]] = []
    for ch in visual:
        name = maps[0][0]
        for n, cmap in maps:
            if ord(ch) in cmap or ch.isspace():
                name = n
                break
        if out and out[-1][0] == name:
            out[-1] = (name, out[-1][1] + ch)
        else:
            out.append((name, ch))
    return out


def text_width(visual: str, family: str, size: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return sum(stringWidth(t, n, size) for n, t in runs(visual, family))


def base_direction(text: str) -> str:
    """'rtl' if the first strong character is Arabic, else 'ltr'."""
    for ch in text:
        if is_arabic_char(ch):
            return "rtl"
        if ch.isalpha():
            return "ltr"
    return "rtl" if has_arabic(text) else "ltr"


def shape_line(line: str, direction: Optional[str] = None) -> str:
    if not has_arabic(line):
        return line
    d = direction or base_direction(line)
    return shape_for_display(line, base_dir="R" if d == "rtl" else "L")


def wrap(text: str, family: str, size: float, max_width: float) -> List[str]:
    """Greedy word wrap on logical text; returns logical lines."""
    lines: List[str] = []
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = w if not cur else cur + " " + w
            if not cur or text_width(shape_line(cand), family, size) <= max_width:
                cur = cand
                continue
            lines.append(cur)
            cur = w
        # a single word wider than the box is broken by characters
        while cur and text_width(shape_line(cur), family, size) > max_width and len(cur) > 1:
            cut = len(cur)
            while cut > 1 and text_width(shape_line(cur[:cut]), family, size) > max_width:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
        lines.append(cur)
    return lines


def draw_text(c, text: str, x: float, y: float, w: float, h: float, *, family: str = "naskh",
              size: float = 14.0, color: Color = (0, 0, 0), align: str = "auto", padding: float = 2.0,
              line_gap: float = 1.3, valign: str = "top", wrap_text: bool = True) -> int:
    """Draw wrapped text inside a box with ReportLab canvas ``c``; return line count."""
    inner = max(w - 2 * padding, 1.0)
    lines = wrap(text, family, size, inner) if wrap_text else text.split("\n")
    lh = size * line_gap
    total = lh * len(lines)
    if valign == "middle":
        top = y + h / 2 + total / 2
    else:
        top = y + h - padding
    c.setFillColorRGB(*color)
    for k, line in enumerate(lines):
        d = base_direction(line) if align == "auto" else None
        a = align
        if align == "auto":
            a = "right" if d == "rtl" else "left"
        vis = shape_line(line, d)
        tw = text_width(vis, family, size)
        if a == "right":
            cx = x + w - padding - tw
        elif a == "center":
            cx = x + (w - tw) / 2
        else:
            cx = x + padding
        base = top - lh * k - size * 0.95
        for name, part in runs(vis, family):
            c.setFont(name, size)
            c.drawString(cx, base, part)
            cx += c.stringWidth(part, name, size)
    return len(lines)


def fit_size(text: str, family: str, w: float, h: float, start: float = 14.0, minimum: float = 5.0,
             padding: float = 2.0, line_gap: float = 1.3) -> float:
    """Largest font size <= start whose wrapped text fits the box."""
    s = start
    while s > minimum:
        n = len(wrap(text, family, s, max(w - 2 * padding, 1)))
        if n * s * line_gap <= h - padding:
            return s
        s -= 0.5
    return minimum


def text_box_pdf(w: float, h: float, text: str, *, family: str = "naskh", size: float = 14.0,
                 color: Color = (0, 0, 0), fill: Optional[Color] = None, border: Optional[Color] = None,
                 border_width: float = 1.0, align: str = "auto", opacity: float = 1.0,
                 valign: str = "top", padding: float = 3.0) -> bytes:
    """A one-page PDF of size w x h with the text box drawn on it."""
    from reportlab.pdfgen import canvas

    w = max(w, 2.0)
    h = max(h, 2.0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h), pageCompression=1)
    if opacity < 1.0:
        c.setFillAlpha(opacity)
        c.setStrokeAlpha(opacity)
    if fill is not None or border is not None:
        if fill is not None:
            c.setFillColorRGB(*fill)
        if border is not None:
            c.setStrokeColorRGB(*border)
            c.setLineWidth(border_width)
        bw = border_width / 2 if border is not None else 0
        c.rect(bw, bw, w - 2 * bw, h - 2 * bw, stroke=1 if border is not None else 0,
               fill=1 if fill is not None else 0)
    if text:
        draw_text(c, text, 0, 0, w, h, family=family, size=size, color=color, align=align,
                  padding=padding + (border_width if border is not None else 0), valign=valign)
    c.showPage()
    c.save()
    return buf.getvalue()


def image_pdf(w: float, h: float, png_bytes: bytes, opacity: float = 1.0) -> bytes:
    """A one-page PDF of size w x h with an image (alpha kept) stretched over it."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    im = Image.open(io.BytesIO(png_bytes))
    im.load()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(max(w, 1), max(h, 1)), pageCompression=1)
    if opacity < 1.0:
        c.setFillAlpha(opacity)
    c.drawImage(ImageReader(im), 0, 0, w, h, mask="auto")
    c.showPage()
    c.save()
    return buf.getvalue()


def note_icon_pdf(size: float, color: Color) -> bytes:
    """A small speech-bubble icon used as the appearance of a sticky note."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(size, size))
    c.setFillColorRGB(*color)
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(0.8)
    p = c.beginPath()
    s = size
    p.roundRect(1, s * 0.25, s - 2, s * 0.72, s * 0.12)
    c.drawPath(p, stroke=1, fill=1)
    p = c.beginPath()
    p.moveTo(s * 0.25, s * 0.27)
    p.lineTo(s * 0.18, 1)
    p.lineTo(s * 0.45, s * 0.27)
    c.drawPath(p, stroke=0, fill=1)
    c.setStrokeColorRGB(0.25, 0.25, 0.25)
    for k in range(3):
        yy = s * (0.78 - 0.16 * k)
        c.line(s * 0.2, yy, s * 0.8, yy)
    c.showPage()
    c.save()
    return buf.getvalue()


def wrapped_lines_for_preview(text: str, family: str, size: float, w: float) -> Sequence[str]:
    return wrap(text, family, size, w)
