"""Core of the viewer / editor: geometry, search, annotations, save, forms, redaction."""
import io
import shutil
import subprocess
import time
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest
from PIL import Image

from waraq.core import annots as A
from waraq.core import textsearch as TS
from waraq.core.document import Document
from waraq.core.errors import NeedsPasswordError, WaraqError
from waraq.core.geom import PageGeom

SECRET = "زمرد"


def _ink_bbox(img, thr=200):
    g = img.convert("L").point(lambda v: 255 if v < thr else 0)
    return g.getbbox()


# ---------------------------------------------------------------- geometry
@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_geometry_matches_pdfium(rot):
    from reportlab.pdfgen import canvas as rl

    buf = io.BytesIO()
    c = rl.Canvas(buf, pagesize=(400, 300))
    c.rect(50, 60, 30, 20, fill=1)          # a black box at known PDF coordinates
    c.save()
    pdf = pikepdf.open(io.BytesIO(buf.getvalue()))
    pdf.pages[0].obj.Rotate = rot
    pdf.pages[0].obj.CropBox = [10, 20, 400, 300]
    out = io.BytesIO()
    pdf.save(out)
    d = pdfium.PdfDocument(out.getvalue())
    pg = d[0]
    img = pg.render(scale=2).to_pil()
    bx = pg.get_bbox()
    g = PageGeom(*bx, rotation=rot, scale=2)
    assert (round(g.display_size()[0]), round(g.display_size()[1])) == img.size
    l, t, r, b = g.rect_to_screen((50, 60, 80, 80))
    got = _ink_bbox(img)
    assert abs(got[0] - l) <= 1.5 and abs(got[1] - t) <= 1.5 and abs(got[2] - r) <= 1.5 and abs(got[3] - b) <= 1.5
    # and back
    x, y = g.to_pdf(*g.to_screen(55, 65))
    assert abs(x - 55) < 1e-6 and abs(y - 65) < 1e-6
    # pdfium's own transform agrees
    for px, py in [(50, 60), (80, 80), (300, 250)]:
        sx, sy = g.to_screen(px, py)
        dx, dy = _pdfium_device(pg, img.size, rot, px, py)
        assert abs(sx - dx) <= 1.01 and abs(sy - dy) <= 1.01
    pg.close()
    d.close()


def _pdfium_device(page, size, rot, x, y):
    import ctypes
    import pypdfium2.raw as raw

    dx, dy = ctypes.c_int(), ctypes.c_int()
    raw.FPDF_PageToDevice(page, 0, 0, size[0], size[1], 0, x, y, dx, dy)
    # FPDF_PageToDevice's rotate is relative to the page's own /Rotate, which
    # FPDF_RenderPage applies automatically; we rendered with rotate=0.
    return dx.value, dy.value


# ---------------------------------------------------------------- search
def test_arabic_search_and_normalisation(fx):
    doc = Document(fx / "arabic_book_240p.pdf")
    assert len(doc) == 240
    hits = doc.search_page(239, SECRET)
    assert len(hits) == 1 and hits[0]
    # harakat / alef variants still match
    assert TS.find_all("إِنَّ الكتابَ", "ان الكتاب")
    assert TS.find_all("مكتبة", "مكتبه")
    doc.close()


def test_search_all_pages_fast(fx):
    doc = Document(fx / "arabic_book_240p.pdf")
    t0 = time.perf_counter()
    total = sum(len(doc.search_page(i, "مجانا")) for i in range(len(doc)))
    dt = time.perf_counter() - t0
    assert total > 100
    assert dt < 8.0, dt
    doc.close()


def test_outline(fx):
    doc = Document(fx / "arabic_book_240p.pdf")
    out = doc.outline()
    assert len(out) == 24
    assert all(p is not None for _, _, p in out)
    assert any(level == 1 for level, _, _ in out)
    doc.close()


def test_copy_text_is_logical(fx):
    doc = Document(fx / "arabic_reportlab.pdf")
    txt = TS.readable(doc.page_text(0))
    assert any("\u0600" <= ch <= "\u06ff" for ch in txt)
    doc.close()


