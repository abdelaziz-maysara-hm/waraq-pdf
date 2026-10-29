"""The document behind the viewer / editor.

Pages are a list of immutable ``PageRef`` (which source page, extra
rotation, annotations).  Every edit replaces that list, so undo/redo are
just snapshots.  Rendering uses PDFium on the untouched source bytes;
editor annotations are drawn on top by the GUI and only written into a PDF
by ``save`` (pikepdf), as real PDF annotations.
"""
from __future__ import annotations

import io
import os
import uuid
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import annots as A
from . import forms as F
from .errors import NeedsPasswordError, WaraqError, WrongPasswordError
from .geom import PageGeom


def _uid() -> str:
    return uuid.uuid4().hex[:10]


@dataclass(frozen=True)
class PageRef:
    src: str                     # source key ("main", "ins1", ...) or "blank"
    index: int = 0               # page index inside the source
    rot: int = 0                 # extra clockwise rotation saved with the file
    annots: Tuple[A.Annot, ...] = ()
    size: Tuple[float, float] = (595.0, 842.0)   # blank pages only
    uid: str = field(default_factory=_uid)


class Source:
    def __init__(self, key: str, path: Optional[str], raw: bytes, password: Optional[str]):
        self.key = key
        self.path = path
        self.raw = raw
        self.password = password
        self.encrypted = False
        self.render_bytes = raw
        self.pdf = None          # pypdfium2 document
        self.forms = False

    def open_pdfium(self, init_forms: bool = False):
        import pypdfium2 as pdfium

        try:
            self.pdf = pdfium.PdfDocument(self.render_bytes,
                                          password=None if self.render_bytes is not self.raw else self.password)
        except pdfium.PdfiumError as e:
            msg = str(e).lower()
            if "password" in msg:
                if self.password:
                    raise WrongPasswordError(str(self.path))
                raise NeedsPasswordError(str(self.path))
            raise WaraqError(f"Cannot open {self.path}: {e}", "bad_pdf", path=str(self.path))
        if init_forms:
            try:
                if self.pdf.get_formtype():
                    self.pdf.init_forms()
                    self.forms = True
            except Exception:
                self.forms = False

    def close(self):
        try:
            if self.pdf is not None:
                self.pdf.close()
        except Exception:
            pass
        self.pdf = None


def _open_pikepdf(raw: bytes, password: Optional[str], path):
    import pikepdf

    try:
        return pikepdf.open(io.BytesIO(raw), password=password or "")
    except pikepdf.PasswordError:
        if password:
            raise WrongPasswordError(str(path))
        raise NeedsPasswordError(str(path))
    except Exception as e:
        raise WaraqError(f"Not a valid PDF: {path} ({e})", "bad_pdf", path=str(path))


