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

from applog import get_logger
from snapshot_history import SnapshotHistory
from gui.theme import *
from gui.widgets import *
from gui.dialogs import *
from gui.panels import *
from gui.settings import GuiSettings, RecentFiles

logger = get_logger(__name__)


class PowerSeqGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._base_title = f"{APP_NAME} {APP_VERSION}"
        self.title(self._base_title)
        self.geometry("1400x850")
        self.minsize(1000, 650)
        self.config_obj = PowerSeqConfig()

        self._dirty = False
        self._topmost = False
        self._inspect_mode = False
        self._show_preview = True
        self._preview_pane_in_paned = False
        self._paned_sash_drag = False
        self._history = SnapshotHistory(UNDO_LIMIT)
        self._preview_after_id: Optional[str] = None
        self._schemdraw_preview_after_id: Optional[str] = None
        self._schemdraw_render_gen = 0
        self._schemdraw_preview_opts: TimingExportOptions | None = None
        self._current_path: Optional[str] = None
        self._gui_settings = GuiSettings()
        self._recent = RecentFiles()
        self._tooltips: list[Tooltip] = []  # 強引用，避免 GC
        self._node_list_delete_armed = False

        self._build_ui()
        self._bind_shortcuts()
        self._refresh_all()
        self.after_idle(self._apply_paned_layout)
        self.after_idle(self.node_list._sync_scroll_height)

    # ---- UI ----
    def _tt(self, widget, text: str):
        """Attach tooltip; keep reference to avoid GC."""
        self._tooltips.append(Tooltip(widget, text))

    def _sep(self, parent):
        """Toolbar 視覺分隔線。

        注意：CTkFrame 預設 height=200，若不顯式指定且 fill='y'，會把整個
        toolbar 撐高到 200+，按鈕變成中段一條、上下大片空白。固定 height=22
        與按鈕視覺對齊。
        """
        s = ctk.CTkFrame(parent, width=1, height=22, fg_color=("gray70", "gray30"))
        s.pack(side="left", fill="y", padx=S_SM, pady=S_XS)
        return s

    # 主動作（產出）著色
    ACCENT_FG = ("#2563eb", "#1d4ed8")
    ACCENT_HOVER = ("#1d4ed8", "#1e40af")
    _GEN_MENU_LABEL = "Generate"
    _GEN_MENU_ITEMS = ("Verilog", "C")
    _EXPORT_MENU_LABEL = "Export"
    _EXPORT_MENU_ITEMS = ("Draw.io", "Schemdraw")

    def _build_ui(self):
        # ----- Toolbar -----
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=S_MD, pady=(S_MD, S_SM))

        # group: file
        self._open_btn = ctk.CTkButton(toolbar, text="Open", width=70, command=self._load_json)
        self._open_btn.pack(side="left", padx=(0, S_XS))
        self._tt(self._open_btn, "Open JSON or Excel  (Ctrl+O)")
        self._recent_btn = ctk.CTkButton(toolbar, text="\u25BC", width=24, command=self._show_recent_menu)
        self._recent_btn.pack(side="left", padx=(0, S_SM))
        self._tt(self._recent_btn, "Recent files")
        b_save = ctk.CTkButton(toolbar, text="Save", width=70, command=self._save_json)
        b_save.pack(side="left", padx=(0, S_XS))
        self._tt(b_save, "Save JSON or Excel  (Ctrl+S)")
        b_saveas = ctk.CTkButton(toolbar, text="Save As...", width=80, command=self._save_json_as)
        b_saveas.pack(side="left", padx=(0, S_SM))
        self._tt(b_saveas, "Save As JSON or Excel  (Ctrl+Shift+S)")

        self._sep(toolbar)

        # group: history
        self._undo_btn = ctk.CTkButton(toolbar, text="\u21B6", width=36, command=self._undo)
        self._undo_btn.pack(side="left", padx=(0, S_XS))
        self._tt(self._undo_btn, "Undo  (Ctrl+Z)")
        self._redo_btn = ctk.CTkButton(toolbar, text="\u21B7", width=36, command=self._redo)
        self._redo_btn.pack(side="left", padx=(0, S_SM))
        self._tt(self._redo_btn, "Redo  (Ctrl+Y)")

        self._sep(toolbar)

        # group: view toggles
        self._inspect_var = tk.BooleanVar(value=False)
        cb_ins = ctk.CTkCheckBox(toolbar, text="Inspect", variable=self._inspect_var,
                                  width=80, command=self._toggle_inspect)
        cb_ins.pack(side="left", padx=(0, S_SM))
        self._tt(cb_ins, "Show only selected node, fully expanded")
        self._preview_var = tk.BooleanVar(value=True)
        cb_pv = ctk.CTkCheckBox(toolbar, text="Preview", variable=self._preview_var,
                                 width=80, command=self._toggle_preview)
        cb_pv.pack(side="left", padx=(0, S_SM))
        self._tt(cb_pv, "Toggle right-side preview (Verilog, C, or Schemdraw timing)")

        # right side: pin / theme / help / validation badge / main actions
        self._pin_btn = ctk.CTkButton(toolbar, text="Pin", width=44, command=self._toggle_topmost)
        self._pin_btn.pack(side="right")
        self._tt(self._pin_btn, "Toggle always-on-top")

        self._theme_var = tk.StringVar(value="Dark")
        theme_menu = ctk.CTkOptionMenu(
            toolbar, values=["Dark", "Light", "System"], width=90,
            variable=self._theme_var, command=self._apply_theme,
        )
        theme_menu.pack(side="right", padx=(0, S_SM))
        self._tt(theme_menu, "Appearance mode")

        b_about = ctk.CTkButton(toolbar, text="About", width=56, command=self._open_about)
        b_about.pack(side="right", padx=(0, S_XS))
        self._tt(b_about, "About this application")
        b_help = ctk.CTkButton(toolbar, text="?", width=28, command=self._open_help)
        b_help.pack(side="right", padx=(0, S_SM))
        self._tt(b_help, "Keyboard shortcuts  (F1)")

        # validation badge：0 errors 隱藏，否則紅色 ⚠ N
        self._validation_badge = ctk.CTkLabel(
            toolbar, text="", font=FONT_CHIP, width=50, corner_radius=10,
            fg_color=("#fee2e2", "#7f1d1d"),
            text_color=("#991b1b", "#fecaca"),
            cursor="hand2",
        )
        # 不立即 pack；_update_validation 中根據錯誤數顯示 / 隱藏
        self._validation_badge.bind("<Button-1>", lambda _e: self._focus_validation())

        export_menu = ctk.CTkOptionMenu(
            toolbar, values=list(self._EXPORT_MENU_ITEMS), width=110,
            command=self._on_export_menu,
            fg_color=self.ACCENT_FG, button_color=self.ACCENT_FG,
            button_hover_color=self.ACCENT_HOVER,
        )
        export_menu.set(self._EXPORT_MENU_LABEL)
        export_menu.pack(side="right", padx=(0, S_SM))
        self._export_menu = export_menu
        self._tt(export_menu, "Export Draw.io (Ctrl+E) or Schemdraw timing (Ctrl+Shift+E)")
        gen_menu = ctk.CTkOptionMenu(
            toolbar, values=list(self._GEN_MENU_ITEMS), width=110,
            command=self._on_generate_menu,
            fg_color=self.ACCENT_FG, button_color=self.ACCENT_FG,
            button_hover_color=self.ACCENT_HOVER,
        )
        gen_menu.set(self._GEN_MENU_LABEL)
        gen_menu.pack(side="right", padx=(0, S_SM))
        self._gen_menu = gen_menu
        self._tt(gen_menu, "Generate Verilog (Ctrl+G) or C (Ctrl+Shift+G)")

        # ----- Body (3-col, resizable) -----
        body_wrap = ctk.CTkFrame(self, fg_color="transparent")
        body_wrap.pack(fill="both", expand=True, padx=S_MD, pady=(0, 0))

        # 用 tk.PanedWindow 提供拖拉分隔；內嵌 ctk frame
        # opaqueresize=False：拖時只顯示分隔線，放手才 reflow，避免 ctk widgets 持續重繪造成卡頓
        sash_bg = "#374151"
        paned = tk.PanedWindow(
            body_wrap, orient=tk.HORIZONTAL,
            sashrelief="flat",
            sashwidth=self._PANED_SASH_WIDTH,
            showhandle=True,
            handlesize=self._PANED_SASH_HANDLE_SIZE,
            bg=sash_bg, bd=0,
            opaqueresize=False,
        )
        paned.pack(fill="both", expand=True)
        self._paned = paned
        self._bind_paned_sash_interaction()

        # left — 節點列表撐滿上方；Timing Signals 固定貼底，避免中間空白
        left_wrap = ctk.CTkFrame(paned, fg_color=("gray90", "gray17"), width=260)
        paned.add(left_wrap, minsize=200, stretch="never", width=260)
        left_wrap.grid_rowconfigure(0, weight=1)
        left_wrap.grid_rowconfigure(1, weight=0)
        left_wrap.grid_columnconfigure(0, weight=1)

        self.pulse_panel = PulsePanel(left_wrap, on_change=self._on_pulses_changed)
        self.pulse_panel.grid(row=1, column=0, sticky="ew", padx=S_XS, pady=(0, S_SM))

        self.node_list = NodeListPanel(
            left_wrap, fg_color="transparent",
            on_select=self._on_node_selected,
            on_reorder=self._on_node_reordered,
            on_multi_change=self._on_multi_changed,
            on_add=self._add_rail,
            on_delete_btn=self._delete_selected,
            on_delete=self._delete_selected_from_node_list,
            on_activate=self._arm_node_list_delete,
            on_disarm=self._disarm_node_list_delete,
        )
        self.node_list.grid(row=0, column=0, sticky="nsew", padx=S_XS, pady=(S_XS, 0))
        self.pulse_panel.entry.bind(
            "<FocusIn>", lambda _e: self._disarm_node_list_delete(), add="+")

        # middle — stretch="never"：視窗變寬時不把額外空間給編輯區
        mid = ctk.CTkFrame(paned, fg_color="transparent")
        paned.add(mid, minsize=480, stretch="never")
        mid.grid_rowconfigure(2, weight=1)
        mid.grid_columnconfigure(0, weight=1)

        # editor mini header：Expand all / Collapse all
        editor_hdr = ctk.CTkFrame(mid, fg_color="transparent")
        editor_hdr.grid(row=0, column=0, sticky="ew", pady=(0, S_XS))
        ctk.CTkLabel(editor_hdr, text="Nodes", font=FONT_SECTION).pack(side="left", padx=(S_XS, S_MD))
        b_exp = ctk.CTkButton(editor_hdr, text="Expand all", width=90, height=24,
                               fg_color="transparent", border_width=1,
                               command=self._expand_all)
        b_exp.pack(side="right", padx=(S_XS, 0))
        b_col = ctk.CTkButton(editor_hdr, text="Collapse all", width=100, height=24,
                               fg_color="transparent", border_width=1,
                               command=self._collapse_all)
        b_col.pack(side="right", padx=(S_XS, 0))

        self.batch_panel = BatchPanel(
            mid, on_delete=self._batch_delete, on_set_type=self._batch_set_type,
        )
        self.batch_panel.grid(row=1, column=0, sticky="ew", pady=(0, S_SM))
        self.batch_panel.grid_remove()  # 初始隱藏

        self.editor_scroll = ctk.CTkScrollableFrame(mid, fg_color="transparent")
        self.editor_scroll.grid(row=2, column=0, sticky="nsew")
        self.collapsible_frames: list[CollapsibleRailFrame] = []

        self.validation = ValidationPanel(
            mid, on_jump=self._jump_to_rail,
            fg_color=("gray90", "gray17"),
        )
        self.validation.grid(row=3, column=0, sticky="ew", pady=(S_SM, 0))

        # right (preview) — 預設略窄，把空間留給中間編輯區（Inv 等）
        self.preview_wrap = ctk.CTkFrame(paned, fg_color=("gray90", "gray17"), width=320)
        paned.add(self.preview_wrap, minsize=240, stretch="always", width=320)
        self._preview_pane_in_paned = True
        self.preview = PreviewPanel(
            self.preview_wrap, fg_color="transparent",
            on_lang_change=self._schedule_preview,
            on_font_size_change=self._gui_settings.set_preview_font_size,
            on_schemdraw_refresh=self._schedule_schemdraw_preview,
            on_schemdraw_select_nodes=self._open_schemdraw_preview_nodes,
            on_timing_globals_changed=self._on_timing_globals_changed,
            tooltip_fn=self._tt,
            initial_font_size=self._gui_settings.get_preview_font_size(),
        )
        self.preview.pack(fill="both", expand=True)

        # ----- Status bar -----
        self._status = StatusBar(self)
        self._status.pack(side="bottom", fill="x")
        self._status._author_lbl.bind("<Button-1>", lambda _e: self._open_about())
        self._status._author_lbl.configure(cursor="hand2")
        self._tt(self._status._author_lbl, "About this application")

    def _bind_shortcuts(self):
        self.bind_all("<Control-s>", lambda _e: self._save_json())
        self.bind_all("<Control-S>", lambda _e: self._save_json())
        self.bind_all("<Control-Shift-s>", lambda _e: self._save_json_as())
        self.bind_all("<Control-Shift-S>", lambda _e: self._save_json_as())
        self.bind_all("<Control-o>", lambda _e: self._load_json())
        self.bind_all("<Control-O>", lambda _e: self._load_json())
        self.bind_all("<F1>", lambda _e: self._open_help())
        self.bind_all("<Control-n>", lambda _e: self._add_rail())
        self.bind_all("<Control-N>", lambda _e: self._add_rail())
        self.bind_all("<Control-g>", lambda _e: self._generate_verilog())
        self.bind_all("<Control-G>", lambda _e: self._generate_verilog())
        self.bind_all("<Control-Shift-g>", lambda _e: self._generate_c())
        self.bind_all("<Control-Shift-G>", lambda _e: self._generate_c())
        self.bind_all("<Control-e>", lambda _e: self._export_drawio())
        self.bind_all("<Control-E>", lambda _e: self._export_drawio())
        self.bind_all("<Control-Shift-e>", lambda _e: self._export_schemdraw())
        self.bind_all("<Control-Shift-E>", lambda _e: self._export_schemdraw())
        self.bind_all("<Control-f>", lambda _e: self.node_list.focus_search())
        self.bind_all("<Control-F>", lambda _e: self.node_list.focus_search())
        self.bind_all("<Control-z>", lambda _e: self._undo())
        self.bind_all("<Control-Z>", lambda _e: self._undo())
        self.bind_all("<Control-y>", lambda _e: self._redo())
        self.bind_all("<Control-Y>", lambda _e: self._redo())
        # Delete：僅在左側 Node 列表點選後生效（避免編輯 Entry 時誤刪）
        self.bind_all("<Delete>", self._on_delete_key)

    def _arm_node_list_delete(self):
        self._node_list_delete_armed = True

    def _disarm_node_list_delete(self):
        self._node_list_delete_armed = False

    def _delete_selected_from_node_list(self):
        if not self._node_list_delete_armed:
            return
        self._delete_selected()

    def _on_delete_key(self, _event):
        if not self._node_list_delete_armed:
            return
        if not self.node_list.get_selection():
            return
        self._delete_selected_from_node_list()
        return "break"

    # ---- title / dirty ----
    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _mark_clean(self):
        self._dirty = False
        self._update_title()

    def _update_title(self):
        self.title(self._base_title + (" *" if self._dirty else ""))
        if hasattr(self, "_status"):
            self._status.set_file(self._current_path, self._dirty)

    def _update_stats(self):
        if not hasattr(self, "_status"):
            return
        n = len(self.config_obj.rails)
        n_out = sum(1 for r in self.config_obj.rails if r.seq_type == "output")
        n_in = sum(1 for r in self.config_obj.rails if r.seq_type == "input")
        self._status.set_stats(n, n_out, n_in)

    def _status_msg(self, msg: str, level: str = "info"):
        if hasattr(self, "_status"):
            self._status.set_message(msg, level)

    # ---- undo / redo ----
    def _push_undo(self):
        snap = json.dumps(self._collect_config().to_dict(), ensure_ascii=False)
        self._history.push(snap)
        self._update_undo_btns()

    def _undo(self):
        if not self._history.can_undo:
            return
        current = json.dumps(self._collect_config().to_dict(), ensure_ascii=False)
        target = self._history.undo(current)
        self.config_obj = PowerSeqConfig.from_dict(json.loads(target))
        self._refresh_all()
        self._mark_dirty()
        self._update_undo_btns()

    def _redo(self):
        if not self._history.can_redo:
            return
        current = json.dumps(self._collect_config().to_dict(), ensure_ascii=False)
        target = self._history.redo(current)
        self.config_obj = PowerSeqConfig.from_dict(json.loads(target))
        self._refresh_all()
        self._mark_dirty()
        self._update_undo_btns()

    def _update_undo_btns(self):
        self._undo_btn.configure(state="normal" if self._history.can_undo else "disabled")
        self._redo_btn.configure(state="normal" if self._history.can_redo else "disabled")

    # ---- per-node Apply ----
    def _apply_rail(self, idx: int):
        """將單一 Node 編輯器內容寫入 config；僅此時更新 header chip 與 Preview。"""
        if idx < 0 or idx >= len(self.collapsible_frames):
            return
        cf = self.collapsible_frames[idx]
        if cf.editor is None:
            return

        old_name = cf.rail.name
        old_type = cf.rail.seq_type
        new_name = cf.editor.entry_name.get().strip()
        if not new_name:
            messagebox.showwarning("Notice", "Name cannot be empty")
            return
        if new_name != old_name and any(
            r.name == new_name for i, r in enumerate(self.config_obj.rails) if i != idx
        ):
            messagebox.showerror("Error", f"Name '{new_name}' already exists")
            return

        self._push_undo()
        new_rail = cf.get_rail()
        if new_name != old_name:
            new_rail.name = old_name
            self.config_obj.rails[idx] = new_rail
            if not self.config_obj.rename_rail(old_name, new_name):
                return
        else:
            self.config_obj.rails[idx] = new_rail

        cf.rail = self.config_obj.rails[idx]
        self._mark_dirty()

        if old_type != cf.rail.seq_type or new_name != old_name:
            self._refresh_all()
            return

        cf.editor.rail = cf.rail
        cf.update_summary()
        self._update_validation()
        self._schedule_preview()

    def _timing_globals_from_toolbar(self) -> tuple[int, int]:
        return self.preview.get_timing_globals()

    def _sync_timing_toolbar_from_config(self) -> None:
        wd = self.config_obj.timing_scenario or {}
        steps = int(wd.get("steps", 50))
        hscale = int(wd.get("hscale", wd.get("cond_step_delay", 1)))
        self.preview.set_timing_globals(steps, hscale)

    def _on_timing_globals_changed(self, _event=None):
        steps, hscale = self.preview.get_timing_globals()
        self.preview.set_timing_globals(steps, hscale)
        self._mark_dirty()

    def _timing_scenario_for_export(self, cfg: PowerSeqConfig) -> TimingScenario:
        return build_timing_scenario(cfg)

    # ---- collect ----
    def _collect_config(self) -> PowerSeqConfig:
        rails = [cf.rail for cf in self.collapsible_frames]
        self.config_obj.rails = rails
        steps, hscale = self._timing_globals_from_toolbar()
        has_input = any(r.seq_type == "input" for r in rails)
        timing_scenario = None
        if has_input or steps != 50 or hscale != 1:
            timing_scenario = {"steps": steps}
            if hscale != 1:
                timing_scenario["hscale"] = hscale
        self.config_obj.timing_scenario = timing_scenario
        return PowerSeqConfig(
            rails=rails,
            module_name=self.config_obj.module_name,
            clock_freq_mhz=self.config_obj.clock_freq_mhz,
            pulse_period_ns=self.config_obj.pulse_period_ns,
            pulses=getattr(self.config_obj, "pulses", None) or [DEFAULT_PULSE],
            timing_scenario=timing_scenario,
        )

    def _input_wave_spec_for(self, rail_name: str) -> InputWaveSpec:
        for r in self.config_obj.rails:
            if r.name == rail_name and r.seq_type == "input":
                return rail_input_wave_spec(r)
        return InputWaveSpec(hi_mode="depends", lo_mode="constant_0")

    def _get_pulses(self) -> list[str]:
        return getattr(self.config_obj, "pulses", None) or [DEFAULT_PULSE]

    def _get_all_rails(self) -> list[PowerRail]:
        return self.config_obj.rails

    # ---- refresh ----
    def _refresh_all(self):
        # 收集當前 expanded 集合，refresh 後保留
        prev_expanded: set[str] = set()
        for cf in self.collapsible_frames:
            if cf._expanded:
                prev_expanded.add(cf.rail.name)

        # validation / preview 會 _collect_config()，須先讓 preview timing 與 config 一致
        self._sync_timing_toolbar_from_config()

        for w in self.editor_scroll.winfo_children():
            w.destroy()
        self.collapsible_frames = []
        for idx, r in enumerate(self.config_obj.rails):
            is_expanded = r.name in prev_expanded
            cf = CollapsibleRailFrame(
                self.editor_scroll, r,
                get_all_rails=self._get_all_rails,
                get_pulses=self._get_pulses,
                on_apply=lambda i=idx: self._apply_rail(i),
                get_input_wave_spec=self._input_wave_spec_for,
                expanded=is_expanded,
            )
            # pack 由 _apply_inspect_mode 統一處理（避免 inspect toggle 後順序錯亂）
            self.collapsible_frames.append(cf)

        primary = self.node_list.get_primary()
        self.node_list.set_rails(self.config_obj.rails, primary_idx=primary)
        self.pulse_panel.set_pulses(self._get_pulses())
        self._apply_inspect_mode()
        self._update_validation()
        self._schedule_preview()
        self._update_undo_btns()
        self._update_stats()

    def _apply_inspect_mode(self):
        # 先全部 pack_forget 再依序重新 pack，避免 toggle 後順序錯亂
        for cf in self.collapsible_frames:
            cf.pack_forget()
        if self._inspect_mode:
            primary = self.node_list.get_primary()
            primary_name = None
            if primary is not None and 0 <= primary < len(self.config_obj.rails):
                primary_name = self.config_obj.rails[primary].name
            for cf in self.collapsible_frames:
                if primary_name is not None and cf.rail.name == primary_name:
                    cf.pack(fill="x", pady=S_XS, padx=S_XS)
                    cf.expand()
        else:
            for cf in self.collapsible_frames:
                cf.pack(fill="x", pady=S_XS, padx=S_XS)

    # ---- node list callbacks ----
    def _on_node_selected(self, idx: int):
        if not (0 <= idx < len(self.collapsible_frames)):
            return
        cf = self.collapsible_frames[idx]
        if self._inspect_mode:
            self._apply_inspect_mode()
            return
        cf.expand()
        self.after(50, lambda: self._scroll_to_widget(cf))

    def _on_node_reordered(self, from_idx: int, to_idx: int):
        if from_idx == to_idx:
            return
        if not (0 <= from_idx < len(self.config_obj.rails)):
            return
        if not (0 <= to_idx < len(self.config_obj.rails)):
            return
        self._push_undo()
        # 重排前先 collect 一次，避免改順序時遺失目前 widget 內未提交的編輯
        self.config_obj = self._collect_config()
        rail = self.config_obj.rails.pop(from_idx)
        self.config_obj.rails.insert(to_idx, rail)
        self._mark_dirty()
        self._refresh_all()

    def _on_multi_changed(self, selected: set[int]):
        if len(selected) > 1:
            self.batch_panel.set_count(len(selected))
            self.batch_panel.grid()
        else:
            self.batch_panel.grid_remove()

    def _scroll_to_widget(self, widget):
        canvas = self.editor_scroll._parent_canvas
        canvas.update_idletasks()
        try:
            widget_y = widget.winfo_y()
            scroll_height = canvas.winfo_height()
            region = canvas.bbox("all")
            if region is None:
                return
            total_height = region[3]
            if total_height <= scroll_height:
                return
            target = max(0.0, min(1.0, widget_y / total_height))
            canvas.yview_moveto(target)
        except Exception:
            pass

    # ---- rail mutations (commit points) ----
    def _add_rail(self):
        self._push_undo()
        self.config_obj = self._collect_config()
        n = len(self.config_obj.rails) + 1
        name = f"SIG_{n}"
        while any(r.name == name for r in self.config_obj.rails):
            n += 1
            name = f"SIG_{n}"
        self.config_obj.rails.append(PowerRail(name=name, seq_type="output"))
        self._mark_dirty()
        self._refresh_all()
        if self.collapsible_frames:
            self.collapsible_frames[-1].expand()

    def _delete_selected(self):
        selection = self.node_list.get_selection()
        if not selection:
            messagebox.showinfo("Notice", "Select a node to delete")
            return
        self._push_undo()
        self.config_obj = self._collect_config()
        for i in sorted(selection, reverse=True):
            if 0 <= i < len(self.config_obj.rails):
                del self.config_obj.rails[i]
        self.node_list.clear_selection()
        self._mark_dirty()
        self._refresh_all()

    def _batch_delete(self):
        self._delete_selected()

    def _batch_set_type(self, new_type: str):
        selection = self.node_list.get_selection()
        if not selection:
            return
        self._push_undo()
        self.config_obj = self._collect_config()
        for i in selection:
            if 0 <= i < len(self.config_obj.rails):
                self.config_obj.rails[i].seq_type = new_type
        self._mark_dirty()
        self._refresh_all()

    # ---- pulses ----
    def _on_pulses_changed(self, new_pulses: list[str]):
        self._push_undo()
        self.config_obj = self._collect_config()
        old_pulses = list(self._get_pulses())
        self.config_obj.pulses = new_pulses
        fallback = new_pulses[0] if new_pulses else DEFAULT_PULSE
        removed = set(old_pulses) - set(new_pulses)
        if removed:
            for r in self.config_obj.rails:
                if getattr(r, "pulse_hi", None) in removed:
                    r.pulse_hi = fallback
                if getattr(r, "pulse_lo", None) in removed:
                    r.pulse_lo = fallback
                if getattr(r, "pulse_force", None) in removed:
                    r.pulse_force = fallback
                if getattr(r, "deb_pulse", None) in removed:
                    r.deb_pulse = fallback
        self._mark_dirty()
        self._refresh_all()

    # ---- inspect / preview toggles ----
    def _toggle_inspect(self):
        self._inspect_mode = bool(self._inspect_var.get())
        self._apply_inspect_mode()

    # 三欄預設寬度（geometry 1400x850、paned 扣 body_wrap 左右 padx）
    _REF_PANED_WIDTH = 1400 - 2 * S_MD
    _DEFAULT_LEFT_WIDTH = 260
    _DEFAULT_MID_WIDTH = 800
    _DEFAULT_PREVIEW_WIDTH = 320
    _PANED_SASH_WIDTH = 8
    _PANED_SASH_HANDLE_SIZE = 12
    _PANED_SASH_HIT_PAD = 4
    _PANED_SASH_CURSOR = "sb_h_double_arrow"

    def _paned_sash_total(self) -> int:
        try:
            sw = int(self._paned.cget("sashwidth"))
            n = max(0, len(self._paned.panes()) - 1)
            return n * sw
        except tk.TclError:
            return 2 * self._PANED_SASH_WIDTH

    def _paned_sash_at(self, x: int) -> int | None:
        """回傳 x 座標附近的 sash 索引（加大 hit 區域）。"""
        paned = self._paned
        try:
            sw = int(paned.cget("sashwidth"))
            half = sw // 2 + self._PANED_SASH_HIT_PAD
            for idx in range(len(paned.panes()) - 1):
                sx, _ = paned.sash_coord(idx)
                if abs(x - sx) <= half:
                    return idx
        except tk.TclError:
            pass
        return None

    def _pointer_over_paned_sash(self) -> bool:
        paned = self._paned
        try:
            px = paned.winfo_pointerx() - paned.winfo_rootx()
            return self._paned_sash_at(px) is not None
        except tk.TclError:
            return False

    def _update_paned_hover_cursor(self, _event=None):
        """依全域座標判斷是否在分隔線上；僅該區域顯示 ↔。"""
        if self._paned_sash_drag:
            return
        try:
            cur = self._PANED_SASH_CURSOR if self._pointer_over_paned_sash() else ""
            self.configure(cursor=cur)
        except tk.TclError:
            pass

    def _bind_paned_sash_interaction(self):
        """加寬 sash 仍難點中時，用座標判斷；拖曳全程維持 ↔ 游標。"""
        paned = self._paned

        def _on_press(event):
            if self._paned_sash_at(event.x) is None:
                return
            self._paned_sash_drag = True
            self.configure(cursor=self._PANED_SASH_CURSOR)
            self._paned_drag_motion_bind = self.bind_all("<B1-Motion>", _on_drag, add="+")
            self._paned_drag_release_bind = self.bind_all("<ButtonRelease-1>", _on_release, add="+")

        def _on_drag(_event):
            if self._paned_sash_drag:
                self.configure(cursor=self._PANED_SASH_CURSOR)

        def _on_release(_event):
            if not self._paned_sash_drag:
                return
            self._paned_sash_drag = False
            for bid in (getattr(self, "_paned_drag_motion_bind", None),
                        getattr(self, "_paned_drag_release_bind", None)):
                if bid:
                    try:
                        self.unbind(bid)
                    except tk.TclError:
                        pass
            self._paned_drag_motion_bind = None
            self._paned_drag_release_bind = None
            self.configure(cursor="")
            self._update_paned_hover_cursor()

        self.bind("<Motion>", self._update_paned_hover_cursor, add="+")
        paned.bind("<ButtonPress-1>", _on_press, add="+")

    def _apply_paned_layout(self):
        """套用預設欄寬：中間編輯區固定較寬；視窗更寬時多出的空間給 preview。"""
        paned = self._paned
        try:
            paned.update_idletasks()
            total = paned.winfo_width()
            if total < 200:
                return
            left = self._DEFAULT_LEFT_WIDTH
            extra = max(0, total - self._REF_PANED_WIDTH)
            preview = max(240, self._DEFAULT_PREVIEW_WIDTH + extra)
            sash_total = self._paned_sash_total()
            mid = total - left - preview - sash_total
            if mid < 480:
                mid = 480
                preview = max(240, total - left - mid - sash_total)
            _, y1 = paned.sash_coord(1)
            paned.sash_place(1, left + mid, y1)
        except (tk.TclError, AttributeError):
            pass

    def _toggle_preview(self):
        self._show_preview = bool(self._preview_var.get())
        paned = self._paned
        if self._show_preview:
            if not self._preview_pane_in_paned:
                paned.add(
                    self.preview_wrap,
                    minsize=240,
                    stretch="always",
                    width=self._DEFAULT_PREVIEW_WIDTH,
                )
                self._preview_pane_in_paned = True
            self.after_idle(self._apply_paned_layout)
            self._schedule_preview()
        elif self._preview_pane_in_paned:
            try:
                paned.forget(self.preview_wrap)
            except tk.TclError:
                pass
            self._preview_pane_in_paned = False

    def _schedule_preview(self):
        if not self._show_preview:
            return
        if self.preview.get_lang() == "Schemdraw":
            self._schedule_schemdraw_preview()
            return
        if self._preview_after_id is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:
                pass
        self._preview_after_id = self.after(300, self._render_preview)

    def _exportable_rail_names(self, cfg: PowerSeqConfig) -> frozenset[str]:
        return frozenset(
            r.name for r in cfg.rails
            if r.seq_type == "input" or r.has_pseqcell
        )

    def _schemdraw_edge_label(self, edge_kinds: frozenset[str]) -> str:
        if edge_kinds == TIMING_EDGE_HI_ONLY:
            return "Hi arrows"
        if edge_kinds == TIMING_EDGE_LO_ONLY:
            return "Lo arrows"
        return "Hi+Lo arrows"

    def _schemdraw_preview_options(self, cfg: PowerSeqConfig) -> TimingExportOptions:
        exportable = self._exportable_rail_names(cfg)
        if self._schemdraw_preview_opts is None:
            return TimingExportOptions(
                include_rails=exportable,
                edge_kinds=TIMING_EDGE_BOTH,
            )
        kept = frozenset(
            n for n in self._schemdraw_preview_opts.include_rails if n in exportable
        )
        if not kept:
            kept = exportable
        return TimingExportOptions(
            include_rails=kept,
            edge_kinds=self._schemdraw_preview_opts.edge_kinds,
        )

    def _open_schemdraw_preview_nodes(self):
        cfg = self._collect_config()
        if not cfg.rails:
            self._status_msg("No nodes. Add rails first.", level="warn")
            return
        existing = getattr(self, "_schemdraw_preview_nodes_dlg", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        initial = self._schemdraw_preview_options(cfg)
        dlg = TimingNodeSelectDialog(
            self,
            cfg.rails,
            self._on_schemdraw_preview_nodes_selected,
            title="Schemdraw Preview — Select Nodes",
            select_hint="Select nodes to include in the Schemdraw preview.",
            action_label="Apply",
            initial_options=initial,
        )
        self._schemdraw_preview_nodes_dlg = dlg

    def _on_schemdraw_preview_nodes_selected(self, opts: TimingExportOptions) -> None:
        self._schemdraw_preview_opts = opts
        self._schedule_schemdraw_preview()

    def _schedule_schemdraw_preview(self):
        if not self._show_preview:
            return
        if self.preview.get_lang() != "Schemdraw":
            return
        if self._schemdraw_preview_after_id is not None:
            try:
                self.after_cancel(self._schemdraw_preview_after_id)
            except Exception:
                pass
        self._schemdraw_preview_after_id = self.after(600, self._start_schemdraw_preview)

    def _start_schemdraw_preview(self):
        self._schemdraw_preview_after_id = None
        if not self._show_preview or self.preview.get_lang() != "Schemdraw":
            return
        try:
            cfg = self._collect_config()
            ok, errs = validate(cfg)
            status = "live" if ok else f"{len(errs)} error{'s' if len(errs) != 1 else ''}"
            scenario = self._timing_scenario_for_export(cfg)
            opts = self._schemdraw_preview_options(cfg)
        except Exception as e:
            self.preview.set_schemdraw_error(str(e))
            return
        if not opts.include_rails:
            self.preview.set_schemdraw_error("No nodes selected. Press Nodes… to choose lanes.")
            return

        self._schemdraw_render_gen += 1
        gen = self._schemdraw_render_gen
        edge_label = self._schemdraw_edge_label(opts.edge_kinds)
        n_nodes = len(opts.include_rails)
        exportable = len(self._exportable_rail_names(cfg))
        self.preview.set_schemdraw_status(
            f"rendering… ({n_nodes}/{exportable} nodes, {edge_label})",
        )

        def worker() -> None:
            try:
                doc = generate_schemdraw_doc(
                    cfg,
                    scenario,
                    output_filename="preview",
                    include_rails=opts.include_rails,
                    edge_kinds=opts.edge_kinds,
                )
                png = render_schemdraw_png_bytes(doc)
                image = Image.open(BytesIO(png))
                edges = len(doc.get("edge", []))
                detail = f"{n_nodes}/{exportable} nodes, {edge_label}, {edges} arrows"
                self.after(
                    0,
                    lambda: self._apply_schemdraw_preview(
                        gen, image, f"{status} · {detail}",
                    ),
                )
            except Exception as e:
                self.after(0, lambda: self._apply_schemdraw_preview_error(gen, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_schemdraw_preview(self, gen: int, image: Image.Image, status: str) -> None:
        if gen != self._schemdraw_render_gen:
            return
        if not self._show_preview or self.preview.get_lang() != "Schemdraw":
            return
        self.preview.set_schemdraw_image(image, status=status)

    def _apply_schemdraw_preview_error(self, gen: int, msg: str) -> None:
        if gen != self._schemdraw_render_gen:
            return
        if not self._show_preview or self.preview.get_lang() != "Schemdraw":
            return
        self.preview.set_schemdraw_error(msg)

    def _preview_c_filename(self) -> str:
        """預覽 C 時決定 output_filename（影響 guard / 函式前綴）。"""
        if self._current_path and self._current_path.lower().endswith(".json"):
            return os.path.splitext(self._current_path)[0] + ".c"
        return "power.c"

    def _render_preview(self):
        self._preview_after_id = None
        if not self._show_preview:
            return
        if self.preview.get_lang() == "Schemdraw":
            return
        try:
            cfg = self._collect_config()
            ok, errs = validate(cfg)
            status = "live" if ok else f"{len(errs)} error{'s' if len(errs) != 1 else ''}"
            lang = self.preview.get_lang()
            if lang == "C":
                code = generate_c(cfg, output_filename=self._preview_c_filename())
            else:
                v_path = None
                if self._current_path and self._current_path.lower().endswith(".json"):
                    v_path = os.path.splitext(self._current_path)[0] + ".v"
                code = generate_verilog(cfg, output_filename=v_path)
            self.preview.set_code(code, status=status)
        except Exception as e:
            self.preview.set_error(str(e))

    # ---- validation ----
    def _update_validation(self):
        cfg = self._collect_config()
        ok, errs = validate(cfg)
        self.validation.set_result(ok, errs)
        # 同步 toolbar badge
        if hasattr(self, "_validation_badge"):
            if ok:
                self._validation_badge.pack_forget()
            else:
                n = len(errs)
                self._validation_badge.configure(text=f"\u26A0 {n}")
                # 確保只 pack 一次
                if not self._validation_badge.winfo_ismapped():
                    self._validation_badge.pack(side="right", padx=(0, S_SM))

    def _focus_validation(self):
        """點 validation badge 時，確保 validation panel 展開並把焦點移到第一個錯誤。"""
        if hasattr(self, "validation") and getattr(self.validation, "_collapsed", False):
            self.validation._toggle()

    def _jump_to_rail(self, name: str):
        for idx, r in enumerate(self.config_obj.rails):
            if r.name == name:
                self.node_list._selected = {idx}
                self.node_list._primary_idx = idx
                self.node_list._render()
                self._on_node_selected(idx)
                return

    # ---- file ops ----
    def _toggle_topmost(self):
        self._topmost = not self._topmost
        self.attributes("-topmost", self._topmost)
        self._pin_btn.configure(
            fg_color=("#10b981", "#059669") if self._topmost
            else ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        )
        self._status_msg("Pinned on top" if self._topmost else "Unpinned")

    # ---- theme ----
    def _apply_theme(self, value: str):
        mode = (value or "Dark").lower()
        if mode not in ("dark", "light", "system"):
            mode = "dark"
        ctk.set_appearance_mode(mode)
        self._status_msg(f"Theme: {value}")

    # ---- help / about ----
    def _open_about(self):
        AboutDialog(self)

    def _open_help(self):
        shortcuts = [
            ("Ctrl+N",        "Add new node"),
            ("Delete",        "Delete selected nodes"),
            ("Ctrl+O",        "Open JSON"),
            ("Ctrl+S",        "Save (overwrite if path known)"),
            ("Ctrl+Shift+S",  "Save As..."),
            ("Ctrl+G",        "Generate Verilog"),
            ("Ctrl+Shift+G",  "Generate C"),
            ("Ctrl+Shift+E",  "Export Schemdraw timing"),
            ("Ctrl+E",        "Export Draw.io"),
            ("Ctrl+F",        "Focus node search"),
            ("Ctrl+Z",        "Undo"),
            ("Ctrl+Y",        "Redo"),
            ("F1",            "Show this dialog"),
        ]
        HelpDialog(self, shortcuts)

    # ---- recent ----
    def _show_recent_menu(self):
        items = self._recent.list()
        menu = tk.Menu(self, tearoff=0)
        if not items:
            menu.add_command(label="(no recent files)", state="disabled")
        else:
            for p in items:
                menu.add_command(label=p, command=lambda _p=p: self._open_path(_p))
        x = self._recent_btn.winfo_rootx()
        y = self._recent_btn.winfo_rooty() + self._recent_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _open_path(self, path: str):
        if not os.path.isfile(path):
            self._status_msg(f"Not found: {path}", level="error")
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".xlsx", ".xlsm", ".xls"):
                from excel_import import load_powerseq_from_excel

                self.config_obj = load_powerseq_from_excel(path)
            else:
                with open(path, encoding="utf-8") as f:
                    self.config_obj = PowerSeqConfig.from_dict(json.load(f))
            self._history.clear()
            self._current_path = path
            self._recent.add(path)
            self._refresh_all()
            self._mark_clean()
            self._status_msg(f"Loaded: {os.path.basename(path)}", level="success")
        except Exception as e:
            logger.exception("Load failed")
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Load failed: {e}", level="error")

    # ---- expand/collapse all ----
    def _expand_all(self):
        for cf in self.collapsible_frames:
            cf.expand()

    def _collapse_all(self):
        for cf in self.collapsible_frames:
            if hasattr(cf, "collapse"):
                cf.collapse()
            elif getattr(cf, "_expanded", False):
                cf._toggle()

    # ---- save / load ----
    def _load_json(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("PowerSeq config", "*.json;*.xlsx;*.xlsm"),
                ("JSON", "*.json"),
                ("Excel", "*.xlsx;*.xlsm"),
                ("All files", "*.*"),
            ]
        )
        if not path:
            return
        self._open_path(path)

    def _save_json(self):
        """Save to current path if known, else fall back to Save As."""
        if self._current_path:
            return self._save_to(self._current_path)
        return self._save_json_as()

    def _save_json_as(self):
        cfg = self._collect_config()
        initial = os.path.basename(self._current_path) if self._current_path else "powerseq.json"
        cur_ext = os.path.splitext(self._current_path or "")[1].lower()
        if cur_ext in (".xlsx", ".xlsm"):
            default_ext = cur_ext.lstrip(".")
        else:
            default_ext = "json"
        path = filedialog.asksaveasfilename(
            defaultextension=default_ext,
            initialfile=initial,
            filetypes=[
                ("JSON", "*.json"),
                ("Excel macro-enabled", "*.xlsm"),
                ("Excel workbook", "*.xlsx"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        return self._save_to(path, cfg)

    def _save_to(self, path: str, cfg: Optional[PowerSeqConfig] = None):
        if cfg is None:
            cfg = self._collect_config()
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".xlsx", ".xlsm", ".xls"):
                from excel_export import export_powerseq_to_excel

                export_powerseq_to_excel(cfg, path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
            self.config_obj = cfg
            self._current_path = path
            self._recent.add(path)
            self._mark_clean()
            self._status_msg(f"Saved: {os.path.basename(path)}", level="success")
        except Exception as e:
            logger.exception("Save failed")
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Save failed: {e}", level="error")

    def _on_generate_menu(self, choice: str):
        if choice == "Verilog":
            self._generate_verilog()
        elif choice == "C":
            self._generate_c()
        self._gen_menu.set(self._GEN_MENU_LABEL)

    def _on_export_menu(self, choice: str):
        if choice == "Draw.io":
            self._export_drawio()
        elif choice == "Schemdraw":
            self._export_schemdraw()
        self._export_menu.set(self._EXPORT_MENU_LABEL)

    def _generate_verilog(self):
        self._generate_code(
            "Verilog", ".v", [("Verilog", "*.v")], generate_verilog,
        )

    def _generate_c(self):
        self._generate_code(
            "C", ".c", [("C source", "*.c")], generate_c,
        )

    def _generate_code(self, label: str, ext: str, filetypes, generator):
        cfg = self._collect_config()
        ok, errs = validate(cfg)
        if not ok:
            messagebox.showerror("Validation Failed", "\n".join(errs))
            self._status_msg(f"{len(errs)} validation error(s); cannot generate", level="error")
            return
        path = filedialog.asksaveasfilename(defaultextension=ext, filetypes=filetypes)
        if not path:
            return
        try:
            code = generator(cfg, output_filename=path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            self._status_msg(f"Generated {label}: {os.path.basename(path)}", level="success")
        except Exception as e:
            logger.exception("Generate %s failed", label)
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Generate {label} failed: {e}", level="error")

    def _run_schemdraw_export(self, export_opts: TimingExportOptions) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".svg",
            filetypes=[
                ("SVG", "*.svg"),
                ("PNG", "*.png"),
                ("PDF", "*.pdf"),
                ("All", "*"),
            ],
        )
        if not path:
            return
        try:
            cfg2 = self._collect_config()
            scenario = self._timing_scenario_for_export(cfg2)
            export_schemdraw_from_options(cfg2, scenario, export_opts, path)
            n = len(export_opts.include_rails)
            if export_opts.edge_kinds == TIMING_EDGE_HI_ONLY:
                edge_label = "Hi arrows"
            elif export_opts.edge_kinds == TIMING_EDGE_LO_ONLY:
                edge_label = "Lo arrows"
            else:
                edge_label = "Hi+Lo arrows"
            self._status_msg(
                f"Exported Schemdraw ({n} lanes, {edge_label}): {os.path.basename(path)}",
                level="success",
            )
        except ImportError as e:
            messagebox.showerror("Schemdraw Missing", str(e))
            self._status_msg("Schemdraw export failed: package not installed", level="error")
        except Exception as e:
            logger.exception("Schemdraw export failed")
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Schemdraw export failed: {e}", level="error")

    def _export_schemdraw(self):
        cfg = self._collect_config()
        ok, errs = validate(cfg)
        if not ok:
            messagebox.showerror("Validation Failed", "\n".join(errs))
            self._status_msg(f"{len(errs)} validation error(s); cannot export", level="error")
            return
        if not cfg.rails:
            self._status_msg("No nodes. Add rails first.", level="warn")
            return
        opts = self._schemdraw_preview_options(cfg)
        if not opts.include_rails:
            messagebox.showwarning(
                "Schemdraw Export",
                "No nodes selected. Open Preview → Schemdraw and press Nodes… to choose lanes.",
            )
            self._status_msg("Schemdraw export cancelled: no nodes selected", level="warn")
            return
        self._run_schemdraw_export(opts)

    def _export_drawio(self):
        cfg = self._collect_config()
        if not cfg.rails:
            self._status_msg("No nodes. Add rails first.", level="warn")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xml",
            filetypes=[("Draw.io XML", "*.xml"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            cfg2 = self._collect_config()
            xml = generate_drawio(cfg2)
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml)
            self._status_msg(f"Exported: {os.path.basename(path)}", level="success")
        except Exception as e:
            logger.exception("Export failed")
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Export failed: {e}", level="error")


def run_gui():
    if not ensure_not_expired():
        return
    app = PowerSeqGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