# ---------------------------------------------------------------- annotations
def _annotate(doc, i=0):
    box, _ = doc.page_box(i)
    x0, y0 = box[0] + 60, box[3] - 120
    made = [
        A.make("highlight", quads=((x0, y0, x0 + 120, y0 + 14),), rect=(x0, y0, x0 + 120, y0 + 14)),
        A.make("underline", quads=((x0, y0 - 30, x0 + 100, y0 - 16),), rect=(x0, y0 - 30, x0 + 100, y0 - 16)),
        A.make("strikeout", quads=((x0, y0 - 60, x0 + 100, y0 - 46),), rect=(x0, y0 - 60, x0 + 100, y0 - 46)),
        A.make("note", rect=(x0 + 200, y0, x0 + 222, y0 + 22), text="ملاحظة مهمة"),
        A.make("freetext", rect=(x0, y0 - 160, x0 + 220, y0 - 90), text="نص عربي (تجربة) 123 English"),
        A.make("ink", strokes=(((x0, y0 - 200), (x0 + 40, y0 - 180), (x0 + 80, y0 - 210)),)),
        A.make("rect", rect=(x0 + 250, y0 - 100, x0 + 320, y0 - 50)),
        A.make("ellipse", rect=(x0 + 250, y0 - 170, x0 + 320, y0 - 120)),
        A.make("arrow", strokes=(((x0 + 250, y0 - 220), (x0 + 330, y0 - 190)),)),
        A.make("stamp", rect=(x0, y0 - 300, x0 + 150, y0 - 250), text="معتمد"),
        A.make("whiteout", rect=(x0 + 200, y0 - 300, x0 + 260, y0 - 260)),
    ]
    for a in made:
        doc.add_annot(i, a)
    return made


def test_annotations_roundtrip(fx, tmp_path):
    doc = Document(fx / "arabic_reportlab.pdf")
    made = _annotate(doc)
    out = doc.save(tmp_path / "a.pdf")
    doc.close()
    pdf = pikepdf.open(out)
    subs = sorted(str(a.Subtype) for a in pdf.pages[0].Annots)
    assert "/Highlight" in subs and "/FreeText" in subs and "/Ink" in subs and "/Stamp" in subs
    assert all("/AP" in a for a in pdf.pages[0].Annots)
    pdf.close()
    # reopen: imported back into the model, editable
    d2 = Document(out)
    kinds = sorted(a.kind for a in d2.pages[0].annots)
    assert kinds == sorted(a.kind for a in made)
    ft = [a for a in d2.pages[0].annots if a.kind == "freetext"][0]
    assert ft.text == "نص عربي (تجربة) 123 English"
    # editing again and saving does not duplicate anything
    d2.update_annot(0, ft.moved(10, 10))
    out2 = d2.save(tmp_path / "b.pdf")
    d2.close()
    d3 = Document(out2)
    assert len(d3.pages[0].annots) == len(made)
    d3.close()


def test_saved_annotations_render_everywhere(fx, tmp_path):
    doc = Document(fx / "arabic_reportlab.pdf")
    _annotate(doc)
    out = doc.save(tmp_path / "a.pdf")
    plain = Document(fx / "arabic_reportlab.pdf").render(0, 1.0)
    d = pdfium.PdfDocument(str(out))
    img = d[0].render(scale=1.0, draw_annots=True).to_pil()
    diff = Image.eval(Image.frombytes("L", img.size, bytes(
        abs(a - b) for a, b in zip(img.convert("L").tobytes(), plain.convert("L").tobytes()))), lambda v: v)
    assert diff.getbbox() is not None
    d.close()
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "72", "-png", "-f", "1", "-l", "1", str(out), str(tmp_path / "pp")],
                       check=True)
        png = sorted(tmp_path.glob("pp*.png"))[0]
        pimg = Image.open(png).convert("L")
        # the yellow highlight & red ink must be visible in poppler as well
        assert pimg.getextrema()[0] < 100


def test_viewer_render_matches_saved(fx, tmp_path):
    """What the editor draws (overlay) is close to what other viewers draw from the saved file."""
    from waraq.gui.overlay import draw_annots

    doc = Document(fx / "arabic_reportlab.pdf")
    _annotate(doc)
    g = doc.geom(0, 1.0)
    shown = draw_annots(doc.render(0, 1.0), g, doc.pages[0].annots).convert("L")
    out = doc.save(tmp_path / "a.pdf")
    d = pdfium.PdfDocument(str(out))
    saved = d[0].render(scale=1.0).to_pil().convert("L")
    d.close()
    assert shown.size == saved.size
    dif = [abs(a - b) for a, b in zip(shown.tobytes(), saved.tobytes())]
    bad = sum(1 for v in dif if v > 90) / len(dif)
    assert bad < 0.01, bad


def test_rotated_page_text_upright(fx, tmp_path):
    doc = Document(fx / "rotated90.pdf")
    _, rot = doc.page_box(0)
    g = doc.geom(0, 1.0)
    w, h = g.display_size()
    r = g.rect_to_pdf(40, 40, 300, 120)
    a = A.make("freetext", rect=r, text="مرحبا بالعالم", rotation=rot, size=24)
    doc.add_annot(0, a)
    out = doc.save(tmp_path / "r.pdf")
    d = pdfium.PdfDocument(str(out))
    img = d[0].render(scale=1).to_pil()
    d.close()
    crop = img.crop((40, 40, 300, 120))
    bb = _ink_bbox(crop)
    assert bb is not None
    # upright text is wider than tall
    assert (bb[2] - bb[0]) > (bb[3] - bb[1])


