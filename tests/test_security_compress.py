import pytest
from pypdf import PdfReader

from waraq.core import compress, security, pages
from waraq.core.errors import NeedsPasswordError, WrongPasswordError, WaraqError


def test_password_roundtrip(fx, tmp_path):
    src = fx / "arabic_reportlab.pdf"
    enc = tmp_path / "enc.pdf"
    security.protect(src, enc, "سر123", owner_password="owner!", allow_print=False)
    assert security.is_encrypted(enc)
    with pytest.raises(NeedsPasswordError):
        pages.page_count(enc)
    with pytest.raises(WrongPasswordError):
        security.unlock(enc, tmp_path / "x.pdf", "wrong")
    r = PdfReader(str(enc)); r.decrypt("سر123")
    assert len(r.pages) == len(PdfReader(str(src)).pages)
    dec = tmp_path / "dec.pdf"
    security.unlock(enc, dec, "سر123")
    assert not security.is_encrypted(dec)
    assert PdfReader(str(dec)).pages[0].extract_text() == PdfReader(str(src)).pages[0].extract_text()
    # owner password also unlocks
    security.unlock(enc, tmp_path / "o.pdf", "owner!")


def test_unlock_fixture_and_not_encrypted(fx, tmp_path):
    security.unlock(fx / "encrypted_user123.pdf", tmp_path / "u.pdf", "user123")
    assert pages.page_count(tmp_path / "u.pdf") >= 1
    with pytest.raises(WaraqError) as e:
        security.unlock(fx / "english_50p.pdf", tmp_path / "n.pdf", "x")
    assert e.value.code == "not_encrypted"
    with pytest.raises(WaraqError):
        security.protect(fx / "english_50p.pdf", tmp_path / "e.pdf", "")


RATIOS = {}


@pytest.mark.parametrize("preset", ["light", "balanced", "strong"])
def test_compress_photos(fx, tmp_path, preset):
    src = fx / "photos_large.pdf"
    out = tmp_path / f"{preset}.pdf"
    res = compress.compress(src, out, preset)
    RATIOS[preset] = res.saved_ratio
    print(preset, res.as_dict())
    assert res.after == out.stat().st_size
    assert res.saved_ratio > 0.5
    assert pages.page_count(out) == pages.page_count(src)
    if len(RATIOS) == 3:
        assert RATIOS["light"] < RATIOS["balanced"] < RATIOS["strong"]


def test_compress_text_pdf_never_grows(fx, tmp_path):
    src = fx / "arabic_reportlab.pdf"
    res = compress.compress(src, tmp_path / "c.pdf", "strong")
    assert res.after <= res.before
    assert PdfReader(str(tmp_path / "c.pdf")).pages[0].extract_text()


def test_compress_encrypted(fx, tmp_path):
    with pytest.raises(NeedsPasswordError):
        compress.compress(fx / "encrypted_user123.pdf", tmp_path / "c.pdf")
    compress.compress(fx / "encrypted_user123.pdf", tmp_path / "c.pdf", password="user123")
