"""Annotations made in the editor and their PDF form.

Every annotation is written as a *real* PDF annotation (Highlight, Text,
FreeText, Ink, Square, Circle, Line, Stamp) with its own appearance stream,
so Acrobat, browsers, PDFgear, Edge, etc. show it.  Arabic text is shaped
and embedded with a bundled font inside the appearance stream.  A private
``/WaraqData`` entry keeps the editable description so Waraq can edit the
annotation again after the file is reopened.
"""
from __future__ import annotations

import io
import json
import math
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from . import textlayout

Rect = Tuple[float, float, float, float]
Color = Tuple[float, float, float]

KINDS = ("highlight", "underline", "strikeout", "note", "freetext", "ink", "rect", "ellipse", "line",
         "arrow", "image", "stamp", "whiteout", "textedit", "redact")
MARKUP = ("highlight", "underline", "strikeout")
BOX_KINDS = ("freetext", "rect", "ellipse", "image", "stamp", "whiteout", "textedit", "redact", "note")

DEFAULT_COLORS = {
    "highlight": (1.0, 0.85, 0.0), "underline": (0.1, 0.45, 0.95), "strikeout": (0.9, 0.1, 0.1),
    "note": (1.0, 0.82, 0.2), "freetext": (0.0, 0.0, 0.0), "ink": (0.85, 0.1, 0.1), "rect": (0.85, 0.1, 0.1),
    "ellipse": (0.85, 0.1, 0.1), "line": (0.85, 0.1, 0.1), "arrow": (0.85, 0.1, 0.1),
    "image": (0, 0, 0), "stamp": (0.8, 0.1, 0.1), "whiteout": (1, 1, 1), "textedit": (0, 0, 0),
    "redact": (0, 0, 0),
}
NOTE_SIZE = 22.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Annot:
    kind: str
    rect: Rect = (0.0, 0.0, 0.0, 0.0)
    color: Color = (0.0, 0.0, 0.0)
    fill: Optional[Color] = None
    width: float = 1.5
    opacity: float = 1.0
    text: str = ""
    family: str = "naskh"
    size: float = 14.0
    quads: Tuple[Rect, ...] = ()
    strokes: Tuple[Tuple[Tuple[float, float], ...], ...] = ()
    image: Optional[bytes] = field(default=None, repr=False, compare=False)
    rotation: int = 0          # display rotation when created; text/images stay upright
    align: str = "auto"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: str = field(default_factory=_now)
    author: str = ""

    # ------------------------------------------------------------------
    def bounds(self) -> Rect:
        pad = self.width / 2 + 1
        if self.kind in MARKUP and self.quads:
            xs = [q[0] for q in self.quads] + [q[2] for q in self.quads]
            ys = [q[1] for q in self.quads] + [q[3] for q in self.quads]
            return (min(xs), min(ys), max(xs), max(ys))
        if self.kind in ("ink", "line", "arrow") and self.strokes:
            pts = [p for s in self.strokes for p in s]
            extra = pad + (self.width * 4 if self.kind == "arrow" else 0)
            return (min(p[0] for p in pts) - extra, min(p[1] for p in pts) - extra,
                    max(p[0] for p in pts) + extra, max(p[1] for p in pts) + extra)
        r = self.rect
        return (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))

    def moved(self, dx: float, dy: float) -> "Annot":
        r = self.rect
        return replace(self, rect=(r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy),
                       quads=tuple((q[0] + dx, q[1] + dy, q[2] + dx, q[3] + dy) for q in self.quads),
                       strokes=tuple(tuple((p[0] + dx, p[1] + dy) for p in s) for s in self.strokes))

    def resized(self, new: Rect) -> "Annot":
        """Scale the geometry so that ``bounds()`` becomes ``new`` (approximately)."""
        nx0, ny0, nx1, ny1 = min(new[0], new[2]), min(new[1], new[3]), max(new[0], new[2]), max(new[1], new[3])
        if self.kind in ("ink", "line", "arrow") and self.strokes:
            ox0, oy0, ox1, oy1 = self.bounds()
            sx = (nx1 - nx0) / max(ox1 - ox0, 1e-6)
            sy = (ny1 - ny0) / max(oy1 - oy0, 1e-6)
            f = lambda p: (nx0 + (p[0] - ox0) * sx, ny0 + (p[1] - oy0) * sy)  # noqa: E731
            return replace(self, strokes=tuple(tuple(f(p) for p in s) for s in self.strokes))
        if self.kind in MARKUP:
            return self
        return replace(self, rect=(nx0, ny0, nx1, ny1))

    def to_json(self) -> str:
        d = asdict(self)
        d.pop("image", None)
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def from_json(s: str, image: Optional[bytes] = None) -> "Annot":
        d = json.loads(s)
        known = {f for f in Annot.__dataclass_fields__}
        d = {k: v for k, v in d.items() if k in known}
        for k in ("rect", "color"):
            if k in d and d[k] is not None:
                d[k] = tuple(d[k])
        if d.get("fill") is not None:
            d["fill"] = tuple(d["fill"])
        d["quads"] = tuple(tuple(q) for q in d.get("quads", ()))
        d["strokes"] = tuple(tuple(tuple(p) for p in s) for s in d.get("strokes", ()))
        d["image"] = image
        return Annot(**d)


