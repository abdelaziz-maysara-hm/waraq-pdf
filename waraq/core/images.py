"""Images -> PDF (ReportLab BSD + Pillow HPND)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .errors import WaraqError
from .util import safe_write_bytes

PAGE_SIZES_PT = {
    "a4": (595.2756, 841.8898),
    "letter": (612.0, 792.0),
}
SUPPORTED = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}


def _prepare(path):
    """Return (reader_source, width_px, height_px, dpi) honouring EXIF rotation."""
    from PIL import Image, ImageOps
    from reportlab.lib.utils import ImageReader

    p = Path(path)
    if p.suffix.lower() not in SUPPORTED:
        raise WaraqError(f"Unsupported image: {p.name}", "bad_image", path=str(p))
    try:
        im = Image.open(p)
        im.load()
    except Exception as e:
        raise WaraqError(f"Cannot read image {p.name}: {e}", "bad_image", path=str(p))
    dpi = im.info.get("dpi", (96, 96))[0] or 96
    try:
        dpi = float(dpi)
    except Exception:
        dpi = 96.0
    if dpi < 30:
        dpi = 96.0
    orientation = 1
    try:
        orientation = im.getexif().get(0x0112, 1)
    except Exception:
        pass
    if im.format == "JPEG" and orientation in (1, None) and im.mode in ("RGB", "L"):
        # pass the original JPEG bytes through untouched (no quality loss)
        return ImageReader(str(p)), im.width, im.height, dpi
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if im.format == "JPEG" or (p.suffix.lower() in (".jpg", ".jpeg")):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=92)
        buf.seek(0)
        return ImageReader(buf), im.width, im.height, dpi
    return ImageReader(im), im.width, im.height, dpi


def images_to_pdf(images: Sequence, dst, page_size: str = "fit", margin_mm: float = 0.0,
                  progress: Optional[Callable[[int, int], None]] = None) -> int:
    """Put each image on its own page.

    page_size="fit" makes each page exactly the image size (at its DPI);
    "a4"/"letter" fit the image inside the page, portrait or landscape to
    match the image.
    """
    from reportlab.pdfgen import canvas

    if not images:
        raise WaraqError("No images selected", "no_input")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setCreator("Waraq PDF")
    margin = margin_mm * 72 / 25.4
    for k, path in enumerate(images, 1):
        src, w, h, dpi = _prepare(path)
        iw, ih = w * 72.0 / dpi, h * 72.0 / dpi
        if page_size == "fit":
            pw, ph = iw + 2 * margin, ih + 2 * margin
            dw, dh = iw, ih
        else:
            pw, ph = PAGE_SIZES_PT[page_size.lower()]
            if iw > ih:
                pw, ph = ph, pw
            s = min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih)
            dw, dh = iw * s, ih * s
        c.setPageSize((pw, ph))
        c.drawImage(src, (pw - dw) / 2, (ph - dh) / 2, dw, dh)
        c.showPage()
        if progress:
            progress(k, len(images))
    c.save()
    safe_write_bytes(dst, buf.getvalue())
    return len(images)
