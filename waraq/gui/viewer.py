"""PDF viewer + editor tab (one per open document)."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import tkinter as tk
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import ImageChops, Image, ImageOps, ImageTk

from . import i18n, overlay
from .dialogs import TextDialog
from .i18n import t
from ..core import annots as A
from ..core import textsearch as TS
from ..core.document import Document
from ..core.errors import WaraqError

PX_PER_PT = 96 / 72          # 100 % = real size on a 96 dpi screen
ZOOMS = [10, 25, 33, 50, 67, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400]
GAP = 14
MARGIN = 16
SHAPE_TOOLS = ("rect", "ellipse", "line", "arrow", "whiteout", "redact", "screenshot", "freetext")
MARKUP_TOOLS = ("highlight", "underline", "strikeout")
COLORS = [(1.0, 0.85, 0.1), (0.2, 0.8, 0.3), (0.25, 0.6, 1.0), (1.0, 0.45, 0.7),
          (0.85, 0.1, 0.1), (0.0, 0.0, 0.0), (0.1, 0.25, 0.75), (1.0, 1.0, 1.0)]
STAMPS = ["stamp_approved", "stamp_confidential", "stamp_draft", "stamp_received"]
HANDLE = 5


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(v * 255) for v in c[:3])


CACHE_BYTES = 96e6   # rendered page bitmaps kept for fast scrolling


class DocView(ctk.CTkFrame):
    """Viewer and editor for one ``Document``.

    Pages are drawn on a plain ``tk.Canvas``; only the visible pages are
    rendered (PDFium, in idle time) and kept in a small cache, so very long
    documents open instantly and use little memory.
    """

    def __init__(self, master, app, doc: Document, state=None):
        super().__init__(master, corner_radius=0, fg_color=("gray92", "gray14"))
        self.app = app
        self.doc = doc
        st = state or {}
        self.zoom = st.get("zoom", 100)
        self.fit = st.get("fit", "width")
        self.mode = st.get("mode", "continuous")
        self.view_rot = st.get("view_rot", 0)
        self.night = st.get("night", False)
        self.cur = st.get("cur", 0)
        self.tool = "select"
        self.color = {"highlight": COLORS[0], "underline": (0.1, 0.35, 0.9), "strikeout": (0.85, 0.1, 0.1),
                      "ink": (0.85, 0.1, 0.1), "rect": (0.85, 0.1, 0.1), "ellipse": (0.85, 0.1, 0.1),
                      "line": (0.85, 0.1, 0.1), "arrow": (0.85, 0.1, 0.1), "freetext": (0, 0, 0),
                      "note": (1.0, 0.8, 0.1), "stamp": (0.8, 0.1, 0.1)}
        self.width_pt = 2.0
        self.font_size = 14.0
        self.family = "naskh"
        self.shape_fill = None
        self.stamp_text = i18n.raw("stamp_approved")
        self.pending_image = None      # (png bytes, w, h) for image / signature tools
        self.show_fields = True
        self.sel_pages = {self.cur}
        self.scale = self.zoom / 100 * PX_PER_PT
        self.slots = []                 # page -> (x, y, w, h) or None
        self.total_h = 1
        self.base_cache: "OrderedDict[tuple, Image.Image]" = OrderedDict()
        self.photos = {}
        self.items = {}
        self.queue = []
        self._render_job = None
        self._layout_job = None
        self._thumb_job = None
        self.selected = None            # (page, annot id)
        self.drag = None
        self.text_sel = None            # (page, a, b)
        self._selecting = False
        self.hidden = set()
        self.query = ""
        self.hits = {}
        self.hit_list = []
        self.hit_idx = -1
        self._search_job = None
        self._search_pos = 0
        self._search_jump = True
        self._search_start = 0
        self.auto_scroll = 0
        self._as_job = None
        self.ribbon_tab = "tab_home"
        self.tool_btns = {}
        self.field_widgets = {}
        self.thumb_slots = []
        self.doc.listeners.append(self._doc_changed)
        self._build()
        self.after(10, self.relayout)

    # ------------------------------------------------------------------ UI
    def _build(self):
        rtl = i18n.is_rtl()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        tabs = ctk.CTkFrame(self, fg_color="transparent", height=30)
        tabs.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        self.tab_btns = {}
        for k in ["tab_home", "tab_comment", "tab_edit", "tab_form", "tab_page", "tab_protect", "tab_tools"]:
            b = ctk.CTkButton(tabs, text=t(k), width=80, height=26, corner_radius=6, font=self.app.app_font,
                              fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray80", "gray25"), command=lambda k=k: self.show_tab(k))
            b.pack(side="right" if rtl else "left", padx=1)
            self.tab_btns[k] = b
        self.ribbon = ctk.CTkFrame(self, height=66, corner_radius=8)
        self.ribbon.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 4))
        self.ribbon.grid_propagate(False)
        self.ribbon.pack_propagate(False)
        self.tab_frames = {}
        self.findbar = ctk.CTkFrame(self, fg_color="transparent")
        self._build_findbar()
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=3, column=0, sticky="nsew")
        self.mid = mid
        mid.grid_rowconfigure(0, weight=1)
        side_col, can_col, right_col = (2, 1, 0) if rtl else (0, 1, 2)
        mid.grid_columnconfigure(can_col, weight=1)
        self.sidebar = ctk.CTkFrame(mid, width=190, corner_radius=0)
        self.sidebar.grid(row=0, column=side_col, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        self.sidebar_col = side_col
        self._build_sidebar()
        cf = tk.Frame(mid, bd=0, highlightthickness=0)
        cf.grid(row=0, column=can_col, sticky="nsew")
        cf.grid_rowconfigure(0, weight=1)
        cf.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(cf, highlightthickness=0, bd=0, takefocus=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = ctk.CTkScrollbar(cf, command=self._yview)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar = ctk.CTkScrollbar(cf, orientation="horizontal", command=self.canvas.xview)
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=self._yscroll, xscrollcommand=self.hbar.set)
        self.right = ctk.CTkScrollableFrame(mid, width=250, corner_radius=0)
        self.right_col = right_col
        self.apply_theme()
        self._build_statusbar()
        self.show_tab(self.ribbon_tab)
        self._bind_keys()

    def _yview(self, *a):
        self.canvas.yview(*a)
        self._on_scroll()

    def _yscroll(self, a, b):
        self.vbar.set(a, b)
        self._on_scroll()

    def apply_theme(self):
        dark = ctk.get_appearance_mode() == "Dark"
        self.canvas.configure(bg="#2b2b2b" if dark else "#d6d6d6")
        try:
            self.thumbs.configure(bg="#232323" if dark else "#ececec")
        except Exception:
            pass

    def _rbtn(self, parent, icon, key, cmd, tool=None, width=None):
        b = ctk.CTkButton(parent, text=icon + "\n" + t(key), width=width or 62, height=56, corner_radius=6,
                          font=ctk.CTkFont(family=self.app.app_font.cget("family"), size=12),
                          fg_color="transparent", text_color=("gray10", "gray92"),
                          hover_color=("gray78", "gray28"), command=cmd)
        b.pack(side="right" if i18n.is_rtl() else "left", padx=1, pady=4)
        if tool:
            self.tool_btns.setdefault(tool, []).append(b)
        return b

    def _sep(self, parent):
        f = ctk.CTkFrame(parent, width=2, height=44, fg_color=("gray75", "gray30"))
        f.pack(side="right" if i18n.is_rtl() else "left", padx=5, pady=10)

    def show_tab(self, key):
        self.ribbon_tab = key
        for k, b in self.tab_btns.items():
            b.configure(fg_color=("#3a7ebf", "#1f538d") if k == key else "transparent",
                        text_color="white" if k == key else ("gray10", "gray90"))
        for f in self.tab_frames.values():
            f.pack_forget()
        if key not in self.tab_frames:
            f = ctk.CTkFrame(self.ribbon, fg_color="transparent")
            getattr(self, "_tab_" + key[4:])(f)
            self.tab_frames[key] = f
        self.tab_frames[key].pack(fill="both", expand=True, padx=4)
        if key == "tab_form":
            self.show_right(True)
        elif self.right.winfo_ismapped():
            self.show_right(False)
        self._mark_tool()

    def _tab_home(self, f):
        self._rbtn(f, "💾", "save", self.save)
        self._rbtn(f, "🗎", "save_as_btn", self.save_as)
        self._rbtn(f, "↶", "undo", self.undo)
        self._rbtn(f, "↷", "redo", self.redo)
        self._sep(f)
        self._rbtn(f, "⬚", "t_select", lambda: self.set_tool("select"), "select")
        self._rbtn(f, "✋", "t_hand", lambda: self.set_tool("hand"), "hand")
        self._sep(f)
        self._rbtn(f, "−", "zoom_out", lambda: self.step_zoom(-1))
        self._rbtn(f, "+", "zoom_in", lambda: self.step_zoom(1))
        self._rbtn(f, "↔", "fit_width", lambda: self.set_fit("width"), width=70)
        self._rbtn(f, "⤢", "fit_page", lambda: self.set_fit("page"), width=70)
        self._sep(f)
        self._rbtn(f, "▯", "mode_single", lambda: self.set_mode("single"), "mode_single", width=74)
        self._rbtn(f, "▯▯", "mode_double", lambda: self.set_mode("double"), "mode_double", width=66)
        self._rbtn(f, "☰", "mode_cont", lambda: self.set_mode("continuous"), "mode_continuous", width=66)
        self._sep(f)
        self._rbtn(f, "⟲", "rot_view_l", lambda: self.rotate_view(-90), width=80)
        self._rbtn(f, "⟳", "rot_view_r", lambda: self.rotate_view(90), width=80)
        self._sep(f)
        self._rbtn(f, "⇣", "auto_scroll", self.toggle_auto_scroll, "auto_scroll", width=78)
        self._rbtn(f, "▶", "slide_show", self.slide_show, width=70)
        self._rbtn(f, "✂", "screenshot", lambda: self.set_tool("screenshot"), "screenshot")
        self._rbtn(f, "🔍", "find", self.open_find)
        self._rbtn(f, "☾", "night", self.toggle_night, "night", width=70)
        self._rbtn(f, "🖶", "print", self.print_doc)

    def _tab_comment(self, f):
        self._rbtn(f, "🖍", "t_highlight", lambda: self.set_tool("highlight"), "highlight")
        self._rbtn(f, "U̲", "t_underline", lambda: self.set_tool("underline"), "underline")
        self._rbtn(f, "S̶", "t_strikeout", lambda: self.set_tool("strikeout"), "strikeout", width=72)
        self._rbtn(f, "🗨", "t_note", lambda: self.set_tool("note"), "note")
        self._rbtn(f, "T", "t_freetext", lambda: self.set_tool("freetext"), "freetext")
        self._rbtn(f, "✎", "t_ink", lambda: self.set_tool("ink"), "ink")
        self._rbtn(f, "▭", "t_rect", lambda: self.set_tool("rect"), "rect")
        self._rbtn(f, "◯", "t_ellipse", lambda: self.set_tool("ellipse"), "ellipse", width=70)
        self._rbtn(f, "╱", "t_line", lambda: self.set_tool("line"), "line")
        self._rbtn(f, "➚", "t_arrow", lambda: self.set_tool("arrow"), "arrow")
        self._rbtn(f, "⎔", "t_stamp", self.choose_stamp, "stamp")
        self._sep(f)
        self._props(f)

    def _props(self, f):
        side = "right" if i18n.is_rtl() else "left"
        box = ctk.CTkFrame(f, fg_color="transparent")
        box.pack(side=side, padx=4)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x")
        for c in COLORS:
            ctk.CTkButton(top, text="", width=18, height=18, corner_radius=9, fg_color=_hex(c),
                          hover_color=_hex(c), border_width=1, border_color="gray50",
                          command=lambda c=c: self.set_color(c)).pack(side=side, padx=1, pady=2)
        bot = ctk.CTkFrame(box, fg_color="transparent")
        bot.pack(fill="x", pady=(2, 0))
        small = ctk.CTkFont(family=self.app.app_font.cget("family"), size=11)
        ctk.CTkLabel(bot, text=t("thickness"), font=small).pack(side=side, padx=2)
        wm = ctk.CTkOptionMenu(bot, values=["1", "2", "3", "5", "8"], width=52, height=22, font=small,
                               command=lambda v: self._set_width(float(v)))
        wm.set(str(int(self.width_pt)))
        wm.pack(side=side, padx=2)
        ctk.CTkLabel(bot, text=t("font_size"), font=small).pack(side=side, padx=2)
        sm = ctk.CTkOptionMenu(bot, values=["10", "12", "14", "16", "18", "24", "32"], width=56, height=22,
                               font=small, command=lambda v: setattr(self, "font_size", float(v)))
        sm.set(str(int(self.font_size)))
        sm.pack(side=side, padx=2)
        fillv = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(bot, text=t("fill"), font=small, width=20, checkbox_width=16, checkbox_height=16,
                        variable=fillv,
                        command=lambda: setattr(self, "shape_fill", (1, 1, 0.6) if fillv.get() else None)
                        ).pack(side=side, padx=4)

    def _tab_edit(self, f):
        self._rbtn(f, "✎", "t_edittext", lambda: self.set_tool("textedit"), "textedit", width=70)
        self._rbtn(f, "T", "t_freetext", lambda: self.set_tool("freetext"), "freetext")
        self._rbtn(f, "🖼", "t_image", self.choose_image, "image", width=70)
        self._rbtn(f, "✍", "t_signature", self.choose_signature, "signature")
        self._rbtn(f, "⬜", "t_whiteout", lambda: self.set_tool("whiteout"), "whiteout", width=80)
        self._rbtn(f, "■", "t_redact", lambda: self.set_tool("redact"), "redact", width=80)
        self._rbtn(f, "🗑", "t_delete", self.delete_selected)
        self._sep(f)
        self._rbtn(f, "↶", "undo", self.undo)
        self._rbtn(f, "↷", "redo", self.redo)
        self._sep(f)
        self.edit_hint = ctk.CTkLabel(f, text="", wraplength=330, font=ctk.CTkFont(size=11),
                                      justify="right" if i18n.is_rtl() else "left", text_color="gray55")
        self.edit_hint.pack(side="right" if i18n.is_rtl() else "left", padx=6)

    def _tab_form(self, f):
        self._rbtn(f, "▤", "highlight_fields", self.toggle_fields, "fields", width=90)
        self._rbtn(f, "↶", "undo", self.undo)
        self._rbtn(f, "↷", "redo", self.redo)
        self._rbtn(f, "💾", "save", self.save)
        self._sep(f)
        msg = t("form_fields") if self.doc.fields else t("no_fields")
        ctk.CTkLabel(f, text=msg, font=self.app.app_font).pack(side="right" if i18n.is_rtl() else "left", padx=8)

    def _tab_page(self, f):
        self._rbtn(f, "⟲", "pg_rot_l", lambda: self.rotate_pages(-90), width=74)
        self._rbtn(f, "⟳", "pg_rot_r", lambda: self.rotate_pages(90), width=74)
        self._rbtn(f, "🗑", "pg_delete", self.delete_pages, width=74)
        self._rbtn(f, "＋", "pg_insert_blank", self.insert_blank, width=78)
        self._rbtn(f, "⎘", "pg_insert_pdf", self.insert_pdf, width=88)
        self._rbtn(f, "⇪", "pg_extract", self.extract_pages, width=84)
        self._rbtn(f, "⧉", "pg_duplicate", self.duplicate_page, width=66)
        self._rbtn(f, "↑", "pg_up", lambda: self.move_page(-1), width=78)
        self._rbtn(f, "↓", "pg_down", lambda: self.move_page(1), width=78)
        self._sep(f)
        self.pages_lbl = ctk.CTkLabel(f, text="", font=self.app.app_font)
        self.pages_lbl.pack(side="right" if i18n.is_rtl() else "left", padx=6)
        self._update_pages_lbl()

    def _tab_protect(self, f):
        self._rbtn(f, "🔒", "t_password", lambda: self.open_tool("security"), width=70)
        self._rbtn(f, "■", "t_redact", lambda: (self.show_tab("tab_edit"), self.set_tool("redact")), width=80)
        self._rbtn(f, "✍", "t_stampsign", lambda: self.open_tool("sign"), width=84)
        self._rbtn(f, "▣", "save_flat", lambda: self.save_as(flatten=True), width=96)

    def _tab_tools(self, f):
        for icon, key, tool in [("⊕", "t_merge", "merge"), ("✂", "t_split", "split"),
                                ("▦", "t_organize", "organize"), ("⇲", "t_compress", "compress"),
                                ("W", "t_convert", "convert"), ("👁", "ocr_btn", "ocr"),
                                ("🖼", "t_toimages", "images"), ("✍", "t_stampsign", "sign"),
                                ("🔒", "t_password", "security")]:
            self._rbtn(f, icon, key, lambda k=tool: self.open_tool(k), width=78)

    def _build_findbar(self):
        rtl = i18n.is_rtl()
        side = "right" if rtl else "left"
        fb = self.findbar
        self.find_entry = ctk.CTkEntry(fb, width=260, font=self.app.text_font, justify="right" if rtl else "left",
                                       placeholder_text=t("find_ph"))
        self.find_entry.pack(side=side, padx=4)
        ctk.CTkButton(fb, text=t("find_prev"), width=70, command=lambda: self.find_step(-1),
                      font=self.app.app_font).pack(side=side, padx=2)
        ctk.CTkButton(fb, text=t("find_next"), width=70, command=lambda: self.find_step(1),
                      font=self.app.app_font).pack(side=side, padx=2)
        self.find_lbl = ctk.CTkLabel(fb, text="", font=self.app.app_font)
        self.find_lbl.pack(side=side, padx=8)
        ctk.CTkButton(fb, text=t("redact_all_hits"), width=120, fg_color="gray35", command=self.redact_hits,
                      font=self.app.app_font).pack(side=side, padx=6)
        ctk.CTkButton(fb, text="✕", width=30, fg_color="transparent", text_color=("gray10", "gray90"),
                      command=self.close_find).pack(side="left" if rtl else "right", padx=4)
        self.find_entry.bind("<Return>", lambda e: self.find(self.find_entry.get()))
        self.find_entry.bind("<Shift-Return>", lambda e: self.find_step(-1))
        self.find_entry.bind("<Escape>", lambda e: self.close_find())

    def _build_sidebar(self):
        sb = self.sidebar
        self.side_tabs = ctk.CTkSegmentedButton(sb, values=[t("thumbs"), t("bookmarks"), t("annotations")],
                                                command=self._side_tab, font=ctk.CTkFont(size=11))
        self.side_tabs.pack(fill="x", padx=4, pady=4)
        self.side_body = ctk.CTkFrame(sb, fg_color="transparent")
        self.side_body.pack(fill="both", expand=True)
        self.thumbs = tk.Canvas(self.side_body, highlightthickness=0, bd=0, width=170)
        self.thumb_bar = ctk.CTkScrollbar(self.side_body, command=self._thumb_yview)
        self.thumbs.configure(yscrollcommand=self._thumb_yscroll)
        self.thumb_photos = {}
        self.thumb_items = {}
        self.thumbs.bind("<Button-1>", self._thumb_click)
        self.thumbs.bind("<Configure>", lambda e: self._thumb_layout())
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.thumbs.bind(seq, self._thumb_wheel)
        self.bm_frame = None
        self.an_frame = None
        self.side_tabs.set(t("thumbs"))
        self._side_tab(t("thumbs"))

    def _side_tab(self, v):
        for w in (self.thumbs, self.thumb_bar, self.bm_frame, self.an_frame):
            if w is not None:
                w.pack_forget()
        if v == t("thumbs"):
            self.thumb_bar.pack(side="right", fill="y")
            self.thumbs.pack(side="left", fill="both", expand=True)
            self.after(20, self._thumb_layout)
        elif v == t("bookmarks"):
            self._fill_bookmarks()
            self.bm_frame.pack(fill="both", expand=True)
        else:
            self._fill_annots()
            self.an_frame.pack(fill="both", expand=True)

    def _build_statusbar(self):
        rtl = i18n.is_rtl()
        side = "right" if rtl else "left"
        far = "left" if rtl else "right"
        sb = ctk.CTkFrame(self, height=34, corner_radius=0)
        sb.grid(row=4, column=0, sticky="ew")
        self.sbar = sb
        ctk.CTkButton(sb, text="☰", width=30, height=26, command=self.toggle_sidebar,
                      fg_color="transparent", text_color=("gray10", "gray90")).pack(side=side, padx=4)
        ctk.CTkButton(sb, text="⏮" if not rtl else "⏭", width=30, height=26,
                      command=lambda: self.goto(0)).pack(side=side, padx=1)
        ctk.CTkButton(sb, text="◀" if not rtl else "▶", width=30, height=26,
                      command=lambda: self.goto(self.cur - 1)).pack(side=side, padx=1)
        self.page_entry = ctk.CTkEntry(sb, width=56, height=26, justify="center")
        self.page_entry.pack(side=side, padx=3)
        self.page_total = ctk.CTkLabel(sb, text="", font=self.app.app_font)
        self.page_total.pack(side=side, padx=2)
        ctk.CTkButton(sb, text="▶" if not rtl else "◀", width=30, height=26,
                      command=lambda: self.goto(self.cur + 1)).pack(side=side, padx=1)
        ctk.CTkButton(sb, text="⏭" if not rtl else "⏮", width=30, height=26,
                      command=lambda: self.goto(len(self.doc) - 1)).pack(side=side, padx=1)
        self.page_entry.bind("<Return>", self._page_entered)
        self.msg = ctk.CTkLabel(sb, text="", font=self.app.app_font, text_color="gray55")
        self.msg.pack(side=side, padx=12)
        self.zoom_menu = ctk.CTkOptionMenu(sb, values=[f"{z}%" for z in ZOOMS], width=80, height=26,
                                           command=lambda v: self.set_zoom(int(v.rstrip("%"))))
        self.zoom_menu.pack(side=far, padx=4)
        ctk.CTkButton(sb, text="+", width=28, height=26, command=lambda: self.step_zoom(1)).pack(side=far, padx=1)
        self.zoom_slider = ctk.CTkSlider(sb, from_=10, to=400, width=140, command=self._slider)
        self.zoom_slider.pack(side=far, padx=2)
        ctk.CTkButton(sb, text="−", width=28, height=26, command=lambda: self.step_zoom(-1)).pack(side=far, padx=1)

    # ------------------------------------------------------------------ bindings
    def _bind_keys(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self._schedule_layout())
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double)
        c.bind("<Button-3>", self._context)
        c.bind("<Motion>", self._hover)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Button-4>", self._wheel)
        c.bind("<Button-5>", self._wheel)
        c.bind("<Control-MouseWheel>", self._ctrl_wheel)
        c.bind("<Control-Button-4>", lambda e: self.step_zoom(1))
        c.bind("<Control-Button-5>", lambda e: self.step_zoom(-1))
        keys = [("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Control-Z>", self.redo),
                ("<Control-s>", self.save), ("<Control-S>", self.save_as), ("<Control-f>", self.open_find),
                ("<Control-c>", self.copy_selection), ("<Delete>", self.delete_selected),
                ("<Next>", lambda: self.goto(self.cur + 1)), ("<Prior>", lambda: self.goto(self.cur - 1)),
                ("<Home>", lambda: self.goto(0)), ("<End>", lambda: self.goto(len(self.doc) - 1)),
                ("<Escape>", self._escape), ("<Control-plus>", lambda: self.step_zoom(1)),
                ("<Control-equal>", lambda: self.step_zoom(1)), ("<Control-minus>", lambda: self.step_zoom(-1)),
                ("<Control-0>", lambda: self.set_fit("width")), ("<F3>", lambda: self.find_step(1)),
                ("<Down>", lambda: self._scroll_units(3)), ("<Up>", lambda: self._scroll_units(-3))]
        for seq, fn in keys:
            c.bind(seq, lambda e, fn=fn: (fn(), "break")[1])

    def _scroll_units(self, n):
        self.canvas.yview_scroll(n, "units")
        self._on_scroll()

    def focus_canvas(self):
        try:
            self.canvas.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------------------ layout
    def _schedule_layout(self):
        if self._layout_job:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(60, self.relayout)

    def _sizes(self):
        return [self.doc.display_size(i, self.view_rot) for i in range(len(self.doc))]

    def relayout(self, keep_page=True):
        self._layout_job = None
        if not self.winfo_exists():
            return
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        n = len(self.doc)
        self.cur = max(0, min(self.cur, n - 1))
        sizes = self._sizes()
        self._sizes_pt = sizes
        if self.fit:
            if self.mode == "double":
                k = self.cur - self.cur % 2
                pair = [sizes[j] for j in (k, k + 1) if j < n]
                pw = sum(s[0] for s in pair) + (GAP / PX_PER_PT) * (len(pair) - 1)
                ph = max(s[1] for s in pair)
            elif self.mode == "single" or self.fit == "page":
                pw, ph = sizes[self.cur]
            else:
                pw, ph = max(s[0] for s in sizes), sizes[self.cur][1]
            sw = (cw - 2 * MARGIN) / max(pw, 1)
            sc = sw if self.fit == "width" else min(sw, (ch - 2 * MARGIN) / max(ph, 1))
            self.scale = max(0.1 * PX_PER_PT, min(4 * PX_PER_PT, sc))
            self.zoom = round(self.scale / PX_PER_PT * 100)
        else:
            self.scale = self.zoom / 100 * PX_PER_PT
        s = self.scale
        slots = [None] * n
        rtl = i18n.is_rtl()
        if self.mode == "continuous":
            y = MARGIN
            maxw = max(w for w, _ in sizes) * s
            total_w = max(cw, maxw + 2 * MARGIN)
            for i, (w, h) in enumerate(sizes):
                slots[i] = ((total_w - w * s) / 2, y, w * s, h * s)
                y += h * s + GAP
            total_h = y + MARGIN - GAP
        elif self.mode == "double":
            y = MARGIN
            rows = []
            for k in range(0, n, 2):
                pair = [j for j in (k, k + 1) if j < n]
                rw = sum(sizes[j][0] * s for j in pair) + GAP * (len(pair) - 1)
                rh = max(sizes[j][1] * s for j in pair)
                rows.append((pair, rw, rh, y))
                y += rh + GAP
            total_w = max(cw, max(r[1] for r in rows) + 2 * MARGIN)
            for pair, rw, rh, y0 in rows:
                x = (total_w - rw) / 2
                for j in (list(reversed(pair)) if rtl else pair):   # Arabic books read right to left
                    slots[j] = (x, y0, sizes[j][0] * s, sizes[j][1] * s)
                    x += sizes[j][0] * s + GAP
            total_h = y + MARGIN - GAP
        else:
            w, h = sizes[self.cur]
            total_w = max(cw, w * s + 2 * MARGIN)
            slots[self.cur] = ((total_w - w * s) / 2, max(MARGIN, (ch - h * s) / 2), w * s, h * s)
            total_h = max(ch, h * s + 2 * MARGIN)
        self.slots = slots
        self.canvas.delete("all")
        self.items.clear()
        self.photos.clear()
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))
        self.total_h = total_h
        for i, sl in enumerate(slots):
            if sl is None:
                continue
            x, y, w, h = sl
            self.canvas.create_rectangle(x + 3, y + 3, x + w + 3, y + h + 3, fill="#1a1a1a", outline="",
                                         tags=("shadow",))
            self.canvas.create_rectangle(x, y, x + w, y + h, fill="white", outline="#999999", tags=("ph",))
        if keep_page and self.mode != "single":
            self._scroll_to_page(self.cur)
        elif self.mode == "single":
            self.canvas.yview_moveto(0)
        self._update_zoom_widgets()
        self._update_page_widgets()
        self._on_scroll()
        self._thumb_layout()
        self._draw_selection()

    def _scroll_to_page(self, i, y_off=0.0):
        sl = self.slots[i] if 0 <= i < len(self.slots) else None
        if not sl or not self.total_h:
            return
        self.canvas.yview_moveto(max(0.0, (sl[1] - MARGIN / 2 + y_off) / self.total_h))
        try:
            region_w = float(str(self.canvas.cget("scrollregion")).split()[2])
            cw = self.canvas.winfo_width()
            if region_w > cw:
                self.canvas.xview_moveto(max(0.0, (sl[0] + sl[2] / 2 - cw / 2) / region_w))
        except Exception:
            pass

    def visible_pages(self):
        if not self.slots:
            return []
        top = self.canvas.canvasy(0)
        bot = self.canvas.canvasy(self.canvas.winfo_height())
        out = []
        for i, sl in enumerate(self.slots):
            if sl is None:
                continue
            if sl[1] + sl[3] >= top and sl[1] <= bot:
                out.append(i)
            elif sl[1] > bot:
                break
        return out

    def _on_scroll(self):
        if not self.slots:
            return
        vis = self.visible_pages()
        if not vis:
            return
        if self.mode != "single":
            mid = self.canvas.canvasy(self.canvas.winfo_height() / 3)
            cur = vis[0]
            for i in vis:
                if self.slots[i][1] <= mid:
                    cur = i
            if cur != self.cur:
                self.cur = cur
                self._update_page_widgets()
                self._thumb_mark()
        keep = set(vis)
        for i in vis:
            keep.update((i - 1, i + 1))
        for i in list(self.items):
            if i not in keep:
                self.canvas.delete(self.items.pop(i))
                self.photos.pop(i, None)
        want = [i for i in vis if i not in self.items]
        want += [i for i in (vis[0] - 1, vis[-1] + 1)
                 if 0 <= i < len(self.slots) and self.slots[i] and i not in self.items]
        self.queue = want
        if want and not self._render_job:
            self._render_job = self.after(1, self._render_tick)

    def _render_tick(self):
        self._render_job = None
        t0 = time.perf_counter()
        while self.queue and time.perf_counter() - t0 < 0.05:
            i = self.queue.pop(0)
            if i < len(self.slots) and self.slots[i] and i not in self.items:
                try:
                    self.compose(i)
                except Exception as e:  # noqa: BLE001
                    self.status(str(e), error=True)
        if self.queue:
            self._render_job = self.after(1, self._render_tick)

    def render_all_visible(self):
        """Synchronously render what is on screen (tests, screenshots)."""
        self.update_idletasks()
        self._on_scroll()
        while self.queue:
            self._render_tick()

    def base_image(self, i):
        ref = self.doc.pages[i]
        key = (ref.src, ref.index, ref.uid if ref.src == "blank" else "", ref.rot, round(self.scale, 4),
               self.view_rot)
        if key in self.base_cache:
            self.base_cache.move_to_end(key)
            return self.base_cache[key]
        img = self.doc.render(i, self.scale, self.view_rot)
        self.base_cache[key] = img
        while len(self.base_cache) > 2 and sum(im.width * im.height * len(im.getbands())
                                               for im in self.base_cache.values()) > CACHE_BYTES:
            self.base_cache.popitem(last=False)
        return img

    def compose(self, i):
        """(Re)draw page i with its overlays."""
        sl = self.slots[i] if i < len(self.slots) else None
        if not sl:
            return
        base = img = self.base_image(i).convert("RGB")
        g = self.doc.geom(i, self.scale, self.view_rot)
        ref = self.doc.pages[i]
        if ref.annots:
            img = overlay.draw_annots(img, g, ref.annots, self.hidden)
        if self.doc.fields:
            w = self.doc.widgets_on(i)
            if w:
                img = overlay.draw_fields(img, g, w, self.doc.form_values, self.show_fields)
        if self.night:
            # invert the page only; annotations and form values keep their real colours
            lit = img.convert("RGB")
            img = ImageOps.invert(base)
            if lit is not base:
                mask = ImageChops.difference(lit, base).convert("L").point(lambda v: 255 if v > 6 else 0)
                img.paste(lit, mask=mask)
                # dark ink / black text would vanish on the dark page: show it light instead
                dark = lit.convert("L").point(lambda v: 255 if v < 90 else 0)
                img.paste(ImageOps.invert(lit), mask=ImageChops.multiply(mask, dark))
        if self.hits.get(i):
            cur = self.hit_list[self.hit_idx] if 0 <= self.hit_idx < len(self.hit_list) else None
            other = [r for k, rs in enumerate(self.hits[i]) if cur != (i, k) for r in rs]
            img = overlay.draw_rects(img, g, other, (255, 200, 0, 90))
            if cur and cur[0] == i:
                img = overlay.draw_rects(img, g, self.hits[i][cur[1]], (255, 120, 0, 140), (230, 80, 0, 255))
        if self.text_sel and self.text_sel[0] == i:
            img = overlay.draw_rects(img, g, self._sel_rects(), (40, 110, 255, 80))
        size = (max(1, round(sl[2])), max(1, round(sl[3])))
        if img.size != size:
            img = img.resize(size)
        photo = ImageTk.PhotoImage(img)
        self.photos[i] = photo
        if i in self.items:
            self.canvas.itemconfigure(self.items[i], image=photo)
        else:
            self.items[i] = self.canvas.create_image(sl[0], sl[1], image=photo, anchor="nw", tags=("page",))
            self.canvas.tag_raise("sel")
            self.canvas.tag_raise("tmp")

    def redraw(self, pages=None):
        for i in (pages if pages is not None else list(self.items)):
            if i in self.items:
                self.compose(i)
        self._draw_selection()

    # ------------------------------------------------------------------ coordinates
    def page_at(self, cx, cy):
        for i, sl in enumerate(self.slots):
            if sl and sl[0] <= cx <= sl[0] + sl[2] and sl[1] <= cy <= sl[1] + sl[3]:
                return i
        return None

    def to_pdf(self, i, cx, cy):
        x, y, _, _ = self.slots[i]
        return self.doc.geom(i, self.scale, self.view_rot).to_pdf(cx - x, cy - y)

    def to_canvas(self, i, px, py):
        x, y, _, _ = self.slots[i]
        sx, sy = self.doc.geom(i, self.scale, self.view_rot).to_screen(px, py)
        return x + sx, y + sy

    def rect_to_canvas(self, i, r):
        x, y, _, _ = self.slots[i]
        l, t_, rr, b = self.doc.geom(i, self.scale, self.view_rot).rect_to_screen(r)
        return x + l, y + t_, x + rr, y + b

    def _cxy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    # ------------------------------------------------------------------ navigation / zoom
    def goto(self, i, y_off=0.0):
        n = len(self.doc)
        i = max(0, min(int(i), n - 1))
        self.cur = i
        self.sel_pages = {i}
        if self.mode in ("single", "double") and (i >= len(self.slots) or self.slots[i] is None
                                                  or self.mode == "single"):
            self.relayout(keep_page=False)
        if self.mode != "single":
            self._scroll_to_page(i, y_off)
        self._update_page_widgets()
        self._on_scroll()
        self._thumb_mark(scroll=True)

    def _page_entered(self, e=None):
        try:
            self.goto(int(self.page_entry.get().strip()) - 1)
        except ValueError:
            self._update_page_widgets()
        self.focus_canvas()

    def _update_page_widgets(self):
        try:
            self.page_entry.delete(0, "end")
            self.page_entry.insert(0, str(self.cur + 1))
            self.page_total.configure(text=f"/ {len(self.doc)}")
        except Exception:
            pass
        self._update_pages_lbl()

    def _update_pages_lbl(self):
        lbl = getattr(self, "pages_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(text=t("pages_selected", n=len(self.sel_pages)))
            except Exception:
                pass

    def _update_zoom_widgets(self):
        self.zoom_menu.set(f"{self.zoom}%")
        self.zoom_slider.set(self.zoom)

    def _page_frac(self):
        sl = self.slots[self.cur] if self.cur < len(self.slots) else None
        if not sl:
            return 0.0
        return (self.canvas.canvasy(0) - sl[1]) / max(sl[3], 1)

    def _restore_pos(self, cur, frac):
        sl = self.slots[cur] if cur < len(self.slots) else None
        if sl and self.mode != "single":
            self.canvas.yview_moveto(max(0.0, (sl[1] + frac * sl[3]) / self.total_h))
        self._on_scroll()

    def set_zoom(self, z):
        z = max(10, min(400, int(z)))
        self.fit = None
        cur, frac = self.cur, self._page_frac()
        self.zoom = z
        self.relayout(keep_page=False)
        self._restore_pos(cur, frac)

    def _slider(self, v):
        if abs(int(v) - self.zoom) >= 2:
            if self._layout_job:
                self.after_cancel(self._layout_job)
            self._layout_job = self.after(150, lambda: self.set_zoom(int(v)))

    def step_zoom(self, d):
        z = self.zoom
        if d > 0:
            nxt = [s for s in ZOOMS if s > z]
            self.set_zoom(nxt[0] if nxt else 400)
        else:
            prv = [s for s in ZOOMS if s < z]
            self.set_zoom(prv[-1] if prv else 10)

    def set_fit(self, f):
        self.fit = f
        cur, frac = self.cur, self._page_frac()
        self.relayout(keep_page=False)
        self._restore_pos(cur, frac if f == "width" else 0.0)

    def set_mode(self, m):
        self.mode = m
        self.relayout()
        self._mark_tool()

    def rotate_view(self, d):
        self.view_rot = (self.view_rot + d) % 360
        self.relayout()

    def toggle_night(self):
        self.night = not self.night
        self.redraw()
        self._mark_tool()

    def toggle_fields(self):
        self.show_fields = not self.show_fields
        self.redraw()
        self._mark_tool()

    def _wheel(self, e):
        up = getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0
        if self.mode == "single" and not self._can_scroll():
            self.goto(self.cur + (-1 if up else 1))
            return
        self.canvas.yview_scroll(-3 if up else 3, "units")
        self._on_scroll()

    def _can_scroll(self):
        a, b = self.canvas.yview()
        return b - a < 0.999

    def _ctrl_wheel(self, e):
        self.step_zoom(1 if e.delta > 0 else -1)

    # ------------------------------------------------------------------ tools
    def set_tool(self, tool):
        if tool == self.tool and tool != "select":
            tool = "select"
        self.tool = tool
        if tool not in MARKUP_TOOLS + ("select",):
            self.text_sel = None
        self.canvas.delete("tmp")
        cur = {"hand": "fleur", "select": "", "ink": "pencil", "note": "hand2", "textedit": "xterm"}.get(
            tool, "crosshair")
        self.canvas.configure(cursor=cur)
        self._mark_tool()
        hint = {"whiteout": "whiteout_note", "redact": "redact_note", "textedit": "edit_note"}.get(tool)
        if getattr(self, "edit_hint", None) is not None:
            self.edit_hint.configure(text=t(hint) if hint else "")
        self.focus_canvas()

    def _mark_tool(self):
        on = {self.tool, "mode_" + self.mode}
        if self.night:
            on.add("night")
        if self.show_fields:
            on.add("fields")
        if self.auto_scroll:
            on.add("auto_scroll")
        for k, bs in self.tool_btns.items():
            for b in bs:
                try:
                    b.configure(fg_color=("#c5d9f1", "#1f538d") if k in on else "transparent")
                except Exception:
                    pass

    def set_color(self, c):
        c = tuple(c)
        if self.selected:
            i, aid = self.selected
            a = self.doc.find_annot(i, aid)
            if a is not None:
                self.doc.update_annot(i, replace(a, color=c))
                if a.kind in self.color:
                    self.color[a.kind] = c
                return
        if self.tool in self.color:
            self.color[self.tool] = c
        else:
            for kk in ("ink", "rect", "ellipse", "line", "arrow", "freetext"):
                self.color[kk] = c

    def _set_width(self, w):
        self.width_pt = w
        if self.selected:
            i, aid = self.selected
            a = self.doc.find_annot(i, aid)
            if a is not None and a.kind in ("ink", "rect", "ellipse", "line", "arrow"):
                self.doc.update_annot(i, replace(a, width=w))

    def choose_stamp(self):
        m = tk.Menu(self, tearoff=0)
        for k in STAMPS:
            m.add_command(label=i18n.ui(i18n.raw(k)), command=lambda k=k: self._stamp_set(i18n.raw(k)))
        m.add_separator()
        m.add_command(label=i18n.ui(i18n.raw("stamp_custom")), command=self._stamp_custom)
        try:
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            m.grab_release()

    def _stamp_set(self, text):
        self.stamp_text = text
        self.tool = "select"
        self.set_tool("stamp")

    def _stamp_custom(self):
        res = self._text_dialog("", 20, "naskh", (160, 50))
        if res and res["text"].strip():
            self._stamp_set(res["text"].strip())

    def _ask_open(self, kinds):
        if self.app.test_answers:
            return self.app.test_answers.pop(0)
        return filedialog.askopenfilename(filetypes=kinds, initialdir=self.app.settings.get("last_dir") or None)

    def choose_image(self, path=None):
        path = path or self._ask_open([("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff")])
        if not path:
            return
        self._load_pending(path, transparent=False)
        self.tool = "select"
        self.set_tool("image")

    def choose_signature(self, path=None):
        path = path or self._ask_open([("Images", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        self._load_pending(path, transparent=True)
        self.tool = "select"
        self.set_tool("signature")

    def _load_pending(self, path, transparent):
        im = ImageOps.exif_transpose(Image.open(path))
        if transparent:
            try:
                from ..core.sign import make_transparent
                im = make_transparent(im)
            except Exception:
                im = im.convert("RGBA")
        im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        self.pending_image = (buf.getvalue(), im.width, im.height)

    # ------------------------------------------------------------------ mouse
    def _press(self, e):
        self.focus_canvas()
        cx, cy = self._cxy(e)
        self.drag = None
        if self.tool == "hand":
            self.canvas.scan_mark(e.x, e.y)
            self.drag = {"kind": "pan"}
            return
        i = self.page_at(cx, cy)
        if i is None:
            self._select(None)
            return
        if i != self.cur and self.mode != "single":
            self.cur = i
            self._update_page_widgets()
        px, py = self.to_pdf(i, cx, cy)
        tl = self.tool
        if tl == "select":
            h = self._handle_at(cx, cy)
            if h is not None:
                a = self.doc.find_annot(*self.selected)
                self.drag = {"kind": "resize", "page": self.selected[0], "annot": a, "handle": h,
                             "start": (cx, cy), "box": self.rect_to_canvas(self.selected[0], a.bounds())}
                return
            a = self._annot_at(i, px, py)
            if a is not None:
                self._select((i, a.id))
                self.drag = {"kind": "move", "page": i, "annot": a, "start": (cx, cy),
                             "box": self.rect_to_canvas(i, a.bounds()), "moved": False}
                return
            w = self._widget_at(i, px, py)
            if w is not None:
                self._select(None)
                self._click_field(*w)
                return
            self._select(None)
            self._start_text_sel(i, px, py)
            return
        if tl in MARKUP_TOOLS:
            tp = self.doc.textpage(i)
            if tp is not None and tp.count_chars() > 0:
                self._start_text_sel(i, px, py)
                return
            self.drag = {"kind": "shape", "page": i, "start": (cx, cy), "tool": tl}
            return
        if tl == "ink":
            self.drag = {"kind": "ink", "page": i, "pts": [(cx, cy)]}
            return
        if tl in SHAPE_TOOLS or tl in ("image", "signature", "stamp"):
            self.drag = {"kind": "shape", "page": i, "start": (cx, cy), "tool": tl}
            return
        if tl == "note":
            self._add_note(i, px, py)
            return
        if tl == "textedit":
            self._edit_text_at(i, px, py)

    def _motion(self, e):
        d = self.drag
        cx, cy = self._cxy(e)
        if d is None:
            if self.text_sel is not None and self._selecting:
                self._extend_text_sel(cx, cy)
            return
        k = d["kind"]
        if k == "pan":
            self.canvas.scan_dragto(e.x, e.y, gain=1)
            self._on_scroll()
        elif k == "ink":
            d["pts"].append((cx, cy))
            self.canvas.delete("tmp")
            if len(d["pts"]) > 1:
                self.canvas.create_line(*[v for p in d["pts"] for v in p], fill=_hex(self.color["ink"]),
                                        width=max(1, self.width_pt * self.scale), capstyle="round",
                                        joinstyle="round", smooth=True, tags=("tmp",))
        elif k == "shape":
            x0, y0 = d["start"]
            self.canvas.delete("tmp")
            tl = d["tool"]
            lw = max(1, self.width_pt * self.scale)
            if tl in ("line", "arrow"):
                self.canvas.create_line(x0, y0, cx, cy, fill=_hex(self.color[tl]), width=lw,
                                        arrow="last" if tl == "arrow" else None, tags=("tmp",))
            elif tl == "ellipse":
                self.canvas.create_oval(x0, y0, cx, cy, outline=_hex(self.color[tl]), width=lw, tags=("tmp",))
            elif tl == "rect":
                self.canvas.create_rectangle(x0, y0, cx, cy, outline=_hex(self.color[tl]), width=lw, tags=("tmp",))
            else:
                fill = {"whiteout": "white", "redact": "black"}.get(tl, "")
                outline = {"redact": "red", "whiteout": "#888888"}.get(tl, "#2f7de1")
                self.canvas.create_rectangle(x0, y0, cx, cy, outline=outline, fill=fill, width=2,
                                             dash=(4, 3) if not fill else None, tags=("tmp",))
        elif k in ("move", "resize"):
            l, t_, r, b = d["box"]
            dx, dy = cx - d["start"][0], cy - d["start"][1]
            if abs(dx) + abs(dy) > 2:
                d["moved"] = True
            if k == "move":
                l, t_, r, b = l + dx, t_ + dy, r + dx, b + dy
            else:
                h = d["handle"]
                l += dx if "l" in h else 0
                r += dx if "r" in h else 0
                t_ += dy if "t" in h else 0
                b += dy if "b" in h else 0
            d["now"] = (l, t_, r, b)
            self.canvas.delete("tmp")
            self.canvas.create_rectangle(l, t_, r, b, outline="#2f7de1", dash=(4, 3), width=2, tags=("tmp",))

    def _release(self, e):
        d = self.drag
        self.drag = None
        cx, cy = self._cxy(e)
        if self._selecting:
            self._selecting = False
            if self.tool in MARKUP_TOOLS and self.text_sel:
                self._markup_from_selection(self.tool)
            elif self.text_sel and self.text_sel[1] == self.text_sel[2]:
                i = self.text_sel[0]
                self.text_sel = None
                self.redraw([i])
            return
        if d is None:
            return
        self.canvas.delete("tmp")
        k = d["kind"]
        if k == "ink":
            i = d["page"]
            pts = tuple(self.to_pdf(i, x, y) for x, y in d["pts"])
            self.doc.add_annot(i, A.make("ink", strokes=(pts,), color=self.color["ink"], width=self.width_pt))
        elif k == "shape":
            self._finish_shape(d, cx, cy)
        elif k == "move" and d.get("moved") and d.get("now"):
            i, a = d["page"], d["annot"]
            x0, y0 = self.to_pdf(i, d["box"][0], d["box"][1])
            x1, y1 = self.to_pdf(i, d["now"][0], d["now"][1])
            self.doc.update_annot(i, a.moved(x1 - x0, y1 - y0))
        elif k == "resize" and d.get("now"):
            i, a = d["page"], d["annot"]
            l, t_, r, b = d["now"]
            if abs(r - l) > 4 and abs(b - t_) > 4:
                x0, y0 = self.to_pdf(i, min(l, r), min(t_, b))
                x1, y1 = self.to_pdf(i, max(l, r), max(t_, b))
                self.doc.update_annot(i, a.resized((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))))

    def _finish_shape(self, d, cx, cy):
        i, tl = d["page"], d["tool"]
        x0, y0 = d["start"]
        sl = self.slots[i]
        cx = max(sl[0], min(cx, sl[0] + sl[2]))
        cy = max(sl[1], min(cy, sl[1] + sl[3]))
        rot = self.doc.page_box(i)[1]
        if abs(cx - x0) < 6 and abs(cy - y0) < 6:
            if tl == "freetext":
                w, h = 220 * self.scale, 60 * self.scale
            elif tl == "stamp":
                w, h = 160 * self.scale, 54 * self.scale
            elif tl in ("image", "signature"):
                iw, ih = self.pending_image[1:] if self.pending_image else (4, 3)
                w = (160 if tl == "image" else 140) * self.scale
                h = w * ih / max(iw, 1)
            else:
                return
            if self.view_rot % 180 and tl in ("image", "signature"):
                w, h = h, w
            cx, cy = min(x0 + w, sl[0] + sl[2]), min(y0 + h, sl[1] + sl[3])
        l, t_, r, b = min(x0, cx), min(y0, cy), max(x0, cx), max(y0, cy)
        p0 = self.to_pdf(i, l, t_)
        p1 = self.to_pdf(i, r, b)
        rect = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
        dims = (rect[2] - rect[0], rect[3] - rect[1]) if rot % 180 == 0 else (rect[3] - rect[1], rect[2] - rect[0])
        if tl in ("rect", "ellipse"):
            self._add(i, A.make(tl, rect=rect, color=self.color[tl], width=self.width_pt, fill=self.shape_fill))
        elif tl in ("line", "arrow"):
            self._add(i, A.make(tl, strokes=((self.to_pdf(i, x0, y0), self.to_pdf(i, cx, cy)),),
                                color=self.color[tl], width=self.width_pt))
        elif tl == "whiteout":
            self._add(i, A.make("whiteout", rect=rect))
        elif tl == "redact":
            self._add(i, A.make("redact", rect=rect))
            self.status(t("redact_note"))
        elif tl in MARKUP_TOOLS:
            self._add(i, A.make(tl, rect=rect, quads=(rect,), color=self.color[tl]))
        elif tl == "screenshot":
            self._screenshot(i, (l, t_, r, b))
        elif tl == "freetext":
            res = self._text_dialog("", self.font_size, self.family, dims)
            if res and res["text"].strip():
                self.family = res["family"]
                self.font_size = res["size"]
                self._add(i, A.make("freetext", rect=rect, text=res["text"], size=res["size"],
                                    family=res["family"], color=self.color["freetext"], rotation=rot))
        elif tl == "stamp":
            self._add(i, A.make("stamp", rect=rect, text=self.stamp_text, color=self.color["stamp"], rotation=rot))
        elif tl in ("image", "signature") and self.pending_image:
            self._add(i, A.make("image", rect=rect, image=self.pending_image[0], rotation=rot))

    def _text_dialog(self, text, size, family, box):
        if self.app.test_answers:
            ans = self.app.test_answers.pop(0)
            return ans if isinstance(ans, dict) or ans is None else {"text": ans, "size": size, "family": family}
        d = TextDialog(self.app, self.app, text=text, size=size, family=family, box=box)
        self.app.wait_window(d)
        return d.result

    def _add(self, i, a):
        self.doc.add_annot(i, a)
        self._select((i, a.id))

    def _add_note(self, i, px, py):
        res = self._text_dialog("", 12, "naskh", (240, 120))
        if not res or not res["text"].strip():
            return
        self._add(i, A.make("note", rect=(px, py - 22, px + 22, py), text=res["text"], color=self.color["note"]))

    def _edit_text_at(self, i, px, py):
        tp = self.doc.textpage(i)
        line = TS.line_at(tp, px, py) if tp is not None else None
        rects = TS.range_rects(tp, line[0], line[1]) if line else []
        if not rects:
            self.status(t("no_text_here"), error=True)
            return
        a, n = line
        l = min(r[0] for r in rects)
        b = min(r[1] for r in rects)
        r_ = max(r[2] for r in rects)
        tt = max(r[3] for r in rects)
        old = TS.readable(tp.get_text_range(a, n)).strip()
        size = round(max(6.0, (tt - b) * 0.95), 1)
        rot = self.doc.page_box(i)[1]
        rect = (l - 1.5, b - 1.5 - size * 0.15, r_ + 1.5, tt + 1.5)
        dims = (rect[2] - rect[0], rect[3] - rect[1]) if rot % 180 == 0 else (rect[3] - rect[1], rect[2] - rect[0])
        res = self._text_dialog(old, size, self.family, dims)
        if not res or res["text"] == old:
            return
        self._add(i, A.make("textedit", rect=rect, text=res["text"], size=res["size"], family=res["family"],
                            color=(0, 0, 0), rotation=rot))
        self.status(t("edit_note"))

    def _double(self, e):
        cx, cy = self._cxy(e)
        i = self.page_at(cx, cy)
        if i is None:
            return
        px, py = self.to_pdf(i, cx, cy)
        a = self._annot_at(i, px, py)
        if a is not None and a.kind in ("freetext", "note", "textedit", "stamp"):
            self.drag = None
            self.edit_annot(i, a)
        elif a is None and self.tool == "select":
            tp = self.doc.textpage(i)
            ln = TS.line_at(tp, px, py) if tp is not None else None
            if ln:
                self._selecting = False
                self.text_sel = (i, ln[0], ln[0] + ln[1] - 1)
                self.redraw([i])

    def edit_annot(self, i, a):
        r = a.rect
        dims = (r[2] - r[0], r[3] - r[1]) if a.rotation % 180 == 0 else (r[3] - r[1], r[2] - r[0])
        res = self._text_dialog(a.text, a.size, a.family, dims)
        if res is None:
            return
        if not res["text"].strip() and a.kind != "textedit":
            self.doc.remove_annot(i, a.id)
            return
        self.doc.update_annot(i, replace(a, text=res["text"], size=res["size"], family=res["family"]))

    def _hover(self, e):
        if self.tool != "select":
            return
        cx, cy = self._cxy(e)
        cur = ""
        if self._handle_at(cx, cy) is not None:
            cur = "sizing"
        else:
            i = self.page_at(cx, cy)
            if i is not None:
                px, py = self.to_pdf(i, cx, cy)
                if self._annot_at(i, px, py) is not None:
                    cur = "fleur"
                elif self._widget_at(i, px, py) is not None:
                    cur = "hand2"
                else:
                    tp = self.doc.textpage(i)
                    if tp is not None and TS.char_at(tp, px, py) >= 0:
                        cur = "xterm"
        if str(self.canvas.cget("cursor")) != cur:
            self.canvas.configure(cursor=cur)

    def _context(self, e):
        cx, cy = self._cxy(e)
        i = self.page_at(cx, cy)
        m = tk.Menu(self, tearoff=0)
        if i is not None:
            px, py = self.to_pdf(i, cx, cy)
            a = self._annot_at(i, px, py)
            if a is not None:
                self._select((i, a.id))
                if a.kind in ("freetext", "note", "textedit", "stamp"):
                    m.add_command(label=i18n.ui(i18n.raw("edit_annot")), command=lambda: self.edit_annot(i, a))
                m.add_command(label=i18n.ui(i18n.raw("t_delete")), command=self.delete_selected)
            if self.text_sel:
                m.add_command(label=i18n.ui(i18n.raw("copy_text")), command=self.copy_selection)
                m.add_command(label=i18n.ui(i18n.raw("highlight_sel")),
                              command=lambda: self._markup_from_selection("highlight"))
        m.add_command(label=i18n.ui(i18n.raw("pg_rot_r")), command=lambda: self.rotate_pages(90))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------------ selection / hit-testing
    def _annot_at(self, i, px, py):
        tol = 4 / self.scale
        for a in reversed(self.doc.pages[i].annots):
            l, b, r, t_ = a.bounds()
            if l - tol <= px <= r + tol and b - tol <= py <= t_ + tol:
                return a
        return None

    def _widget_at(self, i, px, py):
        for f, w in self.doc.widgets_on(i):
            l, b, r, t_ = w.rect
            if l <= px <= r and b <= py <= t_:
                return f, w
        return None

    def _select(self, sel):
        self.selected = sel
        self._draw_selection()

    def _draw_selection(self):
        self.canvas.delete("sel")
        if not self.selected:
            return
        i, aid = self.selected
        if i >= len(self.slots) or not self.slots[i]:
            return
        a = self.doc.find_annot(i, aid)
        if a is None:
            self.selected = None
            return
        l, t_, r, b = self.rect_to_canvas(i, a.bounds())
        self.canvas.create_rectangle(l - 2, t_ - 2, r + 2, b + 2, outline="#2f7de1", width=1, dash=(3, 2),
                                     tags=("sel",))
        if a.kind not in A.MARKUP:
            for hx, hy in self._handles((l, t_, r, b)).values():
                self.canvas.create_rectangle(hx - HANDLE, hy - HANDLE, hx + HANDLE, hy + HANDLE, fill="white",
                                             outline="#2f7de1", width=1, tags=("sel",))

    @staticmethod
    def _handles(box):
        l, t_, r, b = box
        return {"lt": (l, t_), "rt": (r, t_), "lb": (l, b), "rb": (r, b)}

    def _handle_at(self, cx, cy):
        if not self.selected:
            return None
        i, aid = self.selected
        a = self.doc.find_annot(i, aid)
        if a is None or a.kind in A.MARKUP or i >= len(self.slots) or not self.slots[i]:
            return None
        for k, (hx, hy) in self._handles(self.rect_to_canvas(i, a.bounds())).items():
            if abs(cx - hx) <= HANDLE + 2 and abs(cy - hy) <= HANDLE + 2:
                return k
        return None

    def delete_selected(self):
        if self.selected:
            i, aid = self.selected
            self.selected = None
            self.canvas.delete("sel")
            self.doc.remove_annot(i, aid)

    def _escape(self):
        old = self.text_sel
        self.text_sel = None
        self._select(None)
        if self.tool != "select":
            self.set_tool("select")
        if old:
            self.redraw([old[0]])
        if self.auto_scroll:
            self.toggle_auto_scroll()

    # ---- text selection
    def _start_text_sel(self, i, px, py):
        old = self.text_sel
        self.text_sel = None
        if old:
            self.redraw([old[0]])
        tp = self.doc.textpage(i)
        if tp is None or tp.count_chars() == 0:
            return
        k = TS.nearest_char(tp, px, py)
        if k < 0:
            return
        self.text_sel = (i, k, k)
        self._selecting = True

    def _extend_text_sel(self, cx, cy):
        i = self.text_sel[0]
        sl = self.slots[i]
        if not sl:
            return
        cx = max(sl[0], min(cx, sl[0] + sl[2]))
        cy = max(sl[1], min(cy, sl[1] + sl[3]))
        px, py = self.to_pdf(i, cx, cy)
        k = TS.nearest_char(self.doc.textpage(i), px, py)
        if k >= 0 and k != self.text_sel[2]:
            self.text_sel = (i, self.text_sel[1], k)
            self.compose(i)

    def _sel_range(self):
        i, a, b = self.text_sel
        lo, hi = min(a, b), max(a, b)
        return i, lo, hi - lo + 1

    def _sel_rects(self):
        if not self.text_sel:
            return []
        i, a, n = self._sel_range()
        tp = self.doc.textpage(i)
        if tp is None or (n == 1 and self._selecting):
            return []
        return TS.range_rects(tp, a, n)

    def select_text(self, i, start, count):
        """Programmatic selection (tests / double click)."""
        self.text_sel = (i, start, start + count - 1)
        self.redraw([i])

    def selected_text(self):
        if not self.text_sel:
            return ""
        i, a, n = self._sel_range()
        tp = self.doc.textpage(i)
        return TS.readable(tp.get_text_range(a, n)) if tp is not None else ""

    def copy_selection(self):
        txt = self.selected_text()
        if not txt:
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.status(t("copied", n=len(txt)))

    def _markup_from_selection(self, kind):
        if not self.text_sel:
            return
        i, a, n = self._sel_range()
        rects = TS.range_rects(self.doc.textpage(i), a, n)
        self.text_sel = None
        if not rects:
            self.redraw([i])
            return
        quads = tuple(tuple(r) for r in rects)
        bx = (min(q[0] for q in quads), min(q[1] for q in quads), max(q[2] for q in quads), max(q[3] for q in quads))
        self.doc.add_annot(i, A.make(kind, rect=bx, quads=quads, color=self.color.get(kind, (1, 0.85, 0.1))))

    # ------------------------------------------------------------------ forms
    def _click_field(self, f, w):
        if f.readonly:
            return
        if f.kind == "checkbox":
            self.doc.set_field(f.name, not bool(self.doc.field_value(f.name)))
        elif f.kind == "radio":
            self.doc.set_field(f.name, w.on_state)
        elif f.kind in ("text", "choice"):
            if not self.right.winfo_ismapped():
                self.show_tab("tab_form")
            ent = self.field_widgets.get(f.name)
            if ent is not None:
                try:
                    ent.focus_set()
                except Exception:
                    pass

    def show_right(self, on):
        if on:
            self.right.grid(row=0, column=self.right_col, sticky="ns")
            self._fill_fields()
        else:
            self.right.grid_forget()

    def _commit_entry(self, name, widget):
        try:
            if isinstance(widget, ctk.CTkTextbox):
                v = widget.get("1.0", "end").rstrip("\n")
            else:
                v = widget.get()
        except Exception:
            return
        self.doc.set_field(name, v)

    def commit_fields(self):
        for name, w in self.field_widgets.items():
            if isinstance(w, (ctk.CTkEntry, ctk.CTkTextbox)):
                self._commit_entry(name, w)

    def _fill_fields(self):
        for w in self.right.winfo_children():
            w.destroy()
        self.field_widgets = {}
        rtl = i18n.is_rtl()
        anchor = "e" if rtl else "w"
        if not self.doc.fields:
            ctk.CTkLabel(self.right, text=t("no_fields"), wraplength=220, font=self.app.app_font).pack(pady=20)
            return
        for f in self.doc.fields:
            if f.kind in ("button", "signature"):
                continue
            ctk.CTkLabel(self.right, text=i18n.ui(f.name), font=self.app.bold_font).pack(
                anchor=anchor, padx=6, pady=(8, 0))
            v = self.doc.field_value(f.name)
            state = "disabled" if f.readonly else "normal"
            if f.kind == "text":
                if f.multiline:
                    e = ctk.CTkTextbox(self.right, height=70, font=self.app.text_font)
                    e.insert("1.0", v or "")
                else:
                    e = ctk.CTkEntry(self.right, font=self.app.text_font, justify="right" if rtl else "left")
                    e.insert(0, v or "")
                    e.bind("<Return>", lambda ev, n=f.name, e=e: self._commit_entry(n, e))
                e.bind("<FocusOut>", lambda ev, n=f.name, e=e: self._commit_entry(n, e))
                e.configure(state=state)
                e.pack(fill="x", padx=6, pady=2)
            elif f.kind == "checkbox":
                var = tk.BooleanVar(value=bool(v))
                e = ctk.CTkCheckBox(self.right, text="", variable=var, state=state,
                                    command=lambda n=f.name, var=var: self.doc.set_field(n, var.get()))
                e.pack(anchor=anchor, padx=6)
            elif f.kind == "radio":
                states = [w.on_state for w in f.widgets if w.on_state]
                labels = [i18n.ui(s) for s in states] or ["-"]
                e = ctk.CTkSegmentedButton(self.right, values=labels, state=state,
                                           command=lambda lab, n=f.name, st=states, lb=labels:
                                           self.doc.set_field(n, st[lb.index(lab)]))
                if v in states:
                    e.set(labels[states.index(v)])
                e.pack(fill="x", padx=6, pady=2)
            elif f.kind == "choice":
                opts = list(f.options) or [""]
                shown = [i18n.ui(o) for o in opts]
                e = ctk.CTkOptionMenu(self.right, values=shown, state=state,
                                      command=lambda lab, n=f.name, o=opts, s=shown: self.doc.set_field(
                                          n, o[s.index(lab)]))
                e.set(i18n.ui(v) if v in opts else "")
                e.pack(fill="x", padx=6, pady=2)
            else:
                continue
            self.field_widgets[f.name] = e

    # ------------------------------------------------------------------ document changes
    def _doc_changed(self, what):
        if what in ("pages", "undo", "redo"):
            self.text_sel = None
            if self.selected and (self.selected[0] >= len(self.doc)
                                  or self.doc.find_annot(*self.selected) is None):
                self.selected = None
            if self.query:
                self.hits.clear()
                self.hit_list = []
                self.after(10, lambda: self.find(self.query, force=True, jump=False))
            for i in list(self.thumb_items):
                self.thumbs.delete(self.thumb_items.pop(i))
            self.thumb_photos.clear()
            self.relayout(keep_page=True)
            if self.right.winfo_ismapped():
                self._fill_fields()
        else:
            self.redraw()
        if what in ("annots", "undo", "redo", "pages", "forms"):
            self._thumb_refresh_visible()
            if self.an_frame is not None and self.an_frame.winfo_ismapped():
                self._fill_annots()
        self.app.doc_title_changed(self)

    # ------------------------------------------------------------------ page operations
    def _targets(self):
        sel = sorted(i for i in self.sel_pages if 0 <= i < len(self.doc))
        return sel or [self.cur]

    def rotate_pages(self, d):
        self.doc.rotate_pages(self._targets(), d)

    def delete_pages(self):
        try:
            tg = self._targets()
            self.doc.delete_pages(tg)
            self.cur = max(0, min(tg[0], len(self.doc) - 1))
            self.sel_pages = {self.cur}
            self.relayout()
        except WaraqError as e:
            self.status(i18n.error_text(e), error=True)

    def insert_blank(self):
        self.doc.insert_blank(self.cur + 1)
        self.goto(self.cur + 1)

    def insert_pdf(self, path=None, password=None):
        path = path or self._ask_open([("PDF", "*.pdf")])
        if not path:
            return None
        try:
            n = self.doc.insert_pdf(self.cur + 1, path, password)
        except WaraqError as e:
            if getattr(e, "code", "") in ("needs_password", "wrong_password"):
                pw = self.app.ask_password(path)
                if pw is not None:
                    return self.insert_pdf(path, pw)
            self.status(i18n.error_text(e), error=True)
            return None
        self.goto(self.cur + 1)
        return n

    def duplicate_page(self):
        self.doc.duplicate_page(self.cur)

    def move_page(self, d):
        to = self.cur + d
        if 0 <= to < len(self.doc):
            self.doc.move_page(self.cur, to)
            self.goto(to)

    def extract_pages(self, out=None):
        tg = self._targets()
        out = out or self._ask_save(Path(self.doc.path).stem + f"-p{tg[0] + 1}.pdf")
        if not out:
            return
        try:
            self.doc.save(out, page_positions=tg)
            self.status(t("saved_ok", name=Path(out).name))
            self.app.last_output = str(out)
        except Exception as e:  # noqa: BLE001
            self.status(i18n.error_text(e), error=True)

    # ------------------------------------------------------------------ saving
    def _ask_save(self, name):
        if self.app.test_answers:
            return self.app.test_answers.pop(0)
        return filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=name,
                                            filetypes=[("PDF", "*.pdf")],
                                            initialdir=str(Path(self.doc.path).parent)) or None

    def save(self):
        return self._save_to(self.doc.path)

    def save_as(self, out=None, flatten=False):
        out = out or self._ask_save(Path(self.doc.path).stem + "-edited.pdf")
        if not out:
            return False
        return self._save_to(out, flatten=flatten)

    def _save_to(self, out, flatten=False):
        self.commit_fields()
        self.app.set_busy(True)
        self.update_idletasks()
        try:
            self.doc.save(out, flatten=flatten)
        except Exception as e:  # noqa: BLE001
            self.app.set_busy(False)
            self.status(i18n.error_text(e), error=True)
            self.app.last_error = e
            return False
        self.app.set_busy(False)
        self.app.last_output = str(out)
        self.app.last_error = None
        # reopen what was written so the view shows exactly the saved file
        try:
            new = Document(out, self.doc.password)
        except Exception as e:  # noqa: BLE001
            self.status(i18n.error_text(e), error=True)
            return False
        old = self.doc
        old.listeners.clear()
        self.doc = new
        new.listeners.append(self._doc_changed)
        old.close()
        self.base_cache.clear()
        for i in list(self.thumb_items):
            self.thumbs.delete(self.thumb_items.pop(i))
        self.thumb_photos.clear()
        self.selected = None
        self.relayout()
        if self.right.winfo_ismapped():
            self._fill_fields()
        self.app.add_recent(str(out))
        self.app.doc_title_changed(self)
        self.status(t("saved_ok", name=Path(out).name))
        return True

    def view_state(self):
        return {"zoom": self.zoom, "fit": self.fit, "mode": self.mode, "view_rot": self.view_rot,
                "night": self.night, "cur": self.cur}

    def undo(self):
        self.doc.undo()

    def redo(self):
        self.doc.redo()

    # ------------------------------------------------------------------ search
    def open_find(self):
        self.findbar.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 4))
        self.find_entry.focus_set()
        sel = self.selected_text().strip()
        if sel and "\n" not in sel and len(sel) < 60:
            self.find_entry.delete(0, "end")
            self.find_entry.insert(0, sel)

    def close_find(self):
        self.findbar.grid_forget()
        self.query = ""
        self.hits = {}
        self.hit_list = []
        self.hit_idx = -1
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None
        self.redraw()
        self.focus_canvas()

    def find(self, q, force=False, jump=True):
        q = (q or "").strip()
        if not q:
            return
        if q == self.query and not force and self.hit_list:
            self.find_step(1)
            return
        self.query = q
        self.hits = {}
        self.hit_list = []
        self.hit_idx = -1
        self._search_pos = 0
        self._search_jump = jump
        self._search_start = self.cur
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(1, self._search_tick)

    def _search_tick(self):
        self._search_job = None
        n = len(self.doc)
        t0 = time.perf_counter()
        while self._search_pos < n and time.perf_counter() - t0 < 0.04:
            i = self._search_pos
            self._search_pos += 1
            found = self.doc.search_page(i, self.query)
            if found:
                self.hits[i] = found
                self.hit_list.extend((i, k) for k in range(len(found)))
                if i in self.items:
                    self.compose(i)
        if self._search_jump and self.hit_idx < 0 and self.hit_list:
            after = [k for k, h in enumerate(self.hit_list) if h[0] >= self._search_start]
            if after or self._search_pos >= n:
                self.hit_idx = after[0] if after else 0
                self._show_hit()
        if self._search_pos < n:
            self.find_lbl.configure(text=t("find_searching", p=self._search_pos))
            self._search_job = self.after(1, self._search_tick)
        else:
            self._update_find_lbl()

    def search_done(self):
        return self._search_job is None and self._search_pos >= len(self.doc)

    def _update_find_lbl(self):
        if not self.hit_list:
            self.find_lbl.configure(text=t("find_none"))
        else:
            self.find_lbl.configure(text=t("find_count", i=max(self.hit_idx, 0) + 1, n=len(self.hit_list)))

    def find_step(self, d):
        q = self.find_entry.get().strip()
        if q and q != self.query:
            self.find(q)
            return
        if not self.hit_list:
            return
        old = self.hit_list[self.hit_idx][0] if self.hit_idx >= 0 else None
        self.hit_idx = (self.hit_idx + d) % len(self.hit_list)
        self._show_hit(old)
        self._update_find_lbl()

    def _show_hit(self, old_page=None):
        i, k = self.hit_list[self.hit_idx]
        if self.mode != "continuous" and (i >= len(self.slots) or not self.slots[i]):
            self.cur = i
            self.relayout(keep_page=False)
        rects = self.hits[i][k]
        l, t_, r, b = self.rect_to_canvas(i, rects[0])
        ch = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if not (top + 20 < t_ < top + ch - 40) and self.mode != "single":
            self.canvas.yview_moveto(max(0.0, (t_ - ch / 3) / self.total_h))
        self.cur = i
        self._update_page_widgets()
        self._on_scroll()
        for p in {i, old_page}:
            if p is not None and p in self.items:
                self.compose(p)
        self._update_find_lbl()

    def redact_hits(self):
        if not self.hit_list:
            return
        add = {}
        for i, k in self.hit_list:
            for r in self.hits[i][k]:
                add.setdefault(i, []).append(A.make("redact", rect=(r[0] - 1, r[1] - 1, r[2] + 1, r[3] + 1)))
        self.doc.add_annots_bulk(add)
        self.status(t("redact_note"))

    # ------------------------------------------------------------------ thumbnails
    TW = 120

    def _thumb_yview(self, *a):
        self.thumbs.yview(*a)
        self._thumb_render_visible()

    def _thumb_yscroll(self, a, b):
        self.thumb_bar.set(a, b)
        self._thumb_render_visible()

    def _thumb_wheel(self, e):
        up = getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0
        self.thumbs.yview_scroll(-3 if up else 3, "units")
        self._thumb_render_visible()

    def _thumb_layout(self):
        if not self.thumbs.winfo_ismapped():
            return
        c = self.thumbs
        c.delete("all")
        self.thumb_items = {}
        self.thumb_photos = {}
        cw = max(c.winfo_width(), 150)
        y = 10
        self.thumb_slots = []
        sizes = getattr(self, "_sizes_pt", None)
        if not sizes or len(sizes) != len(self.doc):
            sizes = self._sizes()
        for i, (w, h) in enumerate(sizes):
            th = h * self.TW / max(w, 1)
            if th > self.TW * 1.6:
                th = self.TW * 1.6
            tw = w * th / max(h, 1)
            x = (cw - tw) / 2
            self.thumb_slots.append((x, y, tw, th))
            c.create_rectangle(x, y, x + tw, y + th, fill="white", outline="#888888")
            c.create_text(cw / 2, y + th + 9, text=str(i + 1), fill="#888888", font=("TkDefaultFont", 9))
            y += th + 26
        c.configure(scrollregion=(0, 0, cw, y))
        self._thumb_mark(scroll=True)
        self._thumb_render_visible()

    def _thumb_visible(self):
        if not self.thumb_slots:
            return []
        top = self.thumbs.canvasy(0)
        bot = self.thumbs.canvasy(self.thumbs.winfo_height())
        return [i for i, s in enumerate(self.thumb_slots) if s[1] + s[3] >= top and s[1] <= bot]

    def _thumb_render_visible(self):
        if self._thumb_job:
            return
        self._thumb_job = self.after(30, self._thumb_tick)

    def _thumb_tick(self):
        self._thumb_job = None
        if not self.winfo_exists() or not self.thumbs.winfo_ismapped():
            return
        t0 = time.perf_counter()
        vis = self._thumb_visible()
        for i in [i for i in vis if i not in self.thumb_items]:
            if time.perf_counter() - t0 > 0.05:
                self._thumb_job = self.after(1, self._thumb_tick)
                return
            self._thumb_draw(i)
        if vis:
            for i in list(self.thumb_items):
                if i < vis[0] - 30 or i > vis[-1] + 30:
                    self.thumbs.delete(self.thumb_items.pop(i))
                    self.thumb_photos.pop(i, None)

    def thumbs_ready(self):
        while self._thumb_job or [i for i in self._thumb_visible() if i not in self.thumb_items]:
            if self._thumb_job:
                self.after_cancel(self._thumb_job)
                self._thumb_job = None
            self._thumb_tick()
            if not self.thumbs.winfo_ismapped():
                break

    def _thumb_draw(self, i):
        if i >= len(self.doc) or i >= len(self.thumb_slots):
            return
        x, y, tw, th = self.thumb_slots[i]
        w, _ = self.doc.display_size(i, self.view_rot)
        s = tw / max(w, 1)
        img = self.doc.render(i, s, self.view_rot)
        ref = self.doc.pages[i]
        if ref.annots:
            img = overlay.draw_annots(img, self.doc.geom(i, s, self.view_rot), ref.annots)
        ph = ImageTk.PhotoImage(img)
        self.thumb_photos[i] = ph
        if i in self.thumb_items:
            self.thumbs.itemconfigure(self.thumb_items[i], image=ph)
        else:
            self.thumb_items[i] = self.thumbs.create_image(x, y, image=ph, anchor="nw")
        self.thumbs.tag_raise("mark")

    def _thumb_refresh_visible(self):
        vis = set(self._thumb_visible())
        for i in list(self.thumb_items):
            if i in vis:
                try:
                    self._thumb_draw(i)
                except Exception:
                    pass

    def _thumb_mark(self, scroll=False):
        c = self.thumbs
        c.delete("mark")
        if not self.thumb_slots:
            return
        for i in sorted(self.sel_pages | {self.cur}):
            if i >= len(self.thumb_slots):
                continue
            x, y, tw, th = self.thumb_slots[i]
            col = "#2f7de1" if i == self.cur else "#f0a020"
            c.create_rectangle(x - 3, y - 3, x + tw + 3, y + th + 3, outline=col, width=3, tags=("mark",))
        if scroll and self.cur < len(self.thumb_slots):
            _, y, _, th = self.thumb_slots[self.cur]
            top = c.canvasy(0)
            if not (top <= y and y + th <= top + c.winfo_height()):
                try:
                    total = float(str(c.cget("scrollregion")).split()[3])
                except Exception:
                    total = 1.0
                c.yview_moveto(max(0.0, (y - 20) / max(total, 1)))
                self._thumb_render_visible()

    def _thumb_click(self, e):
        y = self.thumbs.canvasy(e.y)
        for i, (x, ty, tw, th) in enumerate(self.thumb_slots):
            if ty - 4 <= y <= ty + th + 16:
                if e.state & 0x4:      # Ctrl: add / remove from the selection
                    self.sel_pages ^= {i}
                    if not self.sel_pages:
                        self.sel_pages = {self.cur}
                elif e.state & 0x1:    # Shift: range
                    a, b = sorted((self.cur, i))
                    self.sel_pages = set(range(a, b + 1))
                else:
                    self.goto(i)
                    return
                self._thumb_mark()
                self._update_pages_lbl()
                return

    def _fill_bookmarks(self):
        if self.bm_frame is None:
            self.bm_frame = ctk.CTkScrollableFrame(self.side_body, fg_color="transparent")
        for w in self.bm_frame.winfo_children():
            w.destroy()
        items = self.doc.outline()
        if not items:
            ctk.CTkLabel(self.bm_frame, text=t("no_bookmarks"), wraplength=160).pack(pady=12)
            return
        rtl = i18n.is_rtl()
        small = ctk.CTkFont(family=self.app.app_font.cget("family"), size=12)
        for level, title, pos in items[:2000]:
            pad = 4 + 14 * min(level, 6)
            ctk.CTkButton(self.bm_frame, text=i18n.ui(title or "—"), anchor="e" if rtl else "w", height=24,
                          fg_color="transparent", text_color=("gray10", "gray90"), font=small,
                          hover_color=("gray80", "gray25"),
                          command=(lambda p=pos: self.goto(p)) if pos is not None else None
                          ).pack(fill="x", padx=(4, pad) if rtl else (pad, 4))

    def _fill_annots(self):
        if self.an_frame is None:
            self.an_frame = ctk.CTkScrollableFrame(self.side_body, fg_color="transparent")
        for w in self.an_frame.winfo_children():
            w.destroy()
        rtl = i18n.is_rtl()
        small = ctk.CTkFont(family=self.app.app_font.cget("family"), size=12)
        n = 0
        for i, ref in enumerate(self.doc.pages):
            for a in ref.annots:
                n += 1
                if n > 400:
                    break
                label = i18n.raw("annot_page", n=i + 1) + " · " + i18n.raw("k_" + a.kind)
                if a.text:
                    label += ": " + a.text.replace("\n", " ")[:22]
                ctk.CTkButton(self.an_frame, text=i18n.ui(label), anchor="e" if rtl else "w", height=24,
                              fg_color="transparent", text_color=("gray10", "gray90"), font=small,
                              hover_color=("gray80", "gray25"),
                              command=lambda i=i, a=a: self._goto_annot(i, a)).pack(fill="x", padx=4)
        if n == 0:
            ctk.CTkLabel(self.an_frame, text=t("no_annots"), wraplength=160).pack(pady=12)

    def _goto_annot(self, i, a):
        self.goto(i)
        self.after(50, lambda: self._select((i, a.id)))

    def toggle_sidebar(self):
        if self.sidebar.winfo_ismapped():
            self.sidebar.grid_forget()
        else:
            self.sidebar.grid(row=0, column=self.sidebar_col, sticky="ns")
            self.after(30, self._thumb_layout)
        self._schedule_layout()

    # ------------------------------------------------------------------ extras
    def toggle_auto_scroll(self):
        self.auto_scroll = 0 if self.auto_scroll else 1
        if self.auto_scroll and not self._as_job:
            self._as_job = self.after(30, self._as_tick)
        self._mark_tool()

    def _as_tick(self):
        self._as_job = None
        if not self.auto_scroll or not self.winfo_exists():
            return
        a, b = self.canvas.yview()
        if b >= 0.9999:
            self.auto_scroll = 0
            self._mark_tool()
            return
        self.canvas.yview_moveto(a + 1.5 / max(self.total_h, 1))
        self._on_scroll()
        self._as_job = self.after(30, self._as_tick)

    def slide_show(self):
        return SlideShow(self, self.cur)

    def _screenshot(self, i, box):
        sl = self.slots[i]
        l, t_, r, b = box
        k = 2.0
        g = self.doc.geom(i, self.scale * k, self.view_rot)
        img = self.doc.render(i, self.scale * k, self.view_rot)
        if self.doc.pages[i].annots:
            img = overlay.draw_annots(img, g, self.doc.pages[i].annots)
        crop = img.crop((round((l - sl[0]) * k), round((t_ - sl[1]) * k),
                         round((r - sl[0]) * k), round((b - sl[1]) * k)))
        self.app.last_screenshot = crop
        if self.app.test_answers:
            out = self.app.test_answers.pop(0)
        else:
            out = filedialog.asksaveasfilename(defaultextension=".png",
                                               initialfile=Path(self.doc.path).stem + f"-p{i + 1}.png",
                                               filetypes=[("PNG", "*.png")]) or None
        if out:
            crop.save(out)
            self.app.last_output = str(out)
            self.status(t("shot_saved", name=Path(out).name))
        self.set_tool("select")

    def print_doc(self):
        """Hand a copy (with comments) to the system's PDF handler for printing."""
        tmp = Path(tempfile.gettempdir()) / f"waraq-print-{os.getpid()}-{Path(self.doc.path).name}"
        dirty = self.doc.dirty
        try:
            self.commit_fields()
            self.doc.save(tmp)
        except Exception as e:  # noqa: BLE001
            self.status(i18n.error_text(e), error=True)
            return
        finally:
            self.doc.dirty = dirty
        try:
            if sys.platform == "win32":
                os.startfile(str(tmp), "print")  # type: ignore[attr-defined]
            else:
                import shutil
                import subprocess
                lp = shutil.which("lp") or shutil.which("lpr")
                if not lp:
                    raise OSError("no lp")
                subprocess.Popen([lp, str(tmp)])
        except Exception:
            self.status(t("print_failed", path=str(tmp)), error=True)

    def open_tool(self, key):
        if self.doc.dirty:
            self.status(t("save_first"), error=True)
        self.app.open_tool(key, self.doc.path)

    def status(self, text, error=False):
        try:
            self.msg.configure(text=text, text_color=("#b00020", "#ff6b6b") if error else "gray55")
        except Exception:
            pass

    def detach(self):
        """Stop background jobs and listeners; the Document stays open (UI rebuild)."""
        for job in (self._render_job, self._search_job, self._as_job, self._thumb_job, self._layout_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        self.doc.listeners.clear()

    def close(self):
        self.detach()
        self.doc.close()


class SlideShow(tk.Toplevel):
    def __init__(self, view: DocView, start: int):
        super().__init__(view)
        self.view = view
        self.i = start
        self.configure(bg="black")
        try:
            self.attributes("-fullscreen", True)
        except Exception:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.lbl = tk.Label(self, bg="black", bd=0)
        self.lbl.pack(fill="both", expand=True)
        for seq, d in (("<Right>", 1), ("<Down>", 1), ("<space>", 1), ("<Next>", 1), ("<Button-1>", 1),
                       ("<Left>", -1), ("<Up>", -1), ("<Prior>", -1), ("<Button-3>", -1)):
            self.bind(seq, lambda e, d=d: self.step(d))
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(80, self.show)
        self.focus_set()

    def step(self, d):
        self.i = max(0, min(len(self.view.doc) - 1, self.i + d))
        self.show()

    def show(self):
        sw, sh = self.winfo_width(), self.winfo_height()
        if sw < 50:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = self.view.doc.display_size(self.i)
        s = min(sw / w, sh / h)
        img = self.view.doc.render(self.i, s)
        ref = self.view.doc.pages[self.i]
        if ref.annots:
            img = overlay.draw_annots(img, self.view.doc.geom(self.i, s), ref.annots)
        self.photo = ImageTk.PhotoImage(img)
        self.lbl.configure(image=self.photo)