def make(kind: str, **kw) -> Annot:
    kw.setdefault("color", DEFAULT_COLORS.get(kind, (0, 0, 0)))
    if kind == "highlight":
        kw.setdefault("opacity", 0.45)
    if kind == "whiteout":
        kw.setdefault("fill", (1.0, 1.0, 1.0))
    if kind == "textedit":
        kw.setdefault("fill", (1.0, 1.0, 1.0))
    if kind == "ink":
        kw.setdefault("width", 2.0)
    return Annot(kind=kind, **kw)


# ----------------------------------------------------------------------
# appearance streams
# ----------------------------------------------------------------------
def _f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _rgb(c: Color, op: str) -> str:
    return f"{_f(c[0])} {_f(c[1])} {_f(c[2])} {op}"


def _arrow_head(x1, y1, x2, y2, size):
    ang = math.atan2(y2 - y1, x2 - x1)
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    return ((x2 + size * math.cos(a1), y2 + size * math.sin(a1)),
            (x2 + size * math.cos(a2), y2 + size * math.sin(a2)))


def _ellipse_path(x0, y0, x1, y1) -> str:
    k = 0.5523
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    p = [f"{_f(cx + rx)} {_f(cy)} m"]
    p.append(f"{_f(cx + rx)} {_f(cy + k * ry)} {_f(cx + k * rx)} {_f(cy + ry)} {_f(cx)} {_f(cy + ry)} c")
    p.append(f"{_f(cx - k * rx)} {_f(cy + ry)} {_f(cx - rx)} {_f(cy + k * ry)} {_f(cx - rx)} {_f(cy)} c")
    p.append(f"{_f(cx - rx)} {_f(cy - k * ry)} {_f(cx - k * rx)} {_f(cy - ry)} {_f(cx)} {_f(cy - ry)} c")
    p.append(f"{_f(cx + k * rx)} {_f(cy - ry)} {_f(cx + rx)} {_f(cy - k * ry)} {_f(cx + rx)} {_f(cy)} c")
    return " ".join(p)


def simple_ap(a: Annot) -> Tuple[str, bool]:
    """Content stream (page coordinates) for vector kinds; returns (ops, needs_multiply)."""
    ops: List[str] = []
    w = a.width
    if a.kind == "highlight":
        ops.append("/GS0 gs " + _rgb(a.color, "rg"))
        for q in a.quads:
            ops.append(f"{_f(q[0])} {_f(q[1])} {_f(q[2] - q[0])} {_f(q[3] - q[1])} re f")
        return "\n".join(ops), True
    if a.kind in ("underline", "strikeout"):
        ops.append("/GS0 gs " + _rgb(a.color, "RG"))
        for q in a.quads:
            hh = q[3] - q[1]
            lw = max(hh / 14.0, 0.8)
            y = q[1] + lw * 1.2 if a.kind == "underline" else q[1] + hh * 0.42
            ops.append(f"{_f(lw)} w {_f(q[0])} {_f(y)} m {_f(q[2])} {_f(y)} l S")
        return "\n".join(ops), False
    ops.append("/GS0 gs 1 J 1 j " + _rgb(a.color, "RG") + f" {_f(w)} w")
    if a.kind == "ink":
        for s in a.strokes:
            if not s:
                continue
            ops.append(f"{_f(s[0][0])} {_f(s[0][1])} m")
            if len(s) == 1:
                ops.append(f"{_f(s[0][0] + 0.01)} {_f(s[0][1])} l")
            for p in s[1:]:
                ops.append(f"{_f(p[0])} {_f(p[1])} l")
            ops.append("S")
    elif a.kind in ("line", "arrow"):
        (x1, y1), (x2, y2) = a.strokes[0][0], a.strokes[0][-1]
        ops.append(f"{_f(x1)} {_f(y1)} m {_f(x2)} {_f(y2)} l S")
        if a.kind == "arrow":
            (ax, ay), (bx, by) = _arrow_head(x1, y1, x2, y2, max(8.0, w * 4))
            ops.append(f"{_f(ax)} {_f(ay)} m {_f(x2)} {_f(y2)} l {_f(bx)} {_f(by)} l S")
    elif a.kind in ("rect", "ellipse", "whiteout"):
        x0, y0, x1, y1 = a.bounds()
        if a.kind == "whiteout":
            ops = ["/GS0 gs " + _rgb(a.fill or (1, 1, 1), "rg"),
                   f"{_f(x0)} {_f(y0)} {_f(x1 - x0)} {_f(y1 - y0)} re f"]
        else:
            if a.fill is not None:
                ops.append(_rgb(a.fill, "rg"))
            paint = "B" if a.fill is not None else "S"
            hw = w / 2
            if a.kind == "rect":
                ops.append(f"{_f(x0 + hw)} {_f(y0 + hw)} {_f(x1 - x0 - w)} {_f(y1 - y0 - w)} re {paint}")
            else:
                ops.append(_ellipse_path(x0 + hw, y0 + hw, x1 - hw, y1 - hw) + " " + paint)
    return "\n".join(ops), False