def test_undo_redo(fx):
    doc = Document(fx / "arabic_reportlab.pdf")
    a = A.make("rect", rect=(10, 10, 50, 50))
    doc.add_annot(0, a)
    doc.rotate_pages([0], 90)
    assert doc.pages[0].rot == 90 and len(doc.pages[0].annots) == 1
    assert doc.undo() and doc.pages[0].rot == 0
    assert doc.undo() and len(doc.pages[0].annots) == 0
    assert not doc.undo()
    assert doc.redo() and len(doc.pages[0].annots) == 1
    doc.close()


def test_page_operations(fx, tmp_path):
    doc = Document(fx / "arabic_book_240p.pdf")
    doc.add_annot(0, A.make("rect", rect=(100, 100, 200, 200)))
    doc.duplicate_page(0)
    doc.rotate_pages([1], 90)
    doc.insert_blank(2)
    doc.insert_pdf(3, fx / "arabic_reportlab.pdf")
    doc.delete_pages([239 + 3])
    doc.move_page(len(doc) - 1, 5)
    n = len(doc)
    # extract first: extracting does not mark the document as saved
    ex = doc.save(tmp_path / "ex.pdf", page_positions=[0, 2])
    assert len(pikepdf.open(ex).pages) == 2
    assert doc.dirty
    out = doc.save(tmp_path / "p.pdf")
    pdf = pikepdf.open(out)
    assert len(pdf.pages) == n
    assert int(pdf.pages[1].obj.get("/Rotate", 0)) % 360 == 90
    # duplicated page keeps its own annotation array
    assert len(pdf.pages[0].Annots) == 1 and len(pdf.pages[1].Annots) == 1
    assert pdf.pages[0].Annots[0].objgen != pdf.pages[1].Annots[0].objgen
    pdf.close()
    assert not doc.dirty
    doc.close()


def test_delete_all_pages_refused(fx):
    doc = Document(fx / "arabic_reportlab.pdf")
    with pytest.raises(WaraqError):
        doc.delete_pages(list(range(len(doc))))
    doc.close()


# ---------------------------------------------------------------- redaction
def _all_text(path, password=None):
    d = pdfium.PdfDocument(str(path), password=password)
    s = []
    for p in d:
        tp = p.get_textpage()
        s.append(tp.get_text_range())
        tp.close()
        p.close()
    d.close()
    return "\n".join(s)


def test_redaction_really_removes_text(fx, tmp_path):
    doc = Document(fx / "arabic_book_240p.pdf")
    last = len(doc) - 1
    hits = doc.search_page(last, SECRET)
    assert hits
    for rects in hits:
        l = min(r[0] for r in rects)
        b = min(r[1] for r in rects)
        r_ = max(r[2] for r in rects)
        t = max(r[3] for r in rects)
        doc.add_annot(last, A.make("redact", rect=(l - 2, b - 2, r_ + 2, t + 2)))
    out = doc.save(tmp_path / "red.pdf")
    doc.close()
    assert SECRET not in TS.normalize(_all_text(out))[0]
    raw = Path(out).read_bytes()
    pdf = pikepdf.open(out)
    pg = pdf.pages[last]
    assert "/Annots" not in pg.obj or len(pg.obj.Annots) == 0
    # content of that page is an image only
    assert b"Tj" not in pg.Contents.read_bytes() if not isinstance(pg.obj.Contents, pikepdf.Array) else True
    pdf.close()
    # other pages keep their text
    d = pdfium.PdfDocument(str(out))
    tp = d[0].get_textpage()
    assert len(tp.get_text_range()) > 20
    tp.close()
    d.close()
    try:
        from pdfminer.high_level import extract_text
        assert SECRET not in extract_text(str(out), page_numbers=[last])
    except ImportError:
        pass
    assert raw.count(b"/Subtype /Image") + raw.count(b"/Subtype/Image") >= 1


def test_whiteout_is_visual_only(fx, tmp_path):
    """Documented limitation: whiteout hides, it does not remove."""
    doc = Document(fx / "arabic_book_240p.pdf")
    last = len(doc) - 1
    rects = doc.search_page(last, SECRET)[0]
    doc.add_annot(last, A.make("whiteout", rect=(min(r[0] for r in rects) - 2, min(r[1] for r in rects) - 2,
                                                  max(r[2] for r in rects) + 2, max(r[3] for r in rects) + 2)))
    out = doc.save(tmp_path / "w.pdf", flatten=True)
    doc.close()
    assert SECRET in TS.normalize(_all_text(out))[0] or "زمرد" in _all_text(out)


