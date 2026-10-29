"""Draw editor annotations, search hits and selections over a page image.

Vector kinds are drawn with Pillow (4x supersampled where it matters);
text boxes, stamps, images and notes are rasterised from the very same
appearance PDF that is written on save, so what you see is what you get.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw

from ..core import annots as A
from ..core.geom import PageGeom

_RICH_CACHE: "OrderedDict[tuple, Image.Image]" = OrderedDict()


def _c255(c, a=255):
    return (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), a)


def _key(a: A.Annot, scale: float, rot: int):
    h = hashlib.md5(a.to_json().encode("utf-8")).hexdigest()
    if a.image:
        h += hashlib.md5(a.image).hexdigest()[:8]
    return (h, round(scale, 3), rot)


def rich_image(a: A.Annot, scale: float, extra_rot: int) -> Image.Image:
    """RGBA raster of a rich annotation in display orientation."""
    import pypdfium2 as pdfium

    k = _key(a, scale, extra_rot)
    if k in _RICH_CACHE:
        _RICH_CACHE.move_to_end(k)
        return _RICH_CACHE[k]
    dw, dh = A.display_dims(a)
    data = A.rich_ap_pdf(a, dw, dh)
    doc = pdfium.PdfDocument(data)
    pg = doc[0]
    img = pg.render(scale=scale, fill_color=(255, 255, 255, 0), rotation=extra_rot % 360).to_pil()
    pg.close()
    doc.close()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    _RICH_CACHE[k] = img
    while len(_RICH_CACHE) > 120:
        _RICH_CACHE.popitem(last=False)
    return img


def _poly_line(draw, pts, color, width):
    if len(pts) == 1:
        x, y = pts[0]
        r = width / 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        return
    draw.line(pts, fill=color, width=max(1, int(round(width))), joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def draw_annots(img: Image.Image, g: PageGeom, annots: Sequence[A.Annot], hidden: Iterable[str] = ()) -> Image.Image:
    """Return a new RGB image with ``annots`` drawn on ``img`` (display space)."""
    hidden = set(hidden)
    base = img.convert("RGB")
    ss = 3  # supersampling for vector shapes
    vec = None
    for a in annots:
        if a.id in hidden:
            continue
        if a.kind == "highlight":
            layer = Image.new("RGB", base.size, (255, 255, 255))
            d = ImageDraw.Draw(layer)
            for q in a.quads:
                d.rectangle(g.rect_to_screen(q), fill=_c255(a.color)[:3])
            mult = ImageChops.multiply(base, layer)
            base = Image.blend(base, mult, max(0.05, min(1.0, a.opacity * 1.6)))
            continue
        if A.is_rich(a):
            total_rot = (g.rotation - a.rotation) % 360
            im = rich_image(a, g.scale, total_rot)
            l, t, r, b = g.rect_to_screen(a.bounds())
            if im.size != (round(r - l), round(b - t)) and r - l >= 1 and b - t >= 1:
                im = im.resize((max(1, round(r - l)), max(1, round(b - t))), Image.LANCZOS)
            base.paste(im, (round(l), round(t)), im)
            continue
        if vec is None:
            vec = Image.new("RGBA", (base.width * ss, base.height * ss), (0, 0, 0, 0))
            vd = ImageDraw.Draw(vec)
        col = _c255(a.color, int(255 * a.opacity))
        S = lambda x, y: tuple(v * ss for v in g.to_screen(x, y))  # noqa: E731
        w = max(1.0, a.width * g.scale * ss)
        if a.kind in ("underline", "strikeout"):
            for q in a.quads:
                hh = q[3] - q[1]
                lw = max(hh / 14.0, 0.8)
                y = q[1] + lw * 1.2 if a.kind == "underline" else q[1] + hh * 0.42
                vd.line([S(q[0], y), S(q[2], y)], fill=col, width=max(1, int(lw * g.scale * ss)))
        elif a.kind == "ink":
            for s in a.strokes:
                _poly_line(vd, [S(*p) for p in s], col, w)
        elif a.kind in ("line", "arrow"):
            (x1, y1), (x2, y2) = a.strokes[0][0], a.strokes[0][-1]
            _poly_line(vd, [S(x1, y1), S(x2, y2)], col, w)
            if a.kind == "arrow":
                p1, p2 = A._arrow_head(x1, y1, x2, y2, max(8.0, a.width * 4))
                _poly_line(vd, [S(*p1), S(x2, y2), S(*p2)], col, w)
        elif a.kind in ("rect", "ellipse"):
            l, t, r, b = [v * ss for v in g.rect_to_screen(a.bounds())]
            hw = w / 2
            box = [l + hw, t + hw, r - hw, b - hw]
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            fill = _c255(a.fill, int(255 * a.opacity)) if a.fill is not None else None
            if a.kind == "rect":
                vd.rectangle(box, outline=col, width=int(w), fill=fill)
            else:
                vd.ellipse(box, outline=col, width=int(w), fill=fill)
        elif a.kind == "whiteout":
            l, t, r, b = [v * ss for v in g.rect_to_screen(a.bounds())]
            vd.rectangle([l, t, r, b], fill=_c255(a.fill or (1, 1, 1)))
        elif a.kind == "redact":
            l, t, r, b = [v * ss for v in g.rect_to_screen(a.bounds())]
            vd.rectangle([l, t, r, b], fill=(0, 0, 0, 255), outline=(230, 30, 30, 255), width=2 * ss)
    if vec is not None:
        vec = vec.resize(base.size, Image.LANCZOS)
        base = base.convert("RGBA")
        base.alpha_composite(vec)
        base = base.convert("RGB")
    return base


def draw_rects(img: Image.Image, g: PageGeom, rects, fill, outline=None) -> Image.Image:
    """Translucent rectangles (search hits, text selection)."""
    if not rects:
        return img
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for r in rects:
        l, t, rr, b = g.rect_to_screen(r)
        d.rectangle([l - 1, t - 1, rr + 1, b + 1], fill=fill, outline=outline)
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def draw_fields(img: Image.Image, g: PageGeom, widgets, values: dict, show_outline: bool) -> Image.Image:
    """Outline form fields and show values typed in the editor."""
    from ..core import textlayout
    import pypdfium2 as pdfium

    if not widgets:
        return img
    out = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for f, w in widgets:
        l, t, r, b = g.rect_to_screen(w.rect)
        if show_outline:
            d.rectangle([l, t, r, b], fill=(80, 140, 255, 38), outline=(60, 120, 240, 200), width=1)
        if f.name not in values:
            continue
        v = values[f.name]
        x0, y0, x1, y1 = w.rect
        if f.kind in ("text", "choice"):
            d.rectangle([l, t, r, b], fill=(255, 255, 255, 255))
            data = textlayout.text_box_pdf(x1 - x0, y1 - y0, str(v or ""),
                                           size=f.font_size or textlayout.fit_size(str(v or ""), "naskh",
                                                                                  x1 - x0, y1 - y0,
                                                                                  start=min(12.0, (y1 - y0) * .7)),
                                           valign="top" if f.multiline else "middle", padding=2.0)
            doc = pdfium.PdfDocument(data)
            pg = doc[0]
            im = pg.render(scale=g.scale, fill_color=(255, 255, 255, 0), rotation=g.rotation % 360).to_pil()
            pg.close()
            doc.close()
            layer.alpha_composite(im.convert("RGBA"), (max(0, round(l)), max(0, round(t))))
            d = ImageDraw.Draw(layer)
        elif f.kind in ("checkbox", "radio"):
            on = bool(v) if f.kind == "checkbox" else (v == w.on_state)
            d.rectangle([l + 1, t + 1, r - 1, b - 1], fill=(255, 255, 255, 255))
            if on:
                if f.kind == "checkbox":
                    d.line([(l + (r - l) * .2, t + (b - t) * .55), (l + (r - l) * .42, t + (b - t) * .8),
                            (l + (r - l) * .82, t + (b - t) * .2)], fill=(0, 0, 0, 255),
                           width=max(2, int((r - l) / 8)))
                else:
                    cx, cy, rr = (l + r) / 2, (t + b) / 2, (r - l) / 4
                    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(0, 0, 0, 255))
    out.alpha_composite(layer)
    return out.convert("RGB")