def rich_ap_pdf(a: Annot, display_w: float, display_h: float) -> bytes:
    """One-page PDF (display orientation) holding the annotation appearance."""
    if a.kind in ("freetext", "textedit"):
        return textlayout.text_box_pdf(display_w, display_h, a.text, family=a.family, size=a.size,
                                       color=a.color, fill=a.fill,
                                       border=(a.color if (a.kind == "freetext" and a.width > 0 and a.fill)
                                               else None),
                                       border_width=a.width, align=a.align, opacity=a.opacity, padding=2.0)
    if a.kind == "stamp":
        bw = max(a.width, 2.0)
        size = textlayout.fit_size(a.text, a.family, display_w - 2 * bw - 8,
                                   display_h - 2 * bw - 4, start=max(8.0, display_h * 0.62))
        return textlayout.text_box_pdf(display_w, display_h, a.text, family=a.family, size=size,
                                       color=a.color, fill=a.fill, border=a.color,
                                       border_width=max(a.width, 2.0), align="center", opacity=a.opacity,
                                       valign="middle")
    if a.kind == "image":
        return textlayout.image_pdf(display_w, display_h, a.image or b"", opacity=a.opacity)
    if a.kind == "note":
        return textlayout.note_icon_pdf(min(display_w, display_h), a.color)
    raise ValueError(a.kind)


def is_rich(a: Annot) -> bool:
    return a.kind in ("freetext", "textedit", "stamp", "image", "note")


def display_dims(a: Annot) -> Tuple[float, float]:
    x0, y0, x1, y1 = a.bounds()
    w, h = x1 - x0, y1 - y0
    return (h, w) if a.rotation % 180 else (w, h)


# ----------------------------------------------------------------------
# writing into a pikepdf page
# ----------------------------------------------------------------------
SUBTYPE = {"highlight": "/Highlight", "underline": "/Underline", "strikeout": "/StrikeOut", "note": "/Text",
           "freetext": "/FreeText", "textedit": "/FreeText", "ink": "/Ink", "rect": "/Square",
           "ellipse": "/Circle", "line": "/Line", "arrow": "/Line", "image": "/Stamp", "stamp": "/Stamp",
           "whiteout": "/Square"}


def _pdf_string(s: str):
    import pikepdf

    return pikepdf.String(s)


def _rot_matrix(r: int, w: float, h: float):
    """Matrix rotating the box [0 0 w h] counter-clockwise by r and moving it back to x,y >= 0."""
    r %= 360
    if r == 0:
        return [1, 0, 0, 1, 0, 0]
    if r == 90:
        return [0, 1, -1, 0, h, 0]
    if r == 180:
        return [-1, 0, 0, -1, w, h]
    return [0, -1, 1, 0, 0, w]


