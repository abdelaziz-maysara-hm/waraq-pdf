"""Compress PDFs by downsampling/recompressing images (pikepdf + Pillow).

No Ghostscript (AGPL).  Text and vector content is never rasterised.
"""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

from .errors import WaraqError
from .util import safe_write_bytes

PRESETS = {
    # name: (max long side in px, JPEG quality)
    "light": (2400, 85),
    "balanced": (1600, 70),
    "strong": (1100, 50),
}


@dataclass
class CompressResult:
    before: int
    after: int
    images_total: int
    images_changed: int
    kept_original: bool

    @property
    def saved_ratio(self) -> float:
        return 0.0 if not self.before else 1.0 - self.after / self.before

    def as_dict(self):
        d = asdict(self)
        d["saved_ratio"] = round(self.saved_ratio, 4)
        return d


def _recompress_image(pdf, obj, max_px: int, quality: int) -> bool:
    import pikepdf
    from PIL import Image
    from pikepdf import Name, PdfImage

    if obj.get("/ImageMask", False):
        return False
    if "/Mask" in obj and isinstance(obj.Mask, pikepdf.Array):
        return False  # colour-key masking would break after JPEG
    if int(obj.get("/BitsPerComponent", 8)) != 8:
        return False
    filt = obj.get("/Filter")
    filters = [str(f) for f in (filt if isinstance(filt, pikepdf.Array) else [filt] if filt else [])]
    if any(f in ("/JBIG2Decode", "/CCITTFaxDecode", "/JPXDecode") for f in filters):
        return False
    try:
        pimg = PdfImage(obj)
        if pimg.colorspace not in ("/DeviceRGB", "/DeviceGray", "/ICCBased", "/CalRGB", "/CalGray"):
            return False
        im = pimg.as_pil_image()
    except Exception:
        return False
    if im.mode not in ("RGB", "L"):
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        else:
            return False  # CMYK etc: leave alone (colour shifts)
    old_len = len(obj.read_raw_bytes())
    w, h = im.size
    if max(w, h) < 64:
        return False
    if max(w, h) > max_px:
        s = max_px / max(w, h)
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=False)
    data = buf.getvalue()
    if len(data) >= old_len * 0.95:
        return False
    obj.write(data, filter=Name.DCTDecode)
    obj.Width, obj.Height = im.size
    obj.ColorSpace = Name.DeviceGray if im.mode == "L" else Name.DeviceRGB
    obj.BitsPerComponent = 8
    for k in ("/DecodeParms", "/Decode", "/SMaskInData"):
        if k in obj:
            del obj[k]
    return True


def compress(src, dst, preset: str = "balanced", password: Optional[str] = None,
             strip_metadata: bool = False,
             progress: Optional[Callable[[int, int], None]] = None) -> CompressResult:
    import pikepdf

    if preset not in PRESETS:
        raise WaraqError(f"unknown preset {preset}", "bad_preset")
    max_px, quality = PRESETS[preset]
    before = Path(src).stat().st_size
    try:
        pdf = pikepdf.open(str(src), password=password or "")
    except pikepdf.PasswordError:
        from .errors import NeedsPasswordError, WrongPasswordError
        raise (WrongPasswordError(str(src)) if password else NeedsPasswordError(str(src)))
    except pikepdf.PdfError as e:
        raise WaraqError(f"Not a valid PDF: {e}", "bad_pdf")
    seen = set()
    total = changed = 0
    with pdf:
        n = len(pdf.pages)
        for pi, page in enumerate(pdf.pages, 1):
            for _name, img in _iter_images(page):
                key = img.objgen
                if key in seen or key == (0, 0):
                    continue
                seen.add(key)
                total += 1
                if _recompress_image(pdf, img, max_px, quality):
                    changed += 1
            if progress:
                progress(pi, n)
        try:
            pdf.remove_unreferenced_resources()
        except Exception:
            pass
        if strip_metadata:
            try:
                del pdf.trailer.Info
            except Exception:
                pass
        buf = io.BytesIO()
        save_kw = dict(compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                       recompress_flate=(preset != "light"))
        if pdf.is_encrypted:
            save_kw["encryption"] = pikepdf.Encryption(owner=password or "", user=password or "", R=6)
        pdf.save(buf, **save_kw)
    data = buf.getvalue()
    if len(data) >= before:
        if Path(src).resolve() != Path(dst).resolve():
            shutil.copyfile(src, dst)
        return CompressResult(before, before, total, changed, True)
    safe_write_bytes(dst, data)
    return CompressResult(before, len(data), total, changed, False)


def _iter_images(page):
    """Yield image XObjects of a page, including inside Form XObjects."""
    import pikepdf

    stack = [page.obj.get("/Resources")]
    visited = set()
    while stack:
        res = stack.pop()
        if res is None or not isinstance(res, pikepdf.Dictionary):
            continue
        xobjs = res.get("/XObject")
        if not isinstance(xobjs, pikepdf.Dictionary):
            continue
        for name, x in xobjs.items():
            if not isinstance(x, pikepdf.Stream):
                continue
            if x.objgen in visited:
                continue
            visited.add(x.objgen)
            sub = x.get("/Subtype")
            if sub == "/Image":
                yield name, x
            elif sub == "/Form":
                stack.append(x.get("/Resources"))
