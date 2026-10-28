"""Shared widgets and the Panel base class."""
from __future__ import annotations

import gc
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import i18n
from .i18n import t, ui
from ..core.errors import NeedsPasswordError, WaraqError, WrongPasswordError


def side():
    return "right" if i18n.is_rtl() else "left"


def far_side():
    return "left" if i18n.is_rtl() else "right"


def anchor():
    return "e" if i18n.is_rtl() else "w"


def justify():
    return "right" if i18n.is_rtl() else "left"


class PasswordDialog(ctk.CTkToplevel):
    def __init__(self, master, name):
        super().__init__(master)
        self.title(i18n.raw("ask_pw_title"))
        self.result = None
        self.resizable(False, False)
        ctk.CTkLabel(self, text=t("ask_pw", name=name), wraplength=360, justify=justify(),
                     font=master.app_font).pack(padx=20, pady=(20, 8), anchor=anchor())
        self.entry = ctk.CTkEntry(self, show="•", width=300, font=master.app_font)
        self.entry.pack(padx=20, pady=6)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=20, pady=(8, 20), fill="x")
        ctk.CTkButton(row, text=t("ok"), width=100, command=self._ok, font=master.app_font).pack(side=far_side(), padx=4)
        ctk.CTkButton(row, text=t("cancel"), width=100, fg_color="gray40", command=self.destroy,
                      font=master.app_font).pack(side=far_side(), padx=4)
        self.entry.bind("<Return>", lambda e: self._ok())
        self.after(50, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.entry.focus_set()
        except Exception:
            pass

    def _ok(self):
        self.result = self.entry.get()
        self.destroy()


class Panel(ctk.CTkFrame):
    """Base class of a tool page.

    All actions accept explicit paths so the GUI can be driven by tests
    without native dialogs.
    """
    title_key = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.font = app.app_font
        self.bold = app.bold_font
        self.status_var = ctk.StringVar(value="")
        head = ctk.CTkLabel(self, text=t(self.title_key), font=app.title_font)
        head.pack(anchor=anchor(), padx=20, pady=(18, 8))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20)
        self.build()
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=(4, 14))
        self.progress = ctk.CTkProgressBar(foot, height=8)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(0, 6))
        self.status = ctk.CTkLabel(foot, textvariable=self.status_var, font=self.font, wraplength=640,
                                   justify=justify(), anchor=anchor())
        self.status.pack(fill="x")

    # ---- building helpers ------------------------------------------------
    def row(self, parent=None, pady=6):
        f = ctk.CTkFrame(parent or self.body, fg_color="transparent")
        f.pack(fill="x", pady=pady)
        return f

    def label(self, parent, key, **kw):
        lab = ctk.CTkLabel(parent, text=t(key, **kw), font=self.font)
        lab.pack(side=side(), padx=(0, 8) if not i18n.is_rtl() else (8, 0))
        return lab

    def button(self, parent, key, cmd, primary=False, **kw):
        b = ctk.CTkButton(parent, text=t(key), command=cmd, font=self.bold if primary else self.font,
                          height=36 if primary else 30, **kw)
        b.pack(side=side(), padx=4)
        return b

    def entry(self, parent, width=120, placeholder_key=None, show=None):
        e = ctk.CTkEntry(parent, width=width, font=self.font, justify=justify(), show=show,
                         placeholder_text=t(placeholder_key) if placeholder_key else None)
        e.pack(side=side(), padx=4)
        return e

    def file_row(self, key="pdf_file", state_key="pdf", types=(("PDF", "*.pdf"),), on_change=None):
        r = self.row()
        self.label(r, key)
        var = ctk.StringVar(value=self.app.store.get(state_key, ""))
        ent = ctk.CTkEntry(r, textvariable=var, font=self.font, width=420)

        def browse():
            p = filedialog.askopenfilename(filetypes=list(types) + [("*", "*.*")],
                                           initialdir=self.app.settings.get("last_dir") or None)
            if p:
                set_path(p)

        def set_path(p):
            var.set(str(p))
            self.app.store[state_key] = str(p)
            self.app.settings["last_dir"] = str(Path(p).parent)
            if on_change:
                on_change(str(p))

        ctk.CTkButton(r, text=t("browse"), width=90, command=browse, font=self.font).pack(side=side(), padx=4)
        ent.pack(side=side(), padx=4, fill="x", expand=True)
        var.set_path = set_path  # type: ignore[attr-defined]
        return var

    # ---- dialogs (overridable by tests) ----------------------------------
    def ask_save(self, default_name, ext, kinds):
        if self.app.test_answers:
            return self.app.test_answers.pop(0)
        return filedialog.asksaveasfilename(defaultextension=ext, initialfile=default_name,
                                            filetypes=kinds,
                                            initialdir=self.app.settings.get("last_dir") or None) or None

    def ask_dir(self):
        if self.app.test_answers:
            return self.app.test_answers.pop(0)
        return filedialog.askdirectory(initialdir=self.app.settings.get("last_dir") or None) or None

    def password_for(self, path):
        """Return (ok, password) - asks the user if the file is protected."""
        from ..core.util import open_reader

        path = str(path)
        pw = self.app.passwords.get(path)
        while True:
            try:
                open_reader(path, pw)
                if pw is not None:
                    self.app.passwords[path] = pw
                return True, pw
            except (NeedsPasswordError, WrongPasswordError) as e:
                if isinstance(e, WrongPasswordError):
                    self.set_status(i18n.error_text(e), error=True)
                if path in self.app.test_passwords:
                    pw = self.app.test_passwords.pop(path)
                    continue
                d = PasswordDialog(self.app, Path(path).name)
                self.app.wait_window(d)
                if d.result is None:
                    return False, None
                pw = d.result
            except WaraqError as e:
                self.set_status(i18n.error_text(e), error=True)
                return False, None

    # ---- status / background work ----------------------------------------
    def set_status(self, text, error=False):
        self.status_var.set(text)
        self.status.configure(text_color=("#b00020", "#ff6b6b") if error else ("gray10", "gray90"))

    def run_task(self, fn, done=None):
        """Run ``fn(progress)`` in a worker thread; ``done(result)`` on the UI thread."""
        if self.app.busy:
            return
        # Tk objects (PhotoImage) must only be destroyed on the UI thread. A
        # garbage collection inside the worker thread can run their __del__
        # there and dead-lock Tk, so collect now and pause the cyclic GC
        # while the worker runs.
        gc.collect()
        gc.disable()
        self.app.set_busy(True)
        self.progress.set(0)
        self.set_status(t("working"))
        q = self.app.events

        def progress(i, n):
            q.put(("progress", self, i / max(n, 1)))

        def work():
            try:
                res = fn(progress)
                q.put(("done", self, (True, res, done)))
            except Exception as e:  # noqa: BLE001
                if not isinstance(e, WaraqError):
                    traceback.print_exc()
                q.put(("done", self, (False, e, done)))

        threading.Thread(target=work, daemon=True).start()

    def on_done(self, payload):
        ok, res, done = payload
        gc.enable()
        self.app.set_busy(False)
        self.progress.set(1 if ok else 0)
        if not ok:
            self.set_status(i18n.error_text(res), error=True)
            self.app.last_error = res
            return
        self.app.last_error = None
        if done:
            done(res)
        else:
            self.set_status(t("done"))

    def saved(self, path, extra=""):
        # the path goes on its own line so right-to-left text never reorders it
        msg = t("saved_to", path="").rstrip() + "\n" + str(path)
        if extra:
            msg = extra + "\n" + msg
        self.set_status(msg)
        self.app.last_output = path


def open_folder(path):
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass
