"""
Power Sequence Config GUI v1.4

v1.4（相對 v1.3）：
- Excel 工作簿 I/O（.xlsx／.xlsm）：Open／Save、Nodes／Conditions／Lists、xlsm Sync 按鈕
- WaveDrom：工具列 steps／hscale；Input Hi/Lo 併入節點；移除獨立 WaveDrom 對話框
- JSON 精簡：移除未使用的 recover／cycle_sync／od；wavedrom_scenario 僅保留全域 steps／hscale
- Draw.io：Cell H_Deb／L_Deb 顯示 debounce 實際時間（cycle × pulse）
- UI：Input 標題列移除 WHi／WLo chip；Preview 字級可記憶；每 Node 獨立 Apply 才更新 config／Preview

v1.3（相對 v1.2）：
- Draw.io：邏輯閘改 *1.xml（numInputs=1）、Cell 對齊 PSEQCELL.v／PSEQCELL.xml（含連接點）
- 工具列 Generate／Export 改為下拉選單（快捷鍵不變）
- 走線鎖定精簡為 drawio_edge_freeze；移除未使用 layout／golden2 比對

v1.2（相對 v1.1）：
- Hi/Lo/Force Cond 三段抽象為 CondSectionFrame，去除 ~500 行重複（B1）
- Hi/Lo/Force 改 Tab 顯示，節點展開後高度減半（B2）
- 三段以顏色語意區分：Hi=綠 / Lo=紅 / Force=琥珀（A1）
- Header chip 化（[Output] [HI:8] [LO:4] [INIT:0]）（A2）
- Dirty flag（title 顯示 *）、快捷鍵 Ctrl+S/Shift+S/O/N/G/E/F/Z/Y/Delete、F1 Help（A3）
- 自動 commit（FocusOut / radio trace），拿掉每張卡片的 Apply 按鈕（A4）→ v1.4 恢復每 Node Apply
- 左側 list 升級為 CTkScrollableFrame，支援搜尋、多選批次刪除 / 改類型（A5/B5）
- Browse / Inspect 雙模式（B3）
- rename_rail 抽到 PowerSeqConfig（B4）
- 三欄式主版面：節點列表 / 屬性編輯 / Verilog 即時預覽（右欄可收合）（C1）
- 屬性表化（General / Timing / Conditions / Debounce 四個 section）（C2）
- Undo / Redo（json snapshot stack，bounded 50）（C4）
- 設計系統 tokens（spacing / fonts / colors）（C5）

未實作：節點群組（C3，需要 schema 變更，目前以搜尋 + 名稱前綴排序替代）
"""
import json
import os
import threading
import tkinter as tk
from io import BytesIO
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

# 關閉自動 DPI 縮放，避免縮放時 dropdown 出現 TclError。
ctk.deactivate_automatic_dpi_awareness()

