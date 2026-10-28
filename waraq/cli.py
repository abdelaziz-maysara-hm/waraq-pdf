"""Command-line interface (also used by the automated tests).

    python -m waraq merge a.pdf b.pdf -o out.pdf
    python -m waraq todocx arabic.pdf -o arabic.docx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core.errors import WaraqError


def _p(msg):
    print(msg, flush=True)


def _utf8_streams():
    """Windows consoles/pipes default to a legacy code page (e.g. cp1252) that can't encode Arabic."""
    for s in (sys.stdout, sys.stderr):
        try:
            if s is not None and (s.encoding or "").lower().replace("-", "") != "utf8":
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _utf8_streams()
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    ap = argparse.ArgumentParser(prog="waraq", description="Waraq PDF - offline Arabic-first PDF toolbox")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--password", default=None, help="password of the input PDF (if any)")
        return sp

    sp = add("info", "show page count and metadata"); sp.add_argument("pdf")
    sp = add("merge", "merge PDFs"); sp.add_argument("pdfs", nargs="+"); sp.add_argument("-o", required=True)
    sp = add("split", "split a PDF"); sp.add_argument("pdf"); sp.add_argument("-o", required=True, help="output folder")
    sp.add_argument("--mode", choices=["each", "every", "ranges", "extract"], default="each")
    sp.add_argument("--ranges"); sp.add_argument("--every", type=int, default=1)
    sp = add("rotate", "rotate pages"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--angle", type=int, default=90); sp.add_argument("--pages")
    sp = add("delete", "delete pages"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--pages", required=True)
    sp = add("reorder", "reorder pages, e.g. 3,1,2 or 10-1"); sp.add_argument("pdf")
    sp.add_argument("-o", required=True); sp.add_argument("--order", required=True)
    sp = add("img2pdf", "images to PDF"); sp.add_argument("images", nargs="+"); sp.add_argument("-o", required=True)
    sp.add_argument("--page-size", default="fit", choices=["fit", "a4", "letter"]); sp.add_argument("--margin-mm", type=float, default=0)
    sp = add("pdf2img", "PDF pages to images"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--dpi", type=int, default=150); sp.add_argument("--format", default="png"); sp.add_argument("--pages")
    sp = add("compress", "compress a PDF"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--preset", default="balanced", choices=["light", "balanced", "strong"])
    sp = add("totext", "PDF to text (Arabic-safe)"); sp.add_argument("pdf"); sp.add_argument("-o")
    sp.add_argument("--ocr", choices=["no", "auto", "force"], default="auto")
    sp = add("todocx", "PDF to Word (Arabic-safe)"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--layout", choices=["paragraphs", "lines"], default="paragraphs")
    sp.add_argument("--ocr", choices=["no", "auto", "force"], default="auto")
    sp = add("ocr", "OCR a scanned PDF to text"); sp.add_argument("pdf"); sp.add_argument("-o")
    sp.add_argument("--engine", default="auto", choices=["auto", "windows", "tesseract"])
    sp.add_argument("--lang", default="ara+eng"); sp.add_argument("--dpi", type=int, default=300)
    sp.add_argument("--searchable", action="store_true", help="write a searchable PDF instead (Tesseract)")
    sp = add("sign", "stamp a signature image and/or text"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--image"); sp.add_argument("--text"); sp.add_argument("--pages", default="last")
    sp.add_argument("--position", default="bottom-right"); sp.add_argument("--width", type=float, default=150)
    sp.add_argument("--remove-white", action="store_true")
    sp = add("protect", "add a password"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)
    sp.add_argument("--user-password", required=True); sp.add_argument("--owner-password")
    sp.add_argument("--no-print", action="store_true"); sp.add_argument("--no-copy", action="store_true")
    sp = add("unlock", "remove a password you know"); sp.add_argument("pdf"); sp.add_argument("-o", required=True)

    a = ap.parse_args(argv)
    try:
        return _run(a)
    except WaraqError as e:
        print(f"error[{e.code}]: {e}", file=sys.stderr)
        return 2


def _pages_with_ocr(path, password, ocr_mode):
    from .core.extract import extract_pages
    from .core import ocr as ocrmod

    pages = extract_pages(path, password=password)
    need = [p for p in pages if p.needs_ocr] if ocr_mode == "auto" else pages if ocr_mode == "force" else []
    if need:
        try:
            eng = ocrmod.get_engine("auto")
        except WaraqError:
            if ocr_mode == "force":
                raise
            print("warning: scanned pages found but no OCR engine is installed", file=sys.stderr)
            return pages
        spec = ",".join(str(p.number) for p in need)
        ocr_pages = ocrmod.ocr_to_pages(path, engine=eng, pages=spec, password=password)
        by_num = {p.number: o for p, o in zip(need, ocr_pages)}
        for o, p in zip(ocr_pages, need):
            o.number = p.number
        pages = [by_num.get(p.number, p) for p in pages]
    return pages


def _run(a) -> int:
    from .core import compress, images, pages, render, security, sign, extract

    pw = getattr(a, "password", None)
    if a.cmd == "info":
        _p(json.dumps(pages.info(a.pdf, pw), ensure_ascii=False, indent=2))
    elif a.cmd == "merge":
        _p(f"pages: {pages.merge(a.pdfs, a.o)}")
    elif a.cmd == "split":
        for p in pages.split(a.pdf, a.o, a.mode, a.ranges, a.every, pw):
            _p(str(p))
    elif a.cmd == "rotate":
        _p(f"pages: {pages.rotate(a.pdf, a.o, a.angle, a.pages, pw)}")
    elif a.cmd == "delete":
        _p(f"pages: {pages.delete(a.pdf, a.o, a.pages, pw)}")
    elif a.cmd == "reorder":
        _p(f"pages: {pages.reorder(a.pdf, a.o, a.order, pw)}")
    elif a.cmd == "img2pdf":
        _p(f"pages: {images.images_to_pdf(a.images, a.o, a.page_size, a.margin_mm)}")
    elif a.cmd == "pdf2img":
        for p in render.pdf_to_images(a.pdf, a.o, a.dpi, a.format, a.pages, pw):
            _p(str(p))
    elif a.cmd == "compress":
        _p(json.dumps(compress.compress(a.pdf, a.o, a.preset, pw).as_dict()))
    elif a.cmd == "totext":
        pgs = _pages_with_ocr(a.pdf, pw, a.ocr)
        if a.o:
            extract.save_txt(pgs, a.o)
        else:
            sys.stdout.write(extract.pages_to_text(pgs))
    elif a.cmd == "todocx":
        pgs = _pages_with_ocr(a.pdf, pw, a.ocr)
        extract.save_docx(pgs, a.o, layout=a.layout)
        _p(a.o)
    elif a.cmd == "ocr":
        from .core import ocr as ocrmod

        if a.searchable:
            if not a.o:
                raise WaraqError("-o is required with --searchable", "no_output")
            _p(f"pages: {ocrmod.make_searchable(a.pdf, a.o, langs=a.lang, dpi=a.dpi, password=pw)}")
        else:
            eng = ocrmod.get_engine(a.engine, a.lang)
            texts = ocrmod.ocr_pdf(a.pdf, engine=eng, langs=a.lang, dpi=a.dpi, password=pw)
            text = "\n\n".join(texts) + "\n"
            if a.o:
                Path(a.o).write_text(text, encoding="utf-8-sig")
            else:
                sys.stdout.write(text)
    elif a.cmd == "sign":
        pl = sign.stamp(a.pdf, a.o, image=a.image, text=a.text, pages=a.pages, position=a.position,
                        width=a.width, remove_white=a.remove_white, password=pw)
        _p(json.dumps([p.__dict__ for p in pl]))
    elif a.cmd == "protect":
        security.protect(a.pdf, a.o, a.user_password, a.owner_password, allow_print=not a.no_print,
                         allow_copy=not a.no_copy, current_password=pw)
        _p(a.o)
    elif a.cmd == "unlock":
        if not pw:
            raise WaraqError("--password is required", "needs_password")
        security.unlock(a.pdf, a.o, pw)
        _p(a.o)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
