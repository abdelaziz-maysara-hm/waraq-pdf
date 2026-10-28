"""Add / remove a password (pikepdf, MPL-2.0). No password cracking."""
from __future__ import annotations

import io
from typing import Optional

from .errors import NeedsPasswordError, WaraqError, WrongPasswordError
from .util import safe_write_bytes, same_file


def is_encrypted(path) -> bool:
    import pikepdf

    try:
        with pikepdf.open(str(path)) as pdf:
            return pdf.is_encrypted
    except pikepdf.PasswordError:
        return True


def _open(path, password: Optional[str]):
    import pikepdf

    try:
        return pikepdf.open(str(path), password=password or "")
    except pikepdf.PasswordError:
        if password:
            raise WrongPasswordError(str(path))
        raise NeedsPasswordError(str(path))
    except FileNotFoundError:
        raise WaraqError(f"File not found: {path}", "not_found")
    except pikepdf.PdfError as e:
        raise WaraqError(f"Not a valid PDF: {e}", "bad_pdf")


def protect(src, dst, user_password: str, owner_password: Optional[str] = None,
            allow_print: bool = True, allow_copy: bool = True, allow_edit: bool = True,
            current_password: Optional[str] = None) -> None:
    """Encrypt with AES-256. ``user_password`` is needed to open the file."""
    import pikepdf

    if not user_password:
        raise WaraqError("Password must not be empty", "empty_password")
    owner_password = owner_password or user_password
    perms = pikepdf.Permissions(
        print_lowres=allow_print, print_highres=allow_print,
        extract=allow_copy, accessibility=True,
        modify_annotation=allow_edit, modify_assembly=allow_edit,
        modify_form=allow_edit, modify_other=allow_edit,
    )
    with _open(src, current_password) as pdf:
        buf = io.BytesIO()
        pdf.save(buf, encryption=pikepdf.Encryption(owner=owner_password, user=user_password, R=6,
                                                   allow=perms))
    safe_write_bytes(dst, buf.getvalue())


def unlock(src, dst, password: str) -> None:
    """Remove encryption from a file whose password the user knows."""
    with _open(src, password) as pdf:
        if not pdf.is_encrypted:
            raise WaraqError("This PDF has no password", "not_encrypted")
        buf = io.BytesIO()
        pdf.save(buf)  # saving without `encryption=` writes an unencrypted file
    safe_write_bytes(dst, buf.getvalue())
