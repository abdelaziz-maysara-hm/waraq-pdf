"""Merge, split, rotate, delete, reorder (pypdf, BSD licence)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from pypdf import PdfWriter

from .errors import WaraqError
from .util import ensure_parent, flat_pages, open_reader, parse_ranges, same_file, write_pdf


def page_count(path, password: Optional[str] = None) -> int:
    return len(open_reader(path, password).pages)


def info(path, password: Optional[str] = None) -> dict:
    r = open_reader(path, password)
    encrypted = r.is_encrypted
    sizes = []
    for p in r.pages[:3]:
        box = p.mediabox
        sizes.append((round(float(box.width)), round(float(box.height))))
    meta = {}
    try:
        if r.metadata:
            meta = {k.lstrip("/"): str(v) for k, v in r.metadata.items()}
    except Exception:
        pass
    return {
        "pages": len(r.pages),
        "encrypted": encrypted,
        "first_page_sizes_pt": sizes,
        "metadata": meta,
        "bytes": Path(path).stat().st_size,
    }


def merge(inputs: Sequence[Union[str, Path, Tuple[str, Optional[str]]]], dst,
          passwords: Optional[Dict[str, str]] = None) -> int:
    """Merge PDFs in order. Each input may be ``path`` or ``(path, "1-3,7")``.

    Returns the page count of the result.
    """
    if not inputs:
        raise WaraqError("No input files", "no_input")
    passwords = passwords or {}
    w = PdfWriter()
    for item in inputs:
        if isinstance(item, (tuple, list)):
            path, spec = item[0], item[1]
        else:
            path, spec = item, None
        if same_file(path, dst):
            raise WaraqError("Output file is one of the inputs", "output_is_input")
        r = open_reader(path, passwords.get(str(path)))
        idx = flat_pages(spec, len(r.pages))
        for i in idx:
            w.add_page(r.pages[i])
    n = len(w.pages)
    write_pdf(w, dst)
    return n


def split(src, out_dir, mode: str = "each", ranges: Optional[str] = None,
          every: int = 1, password: Optional[str] = None, stem: Optional[str] = None) -> List[Path]:
    """Split a PDF.

    mode="each"   -> one file per page
    mode="every"  -> chunks of ``every`` pages
    mode="ranges" -> one file per comma-separated range ("1-3,4-9")
    mode="extract"-> one file containing all pages in ``ranges``
    """
    r = open_reader(src, password)
    n = len(r.pages)
    stem = stem or Path(src).stem
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if mode == "each":
        groups = [[i] for i in range(n)]
    elif mode == "every":
        if every < 1:
            raise WaraqError("every must be >= 1", "bad_range")
        groups = [list(range(i, min(i + every, n))) for i in range(0, n, every)]
    elif mode == "ranges":
        groups = parse_ranges(ranges or "", n)
    elif mode == "extract":
        groups = [flat_pages(ranges, n)]
    else:
        raise WaraqError(f"unknown split mode {mode}", "bad_mode")
    width = len(str(n))
    paths = []
    for g in groups:
        w = PdfWriter()
        for i in g:
            w.add_page(r.pages[i])
        if len(g) == 1:
            name = f"{stem}_p{g[0] + 1:0{width}d}.pdf"
        else:
            name = f"{stem}_p{g[0] + 1:0{width}d}-{g[-1] + 1:0{width}d}.pdf"
        if mode == "extract":
            name = f"{stem}_extract.pdf"
        p = out / name
        write_pdf(w, p)
        paths.append(p)
    return paths


@dataclass
class PageOp:
    """One page of the output: source page index (0-based) + extra rotation."""
    index: int
    rotate: int = 0


def organize(src, dst, ops: Sequence[PageOp], password: Optional[str] = None) -> int:
    """Write ``dst`` with pages in the order/rotation given by ``ops``.

    This single primitive powers rotate, delete and reorder.
    """
    if not ops:
        raise WaraqError("The result would have no pages", "no_pages")
    r = open_reader(src, password)
    n = len(r.pages)
    w = PdfWriter()
    for op in ops:
        if not 0 <= op.index < n:
            raise WaraqError(f"page {op.index + 1} does not exist", "bad_range")
        if op.rotate % 90:
            raise WaraqError("rotation must be a multiple of 90", "bad_rotation")
        page = w.add_page(r.pages[op.index])
        if op.rotate % 360:
            page.rotate(op.rotate % 360)
    write_pdf(w, dst)
    return len(w.pages)


def rotate(src, dst, angle: int, pages: Optional[str] = None, password: Optional[str] = None) -> int:
    n = page_count(src, password)
    sel = set(flat_pages(pages, n))
    return organize(src, dst, [PageOp(i, angle if i in sel else 0) for i in range(n)], password)


def delete(src, dst, pages: str, password: Optional[str] = None) -> int:
    n = page_count(src, password)
    gone = set(flat_pages(pages, n))
    keep = [PageOp(i) for i in range(n) if i not in gone]
    return organize(src, dst, keep, password)


def reorder(src, dst, order: str, password: Optional[str] = None) -> int:
    """``order`` like "3,1,2" or "5-1" (reverse ranges allowed)."""
    n = page_count(src, password)
    idx: List[int] = []
    for part in [p.strip() for p in order.replace("،", ",").split(",") if p.strip()]:
        if "-" in part:
            a, b = [int(x) for x in part.split("-", 1)]
            step = 1 if b >= a else -1
            idx.extend(range(a - 1, b - 1 + step, step))
        else:
            idx.append(int(part) - 1)
    return organize(src, dst, [PageOp(i) for i in idx], password)


def effective_rotations(path, password: Optional[str] = None) -> List[int]:
    r = open_reader(path, password)
    return [int(p.get("/Rotate", 0) or 0) % 360 for p in r.pages]
