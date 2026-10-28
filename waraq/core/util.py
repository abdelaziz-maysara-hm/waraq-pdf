from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Sequence

from .errors import NeedsPasswordError, WaraqError, WrongPasswordError


def parse_ranges(spec: str, page_count: int) -> List[List[int]]:
    """Parse "1-3, 5, 8-" into groups of 0-based page indexes.

    Accepts Arabic-Indic digits, the Arabic comma "،" and "last"/"آخر".
    Raises WaraqError for out-of-range or malformed input.
    """
    if spec is None:
        raise WaraqError("empty page range", "bad_range")
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹،–—", "01234567890123456789,--")
    s = spec.translate(trans).strip().lower()
    s = s.replace("last", str(page_count)).replace("آخر", str(page_count)).replace("اخر", str(page_count))
    if not s or s in ("all", "الكل", "*"):
        return [list(range(page_count))]
    groups: List[List[int]] = []
    for part in [p.strip() for p in s.split(",") if p.strip()]:
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
        elif re.fullmatch(r"\d+", part):
            a = b = int(part)
        else:
            raise WaraqError(f"bad page range: {part!r}", "bad_range", part=part)
        if a < 1 or b > page_count or a > b:
            raise WaraqError(f"page range {part!r} outside 1-{page_count}", "bad_range", part=part)
        groups.append(list(range(a - 1, b)))
    if not groups:
        raise WaraqError("empty page range", "bad_range")
    return groups


def flat_pages(spec: Optional[str], page_count: int) -> List[int]:
    if spec is None or str(spec).strip() == "":
        return list(range(page_count))
    out: List[int] = []
    for g in parse_ranges(spec, page_count):
        out.extend(g)
    return out


def open_reader(path, password: Optional[str] = None):
    """Open a PDF with pypdf, decrypting it when a password is given."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError  # PdfStreamError is a subclass

    try:
        r = PdfReader(str(path))
    except FileNotFoundError:
        raise WaraqError(f"File not found: {path}", "not_found", path=str(path))
    except IsADirectoryError:
        raise WaraqError(f"Not a file: {path}", "not_found", path=str(path))
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as e:
        raise WaraqError(f"Not a valid PDF: {path} ({e})", "bad_pdf", path=str(path))
    if r.is_encrypted:
        if password is None:
            # some PDFs only have an owner password (empty user password)
            try:
                if r.decrypt(""):
                    return r
            except Exception:
                pass
            raise NeedsPasswordError(str(path))
        try:
            ok = r.decrypt(password)
        except Exception:
            ok = 0
        if not ok:
            raise WrongPasswordError(str(path))
    try:
        len(r.pages)  # pypdf parses lazily; surface broken files here
    except Exception as e:
        raise WaraqError(f"Not a valid PDF: {path} ({e})", "bad_pdf", path=str(path))
    return r


def ensure_parent(path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def safe_write_bytes(path, data: bytes) -> None:
    """Write via a temp file so a crash never leaves a half-written PDF."""
    p = ensure_parent(path)
    tmp = p.with_name(p.name + ".waraq-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)


def write_pdf(writer, path) -> None:
    import io

    buf = io.BytesIO()
    writer.write(buf)
    safe_write_bytes(path, buf.getvalue())


def same_file(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return False


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return str(n)
