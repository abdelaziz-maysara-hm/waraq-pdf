# Licence — to be decided by the owner

No licence has been chosen for Waraq's own code yet, so for now all rights are
reserved. Pick one before publishing. Common choices are MIT or Apache-2.0 (permissive) and
GPL-3.0 (copyleft). Then add a `LICENSE` file.

All dependencies were picked so that any of those choices stays possible.
**No AGPL code is used.** PyMuPDF and Ghostscript were deliberately avoided.

| component | licence | notes |
|---|---|---|
| pypdf | BSD-3-Clause | |
| pikepdf (+ qpdf) | MPL-2.0 (qpdf: Apache-2.0) | MPL is file-level copyleft; using it unmodified is fine |
| pypdfium2 (+ PDFium) | Apache-2.0 / BSD-3-Clause | rendering, thumbnails |
| pdfminer.six | MIT | glyph positions |
| python-docx | MIT | |
| Pillow | MIT-CMU (HPND) | |
| reportlab | BSD-3-Clause | |
| customtkinter | MIT | |
| arabic-reshaper | MIT | |
| python-bidi | LGPL-3.0 | used as a separate, replaceable module. In a PyInstaller one-file exe, LGPL compliance is best met by also offering the source/object files or building in one-folder mode |
| winrt (pywinrt) | MIT | Windows OCR |
| Tesseract (optional, not bundled) | Apache-2.0 | |
| Amiri font (bundled in `waraq/assets/fonts`) | SIL OFL 1.1 | may be bundled; keep the OFL text with it and don't sell the font by itself |
