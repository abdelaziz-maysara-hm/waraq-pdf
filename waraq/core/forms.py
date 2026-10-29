"""Fill AcroForm fields (pikepdf).  Values are written with our own
appearance streams (bundled Arabic font) so Arabic answers display in every
viewer, not only in ones that regenerate appearances."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import textlayout


@dataclass
class Widget:
    page: int                      # index in the source document
    rect: Tuple[float, float, float, float]
    on_state: Optional[str] = None  # checkbox / radio "on" appearance name
    objgen: Tuple[int, int] = (0, 0)


@dataclass
class Field:
    name: str
    kind: str          # text, checkbox, radio, choice, button, signature
    value: object = ""
    options: List[str] = field(default_factory=list)
    multiline: bool = False
    readonly: bool = False
    font_size: float = 0.0
    widgets: List[Widget] = field(default_factory=list)


def _inh(node, key):
    seen = 0
    while node is not None and seen < 50:
        if key in node:
            return node[key]
        node = node.get("/Parent")
        seen += 1
    return None


def _full_name(node) -> str:
    parts = []
    seen = 0
    while node is not None and seen < 50:
        if "/T" in node:
            parts.append(str(node.T))
        node = node.get("/Parent")
        seen += 1
    return ".".join(reversed(parts))


def _rect(w):
    r = [float(v) for v in w.Rect]
    return (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))


def _on_state(w) -> Optional[str]:
    try:
        if isinstance(w.AP.N, __import__("pikepdf").Stream):
            return None
        for k in w.AP.N.keys():
            if k != "/Off":
                return str(k)[1:]
    except Exception:
        pass
    return None


def _da_size(da) -> float:
    m = re.search(r"([\d.]+)\s+Tf", str(da or ""))
    return float(m.group(1)) if m else 0.0


def list_fields(pdf) -> List[Field]:
    import pikepdf

    af = pdf.Root.get("/AcroForm")
    if af is None or "/Fields" not in af:
        return []
    page_of = {}
    for i, p in enumerate(pdf.pages):
        for an in p.obj.get("/Annots", []) or []:
            try:
                page_of[an.objgen] = i
            except Exception:
                pass
    terminals: Dict[str, Tuple[object, List]] = {}
    order: List[str] = []

    def walk(node, depth=0):
        if depth > 30:
            return
        kids = node.get("/Kids")
        widget_kids = []
        field_kids = []
        if kids is not None:
            for k in kids:
                if "/T" in k:
                    field_kids.append(k)
                else:
                    widget_kids.append(k)
        if field_kids:
            for k in field_kids:
                walk(k, depth + 1)
        if not field_kids or widget_kids:
            name = _full_name(node)
            widgets = widget_kids if widget_kids else ([node] if node.get("/Subtype") == "/Widget" else [])
            if name not in terminals:
                order.append(name)
                terminals[name] = (node, [])
            terminals[name][1].extend(widgets)

    for f in af.Fields:
        walk(f)
    out = []
    for name in order:
        node, widgets = terminals[name]
        ft = str(_inh(node, "/FT") or "")
        ff = int(_inh(node, "/Ff") or 0)
        v = _inh(node, "/V")
        if ft == "/Tx":
            kind = "text"
            value = str(v) if v is not None else ""
        elif ft == "/Btn":
            if ff & (1 << 16):
                kind = "button"
                value = ""
            elif ff & (1 << 15):
                kind = "radio"
                value = str(v)[1:] if isinstance(v, pikepdf.Name) and str(v) != "/Off" else ""
            else:
                kind = "checkbox"
                value = isinstance(v, pikepdf.Name) and str(v) != "/Off"
        elif ft == "/Ch":
            kind = "choice"
            value = str(v) if v is not None and not isinstance(v, pikepdf.Array) else ""
        elif ft == "/Sig":
            kind = "signature"
            value = ""
        else:
            continue
        opts = []
        o = _inh(node, "/Opt")
        if o is not None:
            for it in o:
                opts.append(str(it[1]) if isinstance(it, pikepdf.Array) else str(it))
        fld = Field(name=name, kind=kind, value=value, options=opts, multiline=bool(ff & (1 << 12)),
                    readonly=bool(ff & 1), font_size=_da_size(_inh(node, "/DA") or af.get("/DA")))
        for w in widgets:
            try:
                fld.widgets.append(Widget(page=page_of.get(w.objgen, -1), rect=_rect(w),
                                          on_state=_on_state(w), objgen=w.objgen))
            except Exception:
                continue
        if kind == "radio":
            fld.options = [w.on_state for w in fld.widgets if w.on_state]
        out.append(fld)
    return out


def text_appearance(pdf, value: str, w: float, h: float, size: float, multiline: bool, align: str = "auto",
                    family: str = "naskh"):
    import pikepdf

    if size <= 0:
        size = textlayout.fit_size(value, family, w, h, start=min(12.0, max(h * 0.7, 6.0))) if value else 10.0
    data = textlayout.text_box_pdf(w, h, value, family=family, size=size, align=align,
                                   valign="top" if multiline else "middle", padding=2.0)
    mini = pikepdf.open(io.BytesIO(data))
    form = pdf.copy_foreign(mini.pages[0].as_form_xobject())
    form.BBox = pikepdf.Array([0, 0, w, h])
    return form


def apply_values(pdf, values: Dict[str, object], family: str = "naskh") -> int:
    """Write ``values`` (field name -> str / bool) into ``pdf``; return how many changed."""
    import pikepdf
    from pikepdf import Dictionary, Name

    if not values:
        return 0
    by_gen = {}
    for p in pdf.pages:
        for an in p.obj.get("/Annots", []) or []:
            try:
                by_gen[an.objgen] = an
            except Exception:
                pass
    fields = {f.name: f for f in list_fields(pdf)}
    af = pdf.Root.get("/AcroForm")
    n = 0
    for name, val in values.items():
        f = fields.get(name)
        if f is None or f.readonly:
            continue
        wobjs = [by_gen.get(w.objgen) for w in f.widgets]
        wobjs = [w for w in wobjs if w is not None]
        # the field dictionary: the widget itself (merged) or its parent
        fdict = None
        for w in wobjs:
            fdict = w if "/T" in w else w.get("/Parent")
            if fdict is not None:
                break
        if fdict is None:
            continue
        if f.kind in ("text", "choice"):
            s = "" if val is None else str(val)
            fdict.V = pikepdf.String(s)
            for w, meta in zip(wobjs, f.widgets):
                x0, y0, x1, y1 = meta.rect
                ww, hh = x1 - x0, y1 - y0
                rot = 0
                try:
                    rot = int(w.MK.R) % 360 if "/MK" in w and "/R" in w.MK else 0
                except Exception:
                    rot = 0
                if rot % 180:
                    ww, hh = hh, ww
                q = int(_inh(w, "/Q") or 0)
                align = {1: "center", 2: "right"}.get(q, "auto")
                form = text_appearance(pdf, s, ww, hh, f.font_size, f.multiline, align, family)
                w.AP = Dictionary(N=form)
            n += 1
        elif f.kind == "checkbox":
            on = bool(val)
            for w, meta in zip(wobjs, f.widgets):
                state = Name("/" + meta.on_state) if (on and meta.on_state) else Name.Off
                w.AS = state
            st = f.widgets[0].on_state if f.widgets else "Yes"
            fdict.V = Name("/" + (st or "Yes")) if on else Name.Off
            n += 1
        elif f.kind == "radio":
            v = str(val or "")
            for w, meta in zip(wobjs, f.widgets):
                w.AS = Name("/" + meta.on_state) if (v and meta.on_state == v) else Name.Off
            fdict.V = Name("/" + v) if v else Name.Off
            n += 1
    if n and af is not None and af.get("/NeedAppearances") is not None:
        # our appearance streams are complete; stop viewers from regenerating
        # them with a font that has no Arabic glyphs
        af.NeedAppearances = False
    return n
