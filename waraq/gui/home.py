"""Start screen: open a file, tool tiles, recent files."""
from __future__ import annotations

import os
import time
from pathlib import Path

import customtkinter as ctk

from . import i18n
from .i18n import t

TILES = [
    ("view", "📖", "tool_view", "#2f7de1"),
    ("form", "▤", "tab_form", "#7b52d6"),
    ("convert", "W", "tool_convert", "#1f6fd1"),
    ("images", "🖼", "tool_images", "#d1731f"),
    ("compress", "⇲", "tool_compress", "#1f9d6b"),
    ("merge", "⊕", "tool_merge", "#d14a7b"),
    ("split", "✂", "tool_split", "#c0392b"),
    ("organize", "▦", "tool_organize", "#3a8f9e"),
    ("ocr", "👁", "tool_ocr", "#8e6b1f"),
    ("sign", "✍", "tool_sign", "#4a6bd1"),
    ("security", "🔒", "tool_security", "#555f6e"),
]


def _size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class HomeView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, corner_radius=0, fg_color=("gray95", "gray12"))
        self.app = app
        rtl = i18n.is_rtl()
        side = "right" if rtl else "left"
        anchor = "e" if rtl else "w"
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=6)
        top = ctk.CTkFrame(scroll, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 6))
        # big open card
        self.drop = ctk.CTkFrame(top, corner_radius=14, border_width=2, border_color=("#9bbbe6", "#2f5f9e"),
                                 fg_color=("#eaf2fd", "#1b2636"), height=150, width=330)
        self.drop.pack(side=side, padx=(0, 14) if not rtl else (14, 0))
        self.drop.pack_propagate(False)
        ctk.CTkLabel(self.drop, text="📄", font=ctk.CTkFont(size=40)).pack(pady=(14, 0))
        self.open_btn = ctk.CTkButton(self.drop, text=t("open_file"), font=app.bold_font, height=38, width=200,
                                      command=app.ask_open)
        self.open_btn.pack(pady=6)
        ctk.CTkLabel(self.drop, text=t("open_hint"), font=app.app_font, text_color="gray55").pack()
        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side=side, fill="both", expand=True)
        ctk.CTkLabel(brand, text=t("app_title"), font=ctk.CTkFont(family=app.app_font.cget("family"), size=30,
                                                                    weight="bold")).pack(anchor=anchor, pady=(18, 0))
        ctk.CTkLabel(brand, text=t("tagline"), font=app.app_font, text_color="gray55").pack(anchor=anchor)
        # tiles
        ctk.CTkLabel(scroll, text=t("hot_tools"), font=app.bold_font).pack(anchor=anchor, padx=16, pady=(14, 4))
        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=12)
        cols = 6
        self.tiles = {}
        for k, (key, icon, label, color) in enumerate(TILES):
            r, c = divmod(k, cols)
            if rtl:
                c = cols - 1 - c
            tile = ctk.CTkButton(grid, text=f"{icon}\n{t(label)}", width=150, height=78, corner_radius=12,
                                 font=app.app_font, fg_color=("white", "gray20"), text_color=("gray10", "gray92"),
                                 hover_color=("#dde9fb", "gray28"), border_width=1,
                                 border_color=("gray80", "gray30"),
                                 command=lambda key=key: self.tile(key))
            tile.grid(row=r, column=c, padx=5, pady=5, sticky="ew")
            stripe = ctk.CTkFrame(tile, height=4, width=40, fg_color=color, corner_radius=2)
            stripe.place(relx=0.5, rely=0.06, anchor="n")
            self.tiles[key] = tile
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1)
        # recent
        head = ctk.CTkFrame(scroll, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(18, 2))
        ctk.CTkLabel(head, text=t("recent"), font=app.bold_font).pack(side=side)
        ctk.CTkButton(head, text=t("recent_clear"), width=90, height=26, fg_color="transparent",
                      text_color=("gray20", "gray80"), border_width=1, border_color=("gray70", "gray35"),
                      command=self.clear_recent, font=app.app_font).pack(side="left" if rtl else "right")
        self.table = ctk.CTkFrame(scroll, corner_radius=10)
        self.table.pack(fill="x", padx=14, pady=(4, 14))
        self.fill_recent()

    def tile(self, key):
        if key == "view":
            self.app.ask_open()
        elif key == "form":
            self.app.ask_open(tab="tab_form")
        else:
            self.app.show(key)

    def fill_recent(self):
        for w in self.table.winfo_children():
            w.destroy()
        rtl = i18n.is_rtl()
        items = self.app.settings.get("recent") or []
        if not items:
            ctk.CTkLabel(self.table, text=t("recent_empty"), font=self.app.app_font, text_color="gray55").pack(
                pady=16)
            return
        cols = [(t("col_name"), 4), (t("col_opened"), 2), (t("col_size"), 1), ("", 0)]
        hdr = ctk.CTkFrame(self.table, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(6, 0))
        self._row_layout(hdr, [ctk.CTkLabel(hdr, text=c, font=self.app.bold_font, text_color="gray55")
                               for c, _ in cols], rtl)
        for it in items[:15]:
            p = Path(it["path"])
            exists = p.exists()
            try:
                size = _size(p.stat().st_size) if exists else "—"
            except OSError:
                size = "—"
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(it.get("ts", 0)))
            row = ctk.CTkFrame(self.table, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=1)
            name = ctk.CTkButton(row, text="📄  " + i18n.ui(p.name) if not rtl else i18n.ui(p.name) + "  📄",
                                 anchor="e" if rtl else "w", fg_color="transparent",
                                 text_color=("gray10", "gray90") if exists else "gray50",
                                 hover_color=("gray85", "gray25"), font=self.app.app_font, height=28,
                                 command=lambda p=str(p): self.app.open_pdf(p))
            folder = ctk.CTkLabel(row, text=when, font=self.app.app_font, text_color="gray55")
            sz = ctk.CTkLabel(row, text=size if exists else t("missing"), font=self.app.app_font,
                              text_color="gray55")
            rm = ctk.CTkButton(row, text="✕", width=28, height=24, fg_color="transparent",
                               text_color=("gray30", "gray70"), hover_color=("gray85", "gray25"),
                               command=lambda p=str(p): self.remove(p))
            self._row_layout(row, [name, folder, sz, rm], rtl)

    @staticmethod
    def _row_layout(row, widgets, rtl):
        weights = [4, 2, 1, 0]
        n = len(widgets)
        for k, (w, wt) in enumerate(zip(widgets, weights)):
            col = n - 1 - k if rtl else k
            row.grid_columnconfigure(col, weight=wt, uniform="c" if wt else None, minsize=40 if not wt else 0)
            w.grid(row=0, column=col, sticky="e" if rtl else "w", padx=4)

    def remove(self, path):
        self.app.settings["recent"] = [r for r in self.app.settings.get("recent", [])
                                       if os.path.normcase(r["path"]) != os.path.normcase(path)]
        self.app.save_settings()
        self.fill_recent()

    def clear_recent(self):
        self.app.settings["recent"] = []
        self.app.save_settings()
        self.fill_recent()
