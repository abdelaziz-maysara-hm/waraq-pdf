"""The key feature: Arabic PDF -> Word/TXT in correct logical order."""
import unicodedata

import pytest
from docx import Document

from conftest import has_fixture, source_lines
from waraq.core import arabic
from waraq.core.extract import extract_pages, save_docx, save_txt, docx_paragraph_texts

HARAKAT = {chr(c) for c in range(0x064B, 0x0653)} | {"\u0670"}


def strip_harakat(s):
    return "".join(ch for ch in s if ch not in HARAKAT)


def lines_of(path):
    out = []
    for p in extract_pages(path):
        for b in p.blocks:
            out.extend(l.text for l in b.lines)
    return [l for l in out if l.strip() and l.strip() != "page 1" and not l.startswith("page ")]


def score(src, got):
    exact = sum(arabic.squash_ws(a) == arabic.squash_ws(b) for a, b in zip(src, got))
    loose = sum(strip_harakat(arabic.squash_ws(a)) == strip_harakat(arabic.squash_ws(b)) for a, b in zip(src, got))
    cer = arabic.char_error_rate("\n".join(src), "\n".join(got))
    return exact, loose, cer


# ---- pure algorithm ---------------------------------------------------------
CASES = source_lines() + source_lines("english_lines.txt") + [
    "(مرحبا) [عالم] {نص}", "سعر 25% و 3.5 كجم", "Hello عالم world", "ﷺ ﷽ ﴾الآية﴿",
]


@pytest.mark.parametrize("text", CASES)
def test_visual_roundtrip(text):
    from bidi.algorithm import get_display
    # paragraph direction from the first strong character (Unicode rule P2);
    # in real PDFs Waraq takes it from the whole page, see extract.py
    first = next(c for c in text if c.isalpha())
    base = "R" if arabic.is_arabic_char(first) else "L"
    visual = get_display(text, base_dir=base)
    assert arabic.visual_to_logical(visual, base=base) == text


def test_presentation_forms_normalized():
    assert arabic.normalize_presentation("\ufee3\ufeae\ufea3\ufe92\ufe8e") == "مرحبا"
    assert arabic.normalize_presentation("ﷺ") == "ﷺ"


def test_shape_for_display_keeps_harakat():
    s = arabic.shape_for_display("مُحَمَّد")
    assert any(unicodedata.combining(c) for c in s)


# ---- real PDFs --------------------------------------------------------------
def test_reportlab_pdf_exact(fx):
    src = source_lines()
    got = lines_of(fx / "arabic_reportlab.pdf")[: len(src)]
    exact, loose, cer = score(src, got)
    print(f"\nreportlab: exact {exact}/{len(src)} cer {cer:.4f}")
    assert exact == len(src)


@pytest.mark.parametrize("name,min_exact", [("arabic_writer.pdf", 12), ("arabic_writer_dejavu.pdf", 10)])
def test_libreoffice_pdf(fx, name, min_exact):
    if not has_fixture(name):
        pytest.skip("LibreOffice not available to build fixture")
    src = source_lines()
    got = lines_of(fx / name)
    assert len(got) == len(src), got
    exact, loose, cer = score(src, got)
    print(f"\n{name}: exact {exact}/{len(src)} harakat-insensitive {loose}/{len(src)} cer {cer:.4f}")
    assert exact >= min_exact
    assert loose == len(src)
    assert cer < 0.01


def test_justified_paragraphs(fx):
    if not has_fixture("arabic_paragraphs.pdf"):
        pytest.skip("LibreOffice not available")
    src = source_lines("arabic_paragraphs.txt")
    blocks = [b.text for b in extract_pages(fx / "arabic_paragraphs.pdf")[0].blocks]
    assert len(blocks) == len(src), blocks
    for s, b in zip(src, blocks):
        cer = arabic.char_error_rate(s, b)
        print(f"\nparagraph cer {cer:.4f}")
        assert cer < 0.02
        assert strip_harakat(arabic.squash_ws(s)) == strip_harakat(arabic.squash_ws(b))


def test_docx_roundtrip_logical_order_and_rtl(fx, tmp_path):
    src = source_lines()
    pages = extract_pages(fx / "arabic_reportlab.pdf")
    out = tmp_path / "a.docx"
    save_docx(pages, out, layout="lines")
    paras = [p for p in docx_paragraph_texts(out) if p.strip() and not p.startswith("page ")]
    assert paras[: len(src)] == src
    doc = Document(str(out))
    p = next(p for p in doc.paragraphs if arabic.has_arabic(p.text))
    xml = p._p.xml
    assert "<w:bidi" in xml and "<w:rtl" in xml
    # no presentation forms / visual-order artefacts in Word
    allt = "".join(paras)
    assert not any(0xFB50 <= ord(c) <= 0xFDFF and c not in "ﷺﷻ﷼﷽" or 0xFE70 <= ord(c) <= 0xFEFF for c in allt)


def test_txt_utf8_bom(fx, tmp_path):
    out = tmp_path / "a.txt"
    save_txt(extract_pages(fx / "arabic_reportlab.pdf"), out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert source_lines()[0] in raw.decode("utf-8-sig")


def test_scanned_page_flagged(fx):
    p = extract_pages(fx / "arabic_scanned.pdf")[0]
    assert p.needs_ocr


def test_english_untouched(fx):
    p = extract_pages(fx / "english_50p.pdf", pages=[0])[0]
    assert "Page 1" in p.blocks[0].text