from app_expiry import EXPIRY_LAST_VALID, ensure_not_expired
from config_models import (
    PowerRail,
    PowerSeqConfig,
    DEFAULT_PULSE,
    apply_input_wave_dict,
    build_wavedrom_scenario,
    normalize_pulse_name,
    rail_input_wave_spec,
)
from drawio_export import generate_drawio
from group_logic import INTRA_OP_LABELS, intra_op_label, normalize_intra_op
from validator import validate
from verilog_generator import generate_verilog
from c_generator import generate_c
from wavedrom_export import (
    WAVEDROM_EDGE_BOTH,
    WAVEDROM_EDGE_HI_ONLY,
    WAVEDROM_EDGE_LO_ONLY,
    WaveDromExportOptions,
    generate_wavedrom_json,
    wavedrom_edge_kinds_from_choice,
)
from wavedrom_sim import (
    DEP_HIGH,
    DEP_LOW,
    InputWaveSpec,
    WaveDromScenario,
    _norm_hscale,
)
from schemdraw_export import (
    export_schemdraw_from_options,
    generate_schemdraw_doc,
    render_schemdraw_png_bytes,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ============================================================
# Design tokens
# ============================================================

SEQ_TYPE_LABELS = {"output": "Output", "input": "Input"}
DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"

# spacing
S_XS, S_SM, S_MD, S_LG = 2, 4, 8, 16

APP_NAME = "Power Sequence Config"
APP_AUTHOR = "Haru"
APP_VERSION = "v1.4"
APP_COPYRIGHT_YEAR = 2026

# About dialog only — change here without affecting the rest of the GUI
ABOUT_FONT_TITLE = ("", 16, "bold")
ABOUT_FONT_VERSION = ("", 14, "bold")
ABOUT_FONT_BODY = ("", 14)

# fonts
FONT_TITLE = ("", 14, "bold")
FONT_SECTION = ("", 12, "bold")
FONT_BODY = ("", 12)
FONT_CHIP = ("", 12, "bold")
FONT_HINT = ("", 12)
FONT_MONO = ("Consolas", 12)

# Hi / Lo / Force 色彩語意（與 Draw.io 輸出可同步）
COND_THEME = {
    "hi": {
        "name": "Hi Cond",
        "short": "Hi",
        "border": ("#2ea043", "#3fb950"),
        "text":   ("#1a7f37", "#3fb950"),
    },
    "lo": {
        "name": "Lo Cond",
        "short": "Lo",
        "border": ("#cf222e", "#ff7b72"),
        "text":   ("#cf222e", "#ff7b72"),
    },
    "force": {
        "name": "Force Cond",
        "short": "Force",
        "border": ("#9a6700", "#e3b341"),
        "text":   ("#9a6700", "#e3b341"),
    },
}


def _resolve_ctk_color(fg_color, appearance: str | None = None) -> str:
    """CTk fg_color（含 tuple / transparent）→ tk 可用的單色字串。"""
    if fg_color in (None, "transparent"):
        return ""
    if isinstance(fg_color, (list, tuple)):
        mode = appearance or ctk.get_appearance_mode()
        return fg_color[1] if mode == "Dark" else fg_color[0]
    return str(fg_color)


def _resolve_canvas_bg(widget: tk.Misc) -> str:
    """沿 widget 樹向上找非 transparent 的 fg_color，供 tk.Canvas bg 使用。"""
    w: tk.Misc | None = widget
    while w is not None:
        try:
            color = _resolve_ctk_color(w.cget("fg_color"))
        except Exception:
            color = ""
        if color:
            return color
        w = w.master
    return "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0"


def _make_hscroll_row(parent, *, bg_color: str = "", row_height: int = 34) -> ctk.CTkFrame:
    """單列橫向捲動容器；回傳 inner frame，子元件以 pack(side=left) 放入。"""
    shell = ctk.CTkFrame(parent, fg_color="transparent")
    shell.pack(fill="x", padx=S_SM, pady=S_XS)
    shell.grid_columnconfigure(0, weight=1)

    canvas = tk.Canvas(
        shell, height=row_height, highlightthickness=0, borderwidth=0,
        bg=bg_color or _resolve_ctk_color(parent.cget("fg_color")),
    )
    canvas.grid(row=0, column=0, sticky="ew")

    hbar = ctk.CTkScrollbar(shell, orientation="horizontal", command=canvas.xview)
    inner = ctk.CTkFrame(canvas, fg_color="transparent")
    win = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _sync_scroll(_evt=None):
        try:
            inner.update_idletasks()
            req_w = inner.winfo_reqwidth()
            req_h = max(row_height, inner.winfo_reqheight())
            canvas.configure(scrollregion=(0, 0, req_w, req_h), height=req_h)
            canvas.itemconfigure(win, width=req_w)
            viewport = canvas.winfo_width()
            if req_w > viewport and viewport > 0:
                canvas.configure(xscrollcommand=hbar.set)
                if not hbar.winfo_ismapped():
                    hbar.grid(row=1, column=0, sticky="ew", pady=(2, 0))
            else:
                hbar.grid_remove()
                canvas.configure(xscrollcommand=lambda *_a: None)
                canvas.xview_moveto(0)
        except Exception:
            pass

    def _on_shift_wheel(evt):
        try:
            canvas.xview_scroll(int(-1 * (evt.delta / 120)), "units")
            return "break"
        except Exception:
            pass

    inner.bind("<Configure>", _sync_scroll, add="+")
    shell.bind("<Configure>", _sync_scroll, add="+")
    for w in (canvas, inner):
        w.bind("<Shift-MouseWheel>", _on_shift_wheel, add="+")
    shell.after_idle(_sync_scroll)
    return inner

TYPE_THEME = {
    "output": {"pill_bg": ("#dbeafe", "#1e3a8a"), "pill_fg": ("#1e3a8a", "#dbeafe")},
    "input":  {"pill_bg": ("#fae8ff", "#581c87"), "pill_fg": ("#581c87", "#fae8ff")},
}

USE_LABELS = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
USE_REVERSE = {v: k for k, v in USE_LABELS.items()}

INPUT_WAVE_MODES = [
    ("Low (0)", "constant_0"),
    ("High (1)", "constant_1"),
    ("Custom wave", "custom"),
    ("Signal cond.", "depends"),
]
INPUT_WAVE_MODE_BY_LABEL = {label: val for label, val in INPUT_WAVE_MODES}
INPUT_WAVE_LABEL_BY_MODE = {val: label for label, val in INPUT_WAVE_MODES}

UNDO_LIMIT = 50


# ============================================================
# Helpers
# ============================================================

def _safe_int(s: str, default: int) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def make_chip(parent, text: str, *, fg=None, bg=None, font=FONT_CHIP) -> ctk.CTkLabel:
    if bg is None:
        bg = ("gray82", "gray28")
    if fg is None:
        fg = ("gray20", "gray85")
    return ctk.CTkLabel(
        parent, text=text, font=font,
        fg_color=bg, text_color=fg, corner_radius=6,
    )


def make_pill(parent, text: str, seq_type: str) -> ctk.CTkLabel:
    th = TYPE_THEME.get(seq_type, TYPE_THEME["output"])
    return ctk.CTkLabel(
        parent, text=text, font=FONT_CHIP,
        fg_color=th["pill_bg"], text_color=th["pill_fg"], corner_radius=8,
    )


# ============================================================
# CondSectionFrame — Hi / Lo / Force 共用條件區塊（B1）
# ============================================================

class CondSectionFrame(ctk.CTkFrame):
    """Hi / Lo / Force 三段條件區塊的共用實作。

    kind: "hi" | "lo" | "force" — 決定配色與標題。
    groups: list[list[str]]，group 內 Operation（AND/OR/XOR），groups 間 OR。
    """

    def __init__(self, master, kind: str,
                 get_dep_options: Callable[[], list[str]],
                 is_pseqcell_for: Callable[[str], bool],
                 initial_groups: list[list[str]],
                 initial_inv_groups: list[list[bool]],
                 initial_use_groups: list[list[str]],
                 initial_inv_flat: dict,
                 initial_use_flat: dict,
                 initial_group_inv: Optional[list[bool]] = None,
                 initial_group_intra_op: Optional[list[str]] = None,
                 show_group_inv: bool = True,
                 on_change: Optional[Callable[[], None]] = None,
                 get_self_name: Optional[Callable[[], str]] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.kind = kind
        self.theme = COND_THEME[kind]
        self.get_dep_options = get_dep_options
        self.get_self_name = get_self_name
        self.is_pseqcell_for = is_pseqcell_for
        self.on_change = on_change
        self.show_group_inv = show_group_inv

        self.groups: list[list[str]] = [list(g) for g in (initial_groups or [[]])]
        if not self.groups:
            self.groups = [[]]

        self._init_inv_groups = initial_inv_groups or []
        self._init_use_groups = initial_use_groups or []
        self._init_inv_flat = initial_inv_flat or {}
        self._init_use_flat = initial_use_flat or {}

        # 每個 group：整組反相、區塊內運算（AND/OR/XOR）。與 self.groups 同序。
        self.group_inv: list[bool] = [bool(x) for x in (initial_group_inv or [])]
        self.group_intra_op: list[str] = [
            normalize_intra_op(x) for x in (initial_group_intra_op or [])
        ]
        self._sync_group_inv_len()
        self._sync_group_intra_op_len()

        self.inv_vars: dict[tuple[int, int], ctk.BooleanVar] = {}
        self.use_vars: dict[tuple[int, int], ctk.StringVar] = {}
        self.group_inv_vars: dict[int, ctk.BooleanVar] = {}
        self.group_intra_op_vars: dict[int, ctk.StringVar] = {}
        self.rows: dict[tuple[int, int], ctk.CTkFrame] = {}
        self.group_frames: list[dict] = []

        self._cond_drag_state: Optional[dict] = None
        self._group_drag_state: Optional[dict] = None

        self._build_ui()

    def _fire_change(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:
                pass

    def _sync_group_inv_len(self):
        """讓 self.group_inv 與 self.groups 等長（補 False / 截斷）。"""
        n = len(self.groups)
        if len(self.group_inv) < n:
            self.group_inv = self.group_inv + [False] * (n - len(self.group_inv))
        elif len(self.group_inv) > n:
            self.group_inv = self.group_inv[:n]

    def _sync_group_intra_op_len(self):
        n = len(self.groups)
        if len(self.group_intra_op) < n:
            self.group_intra_op = self.group_intra_op + ["and"] * (n - len(self.group_intra_op))
        elif len(self.group_intra_op) > n:
            self.group_intra_op = self.group_intra_op[:n]

    # ---- initial value lookup ----
    def _get_initial_inv(self, gi: int, ii: int, name: str) -> bool:
        if self._init_inv_groups:
            try:
                return bool(self._init_inv_groups[gi][ii])
            except IndexError:
                pass
        return bool(self._init_inv_flat.get(name, False))

    def _get_initial_use(self, gi: int, ii: int, name: str) -> str:
        if self._init_use_groups:
            try:
                return str(self._init_use_groups[gi][ii])
            except IndexError:
                pass
        return str(self._init_use_flat.get(name, "self"))

    def _allowed_use_labels(self, name: str) -> list[str]:
        """可選的 use 標籤。自我參照時移除會造成同欄位組合迴圈的選項。

        output 在自己的 Hi 段選自己時，不可再引用自己的 Hi Cond；
        "Node"(self) 在 C 產生器也會對應到同 kind 的 condition，故一併移除。
        """
        labels = list(USE_LABELS.values())
        self_name = self.get_self_name() if self.get_self_name else ""
        if name and self_name and name == self_name:
            forbidden = {USE_LABELS["self"], USE_LABELS.get(self.kind, "")}
            labels = [lb for lb in labels if lb not in forbidden]
        return labels

    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, S_SM))
        ctk.CTkLabel(toolbar, text="group 內 Operation, groups 間 OR",
                     font=FONT_HINT, text_color="gray").pack(side="left", padx=(0, S_MD))
        ctk.CTkButton(toolbar, text="+ Add Group", width=100,
                      command=self.add_group).pack(side="left")

        self.groups_container = ctk.CTkFrame(self, fg_color="transparent")
        self.groups_container.pack(fill="x")
        self._rebuild_groups_ui()

    def _rebuild_groups_ui(self):
        for w in self.groups_container.winfo_children():
            w.destroy()
        self.group_frames.clear()
        self.inv_vars.clear()
        self.use_vars.clear()
        self.group_inv_vars.clear()
        self.group_intra_op_vars.clear()
        self.rows.clear()
        self._sync_group_inv_len()
        self._sync_group_intra_op_len()
        for gi in range(len(self.groups)):
            self._add_group_ui(gi)

    def _add_group_ui(self, gi: int):
        group = self.groups[gi]
        frame = ctk.CTkFrame(
            self.groups_container,
            fg_color=("gray96", "gray18"),
            border_color=self.theme["border"],
            border_width=1,
            corner_radius=6,
        )
        frame.pack(fill="x", pady=S_XS, padx=(S_LG, S_SM))

        group_bg = _resolve_ctk_color(frame.cget("fg_color"))
        header = _make_hscroll_row(frame, bg_color=group_bg, row_height=34)

        handle = ctk.CTkLabel(header, text="\u2261", width=18,
                              text_color=("gray40", "gray70"), cursor="hand2")
        handle.pack(side="left", padx=(0, S_SM))
        handle.bind("<ButtonPress-1>",
                    lambda _e, g=gi: self._on_group_drag_start(g))
        handle.bind("<B1-Motion>",
                    lambda e: self._on_group_drag_motion(e))
        handle.bind("<ButtonRelease-1>",
                    lambda _e: self._on_group_drag_release())

        ctk.CTkLabel(header, text=f"Group {gi + 1}",
                     text_color=self.theme["text"],
                     font=FONT_CHIP, width=56).pack(side="left", padx=(0, S_SM))

        dep_options = self.get_dep_options() or [""]
        combo = ctk.CTkComboBox(header, values=dep_options, width=100)
        combo.pack(side="left", padx=(0, S_SM))
        combo.set(dep_options[0])

        ctk.CTkButton(header, text="+ Add", width=56,
                      command=lambda g=gi: self._add_cond_to_group(g)).pack(
            side="left", padx=(0, S_SM)
        )
        ctk.CTkButton(header, text="Del Group", width=72,
                      command=lambda g=gi: self._remove_group(g)).pack(
            side="left", padx=(0, S_SM)
        )

        op_init = intra_op_label(self.group_intra_op[gi] if gi < len(self.group_intra_op) else "and")
        op_var = ctk.StringVar(value=op_init)
        self.group_intra_op_vars[gi] = op_var
        op_var.trace_add("write", lambda *_a, g=gi: self._on_group_intra_op_changed(g))
        op_row = ctk.CTkFrame(header, fg_color="transparent")
        op_row.pack(side="left", padx=(0, S_SM))
        ctk.CTkLabel(op_row, text="Op", font=FONT_HINT).pack(side="left", padx=(0, 4))
        ctk.CTkOptionMenu(
            op_row, values=list(INTRA_OP_LABELS), variable=op_var, width=68,
        ).pack(side="left")

        if self.show_group_inv:
            inv_init = bool(self.group_inv[gi]) if gi < len(self.group_inv) else False
            gvar = ctk.BooleanVar(value=inv_init)
            self.group_inv_vars[gi] = gvar
            gvar.trace_add("write", lambda *_a, g=gi: self._on_group_inv_changed(g))
            ctk.CTkCheckBox(
                header, text="Inv", variable=gvar, width=72,
            ).pack(side="left", padx=(0, S_SM))

        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        # list_frame 在首列加入時才 pack
        self.group_frames.append({"frame": frame, "combo": combo, "list_frame": list_frame})

        for ii, name in enumerate(group):
            self._add_cond_row(gi, name, ii)

    def _add_cond_row(self, gi: int, name: str, ii: int | None = None):
        if ii is None:
            ii = len(self.groups[gi]) - 1
        key = (gi, ii)
        is_const = name in (DEP_HIGH, DEP_LOW)
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        can_use_hi_lo = (not is_const) and self.is_pseqcell_for(name)

        inv_val = False if is_const else self._get_initial_inv(gi, ii, name)
        use_val = USE_LABELS.get(self._get_initial_use(gi, ii, name), "Node")
        allowed_use = self._allowed_use_labels(name)
        if use_val not in allowed_use:
            use_val = allowed_use[0] if allowed_use else "Node"
        self.inv_vars[key] = ctk.BooleanVar(value=inv_val)
        self.use_vars[key] = ctk.StringVar(value=use_val)
        # trace 在初值設定後才註冊，避免初始化就觸發
        self.inv_vars[key].trace_add("write", lambda *_: self._fire_change())
        self.use_vars[key].trace_add("write", lambda *_: self._fire_change())

        list_frame = self.group_frames[gi]["list_frame"]
        if not list_frame.winfo_ismapped():
            list_frame.pack(fill="x", padx=S_SM, pady=(0, S_XS))

        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        self.rows[key] = row

        rh = ctk.CTkLabel(row, text="\u2261", width=18,
                          text_color=("gray40", "gray70"), cursor="hand2")
        rh.pack(side="left", padx=(2, S_SM))
        rh.bind("<ButtonPress-1>",
                lambda _e, g=gi, i=ii: self._on_cond_drag_start(g, i))
        rh.bind("<B1-Motion>",
                lambda e, g=gi: self._on_cond_drag_motion(g, e))
        rh.bind("<ButtonRelease-1>",
                lambda _e, g=gi: self._on_cond_drag_release(g))

        ctk.CTkLabel(row, text=display_name, width=120, anchor="w").pack(side="left", padx=(0, S_SM))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.inv_vars[key], width=50).pack(side="left", padx=(0, S_SM))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=allowed_use,
                            variable=self.use_vars[key], width=100).pack(side="left", padx=(0, S_SM))
        captured = key
        ctk.CTkButton(row, text="Del", width=50,
                      command=lambda k=captured: self._remove_cond_by_key(k)).pack(side="left")

    def _on_group_inv_changed(self, gi: int):
        if 0 <= gi < len(self.group_inv):
            try:
                self.group_inv[gi] = bool(self.group_inv_vars[gi].get())
            except Exception:
                self.group_inv[gi] = False
        self._fire_change()

    def _on_group_intra_op_changed(self, gi: int):
        if 0 <= gi < len(self.group_intra_op):
            try:
                self.group_intra_op[gi] = normalize_intra_op(
                    self.group_intra_op_vars[gi].get()
                )
            except Exception:
                self.group_intra_op[gi] = "and"
        self._fire_change()

    def add_group(self):
        self.groups.append([])
        self.group_inv.append(False)
        self.group_intra_op.append("and")
        self._rebuild_groups_ui()
        self._fire_change()

    def _add_cond_to_group(self, gi: int):
        gf = self.group_frames[gi]
        sel = gf["combo"].get()
        if not sel:
            return
        dep_key = DEP_HIGH if sel == "High" else (DEP_LOW if sel == "Low" else sel)
        self.groups[gi].append(dep_key)
        self._add_cond_row(gi, dep_key)
        self._fire_change()

    def _remove_cond_by_key(self, key: tuple[int, int]):
        gi, ii = key
        if gi >= len(self.groups) or ii >= len(self.groups[gi]):
            return
        snap = self._snapshot_inv_use_all()
        del self.groups[gi][ii]
        self._rebuild_groups_ui()
        # 還原 snapshot：同 group 內 ii 之後的鍵要左移 1
        for (old_gi, old_ii), (inv, use) in snap.items():
            if old_gi != gi:
                new_key = (old_gi, old_ii)
            elif old_ii < ii:
                new_key = (old_gi, old_ii)
            elif old_ii > ii:
                new_key = (old_gi, old_ii - 1)
            else:
                continue
            if new_key in self.inv_vars:
                self.inv_vars[new_key].set(inv)
            if new_key in self.use_vars:
                self.use_vars[new_key].set(use)
        self._fire_change()

    def _remove_group(self, gi: int):
        if gi >= len(self.groups):
            return
        snap = self._snapshot_inv_use_all()
        del self.groups[gi]
        if gi < len(self.group_inv):
            del self.group_inv[gi]
        if gi < len(self.group_intra_op):
            del self.group_intra_op[gi]
        if not self.groups:
            self.groups = [[]]
            self.group_inv = [False]
            self.group_intra_op = ["and"]
        self._rebuild_groups_ui()
        # 還原 snapshot：被移除 group 之後的 gi 要左移 1
        for (old_gi, old_ii), (inv, use) in snap.items():
            if old_gi < gi:
                new_key = (old_gi, old_ii)
            elif old_gi > gi:
                new_key = (old_gi - 1, old_ii)
            else:
                continue
            if new_key in self.inv_vars:
                self.inv_vars[new_key].set(inv)
            if new_key in self.use_vars:
                self.use_vars[new_key].set(use)
        self._fire_change()

    def _snapshot_inv_use_all(self) -> dict[tuple[int, int], tuple[bool, str]]:
        snap = {}
        keys = set(self.inv_vars.keys()) | set(self.use_vars.keys())
        for k in keys:
            try:
                inv = bool(self.inv_vars[k].get()) if k in self.inv_vars else False
            except Exception:
                inv = False
            try:
                use = self.use_vars[k].get() if k in self.use_vars else "Node"
            except Exception:
                use = "Node"
            snap[k] = (inv, use)
        return snap

    # ---- row drag ----
    def _on_cond_drag_start(self, gi: int, ii: int):
        # 預備虛影 label：用 dep 顯示名稱（High/Low 或實際 rail 名稱）
        pending_text = None
        if 0 <= gi < len(self.groups) and 0 <= ii < len(self.groups[gi]):
            name = self.groups[gi][ii]
            display = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
            pending_text = f"\u2261 {display}"
        self._cond_drag_state = {
            "gi": gi, "from": ii, "target": ii, "target_di": ii,
            "ghost": None, "pending_text": pending_text,
        }
        key = (gi, ii)
        if key in self.rows:
            try:
                self.rows[key].configure(fg_color=("#cfe0ff", "#3a4a6a"))
            except Exception:
                pass

    def _on_cond_drag_motion(self, gi: int, event):
        st = self._cond_drag_state
        if not st or st["gi"] != gi:
            return
        # 虛影 lazy 建立 + 跟隨游標
        if st["ghost"] is None and st.get("pending_text"):
            st["ghost"] = DragGhost.create(self, st["pending_text"], bg=self.theme["text"][0])
            st["pending_text"] = None
        DragGhost.move(st["ghost"], event.x_root, event.y_root)
        result = self._find_row_target_idx(gi, event.y_root)
        if result is None:
            return
        target_vp, target_di = result
        prev_vp = st.get("target", st["from"])
        if target_vp == prev_vp:
            return
        # 即時換位視覺效果（不動 data；release 才寫入）
        # target_vp 是 visual position，跟 _move_cond_visually 的 target_idx 一致
        self._move_cond_visually(gi, st["from"], target_vp)
        prev_di = st.get("target_di", st["from"])
        prev_key = (gi, prev_di)
        if prev_di != st["from"] and prev_key in self.rows:
            try:
                self.rows[prev_key].configure(border_width=0)
            except Exception:
                pass
        new_key = (gi, target_di)
        if target_di != st["from"] and new_key in self.rows:
            try:
                self.rows[new_key].configure(border_width=2,
                                             border_color=("#1f6feb", "#58a6ff"))
            except Exception:
                pass
        st["target"] = target_vp
        st["target_di"] = target_di

    def _move_cond_visually(self, gi: int, from_idx: int, target_idx: int):
        """重排 group gi 內所有 cond row 的 pack 順序為 [..., target_idx 位置含 from_idx, ...]。

        不動 self.groups（data）；只用 pack_forget + pack 重新排版。
        """
        keys = sorted([k for k in self.rows if k[0] == gi], key=lambda k: k[1])
        if not keys:
            return
        n = len(keys)
        if not (0 <= from_idx < n and 0 <= target_idx < n):
            return
        order = list(range(n))
        moved = order.pop(from_idx)
        order.insert(target_idx, moved)
        for ii in order:
            row = self.rows.get((gi, ii))
            if row is None:
                continue
            try:
                row.pack_forget()
                row.pack(fill="x", pady=1)
            except Exception:
                pass

    def _on_cond_drag_release(self, gi: int):
        st = self._cond_drag_state
        if not st or st["gi"] != gi:
            return
        from_idx = st["from"]
        to_idx = st.get("target", from_idx)
        DragGhost.destroy(st.get("ghost"))
        self._cond_drag_state = None
        for (g, _i), row in self.rows.items():
            if g != gi:
                continue
            try:
                row.configure(border_width=0, fg_color="transparent")
            except Exception:
                pass
        if from_idx != to_idx:
            self._reorder_cond(gi, from_idx, to_idx)
            self._fire_change()

    def _find_row_target_idx(self, gi: int, py: int):
        """回傳 (visual_position, data_index) tuple。

        visual_position：游標所在 row 在 y 排序後的 index (0..n-1)。
        data_index：對應 row 的 data index（用於查 self.rows[(gi, di)]）。

        用 visual_position 比較 prev/target 可避免「換位後 row 物理位置變 → 同 y 命中
        不同 data_index」造成的震盪。
        """
        cands = []
        for (g, i), row in self.rows.items():
            if g != gi:
                continue
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
        last_di = cands[-1][0]
        return (len(cands) - 1, last_di)

    def _reorder_cond(self, gi: int, from_idx: int, to_idx: int):
        if gi >= len(self.groups):
            return
        group = self.groups[gi]
        if from_idx == to_idx:
            return
        if not (0 <= from_idx < len(group)) or not (0 <= to_idx < len(group)):
            return
        snap = self._snapshot_inv_use_in_group(gi)
        new_order = list(range(len(group)))
        moved = new_order.pop(from_idx)
        new_order.insert(to_idx, moved)
        self.groups[gi] = [group[old] for old in new_order]
        self._rebuild_groups_ui()
        for new_i, old_i in enumerate(new_order):
            new_key = (gi, new_i)
            if old_i in snap:
                inv, use = snap[old_i]
                if new_key in self.inv_vars:
                    self.inv_vars[new_key].set(inv)
                if new_key in self.use_vars:
                    self.use_vars[new_key].set(use)

    def _snapshot_inv_use_in_group(self, gi: int) -> dict[int, tuple[bool, str]]:
        snap = {}
        n = len(self.groups[gi])
        for i in range(n):
            key = (gi, i)
            try:
                inv = bool(self.inv_vars[key].get()) if key in self.inv_vars else False
            except Exception:
                inv = False
            try:
                use = self.use_vars[key].get() if key in self.use_vars else "Node"
            except Exception:
                use = "Node"
            snap[i] = (inv, use)
        return snap

    # ---- group drag ----
    def _on_group_drag_start(self, gi: int):
        self._group_drag_state = {
            "from": gi, "target": gi, "target_gi": gi,
            "ghost": None, "pending_text": f"\u2261 Group {gi + 1}",
        }
        if 0 <= gi < len(self.group_frames):
            try:
                self.group_frames[gi]["frame"].configure(fg_color=("#cfe0ff", "#3a4a6a"))
            except Exception:
                pass

    def _on_group_drag_motion(self, event):
        st = self._group_drag_state
        if not st:
            return
        if st["ghost"] is None and st.get("pending_text"):
            st["ghost"] = DragGhost.create(self, st["pending_text"], bg=self.theme["text"][0])
            st["pending_text"] = None
        DragGhost.move(st["ghost"], event.x_root, event.y_root)
        result = self._find_group_target_idx(event.y_root)
        if result is None:
            return
        target_vp, target_gi = result
        prev_vp = st.get("target", st["from"])
        if target_vp == prev_vp:
            return
        # 即時換位視覺效果（不動 data）
        self._move_group_visually(st["from"], target_vp)
        prev_gi = st.get("target_gi", st["from"])
        if prev_gi != st["from"] and 0 <= prev_gi < len(self.group_frames):
            try:
                self.group_frames[prev_gi]["frame"].configure(
                    border_width=1, border_color=self.theme["border"])
            except Exception:
                pass
        if target_gi != st["from"] and 0 <= target_gi < len(self.group_frames):
            try:
                self.group_frames[target_gi]["frame"].configure(
                    border_width=2, border_color=("#1f6feb", "#58a6ff"))
            except Exception:
                pass
        st["target"] = target_vp
        st["target_gi"] = target_gi

    def _move_group_visually(self, from_idx: int, target_idx: int):
        """重排所有 group frame 的 pack 順序（不動 self.groups data）。"""
        n = len(self.group_frames)
        if not (0 <= from_idx < n and 0 <= target_idx < n):
            return
        order = list(range(n))
        moved = order.pop(from_idx)
        order.insert(target_idx, moved)
        for gi in order:
            try:
                frame = self.group_frames[gi]["frame"]
                frame.pack_forget()
                frame.pack(fill="x", pady=S_XS, padx=(S_LG, 0))
            except Exception:
                pass

    def _on_group_drag_release(self):
        st = self._group_drag_state
        if not st:
            return
        from_idx = st["from"]
        to_idx = st.get("target", from_idx)
        DragGhost.destroy(st.get("ghost"))
        self._group_drag_state = None
        for gf in self.group_frames:
            try:
                gf["frame"].configure(border_width=1,
                                      border_color=self.theme["border"],
                                      fg_color=("gray96", "gray18"))
            except Exception:
                pass
        if from_idx != to_idx:
            self._reorder_groups(from_idx, to_idx)
            self._fire_change()

    def _find_group_target_idx(self, py: int):
        """回傳 (visual_position, group_index) tuple。

        visual_position：游標所在 frame 在 y 排序後的 index (0..n-1)。
        group_index：對應 group 的 data index（self.group_frames 內的位置）。

        以 visual_position 比較 prev/target 避免換位後的震盪。
        """
        cands = []
        for gi, gf in enumerate(self.group_frames):
            try:
                top = gf["frame"].winfo_rooty()
                h = gf["frame"].winfo_height()
            except Exception:
                continue
            if h <= 0:
                continue
            cands.append((gi, top, top + h))
        if not cands:
            return None
        cands.sort(key=lambda x: x[1])
        for vp, (gi, _t, b) in enumerate(cands):
            if py < b:
                return (vp, gi)
        return (len(cands) - 1, cands[-1][0])

    def _reorder_groups(self, from_idx: int, to_idx: int):
        if from_idx == to_idx:
            return
        if not (0 <= from_idx < len(self.groups)) or not (0 <= to_idx < len(self.groups)):
            return
        snap_all = self._snapshot_inv_use_all()
        new_order = list(range(len(self.groups)))
        moved = new_order.pop(from_idx)
        new_order.insert(to_idx, moved)
        self.groups[:] = [self.groups[old] for old in new_order]
        self._sync_group_inv_len()
        self.group_inv[:] = [self.group_inv[old] for old in new_order]
        self._sync_group_intra_op_len()
        self.group_intra_op[:] = [self.group_intra_op[old] for old in new_order]
        self._rebuild_groups_ui()
        for new_gi, old_gi in enumerate(new_order):
            for ii in range(len(self.groups[new_gi])):
                new_key = (new_gi, ii)
                old_key = (old_gi, ii)
                if old_key in snap_all:
                    inv, use = snap_all[old_key]
                    if new_key in self.inv_vars:
                        self.inv_vars[new_key].set(inv)
                    if new_key in self.use_vars:
                        self.use_vars[new_key].set(use)

    # ---- getters for RailEditorFrame.get_rail() ----
    def get_groups(self) -> list[list[str]]:
        return [list(g) for g in self.groups if g]

    def get_inv_groups(self) -> list[list[bool]]:
        result = []
        for gi, g in enumerate(self.groups):
            if not g:
                continue
            row = []
            for ii in range(len(g)):
                key = (gi, ii)
                val = False
                if key in self.inv_vars:
                    try:
                        val = bool(self.inv_vars[key].get())
                    except Exception:
                        val = False
                row.append(val)
            result.append(row)
        return result

    def get_use_groups(self) -> list[list[str]]:
        result = []
        for gi, g in enumerate(self.groups):
            if not g:
                continue
            row = []
            for ii in range(len(g)):
                key = (gi, ii)
                val = "self"
                if key in self.use_vars:
                    try:
                        val = USE_REVERSE.get(self.use_vars[key].get(), "self")
                    except Exception:
                        val = "self"
                row.append(val)
            result.append(row)
        return result

    def get_group_inv(self) -> list[bool]:
        """每個非空 group 的整組反相旗標，與 get_groups() 同序。"""
        result = []
        for gi, g in enumerate(self.groups):
            if not g:
                continue
            val = False
            if gi in self.group_inv_vars:
                try:
                    val = bool(self.group_inv_vars[gi].get())
                except Exception:
                    val = False
            elif gi < len(self.group_inv):
                val = bool(self.group_inv[gi])
            result.append(val)
        return result

    def get_group_intra_op(self) -> list[str]:
        """每個非空 group 的區塊內運算，與 get_groups() 同序。"""
        result = []
        for gi, g in enumerate(self.groups):
            if not g:
                continue
            val = "and"
            if gi in self.group_intra_op_vars:
                try:
                    val = normalize_intra_op(self.group_intra_op_vars[gi].get())
                except Exception:
                    val = "and"
            elif gi < len(self.group_intra_op):
                val = normalize_intra_op(self.group_intra_op[gi])
            result.append(val)
        return result

    def get_inv_flat(self) -> dict[str, bool]:
        d = {}
        for gi, g in enumerate(self.groups):
            for ii, name in enumerate(g):
                key = (gi, ii)
                if key in self.inv_vars:
                    try:
                        d[name] = bool(self.inv_vars[key].get())
                    except Exception:
                        d[name] = False
        return d

    def get_use_flat(self) -> dict[str, str]:
        d = {}
        for gi, g in enumerate(self.groups):
            for ii, name in enumerate(g):
                key = (gi, ii)
                if key in self.use_vars:
                    try:
                        d[name] = USE_REVERSE.get(self.use_vars[key].get(), "self")
                    except Exception:
                        d[name] = "self"
        return d

    def get_flat_deps(self) -> list[str]:
        return [d for g in self.get_groups() for d in g]


