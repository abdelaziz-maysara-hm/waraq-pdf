"""Drives the real viewer/editor GUI under Xvfb, saves screenshots to docs/screenshots.

Run: xvfb-run -a -s "-screen 0 1366x860x24" python tests/gui_viewer_drive.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WARAQ_SETTINGS_DIR", tempfile.mkdtemp())   # keep the user's recent list clean

import psutil  # noqa: E402
import pikepdf  # noqa: E402
import pypdfium2 as pdfium  # noqa: E402
from PIL import ImageGrab  # noqa: E402

from waraq.core import textsearch as TS  # noqa: E402
from waraq.gui.app import App  # noqa: E402
from waraq.gui.i18n import t  # noqa: E402

FIX = ROOT / "tests" / "_fixtures"
SHOTS = ROOT / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
OUT = Path(tempfile.mkdtemp())
results = []
errors = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""), flush=True)


class E:
    def __init__(self, x, y, state=0):
        self.x, self.y, self.state = int(x), int(y), state
        self.widget = None
        self.delta = 0
        self.num = 0
        self.x_root = self.y_root = 0


def new_app(lang, theme):
    app = App(lang=lang, theme=theme)
    app.report_callback_exception = lambda *a: errors.append("".join(traceback.format_exception(*a)))
    app.geometry("1366x820+0+0")
    pump(app, 0.8)
    return app


def pump(app, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.015)


def settle(app, v):
    for _ in range(200):
        pump(app, 0.05)
        if not v.queue and not v._render_job:
            break
    pump(app, 0.2)


def shot(app, name, crop=None):
    pump(app, 0.4)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY"))
    if crop:
        img = img.crop(crop)
    p = SHOTS / f"{name}.png"
    img.save(p)
    return p


def wxy(v, i, px, py):
    """PDF point -> widget coordinates of the canvas."""
    cx, cy = v.to_canvas(i, px, py)
    return cx - v.canvas.canvasx(0), cy - v.canvas.canvasy(0)


def drag(v, i, p0, p1, steps=6):
    x0, y0 = wxy(v, i, *p0)
    x1, y1 = wxy(v, i, *p1)
    v._press(E(x0, y0))
    for k in range(1, steps + 1):
        v._motion(E(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps))
    v._release(E(x1, y1))


def click(v, i, p):
    x, y = wxy(v, i, *p)
    v._press(E(x, y))
    v._release(E(x, y))


def pdftoppm_ok(path, page=1):
    if not shutil.which("pdftoppm"):
        return True
    r = subprocess.run(["pdftoppm", "-r", "40", "-f", str(page), "-l", str(page), "-png", str(path),
                        str(OUT / "ppm")], capture_output=True, text=True)
    return r.returncode == 0 and "Error" not in r.stderr


def run_ar():
    proc = psutil.Process()
    app = new_app("ar", "dark")
    shot(app, "v_ar_01_home_empty")
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    v = app.open_pdf(FIX / "arabic_book_240p.pdf")
    settle(app, v)
    t_open = time.perf_counter() - t0
    check("ar open 240p and first render", v is not None and len(v.doc) == 240 and v.photos,
          f"{t_open:.2f}s")
    check("ar tab title", any(d["doc"].name == "arabic_book_240p.pdf" for d in app.docs))
    shot(app, "v_ar_02_viewer")
    # thumbnails / bookmarks
    for _ in range(100):
        pump(app, 0.05)
        if v.thumbs_ready():
            break
    check("ar thumbnails drawn", len(v.thumb_photos) > 0, f"{len(v.thumb_photos)} thumbs")
    v._side_tab(t("bookmarks"))
    pump(app, 0.3)
    check("ar bookmarks filled", len(v.doc.outline()) >= 24)
    shot(app, "v_ar_03_bookmarks")
    v._side_tab(t("thumbs"))
    # zoom & modes
    v.set_zoom(100); settle(app, v)
    check("ar zoom 100", v.zoom == 100 and abs(v.scale - 96 / 72) < 1e-6)
    v.set_fit("page"); settle(app, v)
    check("ar fit page", v.fit == "page" and v.zoom < 100, f"{v.zoom}%")
    v.set_mode("double"); settle(app, v)
    s0, s1 = v.slots[0], v.slots[1]
    check("ar double mode RTL order (page 1 on the right)", s0 and s1 and s0[0] > s1[0])
    shot(app, "v_ar_04_double")
    v.set_mode("single"); v.goto(4); settle(app, v)
    check("ar single mode page 5", v.cur == 4 and sum(1 for s in v.slots if s) == 1)
    v.set_mode("continuous"); v.set_fit("width"); v.goto(0); settle(app, v)
    v.rotate_view(90); settle(app, v)
    check("ar rotate view", v.view_rot == 90 and v.slots[0][2] > v.slots[0][3])
    v.rotate_view(-90); settle(app, v)
    # jump to page via entry
    v.page_entry.delete(0, "end"); v.page_entry.insert(0, "120"); v._page_entered()
    settle(app, v)
    check("ar jump to page 120", v.cur == 119, str(v.cur))
    # scroll through the whole book (memory)
    for k in range(0, 240, 6):
        v.goto(k)
        settle(app, v)
    rss1 = proc.memory_info().rss
    check("ar scrolled 240 pages, memory bounded", (rss1 - rss0) / 2**20 < 450,
          f"RSS +{(rss1 - rss0) / 2**20:.0f} MB, cache {sum(im.width * im.height * len(im.getbands()) for im in v.base_cache.values()) / 2**20:.0f} MB")
    v.goto(0); settle(app, v)

    # search with highlight
    v.open_find()
    v.find_entry.delete(0, "end"); v.find_entry.insert(0, "الرحمن")
    v.find("الرحمن")
    for _ in range(400):
        pump(app, 0.02)
        if v.search_done():
            break
    check("ar search all pages", v.search_done() and len(v.hit_list) >= 240, f"{len(v.hit_list)} hits")
    v.goto(0); v.hit_idx = 0; v._show_hit(); settle(app, v)
    shot(app, "v_ar_05_search")
    v.find_step(1); settle(app, v)
    check("ar next hit", v.hit_idx == 1)
    v.close_find(); settle(app, v)

    # text selection + copy
    txt = v.doc.page_text(0)
    a = txt.find("بسم الله")
    v.select_text(0, a, len("بسم الله الرحمن الرحيم"))
    v.copy_selection()
    pump(app, 0.1)
    clip = app.clipboard_get()
    check("ar copy Arabic selection", TS.normalize(clip)[0] == TS.normalize("بسم الله الرحمن الرحيم")[0], clip)

    # ---------------- editor: comment tab
    v.show_tab("tab_comment"); pump(app, 0.2)
    hits = [(s, n) for s, n in TS.find_all(txt, "برنامج ورق")]
    v.set_tool("highlight")
    v.select_text(0, hits[0][0], hits[0][1]); v._markup_from_selection("highlight")
    b = txt.find("يعمل البرنامج")
    v.select_text(0, b, len("يعمل البرنامج")); v._markup_from_selection("underline")
    c = txt.find("بدلاً")
    v.select_text(0, c, 5); v._markup_from_selection("strikeout")
    check("ar markup annots", v.doc.annot_count() == 3, str(v.doc.annot_count()))
    v.set_tool("note"); app.test_answers.append("ملاحظة: راجع السعر")
    click(v, 0, (40, 800))
    v.set_tool("ink")
    drag(v, 0, (60, 110), (220, 70), steps=12)
    pr = TS.range_rects(v.doc.textpage(0), txt.find("السعر"), len("السعر: 0 جنيه (مجاني بالكامل) بدلاً من $240 في السنة"))
    box = (min(r[0] for r in pr) - 4, min(r[1] for r in pr) - 4, max(r[2] for r in pr) + 4, max(r[3] for r in pr) + 4)
    v.set_tool("rect"); drag(v, 0, (box[0], box[3]), (box[2], box[1]))
    v.set_tool("ellipse"); drag(v, 0, (50, 370), (160, 290))
    v.set_tool("arrow"); drag(v, 0, (180, 300), (285, 365))
    v.set_tool("freetext")
    app.test_answers.append({"text": "مرحبًا بكم في ورق (نسخة 0.2)\nنص عربي متصل مع English 123",
                             "size": 15, "family": "naskh"})
    drag(v, 0, (40, 760), (285, 680))
    v.set_tool("stamp"); v._stamp_set("معتمد"); click(v, 0, (50, 628))
    v.choose_signature(str(FIX / "signature.jpg"))
    click(v, 0, (60, 505))
    n_ann = v.doc.annot_count()
    check("ar 11 annotations via the GUI", n_ann == 11, str(n_ann))
    v.set_tool("select"); v._select(None)
    v.set_fit("page"); settle(app, v)
    shot(app, "v_ar_06_editor")
    # Arabic text box close-up at 200 %
    ft = [a for a in v.doc.pages[0].annots if a.kind == "freetext"][0]
    v.set_zoom(200); settle(app, v)
    l, t_, r, b2 = v.rect_to_canvas(0, ft.bounds())
    region_w = float(str(v.canvas.cget("scrollregion")).split()[2])
    v.canvas.yview_moveto(max(0, (t_ - 60) / v.total_h))
    v.canvas.xview_moveto(max(0, (l - 60) / region_w))
    v._on_scroll(); settle(app, v)
    ox, oy = v.canvas.winfo_rootx() - app.winfo_rootx(), v.canvas.winfo_rooty() - app.winfo_rooty()
    sx, sy = v.canvas.canvasx(0), v.canvas.canvasy(0)
    shot(app, "v_ar_07_arabic_textbox",
         crop=(int(ox + l - sx - 60), int(oy + t_ - sy - 30), int(ox + r - sx + 60), int(oy + b2 - sy + 30)))
    v.set_fit("page"); settle(app, v)
    # move + undo/redo
    v.set_tool("select")
    cx = (ft.bounds()[0] + ft.bounds()[2]) / 2
    cy = (ft.bounds()[1] + ft.bounds()[3]) / 2
    drag(v, 0, (cx, cy), (cx - 20, cy - 30))
    moved = v.doc.find_annot(0, ft.id)
    check("ar move text box", moved and abs(moved.bounds()[0] - ft.bounds()[0] + 20) < 1.5,
          f"{moved.bounds()[:2] if moved else None}")
    v.undo(); pump(app, 0.1)
    check("ar undo move", v.doc.find_annot(0, ft.id).bounds() == ft.bounds())
    v.redo(); v.undo(); pump(app, 0.1)
    # edit tab: whiteout, text edit, redaction
    v.show_tab("tab_edit"); pump(app, 0.2)
    v.set_tool("whiteout"); drag(v, 0, (300, 92), (560, 70))
    line = txt.find("رقم الهاتف")
    rr = TS.range_rects(v.doc.textpage(0), line, len("رقم الهاتف"))[0]
    v.set_tool("textedit"); app.test_answers.append({"text": "هاتف الدعم", "size": 18, "family": "naskh"})
    click(v, 0, ((rr[0] + rr[2]) / 2, (rr[1] + rr[3]) / 2))
    check("ar text edit (cover-and-replace)", any(a.kind == "textedit" and a.text == "هاتف الدعم"
                                                  for a in v.doc.pages[0].annots))
    v.set_fit("page"); settle(app, v)
    shot(app, "v_ar_08_edit")
    # page ops on thumbnails
    v.show_tab("tab_page"); pump(app, 0.2)
    v.sel_pages = {1}
    v.rotate_pages(90); v.duplicate_page(); v.insert_blank()
    check("ar page ops", len(v.doc) == 242, str(len(v.doc)))
    v.delete_pages()  # deletes the selection
    pump(app, 0.2)
    check("ar delete page", len(v.doc) == 241, str(len(v.doc)))
    settle(app, v)
    shot(app, "v_ar_09_pages")
    check("ar tab shows unsaved dot", v.doc.dirty)
    out = OUT / "edited_ar.pdf"
    ok = v.save_as(str(out))
    settle(app, v)
    check("ar save as", ok and out.exists() and not v.doc.dirty)
    with pikepdf.open(out) as pdf:
        ann = [str(x.get("/Subtype")) for x in pdf.pages[0].get("/Annots", [])]
    check("ar real PDF annotations saved", {"/Highlight", "/Underline", "/StrikeOut", "/Text", "/Ink", "/Square",
                                            "/Circle", "/Line", "/FreeText", "/Stamp"} <= set(ann), str(ann))
    pdf = pdfium.PdfDocument(str(out))
    check("ar saved renders in pdfium", len(pdf) == 241 and pdf[0].render(scale=0.5).to_pil().size[0] > 100)
    pdf.close()
    check("ar saved renders in pdftoppm", pdftoppm_ok(out))
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-r", "80", "-f", "1", "-l", "1", "-png", "-singlefile", str(out),
                        str(SHOTS / "v_ar_12_saved_pdftoppm")], check=False)
    check("ar annotations reloaded for editing", len(v.doc.pages[0].annots) == 13, str(len(v.doc.pages[0].annots)))
    app.toggle_lang(); pump(app, 0.5)
    v2 = app.view
    check("language switch keeps the open document", v2 is not None and len(v2.doc) == 241 and
          v2.doc.annot_count() == v.doc.annot_count())
    app.toggle_lang(); pump(app, 0.5)
    v = app.view
    settle(app, v)
    # form
    fv = app.open_pdf(FIX / "form_ar.pdf", tab="tab_form")
    settle(app, fv)
    check("second tab opened", len(app.docs) == 2)
    e = fv.field_widgets.get("name")
    e.delete(0, "end"); e.insert(0, "عبد العزيز ميسرة")
    fv._commit_entry("name", e)
    fv.doc.set_field("agree", True)
    fv.doc.set_field("city", fv.doc.fields[[f.name for f in fv.doc.fields].index("city")].options[1]
                     if getattr(fv.doc.fields[4], "options", None) else "القاهرة")
    fv._fill_fields()
    settle(app, fv)
    shot(app, "v_ar_10_form")
    fout = OUT / "form_filled.pdf"
    check("form save", fv.save_as(str(fout)))
    with pikepdf.open(fout) as p:
        vals = {str(f.get("/T")): str(f.get("/V")) for f in p.Root.AcroForm.Fields}
    check("form value saved", vals.get("name") == "عبد العزيز ميسرة", str(vals))
    # close tabs: dirty prompt answered "discard"
    fv.doc.set_field("email", "a@b.c")
    app.test_answers.append("discard")
    app.close_doc(app.active)
    check("close dirty tab (discard)", len(app.docs) == 1)
    app.show_home(); pump(app, 0.4)
    shot(app, "v_ar_11_home_recent")
    check("recent list", len(app.settings["recent"]) >= 3, str(len(app.settings["recent"])))
    app.open_tool("compress", str(FIX / "english_50p.pdf"))
    pump(app, 0.3)
    check("open tool prefilled", app.panels["compress"].file.get().endswith("english_50p.pdf"))
    check("no Tk callback errors (ar)", not errors, errors[-1][-800:] if errors else "")
    app.destroy()


def run_en():
    app = new_app("en", "light")
    src = FIX / "writer_long_ar.pdf"
    if not src.exists():                       # no LibreOffice (e.g. Windows CI)
        src = FIX / "english_50p.pdf"
    v = app.open_pdf(src)
    settle(app, v)
    v.show_tab("tab_comment"); pump(app, 0.2)
    txt = v.doc.page_text(0)
    words = [w for w in txt.split() if len(w) > 3][:3]
    for w, kind in zip(words, ("highlight", "underline", "strikeout")):
        s = txt.find(w)
        v.select_text(0, s, len(w)); v._markup_from_selection(kind)
    v.set_tool("freetext")
    app.test_answers.append({"text": "Reviewed - تمت المراجعة", "size": 14, "family": "sans"})
    drag(v, 0, (40, 810), (300, 775))
    v.set_tool("select"); v._select(None)
    v.set_fit("page"); settle(app, v)
    shot(app, "v_en_01_viewer")
    app.show_home(); pump(app, 0.3)
    shot(app, "v_en_02_home")
    # drag & drop (the <<Drop>> handler; the OS-level drag itself needs a real desktop)
    spaced = OUT / "with space.pdf"
    shutil.copy(FIX / "rotated90.pdf", spaced)

    class Drop:
        data = "{%s} %s" % (spaced, FIX / "signature.jpg")
        action = "copy"
    app._on_drop(Drop())
    pump(app, 0.3)
    check("en drop: PDF with a space opened, non-PDF ignored", len(app.docs) == 2 and
          app.docs[-1]["doc"].name == "with space.pdf", f"dnd loaded={app.dnd}")
    app.close_doc(app.docs[-1])
    app.show_doc(app.docs[0]); v.toggle_night(); settle(app, v)
    shot(app, "v_en_03_night")
    v.toggle_night()
    # dirty on close
    app.test_answers.append(None)          # Cancel
    app.on_close(); pump(app, 0.1)
    check("en cancel close keeps app", app.winfo_exists() and len(app.docs) == 1)
    check("no Tk callback errors (en)", not errors, errors[-1][-800:] if errors else "")
    app.test_answers.append("discard")
    app.on_close()


if __name__ == "__main__":
    try:
        run_ar()
    except Exception:
        traceback.print_exc()
        check("ar run finished", False)
    try:
        run_en()
    except Exception:
        traceback.print_exc()
        check("en run finished", False)
    for e in errors:
        print(e)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} viewer GUI checks passed; screenshots in {SHOTS}")
    sys.exit(1 if bad else 0)
