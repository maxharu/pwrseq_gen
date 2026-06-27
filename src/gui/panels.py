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
from gui.widgets import *


# ============================================================
# NodeListPanel — 左側節點列表（A5 / B5）
# ============================================================

class NodeListPanel(ctk.CTkFrame):
    """左側節點列表：搜尋 + Scrollable + 拖拉重排 + 多選。

    多選：Ctrl+Click toggle。Shift+range 暫不支援。
    """

    def __init__(self, master,
                 on_select: Callable[[int], None],
                 on_reorder: Callable[[int, int], None],
                 on_multi_change: Callable[[set[int]], None],
                 on_add: Callable[[], None],
                 on_delete_btn: Callable[[], None],
                 on_delete: Callable[[], None],
                 on_activate: Callable[[], None],
                 on_disarm: Callable[[], None],
                 **kwargs):
        super().__init__(master, **kwargs)
        self.on_select = on_select
        self.on_reorder = on_reorder
        self.on_multi_change = on_multi_change
        self.on_add = on_add
        self.on_delete_btn = on_delete_btn
        self.on_delete = on_delete
        self.on_activate = on_activate
        self.on_disarm = on_disarm
        self._rails: list[PowerRail] = []
        self._selected: set[int] = set()
        self._primary_idx: Optional[int] = None
        self._row_widgets: dict[int, ctk.CTkFrame] = {}
        self._drag_from: Optional[int] = None  # data index of the dragged row
        self._drag_to: Optional[int] = None  # visual position (0..n-1)
        self._drag_to_di: Optional[int] = None  # data index of row under cursor (for border)
        self._drag_ghost: Optional[tk.Toplevel] = None  # 拖拉跟游標的半透明虛影
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(4, weight=0)

        ctk.CTkLabel(self, text="Sequence Node", font=FONT_TITLE).grid(
            row=0, column=0, sticky="ew", padx=S_SM, pady=(S_MD, S_SM))
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Search node (Ctrl+F)",
                                         textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=S_SM, pady=(0, S_SM))
        self.search_entry.bind("<FocusIn>", lambda _e: self.on_disarm(), add="+")
        self.search_var.trace_add("write", lambda *_: self._render())

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=S_XS, pady=0)

        self.multi_status = ctk.CTkLabel(self, text="", font=FONT_HINT, text_color="gray")
        self.multi_status.grid(row=3, column=0, sticky="ew", padx=S_SM, pady=0)

        self._btn_row = ctk.CTkFrame(self, fg_color="transparent")
        self._btn_row.grid(row=4, column=0, sticky="ew", padx=S_SM, pady=(S_XS, S_SM))
        self._btn_row.columnconfigure(0, weight=1)
        self._btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(self._btn_row, text="+ Add", command=self.on_add).grid(
            row=0, column=0, sticky="ew", padx=(0, S_XS))
        ctk.CTkButton(self._btn_row, text="- Delete", command=self.on_delete_btn).grid(
            row=0, column=1, sticky="ew", padx=(S_XS, 0))

        self.bind("<Delete>", self._on_delete_key)
        self.scroll.bind("<Delete>", self._on_delete_key)
        self.bind("<Configure>", self._on_panel_configure, add="+")

    def _on_panel_configure(self, event=None):
        if event is not None and event.widget is not self:
            return
        self.after_idle(self._sync_scroll_height)

    def _sync_scroll_height(self):
        """CTkScrollableFrame 需手動對齊 grid 分配高度，才會貼近下方 Add/Delete。"""
        try:
            self.update_idletasks()
            bottom = self._btn_row.winfo_y()
            if self.multi_status.winfo_ismapped():
                bottom = min(bottom, self.multi_status.winfo_y())
            h = bottom - self.scroll.winfo_y() - 2
            if h < 40:
                return
            if int(self.scroll.cget("height")) != int(h):
                self.scroll.configure(height=int(h))
        except Exception:
            pass

    def _on_delete_key(self, _event):
        if not self._selected:
            return
        self.on_delete()
        return "break"

    def set_rails(self, rails: list[PowerRail], primary_idx: Optional[int] = None):
        self._rails = rails
        if primary_idx is not None and 0 <= primary_idx < len(rails):
            self._primary_idx = primary_idx
        elif self._primary_idx is not None and self._primary_idx >= len(rails):
            self._primary_idx = None
        self._selected = {i for i in self._selected if 0 <= i < len(rails)}
        self._render()

    def focus_search(self):
        self.search_entry.focus_set()

    def get_selection(self) -> set[int]:
        return set(self._selected)

    def get_primary(self) -> Optional[int]:
        return self._primary_idx

    def clear_selection(self):
        self._selected.clear()
        self._apply_row_bgs()

    def _render(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._row_widgets.clear()
        ft = self.search_var.get().strip().lower()
        for idx, rail in enumerate(self._rails):
            if ft and ft not in rail.name.lower():
                continue
            self._make_row(idx, rail)
        self._update_multi_status()
        self.after_idle(self._sync_scroll_height)

    def _apply_row_bgs(self):
        """輕量更新：只改既有 row 的 fg_color，不 destroy/重建。
        用於 selection / primary 變化等不影響 row 集合的情境，避免按下時整列重繪卡頓。"""
        for i, row in self._row_widgets.items():
            try:
                row.configure(fg_color=self._row_bg(i))
            except Exception:
                pass
        self._update_multi_status()

    def _update_multi_status(self):
        n = len(self._selected)
        if n <= 1:
            self.multi_status.configure(text="")
            self.multi_status.grid_remove()
        else:
            self.multi_status.configure(text=f"{n} nodes selected")
            self.multi_status.grid(row=3, column=0, sticky="ew", padx=S_SM, pady=0)
        self.after_idle(self._sync_scroll_height)

    def _row_bg(self, idx: int) -> tuple[str, str]:
        if idx == self._primary_idx and idx in self._selected:
            return ("#9ec5ff", "#1f6feb")
        if idx == self._primary_idx:
            return ("#cfe0ff", "#264c80")
        if idx in self._selected:
            return ("#dde6f1", "#2a3a52")
        return ("gray86", "gray22")

    def _make_row(self, idx: int, rail: PowerRail):
        bg = self._row_bg(idx)
        row = ctk.CTkFrame(self.scroll, fg_color=bg, corner_radius=4, height=28)
        row.pack(fill="x", pady=1, padx=S_XS)
        self._row_widgets[idx] = row

        type_label = SEQ_TYPE_LABELS.get(rail.seq_type, rail.seq_type)[:6]
        pill = make_pill(row, type_label, rail.seq_type)
        pill.pack(side="left", padx=(S_SM, S_XS), pady=2)

        name = ctk.CTkLabel(row, text=rail.name, font=FONT_BODY, anchor="w")
        name.pack(side="left", fill="x", expand=True, padx=(S_XS, S_SM), pady=2)

        for w in (row, pill, name):
            w.bind("<ButtonPress-1>", lambda e, i=idx: self._on_press(i, e))
            w.bind("<B1-Motion>", lambda e, i=idx: self._on_motion(i, e))
            w.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_release(i, e))

    def _on_press(self, idx: int, event):
        self.on_activate()
        ctrl = (event.state & 0x0004) != 0
        if ctrl:
            if idx in self._selected:
                self._selected.discard(idx)
                if self._primary_idx == idx:
                    self._primary_idx = next(iter(self._selected), None)
            else:
                self._selected.add(idx)
                self._primary_idx = idx
            # 只變顏色不重建 row（row 集合不變）
            self._apply_row_bgs()
            self.on_multi_change(set(self._selected))
            self.focus_set()
            return
        # 普通 click：單選 + 開始拖拉（拖拉提交延後到 release）
        self._selected = {idx}
        self._primary_idx = idx
        self._drag_from = idx
        self._drag_to = idx  # 初始 visual position = data index（_render 後一致）
        self._drag_to_di = idx
        self._apply_row_bgs()
        self.on_multi_change(set(self._selected))
        self.on_select(idx)
        self.focus_set()
        # 預備虛影（lazy：第一次 motion 才真正顯示，避免按下沒拖也建 Toplevel）
        self._ghost_pending_rail = self._rails[idx] if 0 <= idx < len(self._rails) else None

    def _on_motion(self, _idx: int, event):
        if self._drag_from is None:
            return
        # 虛影：第一次 motion 才真正建立 Toplevel
        if self._drag_ghost is None and getattr(self, "_ghost_pending_rail", None) is not None:
            rail = self._ghost_pending_rail
            type_short = SEQ_TYPE_LABELS.get(rail.seq_type, rail.seq_type)[:6]
            self._drag_ghost = DragGhost.create(self, f"[{type_short}] {rail.name}")
            self._ghost_pending_rail = None
        DragGhost.move(self._drag_ghost, event.x_root, event.y_root)
        result = self._find_row_target_idx(event.y_root)
        if result is None:
            return
        target_vp, target_di = result
        if target_vp == self._drag_to:
            return
        # 即時換位視覺效果（不動 data；release 才寫入）
        self._move_row_visually(self._drag_from, target_vp)
        # 還原前一個 target 的邊框；新增當前 target 邊框（用 data index 查 widget）
        prev_di = self._drag_to_di
        if prev_di is not None and prev_di != self._drag_from and prev_di in self._row_widgets:
            try:
                self._row_widgets[prev_di].configure(border_width=0)
            except Exception:
                pass
        if target_di != self._drag_from and target_di in self._row_widgets:
            try:
                self._row_widgets[target_di].configure(
                    border_width=2, border_color=("#1f6feb", "#58a6ff"))
            except Exception:
                pass
        self._drag_to = target_vp
        self._drag_to_di = target_di

    def _move_row_visually(self, from_di: int, target_vp: int):
        """重排 scroll 內 row 的 pack 順序，使 from_di 視覺上位於 target_vp。

        不動 self._rails（data）；release 才呼叫 on_reorder 寫入。
        """
        if not self._row_widgets:
            return
        # 取當前可見 row 的 data index list，按 winfo_y 排序
        pairs = []
        for di, row in self._row_widgets.items():
            try:
                pairs.append((di, row.winfo_rooty()))
            except Exception:
                continue
        if not pairs:
            return
        pairs.sort(key=lambda x: x[1])
        order = [di for di, _y in pairs]
        if from_di not in order:
            return
        from_vp = order.index(from_di)
        if not (0 <= target_vp < len(order)):
            return
        if from_vp == target_vp:
            return
        moved = order.pop(from_vp)
        order.insert(target_vp, moved)
        for di in order:
            row = self._row_widgets.get(di)
            if row is None:
                continue
            try:
                row.pack_forget()
                row.pack(fill="x", pady=1, padx=S_XS)
            except Exception:
                pass

    def _destroy_drag_ghost(self):
        DragGhost.destroy(self._drag_ghost)
        self._drag_ghost = None
        self._ghost_pending_rail = None

    def _on_release(self, _idx: int, _event):
        f, t_vp = self._drag_from, self._drag_to
        self._drag_from = None
        self._drag_to = None
        self._drag_to_di = None
        self._destroy_drag_ghost()
        if f is None or t_vp is None or f == t_vp:
            # 還原邊框（即便沒移動，可能因 motion 加過邊框）
            for row in self._row_widgets.values():
                try:
                    row.configure(border_width=0)
                except Exception:
                    pass
            return
        # 還原所有 row 邊框
        for row in self._row_widgets.values():
            try:
                row.configure(border_width=0)
            except Exception:
                pass
        # t_vp 是 visual position（_rails.pop(f) 後 insert(t_vp, …) 的位置），
        # 與 _move_row_visually 解讀及 _on_node_reordered 內 pop+insert 一致。
        self.on_reorder(f, t_vp)

    def _find_row_target_idx(self, py: int) -> Optional[tuple[int, int]]:
        """回傳 (visual_position, data_index)。

        visual_position：游標所在 row 在 y 排序後的 index (0..n-1)。
        以 visual_position 比較 prev/target 可避免「換位 → row 物理位置變 → 同 y 命中
        不同 data index」造成的震盪。
        """
        cands = []
        for i, row in self._row_widgets.items():
            try:
                top = row.winfo_rooty()
                h = row.winfo_height()
            except Exception:
                continue
            if h <= 0:
                continue
            cands.append((i, top, top + h))
        if not cands:
            return None
        cands.sort(key=lambda x: x[1])
        for vp, (di, _t, b) in enumerate(cands):
            if py < b:
                return (vp, di)
        return (len(cands) - 1, cands[-1][0])


