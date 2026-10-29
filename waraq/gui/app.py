"""Main window: a tab strip (Home + one tab per open PDF), the tool pages."""
from __future__ import annotations

import os
import queue
import sys
import time
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import i18n, settings
from .i18n import t
from .panels import PANELS
from .. import __version__

ICONS = {"merge": "⊕", "split": "✂", "organize": "▦", "images": "🖼", "compress": "⇲", "convert": "W",
         "ocr": "👁", "sign": "✍", "security": "🔒"}

try:  # drag & drop of files from Explorer / the file manager
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:  # pragma: no cover - optional
    _DND = False


class _Base(ctk.CTk, *( [TkinterDnD.DnDWrapper] if _DND else [])):
    pass


class App(_Base):
    def __init__(self, lang=None, theme=None, files=()):
        super().__init__()
        self.dnd = False
        if _DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd = True
            except Exception:
                self.dnd = False
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
        self.geometry("1200x780")
        self.minsize(960, 620)
        self.store = {}
        self.passwords = {}
        self.test_answers = []    # tests put output paths / answers here instead of dialogs
        self.test_passwords = {}
        self.busy = False
        self.last_output = None
        self.last_error = None
        self.last_screenshot = None
        self.events: "queue.Queue" = queue.Queue()
        self._pick_fonts()
        self.current = "home"     # "home", a tool key, or "doc"
        self.panels = {}
        self.docs = []            # [{"doc": Document, "view": DocView, "state": dict}]
        self.active = None        # active doc entry
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build()
        self._pump_id = self.after(40, self._pump)
        for f in files:
            self.after(50, lambda f=f: self.open_pdf(f))

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

    # ------------------------------------------------------------------ layout
    def build(self):
        for d in self.docs:
            if d.get("view") is not None:
                d["state"] = d["view"].view_state()
                d["tab"] = d["view"].ribbon_tab
                d["doc"] = d["view"].doc
                d["view"].detach()
                d["view"] = None
        for w in self.winfo_children():
            w.destroy()
        self.title(i18n.raw("app_title"))
        rtl = i18n.is_rtl()
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        # tab strip
        bar = ctk.CTkFrame(self, height=40, corner_radius=0, fg_color=("gray85", "gray17"))
        bar.grid(row=0, column=0, sticky="ew")
        self.topbar = bar
        side = "right" if rtl else "left"
        far = "left" if rtl else "right"
        self.tabstrip = ctk.CTkFrame(bar, fg_color="transparent")
        self.tabstrip.pack(side=side, fill="x", expand=True, padx=4, pady=4)
        ctk.CTkButton(bar, text=t("lang_toggle"), command=self.toggle_lang, font=self.app_font,
                      width=90, height=28).pack(side=far, padx=4)
        self.theme_switch = ctk.CTkSegmentedButton(bar, values=["☀", "☾"], command=self._theme,
                                                   font=self.app_font, width=70)
        self.theme_switch.set("☾" if ctk.get_appearance_mode() == "Dark" else "☀")
        self.theme_switch.pack(side=far, padx=4)
        self.body = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray95", "gray12"))
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        # tools page (side navigation + panel), as in 0.1
        self.tools = ctk.CTkFrame(self.body, corner_radius=0, fg_color="transparent")
        self.tools.grid_rowconfigure(0, weight=1)
        side_col, main_col = (1, 0) if rtl else (0, 1)
        self.tools.grid_columnconfigure(side_col, weight=0, minsize=230)
        self.tools.grid_columnconfigure(main_col, weight=1)
        nav = ctk.CTkFrame(self.tools, width=230, corner_radius=0)
        nav.grid(row=0, column=side_col, sticky="nsew")
        nav.grid_propagate(False)
        ctk.CTkButton(nav, text=i18n.with_icon("⌂", i18n.raw("home")), anchor="e" if rtl else "w", height=36,
                      font=self.bold_font, fg_color="transparent", text_color=("gray10", "gray90"),
                      hover_color=("gray75", "gray25"), command=self.show_home).pack(fill="x", padx=10, pady=(14, 8))
        self.nav = {}
        for key, _cls in PANELS:
            b = ctk.CTkButton(nav, text=i18n.with_icon(ICONS[key], i18n.raw("tool_" + key)),
                              anchor="e" if rtl else "w", height=38, corner_radius=8, font=self.app_font,
                              fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray25"), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav[key] = b
        ctk.CTkLabel(nav, text=t("about", v=__version__), font=ctk.CTkFont(size=10), text_color="gray55",
                     wraplength=200, justify="right" if rtl else "left").pack(side="bottom", pady=10)
        self.main = ctk.CTkFrame(self.tools, corner_radius=0, fg_color=("gray95", "gray12"))
        self.main.grid(row=0, column=main_col, sticky="nsew")
        self.panels = {}
        from .home import HomeView
        self.home = HomeView(self.body, self)
        self._setup_dnd()
        for d in self.docs:
            self._make_view(d)
        cur = self.current
        if cur == "doc" and self.active in self.docs:
            self.show_doc(self.active)
        elif cur not in ("home", "doc"):
            self.show(cur)
        else:
            self.show_home()

    def _setup_dnd(self):
        if not self.dnd:
            return
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            self.dnd = False

    def _on_drop(self, e):
        files = [f for f in self.tk.splitlist(e.data)]
        self.open_files(files)
        return e.action

    def open_files(self, files):
        pdfs = [f for f in files if str(f).lower().endswith(".pdf")]
        if not pdfs and files:
            self._home_msg(t("drop_not_pdf"))
        for f in pdfs:
            self.open_pdf(f)

    def _home_msg(self, text):
        try:
            self.home.open_btn.configure(text=text)
            self.after(2500, lambda: self.home.open_btn.configure(text=t("open_file")))
        except Exception:
            pass

    def _tabs(self):
        for w in self.tabstrip.winfo_children():
            w.destroy()
        rtl = i18n.is_rtl()
        side = "right" if rtl else "left"
        on = ("#3a7ebf", "#1f538d")
        home_on = self.current != "doc"
        ctk.CTkButton(self.tabstrip, text=i18n.with_icon("⌂", i18n.raw("home")), width=100, height=30,
                      font=self.app_font, corner_radius=8,
                      fg_color=on if home_on else "transparent",
                      text_color="white" if home_on else ("gray10", "gray90"),
                      command=self.show_home).pack(side=side, padx=2)
        for d in self.docs:
            act = self.current == "doc" and d is self.active
            fr = ctk.CTkFrame(self.tabstrip, corner_radius=8, fg_color=on if act else ("gray78", "gray24"))
            fr.pack(side=side, padx=2)
            name = d["doc"].name
            if len(name) > 26:
                name = name[:24] + "…"
            if d["doc"].dirty:
                name = "• " + name
            ctk.CTkButton(fr, text=i18n.ui(name), height=28, font=self.app_font, fg_color="transparent",
                          text_color="white" if act else ("gray10", "gray90"), hover_color=("gray70", "gray30"),
                          command=lambda d=d: self.show_doc(d)).pack(side=side, padx=(4, 0))
            ctk.CTkButton(fr, text="✕", width=24, height=24, fg_color="transparent",
                          text_color="white" if act else ("gray20", "gray80"), hover_color=("#d9534f", "#a33"),
                          command=lambda d=d: self.close_doc(d)).pack(side=side, padx=(0, 4))

    def _hide_all(self):
        self.home.grid_forget()
        self.tools.grid_forget()
        for d in self.docs:
            if d.get("view") is not None:
                d["view"].grid_forget()

    def show_home(self):
        self.current = "home"
        self._hide_all()
        self.home.fill_recent()
        self.home.grid(row=0, column=0, sticky="nsew")
        self._tabs()

    def show(self, key):
        """Show a tool page (kept compatible with 0.1 and its tests)."""
        self.current = key
        self._hide_all()
        self.tools.grid(row=0, column=0, sticky="nsew")
        for k, b in self.nav.items():
            b.configure(fg_color=("#3a7ebf", "#1f538d") if k == key else "transparent",
                        text_color=("white" if k == key else ("gray10", "gray90")))
        for p in self.panels.values():
            p.pack_forget()
        if key not in self.panels:
            cls = dict(PANELS)[key]
            self.panels[key] = cls(self.main, self)
        self.panels[key].pack(fill="both", expand=True)
        self._tabs()
        return self.panels[key]

    def open_tool(self, key, path=None):
        p = self.show(key)
        if path:
            if hasattr(p, "file"):
                p.file.set_path(path)
                for fn in ("load",):
                    if key == "organize" and hasattr(p, fn):
                        try:
                            p.load(path)
                        except Exception:
                            pass
            elif hasattr(p, "list"):
                p.list.add([path])
        return p

    # ------------------------------------------------------------------ documents
    def ask_open(self, tab=None):
        if self.test_answers:
            files = [self.test_answers.pop(0)]
        else:
            files = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf"), ("*", "*.*")],
                                                initialdir=self.settings.get("last_dir") or None)
        view = None
        for f in files or ():
            view = self.open_pdf(f, tab=tab)
        return view

    def ask_password(self, path):
        path = str(path)
        if path in self.test_passwords:
            return self.test_passwords.pop(path)
        from .base import PasswordDialog
        d = PasswordDialog(self, Path(path).name)
        self.wait_window(d)
        return d.result

    def open_pdf(self, path, password=None, tab=None):
        from ..core.document import Document
        from ..core.errors import NeedsPasswordError, WaraqError, WrongPasswordError

        path = str(Path(path).resolve()) if path else path
        for d in self.docs:
            if os.path.normcase(d["doc"].path) == os.path.normcase(path):
                self.show_doc(d)
                if tab:
                    d["view"].show_tab(tab)
                return d["view"]
        pw = password if password is not None else self.passwords.get(path)
        while True:
            try:
                doc = Document(path, pw)
                break
            except (NeedsPasswordError, WrongPasswordError):
                pw = self.ask_password(path)
                if pw is None:
                    return None
            except WaraqError as e:
                self.last_error = e
                self._home_msg(i18n.error_text(e))
                return None
            except Exception as e:  # noqa: BLE001
                self.last_error = e
                self._home_msg(t("open_failed"))
                return None
        if pw:
            self.passwords[path] = pw
        self.settings["last_dir"] = str(Path(path).parent)
        self.add_recent(path)
        d = {"doc": doc, "view": None, "state": None, "tab": tab}
        self.docs.append(d)
        self._make_view(d)
        self.show_doc(d)
        return d["view"]

    def _make_view(self, d):
        from .viewer import DocView
        v = DocView(self.body, self, d["doc"], d.get("state"))
        d["view"] = v
        if d.get("tab"):
            v.show_tab(d["tab"])

    def show_doc(self, d):
        self.current = "doc"
        self.active = d
        self._hide_all()
        d["view"].grid(row=0, column=0, sticky="nsew")
        self._tabs()
        self.title(f"{d['doc'].name} - {i18n.raw('app_title')}")
        d["view"].focus_canvas()

    @property
    def view(self):
        return self.active["view"] if self.active in self.docs else None

    def doc_title_changed(self, view):
        for d in self.docs:
            if d["view"] is view:
                d["doc"] = view.doc
        if self.current == "doc":
            self._tabs()

    def close_doc(self, d, ask=True):
        if d not in self.docs:
            return True
        v = d["view"]
        if ask and d["doc"].dirty:
            ans = self._ask_unsaved(d["doc"].name)
            if ans is None:
                return False
            if ans == "save" and not v.save():
                return False
        v.close()
        v.destroy()
        self.docs.remove(d)
        if self.active is d:
            self.active = self.docs[-1] if self.docs else None
        if self.current == "doc" and self.active:
            self.show_doc(self.active)
        else:
            self.show_home()
        return True

    def _ask_unsaved(self, name):
        if self.test_answers:
            return self.test_answers.pop(0)
        from .dialogs import AskDialog
        d = AskDialog(self, self, i18n.raw("unsaved_title"), t("unsaved_q", name=name),
                      [("save", t("yes_save"), True), ("discard", t("no_discard"), False),
                       (None, t("cancel"), False)])
        self.wait_window(d)
        return d.result

    def add_recent(self, path):
        path = str(path)
        items = [r for r in self.settings.get("recent", []) if os.path.normcase(r["path"]) != os.path.normcase(path)]
        items.insert(0, {"path": path, "ts": time.time()})
        self.settings["recent"] = items[:30]
        self.save_settings()

    def save_settings(self):
        settings.save(self.settings)

    # ------------------------------------------------------------------ misc
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
        for d in self.docs:
            if d.get("view") is not None:
                d["view"].apply_theme()

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
        for d in list(self.docs):
            try:
                d["view"].close()
            except Exception:
                pass
        self.docs = []
        super().destroy()

    def wait_idle(self, timeout=120):
        """Test helper: process events until the background task is finished."""
        end = time.time() + timeout
        while time.time() < end:
            self.update()
            if not self.busy and self.events.empty():
                self.update()
                return True
            time.sleep(0.02)
        return False

    def on_close(self):
        for d in list(self.docs):
            if d["doc"].dirty:
                self.show_doc(d)
                if not self.close_doc(d):
                    return
        settings.save(self.settings)
        self.destroy()


def main(files=()):
    app = App(files=files)
    app.mainloop()


if __name__ == "__main__":
    main(sys.argv[1:])
