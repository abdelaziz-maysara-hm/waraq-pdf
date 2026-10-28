"""OCR for scanned PDFs, behind one small interface.

Engines
-------
* ``WindowsOcrEngine`` - Windows 10/11 built-in OCR (Windows.Media.Ocr)
  through the ``winrt`` Python projection.  Free, offline, no extra
  download except the Arabic language pack.  **Only works on Windows.**
* ``TesseractEngine`` - Tesseract 5 (Apache-2.0) command-line program with
  ``ara`` + ``eng`` data.  Works on every OS when Tesseract is installed (or
  bundled next to the app in a ``tesseract`` folder).

``get_engine("auto")`` prefers Windows OCR when it can read Arabic, then
Tesseract.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Protocol

from .errors import WaraqError
from .util import flat_pages


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def has_language(self, lang: str) -> bool: ...

    def recognize(self, image, langs: str = "ara+eng") -> str: ...


# --------------------------------------------------------------------------
# Tesseract
# --------------------------------------------------------------------------
class TesseractEngine:
    name = "tesseract"

    def __init__(self, cmd: Optional[str] = None):
        self.cmd = cmd or self._find()

    @staticmethod
    def _find() -> Optional[str]:
        env = os.environ.get("WARAQ_TESSERACT")
        if env and Path(env).exists():
            return env
        candidates = []
        base = Path(getattr(sys, "_MEIPASS", Path(sys.argv[0]).resolve().parent))
        exe = "tesseract.exe" if os.name == "nt" else "tesseract"
        candidates += [base / "tesseract" / exe, Path(sys.executable).parent / "tesseract" / exe]
        if os.name == "nt":
            for root in (os.environ.get("ProgramFiles", r"C:\\Program Files"),
                         os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"),
                         os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
                candidates.append(Path(root) / "Tesseract-OCR" / exe)
        for c in candidates:
            if c.exists():
                return str(c)
        return shutil.which("tesseract")

    def available(self) -> bool:
        return bool(self.cmd)

    def languages(self) -> List[str]:
        if not self.cmd:
            return []
        try:
            r = subprocess.run([self.cmd, "--list-langs"], capture_output=True, text=True,
                               timeout=30, **_no_window())
        except Exception:
            return []
        lines = (r.stdout or r.stderr).splitlines()
        return [l.strip() for l in lines[1:] if l.strip()]

    def has_language(self, lang: str) -> bool:
        return all(l in self.languages() for l in lang.split("+"))

    def recognize(self, image, langs: str = "ara+eng") -> str:
        if not self.cmd:
            raise WaraqError("Tesseract is not installed", "ocr_missing")
        buf = io.BytesIO()
        image.save(buf, "PNG")
        r = subprocess.run([self.cmd, "stdin", "stdout", "-l", langs, "--psm", "3"],
                           input=buf.getvalue(), capture_output=True, timeout=600, **_no_window())
        if r.returncode != 0:
            raise WaraqError(r.stderr.decode("utf-8", "replace")[:500], "ocr_failed")
        return _strip_bidi_controls(r.stdout.decode("utf-8", "replace"))

    def searchable_pdf_page(self, image, langs: str = "ara+eng", dpi: int = 300) -> bytes:
        """One-page PDF: the scan image + an invisible text layer."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "p.png"
            image.save(png, dpi=(dpi, dpi))
            base = Path(td) / "out"
            r = subprocess.run([self.cmd, str(png), str(base), "-l", langs, "--psm", "3", "pdf"],
                               capture_output=True, timeout=600, **_no_window())
            if r.returncode != 0:
                raise WaraqError(r.stderr.decode("utf-8", "replace")[:500], "ocr_failed")
            return (base.with_suffix(".pdf")).read_bytes()


def _strip_bidi_controls(text: str) -> str:
    for ch in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066",
               "\u2067", "\u2068", "\u2069", "\f"):
        text = text.replace(ch, "")
    return text


def _no_window():
    if os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


