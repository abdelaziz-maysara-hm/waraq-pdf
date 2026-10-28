"""The tool pages."""
from __future__ import annotations

import tempfile
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageOps

from . import i18n
from .base import Panel, anchor, far_side, justify, side
from .i18n import t, ui
from ..core import compress, images, pages, render, security, sign
from ..core.errors import WaraqError
from ..core.util import human_size

PDF_TYPES = [("PDF", "*.pdf")]
IMG_TYPES = [("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")]


def _stem(p):
    return Path(p).stem


# ==========================================================================
class FileList(ctk.CTkFrame):
    """Ordered list of files with add / remove / up / down."""

    def __init__(self, panel, types, add_key="add_files", height=220):
        super().__init__(panel.body, fg_color="transparent")
        self.panel, self.types = panel, types
        self.files = []
        self.selected = None
        bar = panel.row(self)
        panel.button(bar, add_key, self._browse)
        panel.button(bar, "up", lambda: self.move(-1))
        panel.button(bar, "down", lambda: self.move(1))
        panel.button(bar, "remove", self.remove)
        panel.button(bar, "clear", self.clear)
        self.box = ctk.CTkScrollableFrame(self, height=height)
        self.box.pack(fill="both", expand=True, pady=4)
        self.pack(fill="both", expand=True)

    def _browse(self):
        ps = filedialog.askopenfilenames(filetypes=list(self.types) + [("*", "*.*")])
        self.add(ps)

    def add(self, paths):
        for p in paths:
            self.files.append(str(p))
        self.refresh()

    def remove(self):
        if self.selected is not None and self.selected < len(self.files):
            self.files.pop(self.selected)
            self.selected = None
            self.refresh()

    def clear(self):
        self.files, self.selected = [], None
        self.refresh()

    def move(self, d):
        i = self.selected
        if i is None or not 0 <= i + d < len(self.files):
            return
        self.files[i], self.files[i + d] = self.files[i + d], self.files[i]
        self.selected = i + d
        self.refresh()

    def select(self, i):
        self.selected = i
        self.refresh()

    def refresh(self):
        for w in self.box.winfo_children():
            w.destroy()
        for i, p in enumerate(self.files):
            sel = i == self.selected
            b = ctk.CTkButton(self.box, text=f"{i + 1}.  {Path(p).name}", anchor=anchor(),
                              font=self.panel.font, height=28,
                              fg_color=("#3a7ebf", "#1f538d") if sel else "transparent",
                              text_color=("gray10", "gray90"), hover_color=("gray75", "gray30"),
                              command=lambda i=i: self.select(i))
            b.pack(fill="x", pady=1)


# ==========================================================================
class MergePanel(Panel):
    title_key = "tool_merge"

    def build(self):
        self.list = FileList(self, PDF_TYPES)
        r = self.row()
        self.button(r, "run_merge", self.run, primary=True)

    def run(self, out=None):
        files = self.list.files
        if not files:
            return self.set_status(t("need_two"), error=True)
        pw = {}
        for f in files:
            ok, p = self.password_for(f)
            if not ok:
                return
            if p is not None:
                pw[f] = p
        out = out or self.ask_save("merged.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        self.run_task(lambda prog: pages.merge(files, out, passwords=pw),
                      lambda n: self.saved(out, t("files_n", n=len(files), p=n)))


