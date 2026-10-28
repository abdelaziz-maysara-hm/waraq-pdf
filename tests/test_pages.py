import pytest
from pypdf import PdfReader

from waraq.core import pages
from waraq.core.errors import WaraqError, NeedsPasswordError, WrongPasswordError
from waraq.core.util import parse_ranges, flat_pages


def first_text(path, i=0):
    return PdfReader(str(path)).pages[i].extract_text()


def test_parse_ranges():
    assert parse_ranges("1-3,5", 10) == [[0, 1, 2], [4]]
    assert parse_ranges("١-٣،٥", 10) == [[0, 1, 2], [4]]
    assert flat_pages("8-", 10) == [7, 8, 9]
    assert flat_pages("-2", 10) == [0, 1]
    assert flat_pages("last", 10) == [9]
    assert flat_pages("آخر", 10) == [9]
    for bad in ("0", "11", "3-x", "5-2-1"):
        with pytest.raises(WaraqError):
            flat_pages(bad, 10)


def test_merge_and_ranges(fx, tmp_path):
    out = tmp_path / "m.pdf"
    n = pages.merge([fx / "english_50p.pdf", (fx / "arabic_reportlab.pdf", None)], out)
    assert n == 52 == len(PdfReader(str(out)).pages)
    n = pages.merge([(fx / "english_50p.pdf", "1-3"), fx / "rotated90.pdf"], out)
    assert n == 3 + len(PdfReader(str(fx / "rotated90.pdf")).pages)


def test_merge_encrypted_needs_password(fx, tmp_path):
    with pytest.raises(NeedsPasswordError):
        pages.merge([fx / "encrypted_user123.pdf"], tmp_path / "x.pdf")
    n = pages.merge([fx / "encrypted_user123.pdf", fx / "english_50p.pdf"], tmp_path / "x.pdf",
                    passwords={str(fx / "encrypted_user123.pdf"): "user123"})
    assert n > 50


def test_split_modes(fx, tmp_path):
    each = pages.split(fx / "english_50p.pdf", tmp_path / "each", "each")
    assert len(each) == 50
    assert "Page 7" in first_text(each[6])
    every = pages.split(fx / "english_50p.pdf", tmp_path / "every", "every", every=20)
    assert [len(PdfReader(str(p)).pages) for p in every] == [20, 20, 10]
    rng = pages.split(fx / "english_50p.pdf", tmp_path / "r", "ranges", "1-2,10,48-50")
    assert [len(PdfReader(str(p)).pages) for p in rng] == [2, 1, 3]
    ext = pages.split(fx / "english_50p.pdf", tmp_path / "e", "extract", "1-2,10,48-50")
    assert len(ext) == 1 and len(PdfReader(str(ext[0])).pages) == 6


def test_rotate_delete_reorder(fx, tmp_path):
    src = fx / "english_50p.pdf"
    out = tmp_path / "r.pdf"
    pages.rotate(src, out, 90, "1,3")
    assert pages.effective_rotations(out)[:4] == [90, 0, 90, 0]
    pages.rotate(fx / "rotated90.pdf", out, 270)
    base = pages.effective_rotations(fx / "rotated90.pdf")
    assert pages.effective_rotations(out) == [(r + 270) % 360 for r in base]
    assert pages.delete(src, out, "2-50") == 1
    assert "Page 1" in first_text(out)
    with pytest.raises(WaraqError):
        pages.delete(src, out, "1-50")
    pages.reorder(src, out, "50-48,1")
    assert [("Page %d" % k) in first_text(out, i) for i, k in enumerate([50, 49, 48, 1])] == [True] * 4


def test_bad_inputs(fx, tmp_path):
    with pytest.raises(WaraqError) as e:
        pages.page_count(fx / "not_a_pdf.pdf")
    assert e.value.code == "bad_pdf"
    with pytest.raises(WaraqError):
        pages.page_count(tmp_path / "missing.pdf")
    with pytest.raises(WrongPasswordError):
        pages.page_count(fx / "encrypted_user123.pdf", "nope")


def test_output_same_as_input_is_safe(fx, tmp_path):
    import shutil
    p = tmp_path / "same.pdf"
    shutil.copy(fx / "english_50p.pdf", p)
    pages.delete(p, p, "1")
    assert len(PdfReader(str(p)).pages) == 49
