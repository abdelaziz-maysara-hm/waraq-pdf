"""Main window."""
from __future__ import annotations

import queue
import sys
import tkinter.font as tkfont

import customtkinter as ctk

from . import i18n, settings
from .i18n import t
from .panels import PANELS
from .. import __version__

ICONS = {"merge": "⊕", "split": "✂", "organize": "▦", "images": "🖼", "compress": "⇲", "convert": "W",
         "ocr": "👁", "sign": "✍", "security": "🔒"}


class App(ctk.CTk):
    def __init__(self, lang=None, theme=None):
        super().__init__()
        self.settings = settings.load()
        if lang:
            self.settings["lang"] = lang
        if theme:
            self.settings["theme"] = theme
        i18n.set_lang(self.settings["lang"])
        if self.settings.get("shaping") is not None:
            i18n.set_shaping(self.settings["shaping"])
        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme("blue")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.store = {}
        self.passwords = {}
        self.test_answers = []    # tests put output paths here instead of dialogs
        self.test_passwords = {}
        self.busy = False
        self.last_output = None
        self.last_error = None
        self.events: "queue.Queue" = queue.Queue()
        self._pick_fonts()
        self.current = "merge"
        self.panels = {}
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build()
        self._pump_id = self.after(40, self._pump)

    def _pick_fonts(self):
        fams = set(tkfont.families(self))
        prefs = ["Segoe UI", "Tahoma"] if sys.platform == "win32" else ["Cairo", "Noto Sans Arabic", "DejaVu Sans"]
        fam = next((f for f in prefs if f in fams), "TkDefaultFont")
        text_prefs = ["Arial", "Segoe UI"] if sys.platform == "win32" else ["Noto Naskh Arabic", "Amiri", "DejaVu Sans"]
        tfam = next((f for f in text_prefs if f in fams), fam)
        self.app_font = ctk.CTkFont(family=fam, size=14)
        self.bold_font = ctk.CTkFont(family=fam, size=14, weight="bold")
        self.title_font = ctk.CTkFont(family=fam, size=22, weight="bold")
        self.text_font = ctk.CTkFont(family=tfam, size=16)

    # ------------------------------------------------------------------
    def build(self):
        for w in self.winfo_children():
            w.destroy()
        self.title(i18n.raw("app_title"))
        rtl = i18n.is_rtl()
        self.grid_rowconfigure(0, weight=1)
        side_col, main_col = (1, 0) if rtl else (0, 1)
        self.grid_columnconfigure(side_col, weight=0, minsize=230)
        self.grid_columnconfigure(main_col, weight=1)
        bar = ctk.CTkFrame(self, width=230, corner_radius=0)
        bar.grid(row=0, column=side_col, sticky="nsew")
        bar.grid_propagate(False)
        ctk.CTkLabel(bar, text=t("app_title"), font=self.title_font).pack(pady=(20, 0))
        ctk.CTkLabel(bar, text=t("tagline"), font=ctk.CTkFont(family=self.app_font.cget("family"), size=11),
                     text_color="gray60").pack(pady=(0, 14))
        self.nav = {}
        for key, _cls in PANELS:
            b = ctk.CTkButton(bar, text=i18n.with_icon(ICONS[key], i18n.raw("tool_" + key)),
                              anchor="e" if rtl else "w", height=38, corner_radius=8, font=self.app_font,
                              fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray25"), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav[key] = b
        bottom = ctk.CTkFrame(bar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=10, pady=12)
        ctk.CTkButton(bottom, text=t("lang_toggle"), command=self.toggle_lang, font=self.app_font,
                      height=32).pack(fill="x", pady=3)
        self.theme_switch = ctk.CTkSegmentedButton(bottom, values=["☀", "☾"], command=self._theme,
                                                   font=self.app_font)
        self.theme_switch.set("☾" if ctk.get_appearance_mode() == "Dark" else "☀")
        self.theme_switch.pack(fill="x", pady=3)
        ctk.CTkLabel(bottom, text=t("about", v=__version__), font=ctk.CTkFont(size=10), text_color="gray55",
                     wraplength=200, justify="right" if rtl else "left").pack(pady=(6, 0))
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray95", "gray12"))
        self.main.grid(row=0, column=main_col, sticky="nsew")
        self.panels = {}
        self.show(self.current)

    def show(self, key):
        self.current = key
        for k, b in self.nav.items():
            b.configure(fg_color=("#3a7ebf", "#1f538d") if k == key else "transparent",
                        text_color=("white" if k == key else ("gray10", "gray90")))
        for p in self.panels.values():
            p.pack_forget()
        if key not in self.panels:
            cls = dict(PANELS)[key]
            self.panels[key] = cls(self.main, self)
        self.panels[key].pack(fill="both", expand=True)
        return self.panels[key]

    def toggle_lang(self):
        self.settings["lang"] = "en" if i18n.is_rtl() else "ar"
        i18n.set_lang(self.settings["lang"])
        settings.save(self.settings)
        self.build()

    def _theme(self, v):
        mode = "dark" if v == "☾" else "light"
        self.settings["theme"] = mode
        ctk.set_appearance_mode(mode)
        settings.save(self.settings)

    def set_busy(self, b):
        self.busy = b
        self.configure(cursor="watch" if b else "")

    def _pump(self):
        try:
            while True:
                kind, panel, data = self.events.get_nowait()
                if kind == "progress":
                    panel.progress.set(data)
                elif kind == "done":
                    panel.on_done(data)
        except queue.Empty:
            pass
        self._pump_id = self.after(40, self._pump)

    def destroy(self):
        try:
            self.after_cancel(self._pump_id)
        except Exception:
            pass
        super().destroy()

    def wait_idle(self, timeout=120):
        """Test helper: process events until the background task is finished."""
        import time

        end = time.time() + timeout
        while time.time() < end:
            self.update()
            if not self.busy and self.events.empty():
                self.update()
                return True
            time.sleep(0.02)
        return False

    def on_close(self):
        settings.save(self.settings)
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
