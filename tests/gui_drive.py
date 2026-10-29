"""Drive the real GUI (run under xvfb-run) - every tool, both languages.

    xvfb-run -s "-screen 0 1280x800x24" python tests/gui_drive.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WARAQ_SETTINGS_DIR", tempfile.mkdtemp())

from PIL import ImageGrab  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from waraq.gui.app import App  # noqa: E402
from waraq.core import pages as P, security  # noqa: E402

FIX = ROOT / "tests" / "_fixtures"
SHOTS = ROOT / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
OUT = Path(tempfile.mkdtemp())
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""), flush=True)


def _patch_wait(app):
    import faulthandler
    orig = app.wait_idle

    def w(timeout=60):
        ok = orig(timeout)
        if not ok:
            print("TIMEOUT waiting for task", flush=True)
            faulthandler.dump_traceback(all_threads=True)
        return ok
    app.wait_idle = w


def shot(app, name):
    app.update(); time.sleep(0.25); app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=os.environ.get("DISPLAY"))
    p = SHOTS / f"{name}.png"
    img.save(p)
    return p


def run(lang):
    app = App(lang=lang, theme="dark" if lang == "ar" else "light")
    _patch_wait(app)
    app.geometry("1180x760+0+0")
    app.update()
    sfx = lang

    # merge (with an encrypted file -> password prompt answered programmatically)
    m = app.show("merge")
    m.list.add([FIX / "english_50p.pdf", FIX / "encrypted_user123.pdf", FIX / "rotated90.pdf"])
    m.list.select(1)
    app.test_passwords[str(FIX / "encrypted_user123.pdf")] = "wrong"
    shot(app, f"{sfx}_01_merge")
    out = OUT / f"merged_{lang}.pdf"
    # first a wrong password, then the right one
    import waraq.gui.base as base
    orig = base.PasswordDialog

    class Auto:  # simulates the user typing the right password in the dialog
        def __init__(self, master, name):
            self.result = "user123"
    base.PasswordDialog = Auto
    app.wait_window = lambda d: None
    app.test_answers.append(str(out))
    m.run(); app.wait_idle()
    base.PasswordDialog = orig
    n_expected = 50 + P.page_count(FIX / "encrypted_user123.pdf", "user123") + P.page_count(FIX / "rotated90.pdf")
    check(f"{lang} merge with password", out.exists() and P.page_count(out) == n_expected, m.status_var.get())

    # split
    s = app.show("split")
    s.file.set_path(str(FIX / "english_50p.pdf"))
    s.mode.set("every"); s.every.delete(0, "end"); s.every.insert(0, "20")
    shot(app, f"{sfx}_02_split")
    d = OUT / f"split_{lang}"
    s.run(out_dir=str(d)); app.wait_idle()
    check(f"{lang} split every 20", len(list(d.glob("*.pdf"))) == 3)

    # organize
    o = app.show("organize")
    o.load(str(FIX / "english_50p.pdf")); app.wait_idle()
    o.toggle(0); o.rotate(90); o.toggle(0)
    o.toggle(1); o.delete()
    o.toggle(0); o.move(1); o.toggle(1)
    o.toggle(2)
    shot(app, f"{sfx}_03_organize")
    out = OUT / f"org_{lang}.pdf"
    o.save(str(out)); app.wait_idle()
    r = PdfReader(str(out))
    check(f"{lang} organize", len(r.pages) == 49 and "Page 3" in r.pages[0].extract_text()
          and "Page 1" in r.pages[1].extract_text() and r.pages[1].rotation == 90)

    # images
    im = app.show("images")
    im.list.add(sorted((FIX / "images").iterdir()))
    shot(app, f"{sfx}_04_images")
    out = OUT / f"img_{lang}.pdf"
    im.to_pdf(str(out)); app.wait_idle()
    check(f"{lang} images->pdf", P.page_count(out) == 4)
    im.tabs.set(im.tabs.cget("values")[1]); im._switch(im.tabs.cget("values")[1])
    im.file.set_path(str(FIX / "arabic_reportlab.pdf"))
    d = OUT / f"pdf2img_{lang}"
    im.to_images(str(d)); app.wait_idle()
    check(f"{lang} pdf->images", len(list(d.glob("*.png"))) == 2)

    # compress
    c = app.show("compress")
    c.file.set_path(str(FIX / "photos_large.pdf"))
    c.preset.set("strong")
    out = OUT / f"small_{lang}.pdf"
    c.run(str(out)); app.wait_idle(60)
    shot(app, f"{sfx}_05_compress")
    check(f"{lang} compress", out.exists() and c.last_result.saved_ratio > 0.5,
          f"{c.last_result.saved_ratio:.3f}")

    # convert (key feature)
    cv = app.show("convert")
    cv.layout.set(list(cv.layout_opts)[1])
    cv.extract(str(FIX / "arabic_writer.pdf")); app.wait_idle()
    shot(app, f"{sfx}_06_convert_preview")
    out = OUT / f"conv_{lang}.docx"
    cv.save_docx(str(out)); app.wait_idle()
    from waraq.core.extract import docx_paragraph_texts
    src = [l for l in (ROOT / "tests/data/arabic_lines.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    got = [p for p in docx_paragraph_texts(out) if p.strip()]
    check(f"{lang} pdf->word lines", sum(a == b for a, b in zip(src, got)) >= 12,
          f"{sum(a == b for a, b in zip(src, got))}/{len(src)} exact")
    cv.extract(str(FIX / "arabic_scanned.pdf")); app.wait_idle(60)
    shot(app, f"{sfx}_07_convert_scanned_ocr")
    check(f"{lang} pdf->word scanned auto-OCR", cv.pages and cv.pages[0].ocr, cv.status_var.get())

    # OCR
    oc = app.show("ocr")
    oc.run(str(FIX / "arabic_scanned.pdf")); app.wait_idle(60)
    shot(app, f"{sfx}_08_ocr")
    check(f"{lang} ocr", oc.result and "برنامج" in oc.result[0])

    # sign
    sg = app.show("sign")
    sg.file.set_path(str(FIX / "arabic_reportlab.pdf"))
    sg.image.set_path(str(FIX / "signature.jpg"))
    sg.text.insert(0, "معتمد")
    sg.preview(); app.wait_idle()
    shot(app, f"{sfx}_09_sign")
    out = OUT / f"signed_{lang}.pdf"
    sg.run(str(out)); app.wait_idle()
    check(f"{lang} sign", out.exists() and P.page_count(out) == 2)

    # security
    se = app.show("security")
    se.file.set_path(str(FIX / "english_50p.pdf"))
    se.pw1.insert(0, "abc"); se.pw2.insert(0, "abd")
    se.protect(str(OUT / "x.pdf"))
    check(f"{lang} password mismatch caught", not (OUT / "x.pdf").exists() and se.status_var.get())
    se.pw2.delete(0, "end"); se.pw2.insert(0, "abc")
    out = OUT / f"prot_{lang}.pdf"
    se.protect(str(out)); app.wait_idle()
    shot(app, f"{sfx}_10_security")
    check(f"{lang} protect", security.is_encrypted(out))
    se.file.set_path(str(out)); se.pw_cur.insert(0, "nope")
    se.unlock(str(OUT / "bad.pdf")); app.wait_idle()
    check(f"{lang} wrong password message", app.last_error is not None and not (OUT / "bad.pdf").exists(),
          se.status_var.get())
    se.pw_cur.delete(0, "end"); se.pw_cur.insert(0, "abc")
    se.unlock(str(OUT / f"unl_{lang}.pdf")); app.wait_idle()
    check(f"{lang} unlock", not security.is_encrypted(OUT / f"unl_{lang}.pdf"))

    # error handling: invalid pdf
    s = app.show("split"); s.file.set_path(str(FIX / "not_a_pdf.pdf")); s.run(out_dir=str(OUT / "z"))
    app.update()
    shot(app, f"{sfx}_11_error")
    check(f"{lang} invalid pdf message", s.status_var.get() != "", s.status_var.get())
    app.destroy()


if __name__ == "__main__":
    run("ar")
    run("en")
    # language toggle keeps working
    app = App(lang="en"); app.update(); app.toggle_lang(); app.update()
    check("toggle to Arabic", app.settings["lang"] == "ar" and app.home.winfo_exists())
    app.destroy()
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} GUI checks passed; screenshots in {SHOTS}")
    sys.exit(1 if bad else 0)