class Document:
    MAX_UNDO = 200

    def __init__(self, path, password: Optional[str] = None):
        self.path = str(path)
        p = Path(path)
        if not p.exists():
            raise WaraqError(f"File not found: {path}", "not_found", path=str(path))
        raw = p.read_bytes()
        if b"%PDF" not in raw[:2048]:
            raise WaraqError(f"Not a valid PDF: {path}", "bad_pdf", path=str(path))
        self.password = password
        main = Source("main", self.path, raw, password)
        pk = _open_pikepdf(raw, password, path)
        main.encrypted = bool(pk.is_encrypted)
        self.fields: List[F.Field] = []
        try:
            self.fields = F.list_fields(pk)
        except Exception:
            self.fields = []
        imported: Dict[int, List[A.Annot]] = {}
        for i, pg in enumerate(pk.pages):
            got = A.read_waraq_annotations(pg)
            if got:
                imported[i] = got
        if imported or main.encrypted:
            # PDFium renders a copy without Waraq's own annotations (they are
            # drawn - and edited - from the model) and without encryption.
            A.strip_waraq_annotations(pk)
            buf = io.BytesIO()
            pk.save(buf)
            main.render_bytes = buf.getvalue()
        n = len(pk.pages)
        pk.close()
        main.open_pdfium(init_forms=bool(self.fields))
        self.sources: Dict[str, Source] = {"main": main}
        self.pages: List[PageRef] = [PageRef("main", i, annots=tuple(imported.get(i, ()))) for i in range(n)]
        self.form_values: Dict[str, object] = {}
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []
        self.dirty = False
        self._tp_cache: "OrderedDict[Tuple[str, int], tuple]" = OrderedDict()
        self._text_cache: Dict[Tuple[str, int], str] = {}
        self._ins = 0
        self.listeners: List[Callable[[str], None]] = []

    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return Path(self.path).name

    def __len__(self):
        return len(self.pages)

    def close(self):
        self._drop_textpages()
        for s in self.sources.values():
            s.close()

    def _notify(self, what: str):
        for cb in list(self.listeners):
            try:
                cb(what)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # geometry & rendering
    # ------------------------------------------------------------------
    def _src_page_info(self, ref: PageRef):
        if ref.src == "blank":
            return (0.0, 0.0, ref.size[0], ref.size[1]), 0
        pdf = self.sources[ref.src].pdf
        page = pdf[ref.index]
        try:
            box = page.get_bbox()
            rot = page.get_rotation()
        finally:
            page.close()
        return box, rot

    def page_box(self, i: int):
        """(crop box, total saved rotation) of page i."""
        ref = self.pages[i]
        box, rot = self._box_cache(ref)
        return box, (rot + ref.rot) % 360

    def _box_cache(self, ref: PageRef):
        key = (ref.src, ref.index) if ref.src != "blank" else ("blank", ref.uid)
        c = getattr(self, "_boxes", None)
        if c is None:
            c = self._boxes = {}
        if key not in c:
            c[key] = self._src_page_info(ref)
        return c[key]

    def geom(self, i: int, scale: float = 1.0, view_rot: int = 0) -> PageGeom:
        box, rot = self.page_box(i)
        return PageGeom(box[0], box[1], box[2], box[3], (rot + view_rot) % 360, scale)

    def display_size(self, i: int, view_rot: int = 0) -> Tuple[float, float]:
        """Page size in points as displayed (after rotation)."""
        return self.geom(i, 1.0, view_rot).display_size()

    def render(self, i: int, scale: float, view_rot: int = 0, draw_annots: bool = True):
        """PIL image of page i as stored (no editor annotations)."""
        from PIL import Image

        ref = self.pages[i]
        g = self.geom(i, scale, view_rot)
        w, h = g.display_size()
        if ref.src == "blank":
            return Image.new("RGB", (max(1, round(w)), max(1, round(h))), "white")
        src = self.sources[ref.src]
        page = src.pdf[ref.index]
        try:
            bm = page.render(scale=scale, rotation=(ref.rot + view_rot) % 360, draw_annots=draw_annots,
                             may_draw_forms=src.forms)
            img = bm.to_pil()
        finally:
            page.close()
        return img

    # ------------------------------------------------------------------
    # text
    # ------------------------------------------------------------------
    def _drop_textpages(self):
        for tp, pg in self._tp_cache.values():
            try:
                tp.close()
                pg.close()
            except Exception:
                pass
        self._tp_cache.clear()

    def textpage(self, i: int):
        ref = self.pages[i]
        if ref.src == "blank":
            return None
        key = (ref.src, ref.index)
        if key in self._tp_cache:
            self._tp_cache.move_to_end(key)
            return self._tp_cache[key][0]
        pg = self.sources[ref.src].pdf[ref.index]
        tp = pg.get_textpage()
        self._tp_cache[key] = (tp, pg)
        while len(self._tp_cache) > 24:
            _, (otp, opg) = self._tp_cache.popitem(last=False)
            try:
                otp.close()
                opg.close()
            except Exception:
                pass
        return tp

    def page_text(self, i: int) -> str:
        from .textsearch import page_text

        ref = self.pages[i]
        if ref.src == "blank":
            return ""
        key = (ref.src, ref.index)
        if key not in self._text_cache:
            self._text_cache[key] = page_text(self.textpage(i))
        return self._text_cache[key]

    def search_page(self, i: int, query: str):
        """List of matches on page i; each match is a list of PDF rects."""
        from .textsearch import find_all, range_rects

        tp = self.textpage(i)
        if tp is None:
            return []
        return [range_rects(tp, a, n) for a, n in find_all(self.page_text(i), query)]

    def outline(self):
        """[(level, title, page position or None)] for the bookmarks panel."""
        out = []
        pos = {}
        for k, ref in enumerate(self.pages):
            if ref.src == "main" and ref.index not in pos:
                pos[ref.index] = k
        try:
            for item in self.sources["main"].pdf.get_toc(max_depth=12):
                idx = None
                try:
                    dest = item.get_dest()
                    idx = dest.get_index() if dest is not None else None
                except Exception:
                    idx = None
                out.append((item.level, item.get_title(), pos.get(idx) if idx is not None else None))
        except Exception:
            pass
        return out

    # ------------------------------------------------------------------
    # undo / redo
    # ------------------------------------------------------------------
    def _snapshot(self):
        return (tuple(self.pages), dict(self.form_values))

    def _push(self):
        self._undo.append(self._snapshot())
        if len(self._undo) > self.MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()
        self.dirty = True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        pages, vals = self._undo.pop()
        self.pages, self.form_values = list(pages), vals
        self.dirty = True
        self._notify("undo")
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        pages, vals = self._redo.pop()
        self.pages, self.form_values = list(pages), vals
        self.dirty = True
        self._notify("redo")
        return True

    # ------------------------------------------------------------------
    # annotations
    # ------------------------------------------------------------------
    def add_annot(self, i: int, a: A.Annot) -> A.Annot:
        self._push()
        ref = self.pages[i]
        self.pages[i] = replace(ref, annots=ref.annots + (a,))
        self._notify("annots")
        return a

    def update_annot(self, i: int, a: A.Annot, record: bool = True):
        ref = self.pages[i]
        if record:
            self._push()
        self.pages[i] = replace(ref, annots=tuple(a if x.id == a.id else x for x in ref.annots))
        self._notify("annots")

    def remove_annot(self, i: int, annot_id: str):
        ref = self.pages[i]
        if not any(x.id == annot_id for x in ref.annots):
            return
        self._push()
        self.pages[i] = replace(ref, annots=tuple(x for x in ref.annots if x.id != annot_id))
        self._notify("annots")

    def add_annots_bulk(self, add: Dict[int, Sequence[A.Annot]]):
        """Add many annotations (on several pages) as one undo step."""
        if not add:
            return
        self._push()
        for i, items in add.items():
            ref = self.pages[i]
            self.pages[i] = replace(ref, annots=ref.annots + tuple(items))
        self._notify("annots")

    def find_annot(self, i: int, annot_id: str) -> Optional[A.Annot]:
        for a in self.pages[i].annots:
            if a.id == annot_id:
                return a
        return None

    def annot_count(self) -> int:
        return sum(len(p.annots) for p in self.pages)

    # ------------------------------------------------------------------
    # page operations
    # ------------------------------------------------------------------
    def rotate_pages(self, idx: Sequence[int], delta: int):
        self._push()
        for i in idx:
            r = self.pages[i]
            self.pages[i] = replace(r, rot=(r.rot + delta) % 360)
        self._notify("pages")

    def delete_pages(self, idx: Sequence[int]):
        keep = [p for k, p in enumerate(self.pages) if k not in set(idx)]
        if not keep:
            raise WaraqError("The result would have no pages", "no_pages")
        self._push()
        self.pages = keep
        self._notify("pages")

    def move_page(self, i: int, to: int):
        if i == to or not (0 <= to < len(self.pages)):
            return
        self._push()
        p = self.pages.pop(i)
        self.pages.insert(to, p)
        self._notify("pages")

    def duplicate_page(self, i: int):
        self._push()
        p = self.pages[i]
        self.pages.insert(i + 1, replace(p, uid=_uid()))
        self._notify("pages")

    def insert_blank(self, at: int, size: Optional[Tuple[float, float]] = None):
        if size is None:
            if self.pages:
                k = min(max(at - 1, 0), len(self.pages) - 1)
                w, h = self.display_size(k)
                size = (w, h)
            else:
                size = (595.0, 842.0)
        self._push()
        self.pages.insert(at, PageRef("blank", 0, size=tuple(size)))
        self._notify("pages")

    def insert_pdf(self, at: int, path, password: Optional[str] = None) -> int:
        raw = Path(path).read_bytes()
        self._ins += 1
        key = f"ins{self._ins}"
        src = Source(key, str(path), raw, password)
        pk = _open_pikepdf(raw, password, path)
        src.encrypted = bool(pk.is_encrypted)
        if src.encrypted:
            buf = io.BytesIO()
            pk.save(buf)
            src.render_bytes = buf.getvalue()
        n = len(pk.pages)
        pk.close()
        src.open_pdfium()
        self.sources[key] = src
        self._push()
        for k in range(n):
            self.pages.insert(at + k, PageRef(key, k))
        self._notify("pages")
        return n

    # ------------------------------------------------------------------
    # forms
    # ------------------------------------------------------------------
    def field_value(self, name: str):
        if name in self.form_values:
            return self.form_values[name]
        for f in self.fields:
            if f.name == name:
                return f.value
        return None

    def set_field(self, name: str, value):
        if self.field_value(name) == value:
            return
        self._push()
        self.form_values[name] = value
        self._notify("forms")

    def widgets_on(self, i: int):
        """[(field, widget)] shown on page position i."""
        ref = self.pages[i]
        if ref.src != "main":
            return []
        out = []
        for f in self.fields:
            for w in f.widgets:
                if w.page == ref.index:
                    out.append((f, w))
        return out

    # ------------------------------------------------------------------
    # saving
    # ------------------------------------------------------------------
    def build(self, flatten: bool = False, page_positions: Optional[Sequence[int]] = None,
              redact_dpi: int = 200, progress: Optional[Callable[[int, int], None]] = None):
        """Return (pikepdf.Pdf, encryption) with every change applied."""
        import pikepdf

        main = self.sources["main"]
        pdf = _open_pikepdf(main.raw, main.password, self.path)
        A.strip_waraq_annotations(pdf)
        orig = list(pdf.pages)
        orig_annots = [list(pg.obj.get("/Annots", []) or []) for pg in orig]
        used = set()
        others = {}
        positions = list(range(len(self.pages))) if page_positions is None else list(page_positions)
        if self.form_values and page_positions is None:
            # fill before reordering: widgets are looked up through the page tree
            F.apply_values(pdf, self.form_values)
        while len(pdf.pages):
            del pdf.pages[-1]
        total = len(positions) * 2
        for k, pos in enumerate(positions):
            ref = self.pages[pos]
            if ref.src == "main":
                pdf.pages.append(orig[ref.index])
                if ref.index in used:
                    # a duplicated page is a copy that still shares the /Annots
                    # array of the first one; give it its own array
                    if orig_annots[ref.index] or "/Annots" in pdf.pages[-1].obj:
                        pdf.pages[-1].obj.Annots = pdf.make_indirect(pikepdf.Array(orig_annots[ref.index]))
                used.add(ref.index)
            elif ref.src == "blank":
                pdf.add_blank_page(page_size=ref.size)
            else:
                if ref.src not in others:
                    s = self.sources[ref.src]
                    others[ref.src] = _open_pikepdf(s.raw, s.password, s.path)
                pdf.pages.append(others[ref.src].pages[ref.index])
            page = pdf.pages[-1]
            if ref.rot:
                page.rotate(ref.rot, relative=True)
            for a in ref.annots:
                A.write_annotation(pdf, page, a)
            if progress:
                progress(k + 1, total)
        if flatten:
            pdf.flatten_annotations("all")
        redact_pages = [k for k, pos in enumerate(positions)
                        if any(a.kind == "redact" for a in self.pages[pos].annots)]
        if redact_pages:
            self._apply_redactions(pdf, positions, redact_pages, redact_dpi)
        if progress:
            progress(total, total)
        return pdf, others

    def _apply_redactions(self, pdf, positions, redact_pages, dpi):
        """True redaction: the page is replaced by an image of itself with black boxes,
        so the text and graphics underneath no longer exist in the file."""
        import pikepdf
        import pypdfium2 as pdfium
        from PIL import ImageDraw

        buf = io.BytesIO()
        pdf.save(buf)
        doc = pdfium.PdfDocument(buf.getvalue())
        has_forms = False
        try:
            if doc.get_formtype():
                doc.init_forms()
                has_forms = True
        except Exception:
            pass
        scale = dpi / 72.0
        removed = set()
        for k in redact_pages:
            pos = positions[k]
            pg = doc[k]
            box = pg.get_bbox()
            rot = pg.get_rotation()
            img = pg.render(scale=scale, may_draw_forms=has_forms).to_pil().convert("RGB")
            pg.close()
            g = PageGeom(box[0], box[1], box[2], box[3], rot, scale)
            dr = ImageDraw.Draw(img)
            for a in self.pages[pos].annots:
                if a.kind == "redact":
                    l, t, r, b = g.rect_to_screen(a.bounds())
                    dr.rectangle([l - 1, t - 1, r + 1, b + 1], fill=(0, 0, 0))
            dw, dh = g.display_size()
            wpt, hpt = dw / scale, dh / scale
            page = pdf.pages[k]
            for an in page.obj.get("/Annots", []) or []:
                try:
                    removed.add(an.objgen)
                except Exception:
                    pass
            im = pdf.make_stream(zlib.compress(img.tobytes(), 6))
            im.Type = pikepdf.Name.XObject
            im.Subtype = pikepdf.Name.Image
            im.Width, im.Height = img.width, img.height
            im.ColorSpace = pikepdf.Name.DeviceRGB
            im.BitsPerComponent = 8
            im.Filter = pikepdf.Name.FlateDecode
            for key in ("/Annots", "/CropBox", "/TrimBox", "/BleedBox", "/ArtBox", "/StructParents",
                        "/PieceInfo", "/Thumb", "/B", "/Group", "/Rotate", "/Metadata"):
                if key in page.obj:
                    del page.obj[key]
            page.obj.MediaBox = pikepdf.Array([0, 0, wpt, hpt])
            page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=im))
            page.obj.Contents = pdf.make_stream(f"q {wpt:.4f} 0 0 {hpt:.4f} 0 0 cm /Im0 Do Q".encode())
        doc.close()
        if removed and "/AcroForm" in pdf.Root:
            self._prune_fields(pdf.Root.AcroForm, removed)

    @staticmethod
    def _prune_fields(af, removed):
        import pikepdf

        def prune(arr):
            keep = pikepdf.Array()
            for f in arr:
                try:
                    if f.objgen in removed:
                        continue
                    if "/Kids" in f:
                        f.Kids = prune(f.Kids)
                        if len(f.Kids) == 0 and "/T" in f:
                            continue
                except Exception:
                    pass
                keep.append(f)
            return keep

        if "/Fields" in af:
            af.Fields = prune(af.Fields)

    def save(self, dst, flatten: bool = False, page_positions: Optional[Sequence[int]] = None,
             keep_password: bool = True, progress: Optional[Callable[[int, int], None]] = None) -> Path:
        """Write the edited document to ``dst`` safely.

        The new file is written next to the target, reopened and checked,
        and only then moved over the target in one step, so a crash or a
        full disk never leaves a half-written PDF (the original stays as it
        was).
        """
        import pikepdf
        import pypdfium2 as pdfium

        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        pdf, others = self.build(flatten=flatten, page_positions=page_positions, progress=progress)
        main = self.sources["main"]
        enc = False
        if keep_password and main.encrypted:
            enc = True   # keep the original password / permissions
        tmp = dst.with_name(dst.name + f".waraq-{os.getpid()}.tmp")
        try:
            pdf.save(tmp, encryption=enc, object_stream_mode=pikepdf.ObjectStreamMode.generate)
            pdf.close()
            for o in others.values():
                o.close()
            expected = len(self.pages) if page_positions is None else len(page_positions)
            chk = pdfium.PdfDocument(str(tmp), password=main.password if enc else None)
            n = len(chk)
            p0 = chk[0]
            p0.render(scale=0.1).to_pil()
            p0.close()
            chk.close()
            if n != expected:
                raise WaraqError(f"Saved file has {n} pages, expected {expected}", "save_check")
            os.replace(tmp, dst)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
        if page_positions is None:
            self.dirty = False
        return dst
