import json
import os
import threading
import tkinter as tk
from io import BytesIO
from tkinter import filedialog, messagebox
from typing import Any, Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from app_expiry import EXPIRY_LAST_VALID, ensure_not_expired
from config_models import (
    PowerRail,
    PowerSeqConfig,
    DEFAULT_PULSE,
    apply_input_wave_dict,
    build_timing_scenario,
    normalize_pulse_name,
    rail_input_wave_spec,
)
from drawio_export import generate_drawio
from group_logic import INTRA_OP_LABELS, intra_op_label, normalize_intra_op
from validator import validate
from verilog_generator import generate_verilog
from c_generator import generate_c
from timing_export import (
    TIMING_EDGE_BOTH,
    TIMING_EDGE_HI_ONLY,
    TIMING_EDGE_LO_ONLY,
    TimingExportOptions,
    timing_edge_kinds_from_choice,
)
from timing_sim import (
    InputWaveSpec,
    TimingScenario,
    _norm_hscale,
)
from schemdraw_export import (
    export_schemdraw_from_options,
    generate_schemdraw_doc,
    render_schemdraw_png_bytes,
)

from gui.theme import *


class AboutDialog(ctk.CTkToplevel):
    """About 對話框：產品名稱、版本、作者、版權與試用期限。"""

    def __init__(self, master):
        super().__init__(master)
        self.title("About")
        self.geometry("400x300")
        self.resizable(False, False)
        self.transient(master)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=S_LG, pady=S_LG)

        ctk.CTkLabel(body, text=APP_NAME, font=ABOUT_FONT_TITLE).pack(pady=(0, S_XS))
        ctk.CTkLabel(body, text=f"Version {APP_VERSION.lstrip('v')}", font=ABOUT_FONT_VERSION).pack(
            pady=(0, S_MD),
        )

        for line in (
            f"Author: {APP_AUTHOR}",
            f"Copyright © {APP_COPYRIGHT_YEAR} {APP_AUTHOR}. All rights reserved.",
            "Built with Python / CustomTkinter",
        ):
            ctk.CTkLabel(
                body, text=line, font=ABOUT_FONT_BODY, text_color=("gray25", "gray70"),
            ).pack(pady=2)

        ctk.CTkButton(body, text="Close", width=80, command=self.destroy).pack(pady=(S_MD, 0))
        self.bind("<Escape>", lambda _e: self.destroy())


