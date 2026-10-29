# Licences

Waraq PDF's own code is released under the **MIT License** (see [LICENSE](LICENSE)).

The third-party components below keep their own licences.
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
| python-bidi | LGPL-3.0 | used as a separate, replaceable module. The Windows build is a PyInstaller one-file exe. python-bidi is unmodified and its source is at https://github.com/MeirKriheli/python-bidi; to replace it, rebuild from this repository with your own copy (all build steps are in `.github/workflows/build-windows.yml`) |
| winrt (pywinrt) | MIT | Windows OCR |
| Tesseract (optional, not bundled) | Apache-2.0 | |
| Amiri font (bundled in `waraq/assets/fonts`) | SIL OFL 1.1 | may be bundled; keep the OFL text (`OFL-Amiri.txt`) with it and don't sell the font by itself |
| Noto Sans / Noto Sans Arabic (bundled) | SIL OFL 1.1 | text in free-text boxes and form values; OFL text in `waraq/assets/fonts/OFL-Noto.txt` |
| tkinterdnd2 (+ tkdnd) | MIT (tkdnd: BSD-style) | drag and drop of files onto the window |
