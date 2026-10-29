"""Fixtures for the viewer / editor tests (written to tests/_fixtures).

* arabic_book_240p.pdf - 240 pages, Arabic + English, nested bookmarks
* form_ar.pdf          - AcroForm with text / multiline / checkbox / radio / choice
* writer_long_ar.pdf   - multi-page LibreOffice export (real shaping), if soffice exists
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tests" / "_fixtures"
DATA = ROOT / "tests" / "data"


def _lines():
    ar = [l for l in (DATA / "arabic_lines.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    en = [l for l in (DATA / "english_lines.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    return ar, en


def make_book(path: Path, pages: int = 240):
    from reportlab.pdfgen import canvas
    from waraq.core.arabic import shape_for_display
    from waraq.core.fonts import register_family

    font = register_family("naskh")[0]
    ar, en = _lines()
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setTitle("كتاب اختبار ورق")
    chapter = 0
    for p in range(pages):
        if p % 20 == 0:
            chapter += 1
            title = f"الفصل {chapter}: اختبار العارض"
            c.bookmarkPage(f"ch{chapter}")
            c.addOutlineEntry(title, f"ch{chapter}", level=0)
            c.setFont(font, 24)
            c.drawRightString(555, 780, shape_for_display(title))
            y = 740
        else:
            y = 790
        if p % 20 == 5:
            key = f"s{chapter}_{p}"
            c.bookmarkPage(key)
            c.addOutlineEntry(f"Section {chapter}.1 (English)", key, level=1)
        c.setFont(font, 15)
        k = 0
        while y > 80:
            line = ar[(p + k) % len(ar)]
            c.drawRightString(555, y, shape_for_display(line))
            y -= 26
            if k % 4 == 3:
                c.setFont("Helvetica", 11)
                c.drawString(40, y, en[(p + k) % len(en)][:95])
                c.setFont(font, 15)
                y -= 22
            k += 1
        c.setFont("Helvetica", 9)
        c.drawCentredString(297, 30, f"- {p + 1} -")
        if p == pages - 1:
            c.setFont(font, 15)
            c.drawRightString(555, 60, shape_for_display("كلمة سرية للحذف: زمرد ٤٥٦"))
        c.showPage()
    c.save()


def make_form(path: Path):
    from reportlab.pdfgen import canvas
    from waraq.core.arabic import shape_for_display
    from waraq.core.fonts import register_family

    font = register_family("naskh")[0]
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setFont(font, 20)
    c.drawRightString(555, 790, shape_for_display("نموذج طلب (اختبار تعبئة النماذج)"))
    form = c.acroForm
    c.setFont(font, 14)
    c.drawRightString(555, 740, shape_for_display("الاسم:"))
    form.textfield(name="name", x=240, y=730, width=260, height=24, borderColor=None, fontSize=12)
    c.drawRightString(555, 690, shape_for_display("العنوان:"))
    form.textfield(name="address", x=240, y=630, width=260, height=70, fieldFlags="multiline", fontSize=11)
    c.drawRightString(555, 600, shape_for_display("موافق على الشروط"))
    form.checkbox(name="agree", x=470, y=595, size=18, buttonStyle="check")
    c.drawRightString(555, 560, shape_for_display("النوع:"))
    form.radio(name="gender", value="male", x=470, y=530, size=16, selected=False)
    c.drawRightString(460, 532, shape_for_display("ذكر"))
    form.radio(name="gender", value="female", x=380, y=530, size=16, selected=False)
    c.drawRightString(370, 532, shape_for_display("أنثى"))
    c.drawRightString(555, 490, shape_for_display("المدينة:"))
    form.choice(name="city", x=240, y=480, width=200, height=22, options=["Cairo", "Alexandria", "Giza"],
                value="Cairo", fontSize=11)
    form.textfield(name="email", x=240, y=440, width=260, height=22, value="test@example.com", fontSize=11)
    c.showPage()
    c.save()


def make_writer_long(path: Path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    paras = [l for l in (DATA / "arabic_paragraphs.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    body = "".join(f"<h1>فصل {i + 1}</h1>" + "".join(f"<p>{p}</p>" for p in paras * 3) for i in range(6))
    html = f'<html dir="rtl" lang="ar"><head><meta charset="utf-8"><style>body{{font-family:Amiri;font-size:15pt}}</style></head><body>{body}</body></html>'
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "writer_long_ar.html"
        src.write_text(html, encoding="utf-8")
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf:writer_pdf_Export", "--outdir", td, str(src)],
                           check=True, capture_output=True, timeout=180)
        except Exception:
            return False
        out = Path(td) / "writer_long_ar.pdf"
        if out.exists():
            shutil.copy(out, path)
            return True
    return False


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    make_book(OUT / "arabic_book_240p.pdf")
    make_form(OUT / "form_ar.pdf")
    ok = make_writer_long(OUT / "writer_long_ar.pdf")
    print("viewer fixtures done; writer:", ok)


if __name__ == "__main__":
    main()