# ============================================================
# PulsePanel — Pulse 訊號區
# ============================================================

class PulsePanel(ctk.CTkFrame):
    """左側 Pulse 訊號管理區（列式 UI，風格對齊 NodeListPanel）。"""

    _ROW_H = 30
    _MAX_SCROLL_H = 150  # 約 5 列；超出可捲動

    def __init__(self, master, on_change: Callable[[list[str]], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_change = on_change
        self._pulses: list[str] = [DEFAULT_PULSE]
        self._selected_idx: Optional[int] = None
        self._row_widgets: dict[int, ctk.CTkFrame] = {}
        self._build_ui()
        self._render()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Timing Signals", font=FONT_TITLE).pack(pady=(S_XS, S_SM))
        self.entry = ctk.CTkEntry(self, placeholder_text="New signal (Enter to add)")
        self.entry.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        self.entry.bind("<Return>", lambda _e: self._on_add())
        self.entry.bind("<KP_Enter>", lambda _e: self._on_add())

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="x", padx=S_XS, pady=(0, S_SM))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_row, text="+ Add", command=self._on_add).grid(
            row=0, column=0, sticky="ew", padx=(0, S_XS))
        ctk.CTkButton(btn_row, text="- Delete", command=self._on_del).grid(
            row=0, column=1, sticky="ew", padx=(S_XS, 0))

    def _row_bg(self, idx: int) -> tuple[str, str]:
        if idx == self._selected_idx:
            return ("#cfe0ff", "#264c80")
        return ("gray86", "gray22")

    def _update_scroll_height(self):
        n = max(1, len(self._pulses))
        h = min(max(self._ROW_H + 6, n * self._ROW_H + 6), self._MAX_SCROLL_H)
        try:
            self.scroll.configure(height=h)
        except Exception:
            pass

    def _render(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._row_widgets.clear()
        for idx, name in enumerate(self._pulses):
            bg = self._row_bg(idx)
            row = ctk.CTkFrame(self.scroll, fg_color=bg, corner_radius=4, height=28)
            row.pack(fill="x", pady=1, padx=S_XS)
            self._row_widgets[idx] = row
            lbl = ctk.CTkLabel(row, text=name, font=FONT_MONO, anchor="w")
            lbl.pack(side="left", fill="x", expand=True, padx=(S_SM, S_SM), pady=2)
            for w in (row, lbl):
                w.bind("<ButtonPress-1>", lambda _e, i=idx: self._on_row_press(i))
        self._update_scroll_height()

    def _on_row_press(self, idx: int):
        self._selected_idx = idx
        for i, row in self._row_widgets.items():
            try:
                row.configure(fg_color=self._row_bg(i))
            except Exception:
                pass

    def set_pulses(self, pulses: list[str]):
        self._pulses = list(pulses) if pulses else [DEFAULT_PULSE]
        if self._selected_idx is not None and self._selected_idx >= len(self._pulses):
            self._selected_idx = None
        self._render()

    def _on_add(self):
        name = normalize_pulse_name(self.entry.get().strip())
        if not name or name == "High":
            messagebox.showwarning("Notice", "Enter pulse name")
            return
        if name in self._pulses:
            messagebox.showwarning("Notice", f"Pulse '{name}' already exists")
            return
        new_list = self._pulses + [name]
        self.on_change(new_list)
        self.entry.delete(0, tk.END)

    def _on_del(self):
        if self._selected_idx is None:
            messagebox.showinfo("Notice", "Select a pulse to delete")
            return
        idx = self._selected_idx
        if len(self._pulses) <= 1:
            messagebox.showwarning("Notice", "At least one pulse required")
            return
        new_list = [p for i, p in enumerate(self._pulses) if i != idx]
        self._selected_idx = None
        self.on_change(new_list)


# ============================================================
# ValidationPanel — 驗證結果（A4，可點擊跳轉）
# ============================================================

class ValidationPanel(ctk.CTkFrame):
    """底部驗證面板：✓ OK / ✕ N errors，錯誤可點擊跳到對應節點。"""

    def __init__(self, master, on_jump: Callable[[str], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_jump = on_jump
        self._collapsed = False
        self._build_ui()

    def _build_ui(self):
        self._header = ctk.CTkFrame(self, fg_color="transparent")
        self._header.pack(fill="x", padx=S_SM, pady=(S_SM, 0))
        self._toggle_btn = ctk.CTkLabel(self._header, text="\u25BC", width=20,
                                         cursor="hand2", font=FONT_BODY)
        self._toggle_btn.pack(side="left")
        self._toggle_btn.bind("<Button-1>", lambda _: self._toggle())
        self._status = ctk.CTkLabel(self._header, text="", font=FONT_SECTION, anchor="w")
        self._status.pack(side="left", padx=(S_SM, 0))
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent", height=80)
        self._body.pack(fill="x", padx=S_SM, pady=(0, S_SM))

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._toggle_btn.configure(text="\u25B6" if self._collapsed else "\u25BC")
        if self._collapsed:
            self._body.pack_forget()
        else:
            self._body.pack(fill="x", padx=S_SM, pady=(0, S_SM))

    def set_result(self, ok: bool, errors: list[str]):
        for w in self._body.winfo_children():
            w.destroy()
        if ok:
            self._status.configure(text="\u2713 OK", text_color=("#1a7f37", "#3fb950"))
            return
        self._status.configure(
            text=f"\u2717 {len(errors)} error{'s' if len(errors) != 1 else ''}",
            text_color=("#cf222e", "#ff7b72"),
        )
        for err in errors:
            target = self._extract_rail_name(err)
            row = ctk.CTkFrame(self._body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            if target:
                lbl = ctk.CTkLabel(row, text=f"\u2022 {err}", font=FONT_HINT,
                                   anchor="w", cursor="hand2",
                                   text_color=("#1f6feb", "#58a6ff"))
                lbl.pack(side="left", fill="x", expand=True)
                lbl.bind("<Button-1>", lambda _e, n=target: self.on_jump(n))
            else:
                ctk.CTkLabel(row, text=f"\u2022 {err}", font=FONT_HINT,
                             anchor="w").pack(side="left", fill="x", expand=True)

    @staticmethod
    def _extract_rail_name(err: str) -> Optional[str]:
        # 嘗試抓出 'XXX' 開頭的 rail 名稱
        if err.startswith("'"):
            end = err.find("'", 1)
            if end > 1:
                return err[1:end]
        return None


class PreviewPanel(ctk.CTkFrame):
    """右側預覽：Verilog / C 文字，或 Schemdraw 時序圖（PNG）。"""

    def __init__(
        self,
        master,
        on_lang_change: Optional[Callable[[], None]] = None,
        on_font_size_change: Optional[Callable[[int], None]] = None,
        on_schemdraw_refresh: Optional[Callable[[], None]] = None,
        on_schemdraw_select_nodes: Optional[Callable[[], None]] = None,
        on_timing_globals_changed: Optional[Callable[[], None]] = None,
        tooltip_fn: Optional[Callable[[Any, str], None]] = None,
        initial_font_size: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.on_lang_change = on_lang_change
        self.on_font_size_change = on_font_size_change
        self.on_schemdraw_refresh = on_schemdraw_refresh
        self.on_schemdraw_select_nodes = on_schemdraw_select_nodes
        self.on_timing_globals_changed = on_timing_globals_changed
        self.tooltip_fn = tooltip_fn
        if initial_font_size in PREVIEW_FONT_SIZES:
            self._font_size = initial_font_size
        else:
            self._font_size = PREVIEW_FONT_SIZE_DEFAULT
        self._schemdraw_source: Optional[Image.Image] = None
        self._schemdraw_zoom: float | None = None
        self._schemdraw_configure_after: Optional[str] = None
        self._schemdraw_display_after: Optional[str] = None
        self._schemdraw_display_gen = 0
        self._canvas_tk_image: Optional[ImageTk.PhotoImage] = None
        self._canvas_image_id: int | None = None
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=S_SM, pady=(S_SM, 0))
        self._title = ctk.CTkLabel(header, text="Verilog Preview", font=FONT_SECTION)
        self._title.pack(side="left")
        self._lang_var = tk.StringVar(value="Verilog")
        self._lang_menu = ctk.CTkOptionMenu(
            header, values=list(PREVIEW_LANGS), variable=self._lang_var, width=100,
            command=self._on_lang_selected,
        )
        self._lang_menu.pack(side="left", padx=(S_SM, 0))
        self._timing_opts = ctk.CTkFrame(header, fg_color="transparent")
        ctk.CTkLabel(self._timing_opts, text="Steps:", font=FONT_HINT).pack(side="left", padx=(0, S_XS))
        self._wd_steps_var = tk.StringVar(value="50")
        self._wd_steps_entry = ctk.CTkEntry(
            self._timing_opts, textvariable=self._wd_steps_var, width=56, height=28,
        )
        self._wd_steps_entry.pack(side="left", padx=(0, S_SM))
        ctk.CTkLabel(self._timing_opts, text="hscale:", font=FONT_HINT).pack(side="left", padx=(0, S_XS))
        self._wd_hscale_var = tk.StringVar(value="1")
        self._wd_hscale_entry = ctk.CTkEntry(
            self._timing_opts, textvariable=self._wd_hscale_var, width=40, height=28,
        )
        self._wd_hscale_entry.pack(side="left")
        for w in (self._wd_steps_entry, self._wd_hscale_entry):
            w.bind("<FocusOut>", self._on_timing_globals_changed, add="+")
            w.bind("<Return>", self._on_timing_globals_changed, add="+")
        if self.tooltip_fn:
            self.tooltip_fn(self._wd_steps_entry, "Timing simulation length (saved with project)")
            self.tooltip_fn(self._wd_hscale_entry, "Timing diagram horizontal scale per step (default 1)")
        self._refresh_btn = ctk.CTkButton(
            header, text="Refresh", width=72, command=self._on_schemdraw_refresh,
        )
        self._nodes_btn = ctk.CTkButton(
            header, text="Nodes…", width=72, command=self._on_schemdraw_nodes,
        )
        self._size_frame = ctk.CTkFrame(header, fg_color="transparent")
        self._size_frame.pack(side="left", padx=(S_SM, 0))
        ctk.CTkLabel(self._size_frame, text="Font", font=FONT_HINT).pack(side="left", padx=(0, S_XS))
        self._font_size_var = tk.StringVar(value=str(self._font_size))
        self._font_menu = ctk.CTkOptionMenu(
            self._size_frame,
            values=[str(s) for s in PREVIEW_FONT_SIZES],
            variable=self._font_size_var,
            width=60,
            command=self._on_font_size_selected,
        )
        self._font_menu.pack(side="left")
        self._status = ctk.CTkLabel(header, text="", font=FONT_HINT, text_color="gray")
        self._status.pack(side="right")
        self._zoom_bar = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self._zoom_bar, text="Zoom", font=FONT_HINT).pack(side="left", padx=(0, S_XS))
        ctk.CTkButton(
            self._zoom_bar, text="−", width=28, command=self._schemdraw_zoom_out,
        ).pack(side="left", padx=(0, S_XS))
        self._zoom_label = ctk.CTkLabel(self._zoom_bar, text="Fit", width=52, font=FONT_HINT)
        self._zoom_label.pack(side="left", padx=(0, S_XS))
        ctk.CTkButton(
            self._zoom_bar, text="+", width=28, command=self._schemdraw_zoom_in,
        ).pack(side="left", padx=(0, S_XS))
        ctk.CTkButton(
            self._zoom_bar, text="Fit", width=40, command=self._schemdraw_zoom_fit,
        ).pack(side="left", padx=(0, S_SM))
        ctk.CTkLabel(
            self._zoom_bar,
            text="拖曳平移 · 滾輪垂直 · Shift+滾輪水平 · Ctrl+滾輪縮放",
            font=FONT_HINT,
            text_color=("gray40", "gray60"),
        ).pack(side="left")
        self._text = ctk.CTkTextbox(self, font=_preview_font(self._font_size), wrap="none",
                                    activate_scrollbars=True)
        self._text.pack(fill="both", expand=True, padx=S_SM, pady=(S_XS, S_SM))
        self._text.configure(state="disabled")
        self._bind_preview_text_events()
        self._img_viewport = ctk.CTkFrame(self, fg_color="transparent")
        self._img_viewport.grid_columnconfigure(0, weight=1)
        self._img_viewport.grid_rowconfigure(0, weight=1)
        canvas_bg = _resolve_canvas_bg(self)
        self._img_canvas = tk.Canvas(
            self._img_viewport,
            highlightthickness=0,
            borderwidth=0,
            bg=canvas_bg,
            cursor="fleur",
        )
        self._img_canvas.grid(row=0, column=0, sticky="nsew")
        self._img_vbar = ctk.CTkScrollbar(
            self._img_viewport, orientation="vertical", command=self._img_canvas.yview,
        )
        self._img_vbar.grid(row=0, column=1, sticky="ns")
        self._img_hbar = ctk.CTkScrollbar(
            self._img_viewport, orientation="horizontal", command=self._img_canvas.xview,
        )
        self._img_hbar.grid(row=1, column=0, sticky="ew")
        self._img_canvas.configure(
            xscrollcommand=self._img_hbar.set,
            yscrollcommand=self._img_vbar.set,
        )
        self._schemdraw_show_canvas_hint("Nodes… to choose lanes, then Refresh.")
        self._bind_schemdraw_viewport_events()
        self._img_viewport.bind("<Configure>", self._on_schemdraw_area_configure)
        self._last_code = ""
        self._update_view_mode()

    def _preview_textbox(self) -> tk.Text:
        return self._text._textbox

    def _bind_preview_text_events(self) -> None:
        for widget in (self._text, self._preview_textbox()):
            widget.bind("<MouseWheel>", self._on_preview_text_wheel, add="+")
            widget.bind("<Shift-MouseWheel>", self._on_preview_text_wheel_shift, add="+")
            widget.bind("<Button-4>", self._on_preview_text_wheel_linux, add="+")
            widget.bind("<Button-5>", self._on_preview_text_wheel_linux, add="+")

    def _preview_font_step(self, direction: int) -> None:
        if self.get_lang() == "Schemdraw":
            return
        sizes = PREVIEW_FONT_SIZES
        try:
            idx = sizes.index(self._font_size)
        except ValueError:
            idx = sizes.index(PREVIEW_FONT_SIZE_DEFAULT)
        new_idx = max(0, min(len(sizes) - 1, idx + direction))
        if new_idx != idx:
            self.set_font_size(sizes[new_idx])

    def _on_preview_text_wheel(self, event) -> str | None:
        if self.get_lang() == "Schemdraw":
            return None
        if event.state & 0x0004:
            if event.delta > 0:
                self._preview_font_step(1)
            elif event.delta < 0:
                self._preview_font_step(-1)
            return "break"
        try:
            self._preview_textbox().yview_scroll(
                int(-PREVIEW_SCROLL_UNITS_Y * (event.delta / 120)), "units",
            )
        except Exception:
            pass
        return "break"

    def _on_preview_text_wheel_shift(self, event) -> str | None:
        if self.get_lang() == "Schemdraw":
            return None
        try:
            self._preview_textbox().xview_scroll(
                int(-PREVIEW_SCROLL_UNITS_X * (event.delta / 120)), "units",
            )
        except Exception:
            pass
        return "break"

    def _on_preview_text_wheel_linux(self, event) -> str | None:
        if self.get_lang() == "Schemdraw":
            return None
        tb = self._preview_textbox()
        if event.state & 0x0004:
            if event.num == 4:
                self._preview_font_step(1)
            elif event.num == 5:
                self._preview_font_step(-1)
            return "break"
        try:
            if event.state & 0x0001:
                if event.num == 4:
                    tb.xview_scroll(-PREVIEW_SCROLL_UNITS_X, "units")
                elif event.num == 5:
                    tb.xview_scroll(PREVIEW_SCROLL_UNITS_X, "units")
            elif event.num == 4:
                tb.yview_scroll(-PREVIEW_SCROLL_UNITS_Y, "units")
            elif event.num == 5:
                tb.yview_scroll(PREVIEW_SCROLL_UNITS_Y, "units")
        except Exception:
            pass
        return "break"

    def _schemdraw_show_canvas_hint(self, text: str) -> None:
        self._canvas_tk_image = None
        self._canvas_image_id = None
        self._img_canvas.delete("all")
        self._img_canvas.configure(scrollregion=(0, 0, 1, 1))
        self._img_canvas.create_text(
            12, 12,
            anchor="nw",
            text=text,
            fill="#888888",
            width=max(self._img_canvas.winfo_width() - 24, 200),
            tags=("hint",),
        )

    def _bind_schemdraw_viewport_events(self) -> None:
        self._img_canvas.bind("<MouseWheel>", self._on_schemdraw_wheel, add="+")
        self._img_canvas.bind("<Shift-MouseWheel>", self._on_schemdraw_wheel_shift, add="+")
        self._img_canvas.bind("<Button-4>", self._on_schemdraw_wheel_linux, add="+")
        self._img_canvas.bind("<Button-5>", self._on_schemdraw_wheel_linux, add="+")
        self._img_canvas.bind("<ButtonPress-1>", self._on_schemdraw_pan_start, add="+")
        self._img_canvas.bind("<B1-Motion>", self._on_schemdraw_pan_move, add="+")

    def _on_schemdraw_pan_start(self, event) -> None:
        if self._schemdraw_source is None:
            return
        self._img_canvas.scan_mark(event.x, event.y)

    def _on_schemdraw_pan_move(self, event) -> None:
        if self._schemdraw_source is None:
            return
        self._img_canvas.scan_dragto(event.x, event.y, gain=1)

    def _save_canvas_view(self) -> tuple[tuple[float, float], tuple[float, float]]:
        try:
            return self._img_canvas.xview(), self._img_canvas.yview()
        except Exception:
            return (0.0, 1.0), (0.0, 1.0)

    def _restore_canvas_view(self, views: tuple[tuple[float, float], tuple[float, float]]) -> None:
        try:
            xview, yview = views
            self._img_canvas.xview_moveto(xview[0])
            self._img_canvas.yview_moveto(yview[0])
        except Exception:
            pass

    def _on_schemdraw_wheel(self, event) -> str | None:
        if self.get_lang() != "Schemdraw" or self._schemdraw_source is None:
            return None
        if event.state & 0x0004:
            if event.delta > 0:
                self._schemdraw_zoom_step(1)
            elif event.delta < 0:
                self._schemdraw_zoom_step(-1)
            return "break"
        try:
            self._img_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
        return "break"

    def _on_schemdraw_wheel_shift(self, event) -> str | None:
        if self.get_lang() != "Schemdraw" or self._schemdraw_source is None:
            return None
        try:
            self._img_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
        return "break"

    def _on_schemdraw_wheel_linux(self, event) -> str | None:
        if self.get_lang() != "Schemdraw" or self._schemdraw_source is None:
            return None
        if event.state & 0x0004:
            if event.num == 4:
                self._schemdraw_zoom_step(1)
            elif event.num == 5:
                self._schemdraw_zoom_step(-1)
            return "break"
        try:
            if event.state & 0x0001:
                if event.num == 4:
                    self._img_canvas.xview_scroll(-1, "units")
                elif event.num == 5:
                    self._img_canvas.xview_scroll(1, "units")
            elif event.num == 4:
                self._img_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self._img_canvas.yview_scroll(1, "units")
        except Exception:
            pass
        return "break"

    def _on_schemdraw_area_configure(self, _event=None) -> None:
        if self._schemdraw_source is None or self._schemdraw_zoom is not None:
            return
        if self._schemdraw_configure_after is not None:
            try:
                self.after_cancel(self._schemdraw_configure_after)
            except Exception:
                pass
        self._schemdraw_configure_after = self.after(120, self._schemdraw_configure_refresh)

    def _schemdraw_configure_refresh(self) -> None:
        self._schemdraw_configure_after = None
        if self._schemdraw_source is not None and self._schemdraw_zoom is None:
            self._refresh_schemdraw_display()

    def _schemdraw_viewport_width(self) -> int:
        return max(self._img_canvas.winfo_width() - 8, 280)

    def _schemdraw_effective_zoom(self) -> float:
        if self._schemdraw_source is None:
            return 1.0
        src_w, _ = self._schemdraw_source.size
        if self._schemdraw_zoom is None:
            max_w = self._schemdraw_viewport_width()
            return min(1.0, max_w / src_w) if src_w > max_w else 1.0
        return self._schemdraw_zoom

    def _schemdraw_display_size(self) -> tuple[int, int]:
        if self._schemdraw_source is None:
            return 0, 0
        src_w, src_h = self._schemdraw_source.size
        zoom = self._schemdraw_effective_zoom()
        return max(1, int(src_w * zoom)), max(1, int(src_h * zoom))

    def _schemdraw_zoom_label_text(self) -> str:
        if self._schemdraw_source is None:
            return "—"
        if self._schemdraw_zoom is None:
            return "Fit"
        return f"{int(round(self._schemdraw_effective_zoom() * 100))}%"

    def _schemdraw_zoom_step(self, direction: int) -> None:
        if self._schemdraw_source is None:
            return
        current = self._schemdraw_effective_zoom()
        factor = SCHEMDRAW_ZOOM_STEP if direction > 0 else 1.0 / SCHEMDRAW_ZOOM_STEP
        self._schemdraw_zoom = max(
            SCHEMDRAW_ZOOM_MIN,
            min(SCHEMDRAW_ZOOM_MAX, current * factor),
        )
        self._schedule_schemdraw_display_refresh()

    def _schemdraw_zoom_in(self) -> None:
        self._schemdraw_zoom_step(1)

    def _schemdraw_zoom_out(self) -> None:
        self._schemdraw_zoom_step(-1)

    def _schemdraw_zoom_fit(self) -> None:
        self._schemdraw_zoom = None
        self._refresh_schemdraw_display(immediate=True)

    def _schedule_schemdraw_display_refresh(self) -> None:
        if self._schemdraw_display_after is not None:
            try:
                self.after_cancel(self._schemdraw_display_after)
            except Exception:
                pass
        self._schemdraw_display_after = self.after(
            SCHEMDRAW_ZOOM_DEBOUNCE_MS,
            self._run_schemdraw_display_refresh,
        )

    def _run_schemdraw_display_refresh(self) -> None:
        self._schemdraw_display_after = None
        self._refresh_schemdraw_display(immediate=False)

    def _refresh_schemdraw_display(self, *, immediate: bool = False) -> None:
        if self._schemdraw_source is None:
            return
        dw, dh = self._schemdraw_display_size()
        src = self._schemdraw_source
        if immediate:
            self._apply_schemdraw_scaled(
                src.resize((dw, dh), Image.Resampling.BILINEAR),
            )
            return
        self._schemdraw_display_gen += 1
        gen = self._schemdraw_display_gen

        def worker() -> None:
            scaled = src.resize((dw, dh), Image.Resampling.BILINEAR)
            self.after(0, lambda: self._apply_schemdraw_scaled(scaled, gen=gen))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_schemdraw_scaled(
        self,
        scaled: Image.Image,
        *,
        gen: int | None = None,
    ) -> None:
        if gen is not None and gen != self._schemdraw_display_gen:
            return
        if self._schemdraw_source is None:
            return
        views = self._save_canvas_view()
        dw, dh = scaled.size
        self._canvas_tk_image = ImageTk.PhotoImage(scaled)
        self._img_canvas.delete("all")
        self._canvas_image_id = self._img_canvas.create_image(
            0, 0, anchor="nw", image=self._canvas_tk_image,
        )
        self._img_canvas.configure(scrollregion=(0, 0, dw, dh))
        self._restore_canvas_view(views)
        self._zoom_label.configure(text=self._schemdraw_zoom_label_text())

    def _on_schemdraw_nodes(self):
        if self.on_schemdraw_select_nodes:
            self.on_schemdraw_select_nodes()

    def _on_schemdraw_refresh(self):
        if self.on_schemdraw_refresh:
            self.on_schemdraw_refresh()

    def _on_timing_globals_changed(self, _event=None) -> None:
        steps, hscale = self.get_timing_globals()
        self.set_timing_globals(steps, hscale)
        if self.on_timing_globals_changed:
            self.on_timing_globals_changed()

    def get_timing_globals(self) -> tuple[int, int]:
        try:
            steps = max(10, int(self._wd_steps_var.get().strip()))
        except (ValueError, tk.TclError):
            steps = 50
        try:
            hscale = _norm_hscale(int(self._wd_hscale_var.get().strip()))
        except (ValueError, tk.TclError):
            hscale = 1
        return steps, hscale

    def set_timing_globals(self, steps: int, hscale: int) -> None:
        self._wd_steps_var.set(str(steps))
        self._wd_hscale_var.set(str(hscale))

    def _update_view_mode(self):
        is_sd = self.get_lang() == "Schemdraw"
        if is_sd:
            self._text.pack_forget()
            self._zoom_bar.pack(fill="x", padx=S_SM, pady=(0, S_XS))
            self._img_viewport.pack(fill="both", expand=True, padx=S_SM, pady=(0, S_SM))
            self._size_frame.pack_forget()
            self._timing_opts.pack(side="left", padx=(S_SM, 0))
            self._nodes_btn.pack(side="left", padx=(S_SM, 0))
            self._refresh_btn.pack(side="left", padx=(S_XS, 0))
        else:
            self._img_viewport.pack_forget()
            self._zoom_bar.pack_forget()
            self._refresh_btn.pack_forget()
            self._nodes_btn.pack_forget()
            self._timing_opts.pack_forget()
            self._size_frame.pack(side="left", padx=(S_SM, 0))
            self._text.pack(fill="both", expand=True, padx=S_SM, pady=(S_XS, S_SM))

    def _on_lang_selected(self, _value: str):
        self._last_code = ""
        self._update_title()
        self._update_view_mode()
        if self.on_lang_change:
            self.on_lang_change()

    def _on_font_size_selected(self, value: str):
        try:
            size = int(value)
        except ValueError:
            return
        if size not in PREVIEW_FONT_SIZES:
            return
        self.set_font_size(size)

    def set_font_size(self, size: int):
        if size not in PREVIEW_FONT_SIZES:
            size = PREVIEW_FONT_SIZE_DEFAULT
        self._font_size = size
        self._font_size_var.set(str(size))
        self._text.configure(font=_preview_font(size))
        if self.on_font_size_change:
            self.on_font_size_change(size)

    def get_font_size(self) -> int:
        return self._font_size

    def _update_title(self):
        lang = self.get_lang()
        self._title.configure(text=f"{lang} Preview")

    def get_lang(self) -> str:
        v = self._lang_var.get()
        return v if v in PREVIEW_LANGS else "Verilog"

    def _set_text(self, content: str):
        if content == self._last_code:
            return
        tb = self._text._textbox
        yfrac, xfrac = tb.yview()[0], tb.xview()[0]
        self._text.configure(state="normal")
        tb.delete("1.0", "end")
        tb.insert("1.0", content)
        try:
            tb.yview_moveto(yfrac)
            tb.xview_moveto(xfrac)
        except Exception:
            pass
        self._text.configure(state="disabled")
        self._last_code = content

    def set_code(self, code: str, status: str = ""):
        self._update_title()
        self._set_text(code)
        self._status.configure(text=status, text_color="gray")

    def set_verilog(self, code: str, status: str = ""):
        """相容舊呼叫；等同 set_code。"""
        self.set_code(code, status=status)

    def set_error(self, msg: str):
        self._update_title()
        self._last_code = ""
        if self.get_lang() == "Schemdraw":
            self.set_schemdraw_error(msg)
            return
        self._set_text(f"// 無法預覽：\n// {msg}")
        self._status.configure(text="error", text_color=("#cf222e", "#ff7b72"))

    def set_schemdraw_status(self, msg: str) -> None:
        self._status.configure(text=msg, text_color=("gray40", "gray60"))

    def set_schemdraw_error(self, msg: str) -> None:
        self._schemdraw_source = None
        self._schemdraw_zoom = None
        self._schemdraw_show_canvas_hint(f"無法預覽：\n{msg}")
        self._zoom_label.configure(text="—")
        self._status.configure(text="error", text_color=("#cf222e", "#ff7b72"))

    def set_schemdraw_image(self, image: Image.Image, status: str = "") -> None:
        self._update_title()
        self._schemdraw_source = image.copy()
        self._refresh_schemdraw_display(immediate=True)
        self._status.configure(text=status, text_color="gray")


# ============================================================
# BatchPanel — 多選批次操作（B5）
# ============================================================

class BatchPanel(ctk.CTkFrame):
    """多選時顯示的批次操作工具列。"""

    def __init__(self, master,
                 on_delete: Callable[[], None],
                 on_set_type: Callable[[str], None],
                 **kwargs):
        super().__init__(master, fg_color=("gray90", "gray19"), corner_radius=6, **kwargs)
        self.on_delete = on_delete
        self.on_set_type = on_set_type
        self._build_ui()

    def _build_ui(self):
        self._label = ctk.CTkLabel(self, text="", font=FONT_SECTION)
        self._label.pack(side="left", padx=S_MD, pady=S_SM)
        ctk.CTkButton(self, text="Set Type \u2192 Output", width=140,
                      command=lambda: self.on_set_type("output")).pack(side="left", padx=S_XS)
        ctk.CTkButton(self, text="Set Type \u2192 Input", width=140,
                      command=lambda: self.on_set_type("input")).pack(side="left", padx=S_XS)
        ctk.CTkButton(self, text="Delete Selected", width=120,
                      fg_color=("#cf222e", "#a40e26"), hover_color=("#a40e26", "#7d0a1c"),
                      command=self.on_delete).pack(side="right", padx=S_MD)

    def set_count(self, n: int):
        self._label.configure(text=f"{n} nodes selected")