# --------------------------------------------------------------------------
# Windows built-in OCR  (NOT testable on Linux - see MANUAL.md)
# --------------------------------------------------------------------------
class WindowsOcrEngine:
    name = "windows"

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from winrt.windows.media.ocr import OcrEngine as _E  # noqa: F401
            return True
        except Exception:
            return False

    def _engine(self, lang: str):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine as WinOcr

        tag = {"ara": "ar", "eng": "en"}.get(lang, lang)
        language = Language(tag)
        if not WinOcr.is_language_supported(language):
            return None
        return WinOcr.try_create_from_language(language)

    def has_language(self, lang: str) -> bool:
        if not self.available():
            return False
        try:
            return all(self._engine(l) is not None for l in lang.split("+"))
        except Exception:
            return False

    def recognize(self, image, langs: str = "ara+eng") -> str:
        import asyncio

        first = langs.split("+")[0]
        engine = self._engine(first)
        if engine is None:
            raise WaraqError("Windows OCR language pack missing", "ocr_lang_missing", lang=first)
        return asyncio.run(self._recognize(engine, image))

    async def _recognize(self, engine, image) -> str:
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine as WinOcr
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        im = image.convert("RGB")
        limit = int(WinOcr.max_image_dimension)
        if max(im.size) > limit:
            s = limit / max(im.size)
            im = im.resize((int(im.width * s), int(im.height * s)))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(buf.getvalue())  # bytes is a buffer; a list is rejected by pywinrt
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            words = list(line.words)
            text = " ".join(w.text for w in words) if words else line.text
            # put Arabic words right-to-left by their position, independent of
            # the order the engine reports them in
            from .arabic import has_arabic
            if words and has_arabic(text):
                words.sort(key=lambda w: -w.bounding_rect.x)
                text = " ".join(w.text for w in words)
            lines.append(text)
        return "\n".join(lines)


ENGINES = {"windows": WindowsOcrEngine, "tesseract": TesseractEngine}


def get_engine(preference: str = "auto", langs: str = "ara+eng"):
    """Return a ready engine or raise WaraqError(code='ocr_missing')."""
    order = ["windows", "tesseract"] if preference == "auto" else [preference]
    for name in order:
        eng = ENGINES[name]()
        if eng.available() and eng.has_language(langs.split("+")[0]):
            return eng
    raise WaraqError("No OCR engine with Arabic is available", "ocr_missing")


def ocr_pdf(src, engine=None, langs: str = "ara+eng", dpi: int = 300, pages: Optional[str] = None,
            password: Optional[str] = None,
            progress: Optional[Callable[[int, int], None]] = None) -> List[str]:
    """OCR each selected page, returning one text string per page."""
    from .render import open_pdfium, render_page

    engine = engine or get_engine("auto", langs)
    doc = open_pdfium(src, password)
    idx = flat_pages(pages, len(doc))
    out = []
    for k, i in enumerate(idx, 1):
        img = render_page(doc, i, dpi=dpi).convert("L")
        out.append(engine.recognize(img, langs).strip())
        if progress:
            progress(k, len(idx))
    doc.close()
    return out


def ocr_to_pages(src, **kw):
    """OCR result wrapped as PageText objects (so Word/TXT export can reuse it)."""
    from .extract import Block, Line, PageText
    from .arabic import has_arabic

    texts = ocr_pdf(src, **kw)
    pages = []
    for n, t in enumerate(texts, 1):
        blocks = []
        para: List[Line] = []
        for raw in t.splitlines() + [""]:
            raw = raw.strip()
            if not raw:
                if para:
                    blocks.append(Block(para, any(l.rtl for l in para)))
                    para = []
                continue
            para.append(Line(raw, 0, 0, 0, 0, 12, has_arabic(raw)))
        pages.append(PageText(number=n, blocks=blocks, chars=len(t), ocr=True))
    return pages


def make_searchable(src, dst, engine: Optional[TesseractEngine] = None, langs: str = "ara+eng",
                    dpi: int = 300, password: Optional[str] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> int:
    """Tesseract only: write a PDF that looks the same but has selectable text."""
    from pypdf import PdfReader, PdfWriter

    from .render import open_pdfium, render_page
    from .util import write_pdf

    engine = engine or TesseractEngine()
    if not engine.available():
        raise WaraqError("Tesseract is not installed", "ocr_missing")
    doc = open_pdfium(src, password)
    w = PdfWriter()
    n = len(doc)
    for i in range(n):
        img = render_page(doc, i, dpi=dpi).convert("L")
        page_pdf = engine.searchable_pdf_page(img, langs, dpi)
        w.add_page(PdfReader(io.BytesIO(page_pdf)).pages[0])
        if progress:
            progress(i + 1, n)
    doc.close()
    write_pdf(w, dst)
    return n