# ============================================================
# InputWaveCondFrame — input 專用 WaveDrom Hi/Lo Cond（主頁）
# ============================================================

class InputWaveSidePanel(ctk.CTkFrame):
    """單側 Hi 或 Lo：模式 + Custom wave 或 Signal cond. 群組。"""

    def __init__(
        self,
        master,
        side: str,
        spec: InputWaveSpec,
        get_dep_options: Callable[[], list[str]],
        is_pseqcell_for: Callable[[str], bool],
        get_self_name: Callable[[], str],
        on_change: Optional[Callable[[], None]] = None,
        on_layout_change: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.side = side
        self.on_change = on_change
        self._on_layout_change = on_layout_change
        prefix = side
        mode = getattr(spec, f"{prefix}_mode")
        wave = getattr(spec, f"{prefix}_wave", "0") or "0"
        groups = getattr(spec, f"{prefix}_groups") or []
        inv_groups = getattr(spec, f"{prefix}_inv_groups") or []
        use_groups = getattr(spec, f"{prefix}_use_groups") or []
        group_inv = getattr(spec, f"{prefix}_group_inv") or []
        intra_op = getattr(spec, f"{prefix}_intra_op") or []

        hint = ctk.CTkLabel(
            self,
            text="WaveDrom simulation only (not Verilog depends_on).",
            font=FONT_HINT,
            text_color="gray",
            anchor="w",
        )
        hint.pack(fill="x", pady=(0, S_XS))

        mode_row = ctk.CTkFrame(self, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, S_SM))
        ctk.CTkLabel(mode_row, text="Mode:", font=FONT_BODY).pack(side="left", padx=(0, S_SM))
        self._mode_menu = ctk.CTkOptionMenu(
            mode_row,
            values=[m[0] for m in INPUT_WAVE_MODES],
            width=140,
            command=lambda _v: self._on_mode_change(),
        )
        self._mode_menu.set(INPUT_WAVE_LABEL_BY_MODE.get(mode, "Signal cond."))
        self._mode_menu.pack(side="left")

        self._opt_slot = ctk.CTkFrame(self, fg_color="transparent")
        self._opt_slot.pack(fill="x")

        self._wave_var = tk.StringVar(value=wave)
        self._wave_entry = ctk.CTkEntry(
            self._opt_slot,
            textvariable=self._wave_var,
            width=200,
            placeholder_text="0{29}1",
        )
        self._wave_var.trace_add("write", lambda *_: self._fire_change())

        init_groups = [list(g) for g in groups] if groups else [[]]
        self._cond_section = CondSectionFrame(
            self._opt_slot,
            kind=side,
            get_dep_options=get_dep_options,
            is_pseqcell_for=is_pseqcell_for,
            initial_groups=init_groups,
            initial_inv_groups=inv_groups,
            initial_use_groups=use_groups,
            initial_inv_flat={},
            initial_use_flat={},
            initial_group_inv=list(group_inv),
            initial_group_intra_op=list(intra_op),
            show_group_inv=True,
            on_change=self._fire_change,
            get_self_name=get_self_name,
        )
        self._on_mode_change()

    def _fire_change(self):
        if self.on_change:
            try:
                self.on_change()
            except TypeError:
                self.on_change()

    def _mode_value(self) -> str:
        return INPUT_WAVE_MODE_BY_LABEL.get(self._mode_menu.get(), "depends")

    def _on_mode_change(self):
        self._wave_entry.pack_forget()
        self._cond_section.pack_forget()
        mode = self._mode_value()
        if mode in ("constant_0", "constant_1"):
            self._opt_slot.pack_forget()
        else:
            self._opt_slot.pack(fill="x")
            if mode == "custom":
                self._wave_entry.pack(fill="x", pady=(0, S_XS))
            elif mode == "depends":
                self._cond_section.pack(fill="x")
        if self._on_layout_change:
            self.after(1, self._on_layout_change)

    def content_height(self) -> int:
        """Tabview 內容高度（僅作用中分頁；不含 tab 列）。"""
        base = 58  # hint + mode row
        mode = self._mode_value()
        if mode in ("constant_0", "constant_1"):
            return base
        if mode == "custom":
            return base + 36
        if mode == "depends":
            self.update_idletasks()
            if self._cond_section.winfo_ismapped():
                return base + min(max(self._cond_section.winfo_reqheight(), 120), 220)
            return base + 120
        return base

    def collect_side(self) -> dict:
        mode = self._mode_value()
        out: dict = {"mode": mode}
        if mode == "custom":
            out["wave"] = self._wave_var.get().strip() or "0"
        elif mode == "depends":
            out["groups"] = self._cond_section.get_groups()
            out["inv_groups"] = self._cond_section.get_inv_groups()
            out["use_groups"] = self._cond_section.get_use_groups()
            out["group_inv"] = self._cond_section.get_group_inv()
            out["intra_op"] = self._cond_section.get_group_intra_op()
        return out


