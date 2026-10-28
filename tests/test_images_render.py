from PIL import Image
from pypdf import PdfReader

from waraq.core import images, render


def test_images_to_pdf_fit(fx, tmp_path):
    imgs = sorted((fx / "images").iterdir())
    out = tmp_path / "i.pdf"
    assert images.images_to_pdf(imgs, out) == len(imgs)
    r = PdfReader(str(out))
    sizes = {p.name: Image.open(p).size for p in imgs}
    for page, p in zip(r.pages, imgs):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        iw, ih = sizes[p.name]
        if p.name == "phone_rotated.jpg":  # EXIF orientation 6 -> displayed rotated
            iw, ih = ih, iw
        assert abs(w / h - iw / ih) < 0.02, p.name


def test_images_to_pdf_a4_margin(fx, tmp_path):
    out = tmp_path / "a4.pdf"
    images.images_to_pdf([fx / "images" / "landscape.jpg"], out, page_size="a4", margin_mm=10)
    page = PdfReader(str(out)).pages[0]
    assert round(float(page.mediabox.width)) in (595, 842)


def test_exif_and_transparency_rendered(fx, tmp_path):
    out = tmp_path / "t.pdf"
    images.images_to_pdf([fx / "images" / "transparent.png", fx / "images" / "phone_rotated.jpg"], out)
    pngs = render.pdf_to_images(out, tmp_path / "png", dpi=50)
    im = Image.open(pngs[0]).convert("RGB")
    assert im.getpixel((1, 1))[0] > 240  # transparent corner became white, not black
    im2 = Image.open(pngs[1])
    assert im2.height > im2.width


def test_pdf_to_images(fx, tmp_path):
    out = render.pdf_to_images(fx / "english_50p.pdf", tmp_path, dpi=72, fmt="jpg", pages="1-3")
    assert len(out) == 3 and all(p.suffix == ".jpg" for p in out)
    im = Image.open(out[0])
    assert abs(im.width - 595) < 3 or abs(im.width - 612) < 3


def test_thumbnails(fx):
    th = render.thumbnails(fx / "rotated90.pdf", max_px=120)
    assert all(max(t.size) <= 120 for t in th)
    # rotated pages render landscape-ish (portrait source rotated 90)
    assert th[0].width > th[0].height