# ---------------------------------------------------------------- encryption / safety
def test_encrypted_stays_encrypted(fx, tmp_path):
    with pytest.raises(NeedsPasswordError):
        Document(fx / "encrypted_user123.pdf")
    doc = Document(fx / "encrypted_user123.pdf", password="user123")
    doc.add_annot(0, A.make("note", rect=(50, 50, 72, 72), text="سر"))
    out = doc.save(tmp_path / "e.pdf")
    doc.close()
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(out)
    pdf = pikepdf.open(out, password="user123")
    assert pdf.is_encrypted and len(pdf.pages[0].Annots) >= 1
    pdf.close()
    d2 = Document(out, password="user123")
    assert [a.kind for a in d2.pages[0].annots] == ["note"]
    d2.close()


def test_save_over_open_file(fx, tmp_path):
    src = tmp_path / "x.pdf"
    shutil.copy(fx / "arabic_reportlab.pdf", src)
    doc = Document(src)
    doc.add_annot(0, A.make("rect", rect=(10, 10, 60, 60)))
    doc.save(src)
    assert not doc.dirty
    assert not list(tmp_path.glob("*.tmp"))
    doc.close()
    assert len(Document(src).pages[0].annots) == 1


def test_failed_save_keeps_original(fx, tmp_path, monkeypatch):
    src = tmp_path / "x.pdf"
    shutil.copy(fx / "arabic_reportlab.pdf", src)
    before = src.read_bytes()
    doc = Document(src)
    doc.add_annot(0, A.make("rect", rect=(10, 10, 60, 60)))

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pikepdf.Pdf, "save", boom)
    with pytest.raises(OSError):
        doc.save(src)
    assert src.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
    doc.close()


def test_not_a_pdf(fx):
    with pytest.raises(WaraqError):
        Document(fx / "not_a_pdf.pdf")


# ---------------------------------------------------------------- forms
def test_form_fill_arabic(fx, tmp_path):
    doc = Document(fx / "form_ar.pdf")
    names = {f.name: f for f in doc.fields}
    assert {"name", "address", "agree", "gender", "city", "email"} <= set(names)
    assert doc.field_value("email") == "test@example.com"
    doc.set_field("name", "عبد العزيز ميسرة")
    doc.set_field("address", "١٢ شارع التحرير\nالقاهرة")
    doc.set_field("agree", True)
    doc.set_field("gender", names["gender"].widgets[1].on_state)
    doc.set_field("city", names["city"].options[1])
    out = doc.save(tmp_path / "f.pdf")
    doc.close()
    pdf = pikepdf.open(out)
    from waraq.core.forms import list_fields
    vals = {f.name: f.value for f in list_fields(pdf)}
    pdf.close()
    assert vals["name"] == "عبد العزيز ميسرة"
    assert vals["agree"] in (True, "/Yes", "Yes") or vals["agree"]
    # the filled value is drawn (ink in the name field's rectangle)
    d = pdfium.PdfDocument(str(out))
    d.init_forms()   # PDFium only draws form widgets with the form module on
    img = d[0].render(scale=2, may_draw_forms=True).to_pil()
    d.close()
    w = names["name"].widgets[0]
    d2 = Document(out)
    g = d2.geom(w.page, 2)
    l, t, r, b = g.rect_to_screen(w.rect)
    assert _ink_bbox(img.crop((int(l) + 2, int(t) + 2, int(r) - 2, int(b) - 2)), 140) is not None
    assert d2.field_value("name") == "عبد العزيز ميسرة"
    d2.close()
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "144", "-png", "-f", "1", "-l", "1", str(out), str(tmp_path / "pf")],
                       check=True)
        pimg = Image.open(sorted(tmp_path.glob("pf*.png"))[0])
        assert _ink_bbox(pimg.crop((int(l) + 2, int(t) + 2, int(r) - 2, int(b) - 2)), 140) is not None


# ---------------------------------------------------------------- performance
def test_big_document_performance(fx, tmp_path):
    import psutil

    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    doc = Document(fx / "arabic_book_240p.pdf")
    t_open = time.perf_counter() - t0
    t0 = time.perf_counter()
    for i in range(0, 240, 6):
        doc.render(i, 1.5)
    t_render = (time.perf_counter() - t0) / 40
    for i in range(0, 240, 10):
        doc.add_annot(i, A.make("highlight", quads=((50, 50, 150, 64),), rect=(50, 50, 150, 64)))
    t0 = time.perf_counter()
    doc.save(tmp_path / "big.pdf")
    t_save = time.perf_counter() - t0
    rss = proc.memory_info().rss - rss0
    doc.close()
    print(f"open {t_open:.2f}s render {t_render * 1000:.0f}ms/page save {t_save:.2f}s rss +{rss / 1e6:.0f}MB")
    assert t_open < 5 and t_render < 1.0 and t_save < 20
    assert rss < 600e6
