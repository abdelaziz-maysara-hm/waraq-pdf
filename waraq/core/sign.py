"""Add a signature / stamp image or text to pages (pypdf + ReportLab)."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

from .arabic import shape_for_display
from .errors import WaraqError
from .fonts import register_reportlab_font
from .util import flat_pages, open_reader, write_pdf

POSITIONS = ("bottom-right", "bottom-left", "bottom-center", "top-right", "top-left",
             "top-center", "center")


@dataclass
class Placement:
    page: int          # 1-based page number
    x: float           # PDF points, origin bottom-left of the visible page
    y: float
    width: float
    height: float


def make_transparent(img, threshold: int = 225):
    """Turn a phone photo of a signature on white paper into a transparent PNG."""
    from PIL import ImageChops

    im = img.convert("RGBA")
    r, g, b, a = im.split()
    white = [band.point(lambda v: 255 if v >= threshold else 0) for band in (r, g, b)]
    mask = ImageChops.multiply(ImageChops.multiply(white[0], white[1]), white[2])
    alpha = ImageChops.multiply(a, ImageChops.invert(mask))
    im.putalpha(alpha)
    return im


def _anchor(position, pw, ph, w, h, margin) -> Tuple[float, float]:
    if isinstance(position, (tuple, list)):
        return float(position[0]), float(position[1])
    if position not in POSITIONS:
        raise WaraqError(f"unknown position {position}", "bad_position")
    if position.startswith("bottom"):
        y = margin
    elif position.startswith("top"):
        y = ph - margin - h
    else:
        y = (ph - h) / 2
    if position.endswith("right"):
        x = pw - margin - w
    elif position.endswith("left"):
        x = margin
    else:
        x = (pw - w) / 2
    return x, y


def _select(pages: str, n: int) -> List[int]:
    if pages in (None, "", "all"):
        return list(range(n))
    if pages == "first":
        return [0]
    if pages == "last":
        return [n - 1]
    return flat_pages(pages, n)


def stamp(src, dst, *, image: Optional[Union[str, Path]] = None, text: Optional[str] = None,
          pages: str = "last", position: Union[str, Tuple[float, float]] = "bottom-right",
          width: float = 150.0, margin: float = 36.0, opacity: float = 1.0,
          font_size: float = 18.0, color: Tuple[float, float, float] = (0.05, 0.2, 0.6),
          remove_white: bool = False, password: Optional[str] = None) -> List[Placement]:
    """Stamp an image and/or a (possibly Arabic) text line on pages.

    ``width`` is the stamp width in points (72 pt = 1 inch).  Coordinates
    refer to the page as it is displayed (page rotation is taken into
    account).  Returns where each stamp was placed.
    """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    if not image and not (text and text.strip()):
        raise WaraqError("Choose a signature image or type a text", "no_stamp")
    r = open_reader(src, password)
    n = len(r.pages)
    targets = _select(pages, n)
    img_reader = None
    aspect = 1.0
    if image:
        from PIL import Image

        try:
            im = Image.open(image)
            im.load()
        except Exception as e:
            raise WaraqError(f"Cannot read image: {e}", "bad_image")
        if remove_white:
            im = make_transparent(im)
        elif im.mode not in ("RGB", "RGBA", "L"):
            im = im.convert("RGBA")
        aspect = im.height / im.width
        img_reader = ImageReader(im)
    font = register_reportlab_font()
    shaped = shape_for_display(text.strip()) if text and text.strip() else None

    w = PdfWriter()
    for i, p in enumerate(r.pages):
        w.add_page(p)
    placements: List[Placement] = []
    for i in targets:
        page = w.pages[i]
        if int(page.get("/Rotate", 0) or 0) % 360:
            page.transfer_rotation_to_content()
        box = page.cropbox
        left, bottom = float(box.left), float(box.bottom)
        pw, ph = float(box.width), float(box.height)
        sw = min(width, pw - 2 * margin) if pw > 2 * margin else width
        ih = sw * aspect if img_reader else 0.0
        th = font_size * 1.4 if shaped else 0.0
        total_h = ih + th
        x, y = _anchor(position, pw, ph, sw, total_h, margin)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(float(page.mediabox.right), float(page.mediabox.top)))
        c.translate(left, bottom)
        if opacity < 1.0:
            c.setFillAlpha(opacity)
            c.setStrokeAlpha(opacity)
        if img_reader:
            c.drawImage(img_reader, x, y + th, sw, ih, mask="auto")
        if shaped:
            c.setFont(font, font_size)
            c.setFillColorRGB(*color)
            tw = c.stringWidth(shaped, font, font_size)
            c.drawString(x + (sw - tw) / 2, y + font_size * 0.35, shaped)
        c.save()
        overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
        page.merge_page(overlay)
        placements.append(Placement(i + 1, x, y, sw, total_h))
    write_pdf(w, dst)
    return placements