def write_annotation(pdf, page, a: Annot):
    """Append ``a`` to pikepdf ``page`` as a real annotation; return the dict."""
    import pikepdf
    from pikepdf import Array, Dictionary, Name

    if a.kind == "redact":
        return None
    x0, y0, x1, y1 = a.bounds()
    d = Dictionary(Type=Name.Annot, Subtype=Name(SUBTYPE[a.kind]),
                   Rect=Array([x0, y0, x1, y1]), F=4, NM=_pdf_string("waraq-" + a.id),
                   M=_pdf_string("D:" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%SZ")),
                   C=Array(list(a.color)))
    d.P = page.obj
    if a.author:
        d.T = _pdf_string(a.author)
    if a.text:
        d.Contents = _pdf_string(a.text)
    if a.opacity < 1.0:
        d.CA = a.opacity
    if a.kind in MARKUP:
        qp = []
        for q in a.quads:
            qp += [q[0], q[3], q[2], q[3], q[0], q[1], q[2], q[1]]
        d.QuadPoints = Array(qp)
    elif a.kind == "ink":
        d.InkList = Array([Array([c for p in s for c in p]) for s in a.strokes])
        d.BS = Dictionary(W=a.width, S=Name.S)
    elif a.kind in ("line", "arrow"):
        (lx1, ly1), (lx2, ly2) = a.strokes[0][0], a.strokes[0][-1]
        d.L = Array([lx1, ly1, lx2, ly2])
        d.BS = Dictionary(W=a.width, S=Name.S)
        if a.kind == "arrow":
            d.LE = Array([Name("/None"), Name.OpenArrow])
    elif a.kind in ("rect", "ellipse", "whiteout"):
        d.BS = Dictionary(W=0 if a.kind == "whiteout" else a.width, S=Name.S)
        if a.fill is not None:
            d.IC = Array(list(a.fill))
        if a.kind == "whiteout":
            d.C = Array(list(a.fill or (1, 1, 1)))
    elif a.kind in ("freetext", "textedit"):
        d.DA = _pdf_string(f"/Helv {a.size:g} Tf {a.color[0]:g} {a.color[1]:g} {a.color[2]:g} rg")
        d.Q = 2 if textlayout.base_direction(a.text) == "rtl" and a.align in ("auto", "right") else 0
        if a.fill is not None:
            d.C = Array(list(a.fill))
        else:
            del d["/C"]
        if a.rotation:
            d.Rotate = a.rotation
    elif a.kind == "note":
        d.Name = Name.Comment
        d.Open = False
    elif a.kind in ("image", "stamp"):
        d.Name = Name("/Waraq" + ("Image" if a.kind == "image" else "Stamp"))

    # appearance
    if is_rich(a):
        dw, dh = display_dims(a)
        mini = pikepdf.open(io.BytesIO(rich_ap_pdf(a, dw, dh)))
        xobj = mini.pages[0].as_form_xobject()
        form = pdf.copy_foreign(xobj)
        form.BBox = Array([0, 0, dw, dh])
        m = _rot_matrix(a.rotation, dw, dh)
        # rotate, then move to the annotation rectangle
        form.Matrix = Array([m[0], m[1], m[2], m[3], m[4] + x0, m[5] + y0])
    else:
        ops, multiply = simple_ap(a)
        gs = Dictionary(Type=Name.ExtGState, CA=a.opacity, ca=a.opacity)
        if multiply:
            gs.BM = Name.Multiply
        form = pdf.make_stream(ops.encode("latin-1"))
        form.Type = Name.XObject
        form.Subtype = Name.Form
        form.BBox = Array([x0, y0, x1, y1])
        form.Resources = Dictionary(ExtGState=Dictionary(GS0=gs))
    d.AP = Dictionary(N=form)
    d.WaraqData = _pdf_string(a.to_json())
    if a.image and a.kind == "image":
        d.WaraqImg = pdf.make_stream(a.image)
    ref = pdf.make_indirect(d)
    if "/Annots" not in page.obj:
        page.obj.Annots = pdf.make_indirect(Array())
    page.obj.Annots.append(ref)
    return ref


def read_waraq_annotations(page) -> List[Annot]:
    """Annotations previously written by Waraq on a pikepdf page."""
    out = []
    for an in page.obj.get("/Annots", []) or []:
        try:
            if "/WaraqData" not in an:
                continue
            img = bytes(an.WaraqImg.read_bytes()) if "/WaraqImg" in an else None
            out.append(Annot.from_json(str(an.WaraqData), img))
        except Exception:
            continue
    return out


def strip_waraq_annotations(pdf) -> int:
    """Remove Waraq's own annotations (they are re-created from the model)."""
    import pikepdf

    n = 0
    for page in pdf.pages:
        annots = page.obj.get("/Annots")
        if annots is None:
            continue
        keep = pikepdf.Array()
        changed = False
        for an in annots:
            try:
                if "/WaraqData" in an:
                    changed = True
                    n += 1
                    continue
            except Exception:
                pass
            keep.append(an)
        if changed:
            page.obj.Annots = keep
    return n