class InputWaveCondFrame(ctk.CTkFrame):
    """Input 節點 WaveDrom Hi/Lo Cond（Tab 風格與 Output Conditions 一致）。"""

    def __init__(
        self,
        master,
        spec: InputWaveSpec,
        get_dep_options: Callable[[], list[str]],
        is_pseqcell_for: Callable[[str], bool],
        get_self_name: Callable[[], str],
        on_change: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="x", padx=S_SM, pady=S_SM)
        for side in ("hi", "lo"):
            tab_name = COND_THEME[side]["name"]
            self._tabs.add(tab_name)
            panel = InputWaveSidePanel(
                self._tabs.tab(tab_name),
                side,
                spec,
                get_dep_options=get_dep_options,
                is_pseqcell_for=is_pseqcell_for,
                get_self_name=get_self_name,
                on_change=on_change,
                on_layout_change=self._sync_tab_height,
            )
            panel.pack(fill="x", padx=S_SM, pady=S_SM)
            setattr(self, f"_{side}_panel", panel)

        seg = self._tabs._segmented_button
        prev_tab_cmd = seg.cget("command")

        def _on_tab_selected(value):
            if prev_tab_cmd:
                prev_tab_cmd(value)
            self._sync_tab_height()

        seg.configure(command=_on_tab_selected)
        self._sync_tab_height()

    def _active_panel(self) -> InputWaveSidePanel:
        if self._tabs.get() == COND_THEME["hi"]["name"]:
            return self._hi_panel
        return self._lo_panel

    def _sync_tab_height(self):
        self._tabs.configure(height=self._active_panel().content_height())

    def to_spec(self) -> InputWaveSpec:
        hi = self._hi_panel.collect_side()
        lo = self._lo_panel.collect_side()
        return InputWaveSpec(
            hi_mode=hi["mode"],
            hi_wave=hi.get("wave", "0"),
            hi_groups=hi.get("groups") or [],
            hi_inv_groups=hi.get("inv_groups") or [],
            hi_use_groups=hi.get("use_groups") or [],
            hi_group_inv=hi.get("group_inv") or [],
            hi_intra_op=hi.get("intra_op") or [],
            lo_mode=lo["mode"],
            lo_wave=lo.get("wave", "0"),
            lo_groups=lo.get("groups") or [],
            lo_inv_groups=lo.get("inv_groups") or [],
            lo_use_groups=lo.get("use_groups") or [],
            lo_group_inv=lo.get("group_inv") or [],
            lo_intra_op=lo.get("intra_op") or [],
        )


# ============================================================
# RailEditorFrame — 單一 rail 的屬性編輯面板
# ============================================================

