import pytest
from PIL import Image

from waraq.core import render, sign
from waraq.core.errors import WaraqError


def _ink_bbox(png, ref_png):
    """Bounding box of pixels that differ from the unsigned page."""
    from PIL import ImageChops
    a = Image.open(png).convert("L")
    b = Image.open(ref_png).convert("L")
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > 40 else 0)
    return diff.getbbox(), a.size


@pytest.mark.parametrize("position", ["bottom-right", "bottom-left", "top-right", "center"])
def test_signature_position_pixels(fx, tmp_path, position):
    src = fx / "english_50p.pdf"
    out = tmp_path / "s.pdf"
    pl = sign.stamp(src, out, image=fx / "signature.jpg", pages="last", position=position,
                    width=144, remove_white=True)
    assert len(pl) == 1 and pl[0].page == 50
    p = pl[0]
    ref = render.pdf_to_images(src, tmp_path / "ref", dpi=72, pages="50")[0]
    got = render.pdf_to_images(out, tmp_path / "got", dpi=72, pages="50")[0]
    bbox, (W, H) = _ink_bbox(got, ref)
    assert bbox, "nothing was drawn"
    # expected box in image coords (y flipped)
    ex0, ey0, ex1, ey1 = p.x, H - (p.y + p.height), p.x + p.width, H - p.y
    assert bbox[0] >= ex0 - 3 and bbox[2] <= ex1 + 3, (bbox, (ex0, ex1))
    assert bbox[1] >= ey0 - 3 and bbox[3] <= ey1 + 3, (bbox, (ey0, ey1))
    assert abs(p.width - 144) < 0.01
    if position == "bottom-right":
        assert ex1 == pytest.approx(W - 36, abs=1) and ey1 == pytest.approx(H - 36, abs=1)


def test_stamp_arabic_text_all_pages(fx, tmp_path):
    out = tmp_path / "t.pdf"
    pl = sign.stamp(fx / "arabic_reportlab.pdf", out, text="معتمد - ورق 2026", pages="all", position="top-left")
    assert len(pl) == 2
    from waraq.core.extract import extract_pages
    texts = [b.text for b in extract_pages(out)[0].blocks]
    assert any("معتمد - ورق 2026" in t for t in texts), texts


def test_stamp_on_rotated_page_is_upright_and_inside(fx, tmp_path):
    out = tmp_path / "r.pdf"
    pl = sign.stamp(fx / "rotated90.pdf", out, image=fx / "signature.jpg", pages="first",
                    position="bottom-right", width=120)
    got = render.pdf_to_images(out, tmp_path / "g", dpi=72, pages="1")[0]
    ref = render.pdf_to_images(fx / "rotated90.pdf", tmp_path / "r", dpi=72, pages="1")[0]
    bbox, (W, H) = _ink_bbox(got, ref)
    assert W > H  # displayed landscape
    p = pl[0]
    assert bbox[0] >= p.x - 3 and bbox[2] <= p.x + p.width + 3
    assert bbox[3] <= H - p.y + 3
    # signature is wider than tall when upright
    assert (bbox[2] - bbox[0]) > (bbox[3] - bbox[1])


def test_stamp_requires_something(fx, tmp_path):
    with pytest.raises(WaraqError):
        sign.stamp(fx / "english_50p.pdf", tmp_path / "x.pdf")
