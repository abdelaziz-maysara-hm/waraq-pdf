import subprocess
import sys

import pytest

from conftest import ROOT, source_lines
from waraq.core import arabic
from waraq.core import ocr

needs_tess = pytest.mark.skipif(not ocr.TesseractEngine().has_language("ara"),
                                reason="tesseract with Arabic not installed")


@needs_tess
def test_tesseract_arabic_scan(fx):
    eng = ocr.get_engine("tesseract")
    text = ocr.ocr_pdf(fx / "arabic_scanned.pdf", engine=eng, pages="1")[0]
    src = source_lines()
    cer = arabic.char_error_rate(arabic.squash_ws(" ".join(src)), arabic.squash_ws(text.replace("page 1", "")))
    print(f"\ntesseract CER on synthetic scan: {cer:.4f}")
    assert "\u200e" not in text and "\u200f" not in text
    assert cer < 0.25
    assert "برنامج ورق" in text


@needs_tess
def test_searchable_pdf(fx, tmp_path):
    out = tmp_path / "s.pdf"
    ocr.make_searchable(fx / "arabic_scanned.pdf", out)
    from waraq.core.extract import extract_pages
    p = extract_pages(out)[0]
    assert p.chars > 100


def test_windows_engine_reports_unavailable_on_linux():
    if sys.platform != "win32":
        assert not ocr.WindowsOcrEngine().available()


def run(*args):
    return subprocess.run([sys.executable, "-m", "waraq", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_end_to_end(fx, tmp_path):
    r = run("info", fx / "english_50p.pdf"); assert r.returncode == 0 and '"pages": 50' in r.stdout
    r = run("merge", fx / "english_50p.pdf", fx / "rotated90.pdf", "-o", tmp_path / "m.pdf"); assert r.returncode == 0
    r = run("split", tmp_path / "m.pdf", "-o", tmp_path / "s", "--mode", "every", "--every", "25"); assert r.returncode == 0
    r = run("reorder", fx / "english_50p.pdf", "-o", tmp_path / "r.pdf", "--order", "50-1"); assert r.returncode == 0
    r = run("compress", fx / "photos_large.pdf", "-o", tmp_path / "c.pdf", "--preset", "strong"); assert r.returncode == 0
    r = run("totext", fx / "arabic_reportlab.pdf"); assert source_lines()[1] in r.stdout
    r = run("todocx", fx / "arabic_reportlab.pdf", "-o", tmp_path / "a.docx"); assert r.returncode == 0
    r = run("protect", fx / "english_50p.pdf", "-o", tmp_path / "p.pdf", "--user-password", "x1"); assert r.returncode == 0
    r = run("unlock", tmp_path / "p.pdf", "-o", tmp_path / "u.pdf", "--password", "bad")
    assert r.returncode == 2 and "wrong_password" in r.stderr
    r = run("sign", fx / "english_50p.pdf", "-o", tmp_path / "g.pdf", "--text", "تمت المراجعة"); assert r.returncode == 0
    r = run("info", fx / "not_a_pdf.pdf"); assert r.returncode == 2 and "bad_pdf" in r.stderr


def test_truncated_pdf_is_clean_error(fx, tmp_path):
    import subprocess, sys
    from conftest import ROOT
    bad = tmp_path / "trunc.pdf"
    bad.write_bytes((fx / "english_50p.pdf").read_bytes()[:20000])
    r = subprocess.run([sys.executable, "-m", "waraq", "info", str(bad)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 2 and "error[bad_pdf]" in r.stderr and "Traceback" not in r.stderr