class RailEditorFrame(ctk.CTkFrame):
    """單一 rail 編輯器；按 Apply 才寫入 config 並更新 Preview。"""

    def __init__(self, master, rail: PowerRail,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_apply: Optional[Callable[[], None]] = None,
                 initial_input_wave_spec: Optional[InputWaveSpec] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.rail = rail
        self.get_all_rails = get_all_rails
        self.get_pulses = get_pulses
        self.on_apply = on_apply
        self._initial_input_wave_spec = initial_input_wave_spec or InputWaveSpec(
            hi_mode="depends", lo_mode="constant_0",
        )

        self._build_ui()

    # ---- helpers ----
    def _dep_options(self) -> list[str]:
        # 允許選自己：output 可參照自身的 Hi/Lo/Force condition（用 use 下拉指定欄位）
        return [r.name for r in self.get_all_rails()] + ["High", "Low"]

    def _is_pseqcell_for(self, name: str) -> bool:
        if name in (DEP_HIGH, DEP_LOW):
            return False
        target = next((r for r in self.get_all_rails() if r.name == name), None)
        return target is not None and target.has_pseqcell

    def _pulse_values(self, *current: str) -> list[str]:
        vals = list(self.get_pulses()) + ["High"]
        for v in current:
            if v and v not in vals:
                vals.append(v)
        return vals

    def _make_section(self, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        wrap = ctk.CTkFrame(self, fg_color=("gray95", "gray19"), corner_radius=6)
        wrap.pack(fill="x", pady=(0, S_SM))
        header = ctk.CTkFrame(wrap, fg_color="transparent")
        header.pack(fill="x", padx=S_SM, pady=(S_SM, 0))
        ctk.CTkLabel(header, text=title, font=FONT_SECTION).pack(side="left")
        body = ctk.CTkFrame(wrap, fg_color="transparent")
        body.pack(fill="x")
        return wrap, body

    # ---- UI build ----
    def _build_ui(self):
        # --- General ---
        _, gen_body = self._make_section("General")
        grid = ctk.CTkFrame(gen_body, fg_color="transparent")
        grid.pack(fill="x", padx=S_SM, pady=S_SM)
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ctk.CTkLabel(grid, text="Name:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_name = ctk.CTkEntry(grid, width=160)
        self.entry_name.insert(0, self.rail.name)
        self.entry_name.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid, text="Type:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        type_row = ctk.CTkFrame(grid, fg_color="transparent")
        type_row.grid(row=0, column=3, sticky="w", pady=2)
        self.var_type = ctk.StringVar(value=self.rail.seq_type)
        self._type_seg = ctk.CTkSegmentedButton(
            type_row,
            values=[SEQ_TYPE_LABELS["output"], SEQ_TYPE_LABELS["input"]],
            command=self._on_type_seg_selected,
        )
        self._type_seg.set(SEQ_TYPE_LABELS.get(self.rail.seq_type, "Output"))
        self._type_seg.pack(side="left")

        # --- Timing (output only) ---
        self.timing_wrap, timing_body = self._make_section("Timing")
        grid_t = ctk.CTkFrame(timing_body, fg_color="transparent")
        grid_t.pack(fill="x", padx=S_SM, pady=S_SM)
        for c in range(4):
            grid_t.grid_columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ctk.CTkLabel(grid_t, text="CYCLE_HI:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_hi = ctk.CTkEntry(grid_t, width=100)
        self.entry_hi.insert(0, str(self.rail.cycle_hi))
        self.entry_hi.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_lo = ctk.CTkEntry(grid_t, width=100)
        self.entry_lo.insert(0, str(self.rail.cycle_lo))
        self.entry_lo.grid(row=0, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_t, text="CYCLE_FORCE:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_cycle_force = ctk.CTkEntry(grid_t, width=100)
        self.entry_cycle_force.insert(0, str(getattr(self.rail, "cycle_force", 2)))
        self.entry_cycle_force.grid(row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="INIT:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pseq_init = ctk.StringVar(value="1" if getattr(self.rail, "init", 0) == 1 else "0")
        cmb_pseq_init = ctk.CTkComboBox(grid_t, values=["0", "1"], variable=self.var_pseq_init, width=100)
        cmb_pseq_init.grid(row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="FORCE:", font=FONT_BODY).grid(
            row=2, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_force_val = ctk.StringVar(
            value="1" if getattr(self.rail, "force_val", 0) == 1 else "0")
        cmb_force_val = ctk.CTkComboBox(grid_t, values=["0", "1"], variable=self.var_force_val, width=100)
        cmb_force_val.grid(row=2, column=3, sticky="w", pady=2)

        pulses = self._pulse_values(
            getattr(self.rail, "pulse_hi", DEFAULT_PULSE),
            getattr(self.rail, "pulse_lo", DEFAULT_PULSE),
            getattr(self.rail, "pulse_force", DEFAULT_PULSE),
        )
        ctk.CTkLabel(grid_t, text="Timing Hi:", font=FONT_BODY).grid(
            row=3, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_hi = ctk.StringVar(value=getattr(self.rail, "pulse_hi", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_hi = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_hi, width=130)
        cmb_pulse_hi.grid(row=3, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="Timing Lo:", font=FONT_BODY).grid(
            row=3, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_lo = ctk.StringVar(value=getattr(self.rail, "pulse_lo", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_lo = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_lo, width=130)
        cmb_pulse_lo.grid(row=3, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_t, text="Timing Force:", font=FONT_BODY).grid(
            row=4, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_force = ctk.StringVar(value=getattr(self.rail, "pulse_force", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_force = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_force, width=130)
        cmb_pulse_force.grid(row=4, column=1, sticky="w", padx=(0, S_LG), pady=2)

        # --- Conditions (output only) ---
        self.cond_wrap, cond_body = self._make_section("Conditions")
        self.cond_tabs = ctk.CTkTabview(cond_body, height=220)
        self.cond_tabs.pack(fill="x", padx=S_SM, pady=S_SM)
        self.cond_sections: dict[str, CondSectionFrame] = {}
        for kind in ("hi", "lo", "force"):
            theme = COND_THEME[kind]
            self.cond_tabs.add(theme["name"])
            tab = self.cond_tabs.tab(theme["name"])
            init_groups_fn = {"hi": self.rail.get_hi_groups,
                              "lo": self.rail.get_lo_groups,
                              "force": self.rail.get_force_groups}[kind]
            init_groups = [list(g) for g in init_groups_fn()] if init_groups_fn() else [[]]
            init_inv = {"hi": self.rail.depends_on_hi_inv_groups,
                        "lo": self.rail.depends_on_lo_inv_groups,
                        "force": self.rail.depends_on_force_inv_groups}[kind]
            init_use = {"hi": self.rail.depends_on_hi_use_groups,
                        "lo": self.rail.depends_on_lo_use_groups,
                        "force": self.rail.depends_on_force_use_groups}[kind]
            init_inv_flat = {"hi": self.rail.depends_on_hi_inv,
                             "lo": self.rail.depends_on_lo_inv,
                             "force": self.rail.depends_on_force_inv}[kind]
            init_use_flat = {"hi": self.rail.depends_on_hi_use,
                             "lo": self.rail.depends_on_lo_use,
                             "force": self.rail.depends_on_force_use}[kind]
            init_group_inv = {"hi": self.rail.depends_on_hi_group_inv,
                              "lo": self.rail.depends_on_lo_group_inv,
                              "force": self.rail.depends_on_force_group_inv}[kind]
            init_group_intra_op = {"hi": self.rail.depends_on_hi_intra_op,
                                   "lo": self.rail.depends_on_lo_intra_op,
                                   "force": self.rail.depends_on_force_intra_op}[kind]
            sec = CondSectionFrame(
                tab, kind,
                get_dep_options=self._dep_options,
                is_pseqcell_for=self._is_pseqcell_for,
                initial_groups=init_groups,
                initial_inv_groups=init_inv,
                initial_use_groups=init_use,
                initial_inv_flat=init_inv_flat,
                initial_use_flat=init_use_flat,
                initial_group_inv=init_group_inv,
                initial_group_intra_op=init_group_intra_op,
                get_self_name=lambda: self.rail.name,
            )
            sec.pack(fill="both", expand=True, padx=S_SM, pady=S_SM)
            self.cond_sections[kind] = sec

        # --- Debounce (input only) ---
        self.deb_wrap, deb_body = self._make_section("Debounce")
        self.var_deb_enable = ctk.BooleanVar(value=getattr(self.rail, "deb_enable", True))
        enable_row = ctk.CTkFrame(deb_body, fg_color="transparent")
        enable_row.pack(fill="x", padx=S_SM, pady=S_SM)
        ctk.CTkCheckBox(enable_row, text="Enable Debounce",
                        variable=self.var_deb_enable, width=140,
                        command=self._on_deb_toggle).pack(side="left")

        self.deb_params = ctk.CTkFrame(deb_body, fg_color="transparent")
        grid_d = ctk.CTkFrame(self.deb_params, fg_color="transparent")
        grid_d.pack(fill="x", padx=S_SM, pady=S_SM)
        for c in range(4):
            grid_d.grid_columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ctk.CTkLabel(grid_d, text="CYCLE_HI:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_hi = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_hi.insert(0, str(getattr(self.rail, "deb_cycle_hi", 2)))
        self.entry_deb_cycle_hi.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_d, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_lo = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_lo.insert(0, str(getattr(self.rail, "deb_cycle_lo", 2)))
        self.entry_deb_cycle_lo.grid(row=0, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_d, text="CYCLE_SYNC:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_sync = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_sync.insert(0, str(getattr(self.rail, "deb_cycle_sync", 2)))
        self.entry_deb_cycle_sync.grid(row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_d, text="INIT:", font=FONT_BODY).grid(
            row=1, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_deb_init = ctk.StringVar(value="1" if getattr(self.rail, "deb_init", 0) == 1 else "0")
        cmb_deb_init = ctk.CTkComboBox(grid_d, values=["0", "1"], variable=self.var_deb_init, width=100)
        cmb_deb_init.grid(row=1, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_d, text="Timing Deb:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        deb_pulses = self._pulse_values(getattr(self.rail, "deb_pulse", DEFAULT_PULSE))
        self.var_deb_pulse = ctk.StringVar(value=getattr(self.rail, "deb_pulse", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_deb_pulse = ctk.CTkComboBox(grid_d, values=deb_pulses, variable=self.var_deb_pulse, width=130)
        cmb_deb_pulse.grid(row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)

        # --- WaveDrom Hi/Lo (input only) ---
        self.wavedrom_wrap, wavedrom_body = self._make_section("WaveDrom Hi/Lo")
        self.input_wave_frame = InputWaveCondFrame(
            wavedrom_body,
            self._initial_input_wave_spec,
            get_dep_options=self._dep_options,
            is_pseqcell_for=self._is_pseqcell_for,
            get_self_name=lambda: self.rail.name,
        )
        self.input_wave_frame.pack(fill="x", padx=S_SM, pady=S_SM)

        apply_row = ctk.CTkFrame(self, fg_color="transparent")
        apply_row.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        ctk.CTkButton(
            apply_row, text="Apply", width=88, command=self._on_apply_clicked,
        ).pack(side="right")

        self._on_type_toggle(initial=True)

        for entry in (
            self.entry_name,
            self.entry_hi,
            self.entry_lo,
            self.entry_cycle_force,
            self.entry_deb_cycle_hi,
            self.entry_deb_cycle_lo,
            self.entry_deb_cycle_sync,
        ):
            self._bind_disarm_node_delete_on_focus(entry)

    def _bind_disarm_node_delete_on_focus(self, widget):
        def _on_focus_in(_event):
            top = self.winfo_toplevel()
            disarm = getattr(top, "_disarm_node_list_delete", None)
            if disarm:
                disarm()
        widget.bind("<FocusIn>", _on_focus_in, add="+")

    # ---- callbacks ----
    def _on_apply_clicked(self):
        if self.on_apply:
            self.on_apply()

    def _on_type_seg_selected(self, label: str):
        rev = {v: k for k, v in SEQ_TYPE_LABELS.items()}
        new_type = rev.get(label, "output")
        if new_type != self.var_type.get():
            self.var_type.set(new_type)
        self._on_type_toggle()

    def _on_type_toggle(self, initial: bool = False):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.timing_wrap.pack_forget()
            self.cond_wrap.pack_forget()
            self.deb_wrap.pack(fill="x", pady=(0, S_SM))
            self.wavedrom_wrap.pack(fill="x", pady=(0, S_SM))
            self._on_deb_toggle(initial=initial)
        else:
            self.deb_wrap.pack_forget()
            self.wavedrom_wrap.pack_forget()
            self.timing_wrap.pack(fill="x", pady=(0, S_SM))
            self.cond_wrap.pack(fill="x", pady=(0, S_SM))

    def _on_deb_toggle(self, initial: bool = False):
        if self.var_deb_enable.get():
            self.deb_params.pack(fill="x")
        else:
            self.deb_params.pack_forget()

    # ---- collect ----
    def get_rail(self) -> PowerRail:
        rail_name = self.entry_name.get().strip() or self.rail.name
        cycle_hi = _safe_int(self.entry_hi.get(), self.rail.cycle_hi)
        cycle_lo = _safe_int(self.entry_lo.get(), self.rail.cycle_lo)

        hi = self.cond_sections["hi"]
        lo = self.cond_sections["lo"]
        fo = self.cond_sections["force"]
        groups_hi = hi.get_groups()
        groups_lo = lo.get_groups()
        groups_force = fo.get_groups()
        flat_hi = hi.get_flat_deps()
        flat_lo = lo.get_flat_deps()
        flat_force = fo.get_flat_deps()
        hi_inv_groups = hi.get_inv_groups()
        lo_inv_groups = lo.get_inv_groups()
        force_inv_groups = fo.get_inv_groups()
        hi_use_groups = hi.get_use_groups()
        lo_use_groups = lo.get_use_groups()
        force_use_groups = fo.get_use_groups()
        hi_group_inv = hi.get_group_inv()
        lo_group_inv = lo.get_group_inv()
        force_group_inv = fo.get_group_inv()
        hi_group_intra_op = hi.get_group_intra_op()
        lo_group_intra_op = lo.get_group_intra_op()
        force_group_intra_op = fo.get_group_intra_op()

        seq_type = self.var_type.get()
        if seq_type == "input":
            cycle_hi, cycle_lo = 0, 0
            groups_hi, groups_lo, groups_force = [], [], []
            flat_hi, flat_lo, flat_force = [], [], []
            hi_inv_groups = lo_inv_groups = force_inv_groups = []
            hi_use_groups = lo_use_groups = force_use_groups = []
            hi_group_inv = lo_group_inv = force_group_inv = []
            hi_group_intra_op = lo_group_intra_op = force_group_intra_op = []

        rail = PowerRail(
            name=rail_name,
            seq_type=seq_type,
            depends_on=flat_hi,
            depends_on_hi=flat_hi,
            depends_on_lo=flat_lo,
            depends_on_hi_groups=groups_hi,
            depends_on_lo_groups=groups_lo,
            depends_on_hi_inv=hi.get_inv_flat() if seq_type != "input" else {},
            depends_on_lo_inv=lo.get_inv_flat() if seq_type != "input" else {},
            depends_on_hi_use=hi.get_use_flat() if seq_type != "input" else {},
            depends_on_lo_use=lo.get_use_flat() if seq_type != "input" else {},
            depends_on_hi_inv_groups=hi_inv_groups,
            depends_on_lo_inv_groups=lo_inv_groups,
            depends_on_hi_use_groups=hi_use_groups,
            depends_on_lo_use_groups=lo_use_groups,
            depends_on_hi_group_inv=hi_group_inv,
            depends_on_lo_group_inv=lo_group_inv,
            depends_on_hi_intra_op=hi_group_intra_op,
            depends_on_lo_intra_op=lo_group_intra_op,
            depends_on_force=flat_force,
            depends_on_force_groups=groups_force,
            depends_on_force_inv=fo.get_inv_flat() if seq_type != "input" else {},
            depends_on_force_use=fo.get_use_flat() if seq_type != "input" else {},
            depends_on_force_inv_groups=force_inv_groups,
            depends_on_force_use_groups=force_use_groups,
            depends_on_force_group_inv=force_group_inv,
            depends_on_force_intra_op=force_group_intra_op,
            pulse_hi=self.var_pulse_hi.get() if seq_type != "input" else DEFAULT_PULSE,
            pulse_lo=self.var_pulse_lo.get() if seq_type != "input" else DEFAULT_PULSE,
            pulse_force=self.var_pulse_force.get() if seq_type != "input" else DEFAULT_PULSE,
            deb_enable=self.var_deb_enable.get() if seq_type == "input" else False,
            deb_init=1 if (seq_type == "input" and self.var_deb_init.get() == "1") else 0,
            deb_cycle_hi=_safe_int(self.entry_deb_cycle_hi.get(), 2) if seq_type == "input" else 2,
            deb_cycle_lo=_safe_int(self.entry_deb_cycle_lo.get(), 2) if seq_type == "input" else 2,
            deb_cycle_sync=_safe_int(self.entry_deb_cycle_sync.get(), 2) if seq_type == "input" else 2,
            deb_pulse=self.var_deb_pulse.get() if seq_type == "input" else DEFAULT_PULSE,
            cycle_hi=cycle_hi,
            cycle_lo=cycle_lo,
            cycle_force=_safe_int(self.entry_cycle_force.get(), self.rail.cycle_force)
            if seq_type != "input" else 2,
            init=1 if (seq_type != "input" and self.var_pseq_init.get() == "1") else 0,
            force_val=1 if (seq_type != "input" and self.var_force_val.get() == "1") else 0,
        )
        if seq_type == "input":
            apply_input_wave_dict(rail, self.get_input_wave_spec().to_dict())
        self.rail = rail
        return rail

    def get_input_wave_spec(self) -> InputWaveSpec:
        if getattr(self, "input_wave_frame", None) is not None:
            return self.input_wave_frame.to_spec()
        return self._initial_input_wave_spec


# ============================================================
# CollapsibleRailFrame — accordion 卡片，header 採用 chip 化（A2）
# ============================================================

class CollapsibleRailFrame(ctk.CTkFrame):
    """Accordion wrapper：可點擊 header + 可摺疊 RailEditorFrame。"""

    def __init__(self, master, rail: PowerRail,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_apply: Optional[Callable[[], None]] = None,
                 get_input_wave_spec: Optional[Callable[[str], InputWaveSpec]] = None,
                 expanded: bool = False, **kwargs):
        super().__init__(master, **kwargs)
        self.rail = rail
        self._expanded = expanded
        self._get_all_rails = get_all_rails
        self._get_pulses = get_pulses
        self._on_apply = on_apply
        self._get_input_wave_spec = get_input_wave_spec
        self._initial_input_wave_spec = (
            get_input_wave_spec(rail.name) if get_input_wave_spec else InputWaveSpec()
        )
        self.editor: Optional[RailEditorFrame] = None

        self._header = ctk.CTkFrame(self, fg_color=("gray86", "gray23"), corner_radius=6)
        self._header.pack(fill="x")
        self._header.bind("<Button-1>", lambda _: self.toggle())

        self._arrow = ctk.CTkLabel(self._header, text="", width=20, font=FONT_BODY)
        self._arrow.pack(side="left", padx=(S_SM, S_XS))
        self._arrow.bind("<Button-1>", lambda _: self.toggle())

        self._name_label = ctk.CTkLabel(self._header, text="", font=FONT_TITLE, anchor="w")
        self._name_label.pack(side="left", padx=(0, S_SM), pady=S_SM)
        self._name_label.bind("<Button-1>", lambda _: self.toggle())

        self._chips_holder = ctk.CTkFrame(self._header, fg_color="transparent")
        self._chips_holder.pack(side="left", fill="x", expand=True, padx=(0, S_SM))
        self._chips_holder.bind("<Button-1>", lambda _: self.toggle())

        self._body = ctk.CTkFrame(self, fg_color="transparent")

        self._refresh_header()
        self._update_ui()

    def _refresh_header(self):
        self._name_label.configure(text=self.rail.name)
        for w in self._chips_holder.winfo_children():
            w.destroy()
        type_label = SEQ_TYPE_LABELS.get(self.rail.seq_type, self.rail.seq_type)
        pill = make_pill(self._chips_holder, type_label, self.rail.seq_type)
        pill.pack(side="left", padx=(0, S_SM))
        pill.bind("<Button-1>", lambda _: self.toggle())
        chips: list[tuple[str, str | None, str | None]] = []
        if self.rail.seq_type == "input":
            if getattr(self.rail, "deb_enable", False):
                chips.append(("Deb:ON", None, None))
                chips.append((f"HI:{getattr(self.rail, 'deb_cycle_hi', 2)}", None, None))
                chips.append((f"LO:{getattr(self.rail, 'deb_cycle_lo', 2)}", None, None))
                chips.append((f"INIT:{getattr(self.rail, 'deb_init', 0)}", None, None))
            else:
                chips.append(("Deb:OFF", ("gray40", "gray60"), None))
        else:
            chips.append((f"HI:{self.rail.cycle_hi}", COND_THEME["hi"]["text"], None))
            chips.append((f"LO:{self.rail.cycle_lo}", COND_THEME["lo"]["text"], None))
            chips.append((f"F:{self.rail.cycle_force}", COND_THEME["force"]["text"], None))
            chips.append((f"INIT:{getattr(self.rail, 'init', 0)}", None, None))
            if getattr(self.rail, "force_val", 0) == 1:
                chips.append(("FORCE:1", COND_THEME["force"]["text"], None))
        for text, fg, bg in chips:
            c = make_chip(self._chips_holder, text, fg=fg, bg=bg)
            c.pack(side="left", padx=(0, S_XS))
            c.bind("<Button-1>", lambda _: self.toggle())

    def _ensure_body(self):
        if self.editor is not None:
            return
        self.editor = RailEditorFrame(
            self._body, self.rail,
            get_all_rails=self._get_all_rails,
            get_pulses=self._get_pulses,
            on_apply=self._on_apply,
            initial_input_wave_spec=self._initial_input_wave_spec,
        )
        self.editor.pack(fill="x", padx=S_SM, pady=(S_SM, 0))

    def update_summary(self):
        self._refresh_header()

    def _update_ui(self):
        self._arrow.configure(text="\u25BC" if self._expanded else "\u25B6")
        if self._expanded:
            self._ensure_body()
            self._body.pack(fill="x", pady=(0, S_SM))
        else:
            self._body.pack_forget()

    def toggle(self):
        self._expanded = not self._expanded
        self._update_ui()

    def expand(self):
        if not self._expanded:
            self._expanded = True
            self._update_ui()

    def collapse(self):
        if self._expanded:
            self._expanded = False
            self._update_ui()

    def get_rail(self) -> PowerRail:
        if self.editor is not None:
            self.rail = self.editor.get_rail()
        return self.rail

    def get_input_wave_spec(self) -> InputWaveSpec:
        if self.editor is not None:
            spec = self.editor.get_input_wave_spec()
            self._initial_input_wave_spec = spec
            return spec
        return self._initial_input_wave_spec


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


# ============================================================
# PreviewPanel — 右側 Verilog / C 即時預覽（C1）
# ============================================================

PREVIEW_LANGS = ("Verilog", "C", "Schemdraw")
PREVIEW_FONT_FAMILY = FONT_MONO[0]
PREVIEW_FONT_SIZE_DEFAULT = FONT_MONO[1]
PREVIEW_FONT_SIZES = (8, 10, 12, 14, 16, 18, 20, 24)
SCHEMDRAW_ZOOM_MIN = 0.1
SCHEMDRAW_ZOOM_MAX = 5.0
SCHEMDRAW_ZOOM_STEP = 1.2
SCHEMDRAW_ZOOM_DEBOUNCE_MS = 40


def _preview_font(size: int) -> tuple:
    return (PREVIEW_FONT_FAMILY, size)


class PreviewPanel(ctk.CTkFrame):
    """右側預覽：Verilog / C 文字，或 Schemdraw 時序圖（PNG）。"""

    def __init__(
        self,
        master,
        on_lang_change: Optional[Callable[[], None]] = None,
        on_font_size_change: Optional[Callable[[int], None]] = None,
        on_schemdraw_refresh: Optional[Callable[[], None]] = None,
        on_schemdraw_select_nodes: Optional[Callable[[], None]] = None,
        initial_font_size: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.on_lang_change = on_lang_change
        self.on_font_size_change = on_font_size_change
        self.on_schemdraw_refresh = on_schemdraw_refresh
        self.on_schemdraw_select_nodes = on_schemdraw_select_nodes
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
            text="拖曳平移 · 滾輪縮放 · Shift+滾輪捲動",
            font=FONT_HINT,
            text_color=("gray40", "gray60"),
        ).pack(side="left")
        self._text = ctk.CTkTextbox(self, font=_preview_font(self._font_size), wrap="none",
                                    activate_scrollbars=True)
        self._text.pack(fill="both", expand=True, padx=S_SM, pady=(S_XS, S_SM))
        self._text.configure(state="disabled")
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
        if event.delta > 0:
            self._schemdraw_zoom_step(1)
        elif event.delta < 0:
            self._schemdraw_zoom_step(-1)
        return "break"

    def _on_schemdraw_wheel_shift(self, event) -> str | None:
        if self.get_lang() != "Schemdraw" or self._schemdraw_source is None:
            return None
        try:
            self._img_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
        return "break"

    def _on_schemdraw_wheel_linux(self, event) -> str | None:
        if self.get_lang() != "Schemdraw" or self._schemdraw_source is None:
            return None
        if event.state & 0x0001:
            try:
                if event.num == 4:
                    self._img_canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    self._img_canvas.yview_scroll(1, "units")
            except Exception:
                pass
            return "break"
        if event.num == 4:
            self._schemdraw_zoom_step(1)
        elif event.num == 5:
            self._schemdraw_zoom_step(-1)
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

    def _update_view_mode(self):
        is_sd = self.get_lang() == "Schemdraw"
        if is_sd:
            self._text.pack_forget()
            self._zoom_bar.pack(fill="x", padx=S_SM, pady=(0, S_XS))
            self._img_viewport.pack(fill="both", expand=True, padx=S_SM, pady=(0, S_SM))
            self._size_frame.pack_forget()
            self._nodes_btn.pack(side="left", padx=(S_SM, 0))
            self._refresh_btn.pack(side="left", padx=(S_XS, 0))
        else:
            self._img_viewport.pack_forget()
            self._zoom_bar.pack_forget()
            self._refresh_btn.pack_forget()
            self._nodes_btn.pack_forget()
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


# ============================================================
# Tooltip / StatusBar / RecentFiles / HelpDialog — UI 共用元件
# ============================================================

class Tooltip:
    """簡易 hover tooltip：游標停留 delay ms 後彈出 tk.Toplevel 小標籤。"""

    def __init__(self, widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _e=None):
        self._cancel_pending()
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, _e=None):
        self._cancel_pending()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _cancel_pending(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            tip, text=self.text, bg="#1f2937", fg="#f9fafb",
            padx=8, pady=4, font=("", 9), bd=0,
        )
        lbl.pack()
        self._tip = tip


class DragGhost:
    """Drag preview overlay：alpha=0.7 無邊框 Toplevel，跟游標走。

    用法：
        ghost = DragGhost.create(parent, "label text")
        DragGhost.move(ghost, x_root, y_root)
        DragGhost.destroy(ghost)
    """

    @staticmethod
    def create(parent, text: str, bg: str = "#1f6feb") -> Optional[tk.Toplevel]:
        try:
            top = tk.Toplevel(parent)
            top.wm_overrideredirect(True)
            try:
                top.wm_attributes("-alpha", 0.7)
            except tk.TclError:
                pass
            try:
                top.wm_attributes("-topmost", True)
            except tk.TclError:
                pass
            frame = tk.Frame(top, bg=bg, bd=0, padx=8, pady=4)
            frame.pack()
            tk.Label(frame, text=text, bg=bg, fg="#ffffff",
                     font=("", 10, "bold"), bd=0).pack()
            return top
        except Exception:
            return None

    @staticmethod
    def move(ghost: Optional[tk.Toplevel], x_root: int, y_root: int):
        if ghost is None:
            return
        try:
            ghost.geometry(f"+{x_root + 12}+{y_root + 8}")
        except Exception:
            pass

    @staticmethod
    def destroy(ghost: Optional[tk.Toplevel]):
        if ghost is None:
            return
        try:
            ghost.destroy()
        except Exception:
            pass


class StatusBar(ctk.CTkFrame):
    """底部 status bar：左=檔名+dirty / 中=節點統計 / 右=作者+訊息（toast 文字）。"""

    def __init__(self, master, **kwargs):
        super().__init__(master, height=24, fg_color=("gray85", "gray18"),
                         corner_radius=0, **kwargs)
        self.pack_propagate(False)
        self._file_lbl = ctk.CTkLabel(self, text="(unsaved)", font=FONT_HINT, anchor="w")
        self._file_lbl.pack(side="left", padx=(S_MD, S_SM))
        self._stat_lbl = ctk.CTkLabel(self, text="", font=FONT_HINT, anchor="w",
                                       text_color=("gray35", "gray65"))
        self._stat_lbl.pack(side="left", padx=S_SM)
        self._msg_lbl = ctk.CTkLabel(self, text="", font=FONT_HINT, anchor="e",
                                      text_color=("gray35", "gray65"))
        self._msg_lbl.pack(side="right", padx=(S_SM, S_MD))
        self._author_lbl = ctk.CTkLabel(
            self, text=f"Author: {APP_AUTHOR}", font=FONT_HINT, anchor="e",
            text_color=("gray35", "gray65"),
        )
        self._author_lbl.pack(side="right", padx=(S_SM, 0))
        self._msg_after_id: Optional[str] = None

    def set_file(self, path: Optional[str], dirty: bool):
        if path is None:
            text = "(unsaved)" + (" *" if dirty else "")
        else:
            text = os.path.basename(path) + (" *" if dirty else "")
        self._file_lbl.configure(text=text)

    def set_stats(self, n_total: int, n_output: int, n_input: int):
        self._stat_lbl.configure(text=f"Nodes: {n_total}  (Output: {n_output}, Input: {n_input})")

    def set_message(self, msg: str, level: str = "info", auto_clear_ms: int = 5000):
        color_map = {
            "info":    ("gray25", "#9ca3af"),
            "success": ("#1a7f37", "#3fb950"),
            "warn":    ("#9a6700", "#e3b341"),
            "error":   ("#cf222e", "#ff7b72"),
        }
        self._msg_lbl.configure(text=msg, text_color=color_map.get(level, color_map["info"]))
        if self._msg_after_id is not None:
            try:
                self.after_cancel(self._msg_after_id)
            except Exception:
                pass
            self._msg_after_id = None
        if auto_clear_ms > 0:
            self._msg_after_id = self.after(auto_clear_ms, lambda: self._msg_lbl.configure(text=""))


_PWRSEQ_USER_DIR = os.path.join(os.path.expanduser("~"), ".pwrseq_gen")


class GuiSettings:
    """GUI 偏好設定，儲存於 ~/.pwrseq_gen/gui_settings.json。"""

    def __init__(self):
        self._path = os.path.join(_PWRSEQ_USER_DIR, "gui_settings.json")
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(_PWRSEQ_USER_DIR, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_preview_font_size(self) -> int:
        try:
            size = int(self._data.get("preview_font_size", PREVIEW_FONT_SIZE_DEFAULT))
        except (TypeError, ValueError):
            return PREVIEW_FONT_SIZE_DEFAULT
        return size if size in PREVIEW_FONT_SIZES else PREVIEW_FONT_SIZE_DEFAULT

    def set_preview_font_size(self, size: int) -> None:
        if size not in PREVIEW_FONT_SIZES:
            return
        self._data["preview_font_size"] = size
        self._save()


class RecentFiles:
    """Recent files 儲存於 ~/.pwrseq_gen/recent.json，最多 8 個。"""

    MAX = 8

    def __init__(self):
        self._dir = _PWRSEQ_USER_DIR
        self._path = os.path.join(self._dir, "recent.json")
        self._items: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            with open(self._path, encoding="utf-8") as f:
                items = json.load(f)
            return [p for p in items if isinstance(p, str) and os.path.isfile(p)][: self.MAX]
        except Exception:
            return []

    def _save(self) -> None:
        try:
            os.makedirs(self._dir, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add(self, path: str) -> None:
        if not path:
            return
        path = os.path.abspath(path)
        if path in self._items:
            self._items.remove(path)
        self._items.insert(0, path)
        self._items = self._items[: self.MAX]
        self._save()

    def list(self) -> list[str]:
        return list(self._items)


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


class WaveDromNodeSelectDialog(ctk.CTkToplevel):
    """選擇要包含在 WaveDrom / Schemdraw 圖中的節點（模擬仍用全案）。"""

    def __init__(
        self,
        master,
        rails: list[PowerRail],
        export_callback: Callable[[WaveDromExportOptions], None],
        *,
        title: str = "Export WaveDrom — Select Nodes",
        select_hint: str = "Select nodes to include in the WaveDrom export.",
        action_label: str = "Export…",
        initial_options: WaveDromExportOptions | None = None,
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
        self._shift_click = False
        if initial_options is not None:
            if initial_options.edge_kinds == WAVEDROM_EDGE_HI_ONLY:
                edge_default = "hi"
            elif initial_options.edge_kinds == WAVEDROM_EDGE_LO_ONLY:
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
            text="Shift+Click a checkbox to select a contiguous range (Nodes order).",
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
                command=lambda i=idx: self._on_checkbox_changed(i),
            )
            cb.pack(anchor="w")
            cb.bind("<Button-1>", lambda e, i=idx: self._on_checkbox_button(i, e), add="+")
            self._row_frames.append(row)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=S_MD, pady=(0, S_MD))
        ctk.CTkButton(btns, text="Close", width=90, command=self._close).pack(side="right", padx=(S_SM, 0))
        ctk.CTkButton(btns, text=self._action_label, width=90, command=self._export).pack(side="right")

        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._update_count()
        search.focus_set()

    def _on_checkbox_button(self, idx: int, event) -> None:
        self._shift_click = bool(event.state & 0x0001)

    def _on_checkbox_changed(self, idx: int) -> None:
        name = self._rails[idx].name
        state = self._vars[name].get()
        if self._shift_click and self._anchor_idx is not None:
            lo, hi = sorted((self._anchor_idx, idx))
            for i in range(lo, hi + 1):
                self._vars[self._rails[i].name].set(state)
        elif not self._shift_click:
            self._anchor_idx = idx
        self._shift_click = False
        self._update_count()

    def _apply_filter(self) -> None:
        ft = self.search_var.get().strip().lower()
        for rail, row in zip(self._rails, self._row_frames):
            show = not ft or ft in rail.name.lower() or ft in rail.seq_type.lower()
            if show:
                row.pack(fill="x", pady=1)
            else:
                row.pack_forget()

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

    def _export_options(self) -> WaveDromExportOptions | None:
        selected = {name for name, var in self._vars.items() if var.get()}
        if not selected:
            messagebox.showwarning(
                "No Nodes Selected",
                "Select at least one node.",
                parent=self,
            )
            return None
        return WaveDromExportOptions(
            include_rails=frozenset(selected),
            edge_kinds=wavedrom_edge_kinds_from_choice(self._edge_var.get()),
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


# ============================================================
# PowerSeqGUI — 主視窗
# ============================================================

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
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._preview_after_id: Optional[str] = None
        self._schemdraw_preview_after_id: Optional[str] = None
        self._schemdraw_render_gen = 0
        self._schemdraw_preview_opts: WaveDromExportOptions | None = None
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
    _EXPORT_MENU_ITEMS = ("Draw.io", "WaveDrom", "Schemdraw")

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

        self._sep(toolbar)
        wd_opts = ctk.CTkFrame(toolbar, fg_color="transparent")
        wd_opts.pack(side="left", padx=(0, S_SM))
        ctk.CTkLabel(wd_opts, text="Steps:", font=FONT_BODY).pack(side="left", padx=(0, S_XS))
        self._wd_steps_var = tk.StringVar(value="50")
        wd_steps = ctk.CTkEntry(wd_opts, textvariable=self._wd_steps_var, width=56, height=28)
        wd_steps.pack(side="left", padx=(0, S_SM))
        self._tt(wd_steps, "WaveDrom simulation length (saved with project)")
        ctk.CTkLabel(wd_opts, text="hscale:", font=FONT_BODY).pack(side="left", padx=(0, S_XS))
        self._wd_hscale_var = tk.StringVar(value="1")
        wd_hscale = ctk.CTkEntry(wd_opts, textvariable=self._wd_hscale_var, width=40, height=28)
        wd_hscale.pack(side="left")
        self._tt(wd_hscale, "WaveDrom horizontal pixels per step (default 1)")
        for w in (wd_steps, wd_hscale):
            w.bind("<FocusOut>", self._on_wavedrom_globals_changed, add="+")
            w.bind("<Return>", self._on_wavedrom_globals_changed, add="+")

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
        self._tt(export_menu, "Export Draw.io (Ctrl+E), WaveDrom (Ctrl+Shift+E), or Schemdraw")
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
        self.bind_all("<Control-Shift-e>", lambda _e: self._export_wavedrom())
        self.bind_all("<Control-Shift-E>", lambda _e: self._export_wavedrom())
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
        self._undo_stack.append(snap)
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_btns()

    def _undo(self):
        if not self._undo_stack:
            return
        current = json.dumps(self._collect_config().to_dict(), ensure_ascii=False)
        self._redo_stack.append(current)
        target = self._undo_stack.pop()
        self.config_obj = PowerSeqConfig.from_dict(json.loads(target))
        self._refresh_all()
        self._mark_dirty()
        self._update_undo_btns()

    def _redo(self):
        if not self._redo_stack:
            return
        current = json.dumps(self._collect_config().to_dict(), ensure_ascii=False)
        self._undo_stack.append(current)
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        target = self._redo_stack.pop()
        self.config_obj = PowerSeqConfig.from_dict(json.loads(target))
        self._refresh_all()
        self._mark_dirty()
        self._update_undo_btns()

    def _update_undo_btns(self):
        self._undo_btn.configure(state="normal" if self._undo_stack else "disabled")
        self._redo_btn.configure(state="normal" if self._redo_stack else "disabled")

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

    def _wavedrom_globals_from_toolbar(self) -> tuple[int, int]:
        try:
            steps = max(10, int(self._wd_steps_var.get().strip()))
        except (ValueError, tk.TclError):
            steps = 50
        try:
            hscale = _norm_hscale(int(self._wd_hscale_var.get().strip()))
        except (ValueError, tk.TclError):
            hscale = 1
        return steps, hscale

    def _sync_wavedrom_toolbar_from_config(self) -> None:
        wd = self.config_obj.wavedrom_scenario or {}
        steps = int(wd.get("steps", 50))
        hscale = int(wd.get("hscale", wd.get("cond_step_delay", 1)))
        self._wd_steps_var.set(str(steps))
        self._wd_hscale_var.set(str(hscale))

    def _on_wavedrom_globals_changed(self, _event=None):
        steps, hscale = self._wavedrom_globals_from_toolbar()
        self._wd_steps_var.set(str(steps))
        self._wd_hscale_var.set(str(hscale))
        self._mark_dirty()

    def _wavedrom_scenario_for_export(self, cfg: PowerSeqConfig) -> WaveDromScenario:
        return build_wavedrom_scenario(cfg)

    # ---- collect ----
    def _collect_config(self) -> PowerSeqConfig:
        rails = [cf.rail for cf in self.collapsible_frames]
        self.config_obj.rails = rails
        steps, hscale = self._wavedrom_globals_from_toolbar()
        has_input = any(r.seq_type == "input" for r in rails)
        wavedrom_scenario = None
        if has_input or steps != 50 or hscale != 1:
            wavedrom_scenario = {"steps": steps}
            if hscale != 1:
                wavedrom_scenario["hscale"] = hscale
        self.config_obj.wavedrom_scenario = wavedrom_scenario
        return PowerSeqConfig(
            rails=rails,
            module_name=self.config_obj.module_name,
            clock_freq_mhz=self.config_obj.clock_freq_mhz,
            pulse_period_ns=self.config_obj.pulse_period_ns,
            pulses=getattr(self.config_obj, "pulses", None) or [DEFAULT_PULSE],
            wavedrom_scenario=wavedrom_scenario,
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

        # validation / preview 會 _collect_config()，須先讓 toolbar 與 config 一致
        self._sync_wavedrom_toolbar_from_config()

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
        if edge_kinds == WAVEDROM_EDGE_HI_ONLY:
            return "Hi arrows"
        if edge_kinds == WAVEDROM_EDGE_LO_ONLY:
            return "Lo arrows"
        return "Hi+Lo arrows"

    def _schemdraw_preview_options(self, cfg: PowerSeqConfig) -> WaveDromExportOptions:
        exportable = self._exportable_rail_names(cfg)
        if self._schemdraw_preview_opts is None:
            return WaveDromExportOptions(
                include_rails=exportable,
                edge_kinds=WAVEDROM_EDGE_BOTH,
            )
        kept = frozenset(
            n for n in self._schemdraw_preview_opts.include_rails if n in exportable
        )
        if not kept:
            kept = exportable
        return WaveDromExportOptions(
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
        dlg = WaveDromNodeSelectDialog(
            self,
            cfg.rails,
            self._on_schemdraw_preview_nodes_selected,
            title="Schemdraw Preview — Select Nodes",
            select_hint="Select nodes to include in the Schemdraw preview.",
            action_label="Apply",
            initial_options=initial,
        )
        self._schemdraw_preview_nodes_dlg = dlg

    def _on_schemdraw_preview_nodes_selected(self, opts: WaveDromExportOptions) -> None:
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
            scenario = self._wavedrom_scenario_for_export(cfg)
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
            ("Ctrl+Shift+E",  "Export WaveDrom JSON"),
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
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._current_path = path
            self._recent.add(path)
            self._refresh_all()
            self._mark_clean()
            self._status_msg(f"Loaded: {os.path.basename(path)}", level="success")
        except Exception as e:
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
        elif choice == "WaveDrom":
            self._export_wavedrom()
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
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Generate {label} failed: {e}", level="error")

    def _run_wavedrom_export(self, export_opts: WaveDromExportOptions) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("WaveDrom JSON", "*.json"), ("All", "*")],
        )
        if not path:
            return
        try:
            cfg2 = self._collect_config()
            scenario = self._wavedrom_scenario_for_export(cfg2)
            text = generate_wavedrom_json(
                cfg2,
                scenario,
                output_filename=path,
                include_rails=export_opts.include_rails,
                edge_kinds=export_opts.edge_kinds,
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            n = len(export_opts.include_rails)
            if export_opts.edge_kinds == WAVEDROM_EDGE_HI_ONLY:
                edge_label = "Hi arrows"
            elif export_opts.edge_kinds == WAVEDROM_EDGE_LO_ONLY:
                edge_label = "Lo arrows"
            else:
                edge_label = "Hi+Lo arrows"
            self._status_msg(
                f"Exported WaveDrom ({n} nodes, {edge_label}): {os.path.basename(path)}",
                level="success",
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._status_msg(f"WaveDrom export failed: {e}", level="error")

    def _export_wavedrom(self):
        cfg = self._collect_config()
        ok, errs = validate(cfg)
        if not ok:
            messagebox.showerror("Validation Failed", "\n".join(errs))
            self._status_msg(f"{len(errs)} validation error(s); cannot export", level="error")
            return
        if not cfg.rails:
            self._status_msg("No nodes. Add rails first.", level="warn")
            return
        existing = getattr(self, "_timing_export_dlg", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        dlg = WaveDromNodeSelectDialog(
            self, cfg.rails, self._run_wavedrom_export,
            title="Export WaveDrom — Select Nodes",
            select_hint="Select nodes to include in the WaveDrom export.",
        )
        self._timing_export_dlg = dlg
        self.wait_window(dlg)
        self._timing_export_dlg = None

    def _run_schemdraw_export(self, export_opts: WaveDromExportOptions) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".svg",
            filetypes=[
                ("SVG", "*.svg"),
                ("PNG", "*.png"),
                ("All", "*"),
            ],
        )
        if not path:
            return
        try:
            cfg2 = self._collect_config()
            scenario = self._wavedrom_scenario_for_export(cfg2)
            export_schemdraw_from_options(cfg2, scenario, export_opts, path)
            n = len(export_opts.include_rails)
            if export_opts.edge_kinds == WAVEDROM_EDGE_HI_ONLY:
                edge_label = "Hi arrows"
            elif export_opts.edge_kinds == WAVEDROM_EDGE_LO_ONLY:
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
        existing = getattr(self, "_timing_export_dlg", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        dlg = WaveDromNodeSelectDialog(
            self, cfg.rails, self._run_schemdraw_export,
            title="Export Schemdraw — Select Nodes",
            select_hint="Select nodes to include in the Schemdraw diagram.",
        )
        self._timing_export_dlg = dlg
        self.wait_window(dlg)
        self._timing_export_dlg = None

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
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Export failed: {e}", level="error")


def run_gui():
    if not ensure_not_expired():
        return
    app = PowerSeqGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