# ==========================================================================
class SplitPanel(Panel):
    title_key = "tool_split"

    def build(self):
        self.file = self.file_row()
        self.mode = ctk.StringVar(value="each")
        for key, val in (("split_each", "each"), ("split_every", "every"), ("split_ranges", "ranges"),
                         ("split_extract", "extract")):
            r = self.row(pady=2)
            ctk.CTkRadioButton(r, text=t(key), variable=self.mode, value=val, font=self.font).pack(side=side())
        r = self.row()
        self.label(r, "n_pages")
        self.every = self.entry(r, 60)
        self.every.insert(0, "2")
        self.label(r, "ranges")
        self.ranges = self.entry(r, 220, "pages_hint")
        r = self.row()
        self.button(r, "run_split", self.run, primary=True)

    def run(self, out_dir=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        out_dir = out_dir or self.ask_dir()
        if not out_dir:
            return
        mode, rng = self.mode.get(), self.ranges.get().strip() or None
        try:
            every = int(self.every.get() or 1)
        except ValueError:
            every = 1
        self.run_task(lambda prog: pages.split(src, out_dir, mode, rng, every, pw),
                      lambda paths: self.saved(out_dir, t("files_n", n=len(paths), p="-")))


# ==========================================================================
class OrganizePanel(Panel):
    """Thumbnails: click to select, rotate / delete / move, then save."""
    title_key = "tool_organize"
    THUMB = 130

    def build(self):
        self.file = self.file_row(on_change=lambda p: self.load())
        bar = self.row()
        self.button(bar, "load_pages", self.load)
        self.button(bar, "select_all", self.select_all)
        bar = self.row(pady=2)
        self.button(bar, "rot_left", lambda: self.rotate(-90))
        self.button(bar, "rot_right", lambda: self.rotate(90))
        self.button(bar, "del_page", self.delete)
        self.button(bar, "move_prev", lambda: self.move(-1))
        self.button(bar, "move_next", lambda: self.move(1))
        self.grid_box = ctk.CTkScrollableFrame(self.body, height=360)
        self.grid_box.pack(fill="both", expand=True, pady=4)
        r = self.row()
        self.button(r, "save_as", self.save, primary=True)
        self.pw = None
        self.thumbs = []     # PIL images by source index
        self.ops = []        # list of [index, rotation]
        self.sel = set()     # positions in ops
        self._ctk_images = []

    def load(self, path=None):
        src = path or self.file.get()
        if path:
            self.file.set_path(path)
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        self.pw = pw

        def work(prog):
            th = render.thumbnails(src, self.THUMB, pw, prog)
            return th, pages.effective_rotations(src, pw)

        def done(res):
            self.thumbs, _rots = res
            self.ops = [[i, 0] for i in range(len(self.thumbs))]
            self.sel = set()
            self.redraw()
            self.set_status(t("files_n", n=1, p=len(self.ops)))

        self.run_task(work, done)

    def redraw(self):
        for w in self.grid_box.winfo_children():
            w.destroy()
        self._ctk_images = []
        cols = 5
        for pos, (idx, rot) in enumerate(self.ops):
            im = self.thumbs[idx]
            if rot:
                im = im.rotate(-rot, expand=True)
            im = ImageOps.expand(im, border=1, fill="#888888")
            cimg = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self._ctk_images.append(cimg)
            selected = pos in self.sel
            tile = ctk.CTkFrame(self.grid_box, border_width=3,
                                border_color="#2fa4ff" if selected else ("gray80", "gray25"))
            r, c = divmod(pos, cols)
            if i18n.is_rtl():
                c = cols - 1 - c  # Arabic books run right to left
            tile.grid(row=r, column=c, padx=6, pady=6, sticky="n")
            lab = ctk.CTkLabel(tile, image=cimg, text="")
            lab.pack(padx=6, pady=(6, 2))
            cap = ctk.CTkLabel(tile, text=t("page_n", n=idx + 1) + (f"  {rot}°" if rot else ""), font=self.font)
            cap.pack(pady=(0, 4))
            for w in (tile, lab, cap):
                w.bind("<Button-1>", lambda e, p=pos: self.toggle(p))

    def toggle(self, pos):
        self.sel.symmetric_difference_update({pos})
        self.redraw()

    def select_all(self):
        self.sel = set(range(len(self.ops)))
        self.redraw()

    def rotate(self, d):
        for p in self.sel:
            self.ops[p][1] = (self.ops[p][1] + d) % 360
        self.redraw()

    def delete(self):
        self.ops = [o for p, o in enumerate(self.ops) if p not in self.sel]
        self.sel = set()
        self.redraw()

    def move(self, d):
        if len(self.sel) != 1:
            return
        p = next(iter(self.sel))
        q = p + d
        if 0 <= q < len(self.ops):
            self.ops[p], self.ops[q] = self.ops[q], self.ops[p]
            self.sel = {q}
            self.redraw()

    def save(self, out=None):
        src = self.file.get()
        if not self.ops:
            return self.set_status(t("err_no_pages"), error=True)
        out = out or self.ask_save(_stem(src) + "-organized.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        ops = [pages.PageOp(i, r) for i, r in self.ops]
        self.run_task(lambda prog: pages.organize(src, out, ops, self.pw),
                      lambda n: self.saved(out, t("files_n", n=1, p=n)))


# ==========================================================================
class ImagesPanel(Panel):
    title_key = "tool_images"

    def build(self):
        tabs = ctk.CTkSegmentedButton(self.body, values=[t("img_to_pdf"), t("pdf_to_img")],
                                      command=self._switch, font=self.font)
        tabs.pack(anchor=anchor(), pady=4)
        tabs.set(t("img_to_pdf"))
        self.tabs = tabs
        self.a = ctk.CTkFrame(self.body, fg_color="transparent")
        self.b = ctk.CTkFrame(self.body, fg_color="transparent")
        # images -> pdf
        body = self.body
        self.body = self.a
        self.list = FileList(self, IMG_TYPES, "add_images", height=180)
        r = self.row()
        self.label(r, "page_size")
        self.size = ctk.CTkOptionMenu(r, values=[t("size_fit"), "A4", "Letter"], font=self.font, width=150)
        self.size.pack(side=side(), padx=4)
        self.label(r, "margin")
        self.margin = self.entry(r, 60)
        self.margin.insert(0, "0")
        r = self.row()
        self.button(r, "make_pdf", self.to_pdf, primary=True)
        # pdf -> images
        self.body = self.b
        self.file = self.file_row()
        r = self.row()
        self.label(r, "dpi")
        self.dpi = ctk.CTkOptionMenu(r, values=["100", "150", "200", "300"], font=self.font, width=90)
        self.dpi.set("150")
        self.dpi.pack(side=side(), padx=4)
        self.label(r, "format")
        self.fmt = ctk.CTkOptionMenu(r, values=["png", "jpg"], font=self.font, width=90)
        self.fmt.pack(side=side(), padx=4)
        self.label(r, "pages_opt")
        self.pg = self.entry(r, 140, "pages_hint")
        r = self.row()
        self.button(r, "export_images", self.to_images, primary=True)
        self.body = body
        self.a.pack(fill="both", expand=True)

    def _switch(self, value):
        self.a.pack_forget()
        self.b.pack_forget()
        (self.a if value == t("img_to_pdf") else self.b).pack(fill="both", expand=True)

    def to_pdf(self, out=None):
        files = self.list.files
        if not files:
            return self.set_status(t("need_two"), error=True)
        out = out or self.ask_save("images.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        size = {0: "fit", 1: "a4", 2: "letter"}[[t("size_fit"), "A4", "Letter"].index(self.size.get())]
        try:
            margin = float(self.margin.get() or 0)
        except ValueError:
            margin = 0
        self.run_task(lambda prog: images.images_to_pdf(files, out, size, margin),
                      lambda n: self.saved(out, t("files_n", n=1, p=n)))

    def to_images(self, out_dir=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        out_dir = out_dir or self.ask_dir()
        if not out_dir:
            return
        dpi, fmt, pg = int(self.dpi.get()), self.fmt.get(), self.pg.get().strip() or None
        self.run_task(lambda prog: render.pdf_to_images(src, out_dir, dpi, fmt, pg, pw, progress=prog),
                      lambda ps: self.saved(out_dir, t("files_n", n=len(ps), p=len(ps))))


# ==========================================================================
class CompressPanel(Panel):
    title_key = "tool_compress"

    def build(self):
        self.file = self.file_row()
        self.preset = ctk.StringVar(value="balanced")
        r = self.row()
        self.label(r, "preset")
        for key in ("light", "balanced", "strong"):
            rr = self.row(pady=2)
            ctk.CTkRadioButton(rr, text=t("p_" + key), variable=self.preset, value=key,
                               font=self.font).pack(side=side(), padx=20)
        r = self.row()
        self.button(r, "run_compress", self.run, primary=True)
        self.result = ctk.CTkLabel(self.body, text="", font=self.app.title_font)
        self.result.pack(anchor=anchor(), pady=10)

    def run(self, out=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        out = out or self.ask_save(_stem(src) + "-small.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        preset = self.preset.get()

        def done(res):
            if res.kept_original:
                self.result.configure(text="")
                self.saved(out, t("compress_none"))
            else:
                self.result.configure(text=t("compress_result", before=human_size(res.before),
                                             after=human_size(res.after), pct=round(res.saved_ratio * 100)))
                self.saved(out)
            self.last_result = res

        self.run_task(lambda prog: compress.compress(src, out, preset, pw, progress=prog), done)


# ==========================================================================
class ConvertPanel(Panel):
    """PDF -> Word/TXT with an Arabic-correct preview before saving."""
    title_key = "tool_convert"

    def build(self):
        self.file = self.file_row()
        r = self.row()
        self.label(r, "ocr_mode")
        self.ocr_opts = {t("ocr_auto"): "auto", t("ocr_no"): "no", t("ocr_force"): "force"}
        self.ocr = ctk.CTkOptionMenu(r, values=list(self.ocr_opts), font=self.font, width=180)
        self.ocr.pack(side=side(), padx=4)
        self.label(r, "layout")
        self.layout_opts = {t("layout_par"): "paragraphs", t("layout_lines"): "lines"}
        self.layout = ctk.CTkOptionMenu(r, values=list(self.layout_opts), font=self.font, width=130)
        self.layout.pack(side=side(), padx=4)
        self.button(r, "extract", self.extract, primary=True)
        ctk.CTkLabel(self.body, text=t("preview"), font=self.bold).pack(anchor=anchor(), pady=(8, 2))
        self.text = ctk.CTkTextbox(self.body, height=300, font=self.app.text_font, wrap="word")
        self.text.pack(fill="both", expand=True)
        tb = self.text._textbox
        tb.tag_configure("rtl", justify="right")
        tb.tag_configure("ltr", justify="left")
        tb.tag_configure("page", justify="center", foreground="#7a8899")
        r = self.row()
        self.save_docx_btn = self.button(r, "save_docx", self.save_docx, primary=True, state="disabled")
        self.save_txt_btn = self.button(r, "save_txt", self.save_txt, state="disabled")
        self.pages = None

    def extract(self, path=None):
        if path:
            self.file.set_path(path)
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        mode = self.ocr_opts.get(self.ocr.get(), "auto")

        def work(prog):
            from ..core.extract import extract_pages
            from ..core import ocr as ocrmod

            pgs = extract_pages(src, password=pw, progress=prog)
            need = pgs if mode == "force" else [p for p in pgs if p.needs_ocr] if mode == "auto" else []
            info = {"ocr": 0, "scanned": len([p for p in pgs if p.needs_ocr])}
            if need:
                try:
                    eng = ocrmod.get_engine("auto")
                except WaraqError:
                    if mode == "force":
                        raise
                    return pgs, info
                spec = ",".join(str(p.number) for p in need)
                res = ocrmod.ocr_to_pages(src, engine=eng, pages=spec, password=pw, progress=prog)
                by = {}
                for p, o in zip(need, res):
                    o.number = p.number
                    by[p.number] = o
                pgs = [by.get(p.number, p) for p in pgs]
                info["ocr"] = len(need)
            return pgs, info

        self.run_task(work, self._show)

    def _show(self, res):
        self.pages, info = res
        tb = self.text._textbox
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        layout = self.layout_opts.get(self.layout.get(), "paragraphs")
        for p in self.pages:
            if len(self.pages) > 1:
                tb.insert("end", f"— {p.number} —\n", "page")
            for b in p.blocks:
                chunks = [l.text for l in b.lines] if layout == "lines" else [b.text]
                for c in chunks:
                    tb.insert("end", ui(c) + "\n", "rtl" if b.rtl else "ltr")
                tb.insert("end", "\n")
        self.text.configure(state="disabled")
        self.save_docx_btn.configure(state="normal")
        self.save_txt_btn.configure(state="normal")
        if info["ocr"]:
            self.set_status(t("scanned_note", n=info["ocr"]))
        elif info["scanned"]:
            self.set_status(t("scanned_no_ocr", n=info["scanned"]), error=True)
        else:
            self.set_status(t("done"))

    def save_docx(self, out=None):
        from ..core.extract import save_docx

        if not self.pages:
            return
        out = out or self.ask_save(_stem(self.file.get()) + ".docx", ".docx", [("Word", "*.docx")])
        if not out:
            return
        layout = self.layout_opts.get(self.layout.get(), "paragraphs")
        self.run_task(lambda prog: save_docx(self.pages, out, layout=layout), lambda r: self.saved(out))

    def save_txt(self, out=None):
        from ..core.extract import save_txt

        if not self.pages:
            return
        out = out or self.ask_save(_stem(self.file.get()) + ".txt", ".txt", [("Text", "*.txt")])
        if not out:
            return
        self.run_task(lambda prog: save_txt(self.pages, out), lambda r: self.saved(out))


# ==========================================================================
class OcrPanel(Panel):
    title_key = "tool_ocr"

    def build(self):
        from ..core import ocr as ocrmod

        self.file = self.file_row()
        r = self.row()
        self.label(r, "ocr_engine")
        try:
            eng = ocrmod.get_engine("auto")
            msg, err = t("ocr_status_ok", name=eng.name), False
            self.engine_name = eng.name
        except WaraqError:
            msg, err = t("ocr_status_missing"), True
            self.engine_name = None
        self.engine_label = ctk.CTkLabel(r, text=msg, font=self.font, wraplength=520, justify=justify(),
                                         text_color=("#b00020", "#ff6b6b") if err else None)
        self.engine_label.pack(side=side())
        r = self.row()
        self.button(r, "run_ocr", self.run, primary=True)
        self.search_btn = self.button(r, "searchable", self.searchable)
        if not ocrmod.TesseractEngine().available():
            self.search_btn.configure(state="disabled")
        self.text = ctk.CTkTextbox(self.body, height=300, font=self.app.text_font, wrap="word")
        self.text.pack(fill="both", expand=True, pady=6)
        self.text._textbox.tag_configure("rtl", justify="right")
        r = self.row()
        self.save_btn = self.button(r, "save_txt", self.save_txt, state="disabled")
        self.result = None

    def run(self, path=None):
        from ..core import ocr as ocrmod

        if path:
            self.file.set_path(path)
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return

        def done(texts):
            self.result = texts
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            for i, tx in enumerate(texts, 1):
                for line in tx.splitlines():
                    self.text._textbox.insert("end", ui(line) + "\n", "rtl")
                self.text._textbox.insert("end", "\n")
            self.text.configure(state="disabled")
            self.save_btn.configure(state="normal")
            self.set_status(t("done"))

        self.run_task(lambda prog: ocrmod.ocr_pdf(src, password=pw, progress=prog), done)

    def save_txt(self, out=None):
        if not self.result:
            return
        out = out or self.ask_save(_stem(self.file.get()) + "-ocr.txt", ".txt", [("Text", "*.txt")])
        if out:
            Path(out).write_text("\n\n".join(self.result) + "\n", encoding="utf-8-sig")
            self.saved(out)

    def searchable(self, out=None):
        from ..core import ocr as ocrmod

        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        out = out or self.ask_save(_stem(src) + "-searchable.pdf", ".pdf", PDF_TYPES)
        if out:
            self.run_task(lambda prog: ocrmod.make_searchable(src, out, password=pw, progress=prog),
                          lambda n: self.saved(out))


# ==========================================================================
class SignPanel(Panel):
    title_key = "tool_sign"
    POSITIONS = ["bottom-right", "bottom-left", "bottom-center", "top-right", "top-left", "top-center", "center"]

    def build(self):
        self.file = self.file_row()
        self.image = self.file_row("sig_image", "sig", IMG_TYPES)
        r = self.row()
        self.label(r, "sig_text")
        self.text = ctk.CTkEntry(r, width=300, font=self.font, justify=justify())
        self.text.pack(side=side(), padx=4)
        r = self.row()
        self.label(r, "sig_pages")
        self.page_opts = {t("pg_last"): "last", t("pg_first"): "first", t("pg_all"): "all"}
        self.pg = ctk.CTkOptionMenu(r, values=list(self.page_opts), font=self.font, width=130)
        self.pg.pack(side=side(), padx=4)
        self.label(r, "position")
        self.pos_opts = {t("pos_" + p): p for p in self.POSITIONS}
        self.pos = ctk.CTkOptionMenu(r, values=list(self.pos_opts), font=self.font, width=150)
        self.pos.pack(side=side(), padx=4)
        r = self.row()
        self.label(r, "width_pt")
        self.width = ctk.CTkSlider(r, from_=40, to=400, number_of_steps=36, width=200)
        self.width.set(150)
        self.width.pack(side=side(), padx=4)
        self.white = ctk.CTkCheckBox(r, text=t("remove_white"), font=self.font)
        self.white.select()
        self.white.pack(side=side(), padx=12)
        r = self.row()
        self.button(r, "preview_btn", self.preview)
        self.button(r, "run_sign", self.run, primary=True)
        self.prev = ctk.CTkLabel(self.body, text="")
        self.prev.pack(pady=6)
        self._img = None

    def _kw(self):
        return dict(image=self.image.get() or None, text=self.text.get().strip() or None,
                    pages=self.page_opts.get(self.pg.get(), "last"),
                    position=self.pos_opts.get(self.pos.get(), "bottom-right"),
                    width=float(self.width.get()), remove_white=bool(self.white.get()))

    def preview(self):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        kw = self._kw()

        def work(prog):
            tmp = Path(tempfile.mkdtemp()) / "p.pdf"
            pl = sign.stamp(src, tmp, password=pw, **kw)
            doc = render.open_pdfium(tmp, pw)
            im = render.render_page(doc, pl[0].page - 1, dpi=72, max_px=330)
            doc.close()
            return im

        def done(im):
            im = ImageOps.expand(im, border=1, fill="#888888")
            self._img = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.prev.configure(image=self._img)
            self.set_status(t("done"))

        self.run_task(work, done)

    def run(self, out=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        ok, pw = self.password_for(src)
        if not ok:
            return
        out = out or self.ask_save(_stem(src) + "-signed.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        kw = self._kw()
        self.run_task(lambda prog: sign.stamp(src, out, password=pw, **kw), lambda pl: self.saved(out))


# ==========================================================================
class SecurityPanel(Panel):
    title_key = "tool_security"

    def build(self):
        self.file = self.file_row()
        tabs = ctk.CTkSegmentedButton(self.body, values=[t("add_pw"), t("remove_pw")], command=self._switch,
                                      font=self.font)
        tabs.set(t("add_pw"))
        tabs.pack(anchor=anchor(), pady=6)
        self.a = ctk.CTkFrame(self.body, fg_color="transparent")
        self.b = ctk.CTkFrame(self.body, fg_color="transparent")
        body = self.body
        self.body = self.a
        r = self.row(); self.label(r, "new_pw"); self.pw1 = self.entry(r, 220, show="•")
        r = self.row(); self.label(r, "confirm_pw"); self.pw2 = self.entry(r, 220, show="•")
        r = self.row()
        self.allow_print = ctk.CTkCheckBox(r, text=t("allow_print"), font=self.font); self.allow_print.select()
        self.allow_print.pack(side=side(), padx=4)
        self.allow_copy = ctk.CTkCheckBox(r, text=t("allow_copy"), font=self.font); self.allow_copy.select()
        self.allow_copy.pack(side=side(), padx=12)
        r = self.row(); self.button(r, "run_protect", self.protect, primary=True)
        self.body = self.b
        r = self.row(); self.label(r, "current_pw"); self.pw_cur = self.entry(r, 220, show="•")
        r = self.row(); self.button(r, "run_unlock", self.unlock, primary=True)
        self.body = body
        ctk.CTkLabel(self.body, text=t("pw_note"), font=self.font, text_color="gray55",
                     wraplength=600, justify=justify()).pack(anchor=anchor(), side="bottom", pady=8)
        self.a.pack(fill="x")

    def _switch(self, v):
        self.a.pack_forget(); self.b.pack_forget()
        (self.a if v == t("add_pw") else self.b).pack(fill="x")

    def protect(self, out=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        p1, p2 = self.pw1.get(), self.pw2.get()
        if p1 != p2:
            return self.set_status(t("pw_mismatch"), error=True)
        ok, cur = self.password_for(src)
        if not ok:
            return
        out = out or self.ask_save(_stem(src) + "-protected.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        ap, ac = bool(self.allow_print.get()), bool(self.allow_copy.get())
        self.run_task(lambda prog: security.protect(src, out, p1, allow_print=ap, allow_copy=ac,
                                                    current_password=cur), lambda r: self.saved(out))

    def unlock(self, out=None):
        src = self.file.get()
        if not src:
            return self.set_status(t("need_file"), error=True)
        pw = self.pw_cur.get()
        out = out or self.ask_save(_stem(src) + "-unlocked.pdf", ".pdf", PDF_TYPES)
        if not out:
            return
        self.run_task(lambda prog: security.unlock(src, out, pw), lambda r: self.saved(out))


PANELS = [
    ("merge", MergePanel), ("split", SplitPanel), ("organize", OrganizePanel), ("images", ImagesPanel),
    ("compress", CompressPanel), ("convert", ConvertPanel), ("ocr", OcrPanel), ("sign", SignPanel),
    ("security", SecurityPanel),
]
