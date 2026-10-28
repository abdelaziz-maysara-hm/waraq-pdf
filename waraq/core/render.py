"""Rendering pages to images with pypdfium2 (Apache-2.0 / BSD-3)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from .errors import NeedsPasswordError, WaraqError, WrongPasswordError
from .util import flat_pages


def open_pdfium(path, password: Optional[str] = None):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(str(path), password=password)
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg:
            if password:
                raise WrongPasswordError(str(path))
            raise NeedsPasswordError(str(path))
        raise WaraqError(f"Cannot open {path}: {e}", "bad_pdf", path=str(path))


def render_page(doc, index: int, dpi: float = 150, max_px: Optional[int] = None):
    """Return a PIL image of page ``index``."""
    page = doc[index]
    scale = dpi / 72.0
    if max_px:
        w, h = page.get_size()
        scale = min(scale, max_px / max(w, h))
    bitmap = page.render(scale=scale, rotation=0)
    img = bitmap.to_pil()
    page.close()
    return img


def thumbnails(path, max_px: int = 180, password: Optional[str] = None,
               progress: Optional[Callable[[int, int], None]] = None) -> List:
    doc = open_pdfium(path, password)
    out = []
    n = len(doc)
    for i in range(n):
        out.append(render_page(doc, i, dpi=72, max_px=max_px))
        if progress:
            progress(i + 1, n)
    doc.close()
    return out


def pdf_to_images(src, out_dir, dpi: int = 150, fmt: str = "png", pages: Optional[str] = None,
                  password: Optional[str] = None, jpeg_quality: int = 90,
                  progress: Optional[Callable[[int, int], None]] = None) -> List[Path]:
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("png", "jpg", "jpeg"):
        raise WaraqError(f"unsupported image format {fmt}", "bad_format")
    doc = open_pdfium(src, password)
    n = len(doc)
    idx = flat_pages(pages, n)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    width = len(str(n))
    paths = []
    for k, i in enumerate(idx, 1):
        img = render_page(doc, i, dpi=dpi)
        p = out / f"{Path(src).stem}_p{i + 1:0{width}d}.{'jpg' if fmt != 'png' else 'png'}"
        if fmt == "png":
            img.save(p, "PNG", optimize=False)
        else:
            img.convert("RGB").save(p, "JPEG", quality=jpeg_quality, dpi=(dpi, dpi))
        paths.append(p)
        if progress:
            progress(k, len(idx))
    doc.close()
    return paths