class TimingNodeSelectDialog(ctk.CTkToplevel):
    """選擇要包含在 Schemdraw 時序圖中的節點（模擬仍用全案）。"""

    def __init__(
        self,
        master,
        rails: list[PowerRail],
        export_callback: Callable[[TimingExportOptions], None],
        *,
        title: str = "Timing Diagram — Select Nodes",
        select_hint: str = "Select nodes to include in the timing diagram.",
        action_label: str = "Export…",
        initial_options: TimingExportOptions | None = None,
    ):
        super().__init__(master)
        self._export_callback = export_callback
        self._action_label = action_label
        self.title(title)
        self.geometry("560x700")
        self.minsize(420, 480)
        self.transient(master)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        self._rails = list(rails)
        self._vars: dict[str, ctk.BooleanVar] = {}
        self._row_frames: list[ctk.CTkFrame] = []
        self._anchor_idx: int | None = None
        if initial_options is not None:
            if initial_options.edge_kinds == TIMING_EDGE_HI_ONLY:
                edge_default = "hi"
            elif initial_options.edge_kinds == TIMING_EDGE_LO_ONLY:
                edge_default = "lo"
            else:
                edge_default = "both"
        else:
            edge_default = "both"
        self._edge_var = ctk.StringVar(value=edge_default)
        self._initial_include = (
            frozenset(initial_options.include_rails) if initial_options else None
        )

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=S_MD, pady=(S_MD, S_SM))
        ctk.CTkLabel(
            top,
            text=select_hint,
            font=FONT_BODY,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            top,
            text="Simulation uses all nodes; only the diagram lanes are filtered.",
            font=FONT_HINT,
            text_color=("gray40", "gray60"),
            anchor="w",
        ).pack(fill="x", pady=(S_XS, 0))
        ctk.CTkLabel(
            top,
            text=(
                "Shift+Click: range from anchor (first node until you click without Shift). "
                "Click without Shift sets a new anchor."
            ),
            font=FONT_HINT,
            text_color=("gray40", "gray60"),
            anchor="w",
        ).pack(fill="x", pady=(S_XS, 0))

        tool = ctk.CTkFrame(self, fg_color="transparent")
        tool.pack(fill="x", padx=S_MD, pady=(0, S_SM))
        self.search_var = ctk.StringVar()
        search = ctk.CTkEntry(tool, placeholder_text="Search node", textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True, padx=(0, S_SM))
        search.bind("<KeyRelease>", lambda _e: self._apply_filter())
        ctk.CTkButton(tool, text="All", width=52, command=self._select_all).pack(side="left", padx=(0, S_XS))
        ctk.CTkButton(tool, text="None", width=52, command=self._select_none).pack(side="left")

        self._count_label = ctk.CTkLabel(
            self, text="", font=FONT_HINT, text_color=("gray40", "gray60"), anchor="w",
        )
        self._count_label.pack(fill="x", padx=S_MD, pady=(0, S_XS))

        edge_box = ctk.CTkFrame(self, fg_color="transparent")
        edge_box.pack(fill="x", padx=S_MD, pady=(0, S_SM))
        edge_row = ctk.CTkFrame(edge_box, fg_color="transparent")
        edge_row.pack(fill="x")
        ctk.CTkLabel(
            edge_row,
            text="Condition arrows:",
            font=FONT_SECTION,
            anchor="w",
        ).pack(side="left", padx=(0, S_MD))
        for value, label in (
            ("both", "Hi and Lo"),
            ("hi", "Hi only"),
            ("lo", "Lo only"),
        ):
            ctk.CTkRadioButton(
                edge_row,
                text=label,
                variable=self._edge_var,
                value=value,
            ).pack(side="left", padx=(0, S_MD))

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=S_MD, pady=(0, S_SM))

        for idx, rail in enumerate(self._rails):
            if self._initial_include is None:
                selected = True
            else:
                selected = rail.name in self._initial_include
            var = ctk.BooleanVar(value=selected)
            self._vars[rail.name] = var
            row = ctk.CTkFrame(self.scroll, fg_color="transparent")
            row.pack(fill="x", pady=1)
            tag = SEQ_TYPE_LABELS.get(rail.seq_type, rail.seq_type)
            cb = ctk.CTkCheckBox(
                row,
                text=f"[{tag}] {rail.name}",
                variable=var,
            )
            cb.pack(anchor="w")
            click_handler = lambda e, i=idx: self._on_checkbox_click(i, e)
            cb._canvas.bind("<Button-1>", click_handler)
            cb._text_label.bind("<Button-1>", click_handler)
            self._row_frames.append(row)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=S_MD, pady=(0, S_MD))
        ctk.CTkButton(btns, text="Close", width=90, command=self._close).pack(side="right", padx=(S_SM, 0))
        ctk.CTkButton(btns, text=self._action_label, width=90, command=self._export).pack(side="right")

        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._update_count()
        search.focus_set()

    def _on_checkbox_click(self, idx: int, event) -> None:
        """Explorer-style anchor + Shift range (replaces CTkCheckBox internal toggle)."""
        shift = bool(event.state & 0x0001)
        name = self._rails[idx].name
        if shift:
            anchor = self._anchor_idx if self._anchor_idx is not None else 0
            new_state = not self._vars[name].get()
            lo, hi = sorted((anchor, idx))
            for i in range(lo, hi + 1):
                self._vars[self._rails[i].name].set(new_state)
        else:
            self._vars[name].set(not self._vars[name].get())
            self._anchor_idx = idx
        self._update_count()

    def _apply_filter(self) -> None:
        ft = self.search_var.get().strip().lower()
        for row in self._row_frames:
            row.pack_forget()
        for rail, row in zip(self._rails, self._row_frames):
            if not ft or ft in rail.name.lower() or ft in rail.seq_type.lower():
                row.pack(fill="x", pady=1)

    def _select_all(self) -> None:
        ft = self.search_var.get().strip().lower()
        for rail in self._rails:
            if not ft or ft in rail.name.lower() or ft in rail.seq_type.lower():
                self._vars[rail.name].set(True)
        self._update_count()

    def _select_none(self) -> None:
        ft = self.search_var.get().strip().lower()
        for rail in self._rails:
            if not ft or ft in rail.name.lower() or ft in rail.seq_type.lower():
                self._vars[rail.name].set(False)
        self._update_count()

    def _update_count(self) -> None:
        n = sum(1 for v in self._vars.values() if v.get())
        self._count_label.configure(text=f"{n} / {len(self._rails)} nodes selected")

    def _export_options(self) -> TimingExportOptions | None:
        selected = {name for name, var in self._vars.items() if var.get()}
        if not selected:
            messagebox.showwarning(
                "No Nodes Selected",
                "Select at least one node.",
                parent=self,
            )
            return None
        return TimingExportOptions(
            include_rails=frozenset(selected),
            edge_kinds=timing_edge_kinds_from_choice(self._edge_var.get()),
        )

    def _export(self) -> None:
        opts = self._export_options()
        if opts is not None:
            self._export_callback(opts)

    def _close(self) -> None:
        self.destroy()


class HelpDialog(ctk.CTkToplevel):
    """快捷鍵清單對話框（F1 開啟）。"""

    def __init__(self, master, shortcuts: list[tuple[str, str]]):
        super().__init__(master)
        self.title("Help")
        self.geometry("420x460")
        self.transient(master)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        ctk.CTkLabel(self, text="Keyboard Shortcuts", font=FONT_TITLE).pack(pady=(S_MD, S_SM))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=S_MD, pady=(0, S_MD))
        for key, desc in shortcuts:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=key, font=FONT_MONO, width=140, anchor="w",
                         text_color=("#1f6feb", "#58a6ff")).pack(side="left")
            ctk.CTkLabel(row, text=desc, font=FONT_BODY, anchor="w").pack(side="left")
        ctk.CTkButton(self, text="Close", width=80, command=self.destroy).pack(pady=(0, S_MD))
        self.bind("<Escape>", lambda _e: self.destroy())
