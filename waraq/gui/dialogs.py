"""Small modal dialogs used by the viewer/editor."""
from __future__ import annotations

import customtkinter as ctk

from . import i18n
from .i18n import t


def _center(win, master):
    try:
        win.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - win.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass


class TextDialog(ctk.CTkToplevel):
    """Multi-line text entry with a live preview rendered exactly like the PDF output.

    (Tk on Linux cannot shape Arabic while typing; the preview shows the
    real result.)"""

    def __init__(self, master, app, text="", size=14.0, family="naskh", title_key="text_title",
                 box=(240, 80)):
        super().__init__(master)
        self.app = app
        self.title(i18n.raw(title_key))
        self.result = None
        self.size_v = size
        self.family = family
        self.box = box
        self._job = None
        self._img = None
        rtl = i18n.is_rtl()
        side = "right" if rtl else "left"
        self.tb = ctk.CTkTextbox(self, width=440, height=120, font=app.text_font, wrap="word")
        self.tb.pack(padx=14, pady=(14, 6), fill="both", expand=True)
        if text:
            self.tb.insert("1.0", text)
        try:
            self.tb._textbox.tag_configure("rtl", justify="right")
            if rtl:
                self.tb._textbox.tag_add("rtl", "1.0", "end")
        except Exception:
            pass
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14)
        ctk.CTkLabel(row, text=t("font_size"), font=app.app_font).pack(side=side, padx=4)
        self.size_menu = ctk.CTkOptionMenu(row, values=[str(s) for s in (8, 10, 12, 14, 16, 18, 20, 24, 28, 36, 48)],
                                           width=70, command=lambda v: self._changed(), font=app.app_font)
        self.size_menu.set(str(int(size)) if float(size).is_integer() else str(size))
        self.size_menu.pack(side=side, padx=4)
        ctk.CTkLabel(row, text=t("font_family"), font=app.app_font).pack(side=side, padx=4)
        self.fam_opts = {t("font_naskh"): "naskh", t("font_sans"): "sans"}
        self.fam_menu = ctk.CTkOptionMenu(row, values=list(self.fam_opts), width=140,
                                          command=lambda v: self._changed(), font=app.app_font)
        self.fam_menu.set([k for k, v in self.fam_opts.items() if v == family][0])
        self.fam_menu.pack(side=side, padx=4)
        ctk.CTkLabel(self, text=t("text_preview"), font=app.app_font, text_color="gray55").pack(
            anchor="e" if rtl else "w", padx=14, pady=(8, 0))
        self.prev = ctk.CTkLabel(self, text="", fg_color="white", corner_radius=4, width=440, height=90)
        self.prev.pack(padx=14, pady=4)
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(6, 14))
        far = "left" if rtl else "right"
        ctk.CTkButton(btns, text=t("ok"), width=100, command=self._ok, font=app.app_font).pack(side=far, padx=4)
        ctk.CTkButton(btns, text=t("cancel"), width=100, fg_color="gray40", command=self.destroy,
                      font=app.app_font).pack(side=far, padx=4)
        self.tb.bind("<KeyRelease>", lambda e: self._changed())
        self.bind("<Control-Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self._changed()
        _center(self, master)
        self.after(60, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.tb.focus_set()
        except Exception:
            pass

    def get_text(self):
        return self.tb.get("1.0", "end").rstrip("\n")

    def _changed(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(150, self._render)

    def _render(self):
        self._job = None
        try:
            import pypdfium2 as pdfium
            from ..core.textlayout import text_box_pdf

            w, h = self.box
            data = text_box_pdf(w, h, self.get_text(), family=self.fam_opts.get(self.fam_menu.get(), "naskh"),
                                size=float(self.size_menu.get()))
            doc = pdfium.PdfDocument(data)
            pg = doc[0]
            sc = min(1.6, 430 / max(w, 1))
            im = pg.render(scale=sc).to_pil()
            pg.close()
            doc.close()
            if im.height > 160:
                im = im.crop((0, 0, im.width, 160))
            self._img = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.prev.configure(image=self._img)
        except Exception:
            pass

    def _ok(self):
        self.result = {"text": self.get_text(), "size": float(self.size_menu.get()),
                       "family": self.fam_opts.get(self.fam_menu.get(), "naskh")}
        self.destroy()


class AskDialog(ctk.CTkToplevel):
    """Question with up to three buttons; ``result`` is the chosen key or None."""

    def __init__(self, master, app, title, message, buttons):
        super().__init__(master)
        self.title(title)
        self.result = None
        self.resizable(False, False)
        rtl = i18n.is_rtl()
        ctk.CTkLabel(self, text=message, font=app.app_font, wraplength=420,
                     justify="right" if rtl else "left").pack(padx=20, pady=(20, 12))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))
        for key, label, primary in buttons:
            ctk.CTkButton(row, text=label, width=110, font=app.app_font,
                          **({} if primary else {"fg_color": "gray40"}),
                          command=lambda k=key: self._done(k)).pack(side="left" if rtl else "right", padx=4)
        self.bind("<Escape>", lambda e: self.destroy())
        _center(self, master)
        self.after(60, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass

    def _done(self, k):
        self.result = k
        self.destroy()
