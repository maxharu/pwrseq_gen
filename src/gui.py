"""
Power Sequence Config GUI v1.2

主要改善（相對 v1.1）：
- Hi/Lo/Force Cond 三段抽象為 CondSectionFrame，去除 ~500 行重複（B1）
- Hi/Lo/Force 改 Tab 顯示，節點展開後高度減半（B2）
- 三段以顏色語意區分：Hi=綠 / Lo=紅 / Force=琥珀（A1）
- Header chip 化（[Output] [HI:8] [LO:4] [INIT:0]）（A2）
- Dirty flag（title 顯示 *）、快捷鍵 Ctrl+S/Shift+S/O/N/G/E/F/Z/Y/Delete、F1 Help（A3）
- 自動 commit（FocusOut / radio trace），拿掉每張卡片的 Apply 按鈕（A4）
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
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

# 關閉自動 DPI 縮放，避免縮放時 dropdown 出現 TclError。
ctk.deactivate_automatic_dpi_awareness()

from config_models import PowerRail, PowerSeqConfig
from drawio_export import generate_drawio
from validator import validate
from verilog_generator import generate_verilog
from c_generator import generate_c

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

# fonts
FONT_TITLE = ("", 14, "bold")
FONT_SECTION = ("", 12, "bold")
FONT_BODY = ("", 11)
FONT_CHIP = ("", 10, "bold")
FONT_HINT = ("", 10)
FONT_MONO = ("Consolas", 10)

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

TYPE_THEME = {
    "output": {"pill_bg": ("#dbeafe", "#1e3a8a"), "pill_fg": ("#1e3a8a", "#dbeafe")},
    "input":  {"pill_bg": ("#fae8ff", "#581c87"), "pill_fg": ("#581c87", "#fae8ff")},
}

USE_LABELS = {"self": "Node", "hi": "Hi Cond", "lo": "Lo Cond", "force": "Force Cond"}
USE_REVERSE = {v: k for k, v in USE_LABELS.items()}

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
    groups: list[list[str]]，group 內 AND，groups 間 OR。
    """

    def __init__(self, master, kind: str,
                 get_dep_options: Callable[[], list[str]],
                 is_pseqcell_for: Callable[[str], bool],
                 initial_groups: list[list[str]],
                 initial_inv_groups: list[list[bool]],
                 initial_use_groups: list[list[str]],
                 initial_inv_flat: dict,
                 initial_use_flat: dict,
                 on_change: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.kind = kind
        self.theme = COND_THEME[kind]
        self.get_dep_options = get_dep_options
        self.is_pseqcell_for = is_pseqcell_for
        self.on_change = on_change

        self.groups: list[list[str]] = [list(g) for g in (initial_groups or [[]])]
        if not self.groups:
            self.groups = [[]]

        self._init_inv_groups = initial_inv_groups or []
        self._init_use_groups = initial_use_groups or []
        self._init_inv_flat = initial_inv_flat or {}
        self._init_use_flat = initial_use_flat or {}

        self.inv_vars: dict[tuple[int, int], ctk.BooleanVar] = {}
        self.use_vars: dict[tuple[int, int], ctk.StringVar] = {}
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

    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, S_SM))
        ctk.CTkLabel(toolbar, text="group 內 AND, groups 間 OR",
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
        self.rows.clear()
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
        frame.pack(fill="x", pady=S_XS, padx=(S_LG, 0))

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=S_SM, pady=S_XS)

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
                     font=FONT_CHIP, width=60).pack(side="left", padx=(0, S_SM))

        dep_options = self.get_dep_options() or [""]
        combo = ctk.CTkComboBox(header, values=dep_options, width=140)
        combo.pack(side="left", padx=(0, S_SM))
        combo.set(dep_options[0])

        ctk.CTkButton(header, text="+ Add", width=60,
                      command=lambda g=gi: self._add_cond_to_group(g)).pack(side="left", padx=(0, S_SM))
        ctk.CTkButton(header, text="Del Group", width=80,
                      command=lambda g=gi: self._remove_group(g)).pack(side="left")

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
            ctk.CTkComboBox(row, values=list(USE_LABELS.values()),
                            variable=self.use_vars[key], width=100).pack(side="left", padx=(0, S_SM))
        captured = key
        ctk.CTkButton(row, text="Del", width=50,
                      command=lambda k=captured: self._remove_cond_by_key(k)).pack(side="left")

    def add_group(self):
        self.groups.append([])
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
        if not self.groups:
            self.groups = [[]]
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
# RailEditorFrame — 單一 rail 的屬性編輯面板
# ============================================================

class RailEditorFrame(ctk.CTkFrame):
    """單一 rail 編輯器。

    與 v1.1 不同：
    - 拿掉 Apply 按鈕，改成 FocusOut / radio trace 自動 commit。
    - Hi/Lo/Force 改用 CTkTabview 呈現，由 CondSectionFrame 提供內容。
    - 內部分為 General / Timing / Conditions / Debounce 四個 section。
    """

    def __init__(self, master, rail: PowerRail,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_rename: Callable[[str, str], None],
                 on_type_change: Callable[[str, str, str], None],
                 on_change: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.rail = rail
        self.get_all_rails = get_all_rails
        self.get_pulses = get_pulses
        self.on_rename = on_rename
        self.on_type_change = on_type_change
        self.on_change = on_change

        self._build_ui()

    def _fire_change(self, *_):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:
                pass

    # ---- helpers ----
    def _dep_options(self) -> list[str]:
        return [r.name for r in self.get_all_rails() if r.name != self.rail.name] + ["High", "Low"]

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
        self.entry_name.bind("<FocusOut>", self._on_name_commit)
        self.entry_name.bind("<Return>", self._on_name_commit)

        ctk.CTkLabel(grid, text="Type:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        type_row = ctk.CTkFrame(grid, fg_color="transparent")
        type_row.grid(row=0, column=3, sticky="w", pady=2)
        self.var_type = ctk.StringVar(value=self.rail.seq_type)
        self._old_type = self.rail.seq_type
        for st, label in SEQ_TYPE_LABELS.items():
            ctk.CTkRadioButton(type_row, text=label,
                               variable=self.var_type, value=st).pack(side="left", padx=(0, S_SM))
        self.var_type.trace_add("write", lambda *_: self._on_type_toggle())

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
        self.entry_hi.bind("<FocusOut>", self._fire_change)

        ctk.CTkLabel(grid_t, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_lo = ctk.CTkEntry(grid_t, width=100)
        self.entry_lo.insert(0, str(self.rail.cycle_lo))
        self.entry_lo.grid(row=0, column=3, sticky="w", pady=2)
        self.entry_lo.bind("<FocusOut>", self._fire_change)

        ctk.CTkLabel(grid_t, text="INIT:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pseq_init = ctk.StringVar(value="1" if getattr(self.rail, "init", 0) == 1 else "0")
        ctk.CTkComboBox(grid_t, values=["0", "1"], variable=self.var_pseq_init, width=100).grid(
            row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)
        self.var_pseq_init.trace_add("write", self._fire_change)

        pulses = self._pulse_values(
            getattr(self.rail, "pulse_hi", "iPulse_1us"),
            getattr(self.rail, "pulse_lo", "iPulse_1us"),
            getattr(self.rail, "pulse_force", "iPulse_1us"),
        )
        ctk.CTkLabel(grid_t, text="Timing Hi:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_hi = ctk.StringVar(value=getattr(self.rail, "pulse_hi", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_hi, width=130).grid(
            row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)
        self.var_pulse_hi.trace_add("write", self._fire_change)

        ctk.CTkLabel(grid_t, text="Timing Lo:", font=FONT_BODY).grid(
            row=2, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_lo = ctk.StringVar(value=getattr(self.rail, "pulse_lo", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_lo, width=130).grid(
            row=2, column=3, sticky="w", pady=2)
        self.var_pulse_lo.trace_add("write", self._fire_change)

        ctk.CTkLabel(grid_t, text="Timing Force:", font=FONT_BODY).grid(
            row=3, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_force = ctk.StringVar(value=getattr(self.rail, "pulse_force", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_force, width=130).grid(
            row=3, column=1, sticky="w", padx=(0, S_LG), pady=2)
        self.var_pulse_force.trace_add("write", self._fire_change)

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
            sec = CondSectionFrame(
                tab, kind,
                get_dep_options=self._dep_options,
                is_pseqcell_for=self._is_pseqcell_for,
                initial_groups=init_groups,
                initial_inv_groups=init_inv,
                initial_use_groups=init_use,
                initial_inv_flat=init_inv_flat,
                initial_use_flat=init_use_flat,
                on_change=self._fire_change,
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
        self.entry_deb_cycle_hi.bind("<FocusOut>", self._fire_change)

        ctk.CTkLabel(grid_d, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_lo = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_lo.insert(0, str(getattr(self.rail, "deb_cycle_lo", 2)))
        self.entry_deb_cycle_lo.grid(row=0, column=3, sticky="w", pady=2)
        self.entry_deb_cycle_lo.bind("<FocusOut>", self._fire_change)

        ctk.CTkLabel(grid_d, text="CYCLE_SYNC:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_sync = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_sync.insert(0, str(getattr(self.rail, "deb_cycle_sync", 2)))
        self.entry_deb_cycle_sync.grid(row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)
        self.entry_deb_cycle_sync.bind("<FocusOut>", self._fire_change)

        ctk.CTkLabel(grid_d, text="INIT:", font=FONT_BODY).grid(
            row=1, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_deb_init = ctk.StringVar(value="1" if getattr(self.rail, "deb_init", 0) == 1 else "0")
        ctk.CTkComboBox(grid_d, values=["0", "1"], variable=self.var_deb_init, width=100).grid(
            row=1, column=3, sticky="w", pady=2)
        self.var_deb_init.trace_add("write", self._fire_change)

        ctk.CTkLabel(grid_d, text="Timing Deb:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        deb_pulses = self._pulse_values(getattr(self.rail, "deb_pulse", "iPulse_1us"))
        self.var_deb_pulse = ctk.StringVar(value=getattr(self.rail, "deb_pulse", "iPulse_1us") or "iPulse_1us")
        ctk.CTkComboBox(grid_d, values=deb_pulses, variable=self.var_deb_pulse, width=130).grid(
            row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)
        self.var_deb_pulse.trace_add("write", self._fire_change)

        self._on_type_toggle(initial=True)

    # ---- callbacks ----
    def _on_name_commit(self, _event=None):
        new_name = self.entry_name.get().strip()
        if new_name and new_name != self.rail.name:
            self.on_rename(self.rail.name, new_name)

    def _on_type_toggle(self, initial: bool = False):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.timing_wrap.pack_forget()
            self.cond_wrap.pack_forget()
            self.deb_wrap.pack(fill="x", pady=(0, S_SM))
            self._on_deb_toggle()
        else:
            self.deb_wrap.pack_forget()
            self.timing_wrap.pack(fill="x", pady=(0, S_SM))
            self.cond_wrap.pack(fill="x", pady=(0, S_SM))
        if not initial and self.var_type.get() != self._old_type:
            old = self._old_type
            self._old_type = self.var_type.get()
            self.on_type_change(self.rail.name, old, self.var_type.get())

    def _on_deb_toggle(self):
        if self.var_deb_enable.get():
            self.deb_params.pack(fill="x")
        else:
            self.deb_params.pack_forget()
        self._fire_change()

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

        seq_type = self.var_type.get()
        if seq_type == "input":
            cycle_hi, cycle_lo = 0, 0
            groups_hi, groups_lo, groups_force = [], [], []
            flat_hi, flat_lo, flat_force = [], [], []
            hi_inv_groups = lo_inv_groups = force_inv_groups = []
            hi_use_groups = lo_use_groups = force_use_groups = []

        return PowerRail(
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
            depends_on_force=flat_force,
            depends_on_force_groups=groups_force,
            depends_on_force_inv=fo.get_inv_flat() if seq_type != "input" else {},
            depends_on_force_use=fo.get_use_flat() if seq_type != "input" else {},
            depends_on_force_inv_groups=force_inv_groups,
            depends_on_force_use_groups=force_use_groups,
            pulse_hi=self.var_pulse_hi.get() if seq_type != "input" else "iPulse_1us",
            pulse_lo=self.var_pulse_lo.get() if seq_type != "input" else "iPulse_1us",
            pulse_force=self.var_pulse_force.get() if seq_type != "input" else "iPulse_1us",
            deb_enable=self.var_deb_enable.get() if seq_type == "input" else False,
            deb_init=1 if (seq_type == "input" and self.var_deb_init.get() == "1") else 0,
            deb_cycle_hi=_safe_int(self.entry_deb_cycle_hi.get(), 2) if seq_type == "input" else 2,
            deb_cycle_lo=_safe_int(self.entry_deb_cycle_lo.get(), 2) if seq_type == "input" else 2,
            deb_cycle_sync=_safe_int(self.entry_deb_cycle_sync.get(), 2) if seq_type == "input" else 2,
            deb_pulse=self.var_deb_pulse.get() if seq_type == "input" else "iPulse_1us",
            cycle_hi=cycle_hi,
            cycle_lo=cycle_lo,
            cycle_force=self.rail.cycle_force,
            recover=self.rail.recover,
            init=1 if (seq_type != "input" and self.var_pseq_init.get() == "1") else 0,
            force_val=self.rail.force_val,
            cycle_sync=self.rail.cycle_sync,
            od=self.rail.od,
        )


# ============================================================
# CollapsibleRailFrame — accordion 卡片，header 採用 chip 化（A2）
# ============================================================

class CollapsibleRailFrame(ctk.CTkFrame):
    """Accordion wrapper：可點擊 header + 可摺疊 RailEditorFrame。"""

    def __init__(self, master, rail: PowerRail,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_rename: Callable[[str, str], None],
                 on_type_change: Callable[[str, str, str], None],
                 on_change: Optional[Callable[[], None]] = None,
                 expanded: bool = False, **kwargs):
        super().__init__(master, **kwargs)
        self.rail = rail
        self._expanded = expanded
        self._get_all_rails = get_all_rails
        self._get_pulses = get_pulses
        self._on_rename = on_rename
        self._on_type_change = on_type_change
        self._on_change = on_change
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
            chips.append((f"INIT:{getattr(self.rail, 'init', 0)}", None, None))
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
            on_rename=self._on_rename,
            on_type_change=self._on_type_change,
            on_change=self._on_change,
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
        if self.editor is None:
            return self.rail
        return self.editor.get_rail()


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
                 **kwargs):
        super().__init__(master, **kwargs)
        self.on_select = on_select
        self.on_reorder = on_reorder
        self.on_multi_change = on_multi_change
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
        ctk.CTkLabel(self, text="Sequence Node", font=FONT_TITLE).pack(pady=(S_MD, S_SM))
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Search node (Ctrl+F)",
                                         textvariable=self.search_var)
        self.search_entry.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        self.search_var.trace_add("write", lambda *_: self._render())

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=S_XS, pady=S_XS)

        self.multi_status = ctk.CTkLabel(self, text="", font=FONT_HINT, text_color="gray")
        self.multi_status.pack(fill="x", padx=S_SM)

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
        else:
            self.multi_status.configure(text=f"{n} nodes selected")

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
    """左側 Pulse 訊號管理區。"""

    def __init__(self, master, on_change: Callable[[list[str]], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_change = on_change
        self._pulses: list[str] = ["iPulse_1us"]
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="Timing Signals", font=FONT_TITLE).pack(pady=(S_MD, S_SM))
        self.entry = ctk.CTkEntry(self, placeholder_text="New signal (Enter to add)")
        self.entry.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        self.entry.bind("<Return>", lambda _e: self._on_add())
        self.entry.bind("<KP_Enter>", lambda _e: self._on_add())
        self.listbox = tk.Listbox(self, font=FONT_MONO, selectmode="single", height=4)
        self.listbox.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=S_SM, pady=(0, S_SM))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_row, text="+ Add", command=self._on_add).grid(
            row=0, column=0, sticky="ew", padx=(0, S_XS))
        ctk.CTkButton(btn_row, text="- Delete", command=self._on_del).grid(
            row=0, column=1, sticky="ew", padx=(S_XS, 0))

    def set_pulses(self, pulses: list[str]):
        self._pulses = list(pulses) if pulses else ["iPulse_1us"]
        self.listbox.delete(0, tk.END)
        for p in self._pulses:
            self.listbox.insert(tk.END, p)

    def _on_add(self):
        name = self.entry.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter pulse name")
            return
        if name in self._pulses:
            messagebox.showwarning("Notice", f"Pulse '{name}' already exists")
            return
        new_list = self._pulses + [name]
        self.on_change(new_list)
        self.entry.delete(0, tk.END)

    def _on_del(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Notice", "Select a pulse to delete")
            return
        idx = sel[0]
        if len(self._pulses) <= 1:
            messagebox.showwarning("Notice", "At least one pulse required")
            return
        new_list = [p for i, p in enumerate(self._pulses) if i != idx]
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

PREVIEW_LANGS = ("Verilog", "C")


class PreviewPanel(ctk.CTkFrame):
    """右側預覽面板：Verilog 或 C read-only text，內建主題化捲軸。"""

    def __init__(self, master, on_lang_change: Optional[Callable[[], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_lang_change = on_lang_change
        self._build_ui()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=S_SM, pady=(S_SM, 0))
        self._title = ctk.CTkLabel(header, text="Verilog Preview", font=FONT_SECTION)
        self._title.pack(side="left")
        self._lang_var = tk.StringVar(value="Verilog")
        self._lang_menu = ctk.CTkOptionMenu(
            header, values=list(PREVIEW_LANGS), variable=self._lang_var, width=88,
            command=self._on_lang_selected,
        )
        self._lang_menu.pack(side="left", padx=(S_SM, 0))
        self._status = ctk.CTkLabel(header, text="", font=FONT_HINT, text_color="gray")
        self._status.pack(side="right")
        self._text = ctk.CTkTextbox(self, font=FONT_MONO, wrap="none",
                                    activate_scrollbars=True)
        self._text.pack(fill="both", expand=True, padx=S_SM, pady=(S_XS, S_SM))
        self._text.configure(state="disabled")

    def _on_lang_selected(self, _value: str):
        self._update_title()
        if self.on_lang_change:
            self.on_lang_change()

    def _update_title(self):
        lang = self.get_lang()
        self._title.configure(text=f"{lang} Preview")

    def get_lang(self) -> str:
        v = self._lang_var.get()
        return v if v in PREVIEW_LANGS else "Verilog"

    def _set_text(self, content: str):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("1.0", content)
        self._text.configure(state="disabled")

    def set_code(self, code: str, status: str = ""):
        self._update_title()
        self._set_text(code)
        self._status.configure(text=status, text_color="gray")

    def set_verilog(self, code: str, status: str = ""):
        """相容舊呼叫；等同 set_code。"""
        self.set_code(code, status=status)

    def set_error(self, msg: str):
        self._update_title()
        self._set_text(f"// 無法預覽：\n// {msg}")
        self._status.configure(text="error", text_color=("#cf222e", "#ff7b72"))


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
    """底部 status bar：左=檔名+dirty / 中=節點統計 / 右=訊息（toast 文字）。"""

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


class RecentFiles:
    """Recent files 儲存於 ~/.pwrseq_gen/recent.json，最多 8 個。"""

    MAX = 8

    def __init__(self):
        self._dir = os.path.join(os.path.expanduser("~"), ".pwrseq_gen")
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


class HelpDialog(ctk.CTkToplevel):
    """快捷鍵清單對話框（F1 開啟）。"""

    def __init__(self, master, shortcuts: list[tuple[str, str]]):
        super().__init__(master)
        self.title("Shortcuts")
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
        self._base_title = "Power Sequence Config v1.2"
        self.title(self._base_title)
        self.geometry("1400x850")
        self.minsize(1000, 650)
        self.config_obj = PowerSeqConfig()

        self._dirty = False
        self._topmost = False
        self._inspect_mode = False
        self._show_preview = True
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._preview_after_id: Optional[str] = None
        self._editor_change_after_id: Optional[str] = None
        self._current_path: Optional[str] = None
        self._recent = RecentFiles()
        self._tooltips: list[Tooltip] = []  # 強引用，避免 GC

        self._build_ui()
        self._bind_shortcuts()
        self._refresh_all()

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

    def _build_ui(self):
        # ----- Toolbar -----
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=S_MD, pady=(S_MD, S_SM))

        # group: edit
        b_add = ctk.CTkButton(toolbar, text="+ Add", width=70, command=self._add_rail)
        b_add.pack(side="left", padx=(0, S_XS))
        self._tt(b_add, "Add new node  (Ctrl+N)")
        b_del = ctk.CTkButton(toolbar, text="- Delete", width=80, command=self._delete_selected)
        b_del.pack(side="left", padx=(0, S_SM))
        self._tt(b_del, "Delete selected nodes  (Del)")

        self._sep(toolbar)

        # group: file
        self._open_btn = ctk.CTkButton(toolbar, text="Open", width=70, command=self._load_json)
        self._open_btn.pack(side="left", padx=(0, S_XS))
        self._tt(self._open_btn, "Open JSON  (Ctrl+O)")
        self._recent_btn = ctk.CTkButton(toolbar, text="\u25BC", width=24, command=self._show_recent_menu)
        self._recent_btn.pack(side="left", padx=(0, S_SM))
        self._tt(self._recent_btn, "Recent files")
        b_save = ctk.CTkButton(toolbar, text="Save", width=70, command=self._save_json)
        b_save.pack(side="left", padx=(0, S_XS))
        self._tt(b_save, "Save  (Ctrl+S)")
        b_saveas = ctk.CTkButton(toolbar, text="Save As", width=80, command=self._save_json_as)
        b_saveas.pack(side="left", padx=(0, S_SM))
        self._tt(b_saveas, "Save As...  (Ctrl+Shift+S)")

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
        self._tt(cb_pv, "Toggle right-side live code preview (Verilog or C)")

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

        b_export = ctk.CTkButton(toolbar, text="Export Draw.io", width=130,
                                  fg_color=self.ACCENT_FG, hover_color=self.ACCENT_HOVER,
                                  command=self._export_drawio)
        b_export.pack(side="right", padx=(0, S_SM))
        self._tt(b_export, "Export dependency diagram XML  (Ctrl+E)")
        b_gen_c = ctk.CTkButton(toolbar, text="Generate C", width=110,
                                 fg_color=self.ACCENT_FG, hover_color=self.ACCENT_HOVER,
                                 command=self._generate_c)
        b_gen_c.pack(side="right", padx=(0, S_SM))
        self._tt(b_gen_c, "Validate and generate firmware C  (Ctrl+Shift+G)")
        b_gen = ctk.CTkButton(toolbar, text="Generate Verilog", width=140,
                               fg_color=self.ACCENT_FG, hover_color=self.ACCENT_HOVER,
                               command=self._generate_verilog)
        b_gen.pack(side="right", padx=(0, S_SM))
        self._tt(b_gen, "Validate and generate Verilog .v  (Ctrl+G)")

        # ----- Body (3-col, resizable) -----
        body_wrap = ctk.CTkFrame(self, fg_color="transparent")
        body_wrap.pack(fill="both", expand=True, padx=S_MD, pady=(0, 0))

        # 用 tk.PanedWindow 提供拖拉分隔；內嵌 ctk frame
        # opaqueresize=False：拖時只顯示分隔線，放手才 reflow，避免 ctk widgets 持續重繪造成卡頓
        sash_bg = "#374151"
        paned = tk.PanedWindow(
            body_wrap, orient=tk.HORIZONTAL,
            sashrelief="flat", sashwidth=4,
            bg=sash_bg, bd=0,
            opaqueresize=False,
        )
        paned.pack(fill="both", expand=True)
        self._paned = paned

        # left
        left_wrap = ctk.CTkFrame(paned, fg_color=("gray90", "gray17"), width=260)
        paned.add(left_wrap, minsize=200, stretch="never", width=260)

        self.node_list = NodeListPanel(
            left_wrap, on_select=self._on_node_selected,
            on_reorder=self._on_node_reordered,
            on_multi_change=self._on_multi_changed,
        )
        self.node_list.pack(fill="both", expand=True)

        self.pulse_panel = PulsePanel(left_wrap, on_change=self._on_pulses_changed)
        self.pulse_panel.pack(fill="x")

        # middle
        mid = ctk.CTkFrame(paned, fg_color="transparent")
        paned.add(mid, minsize=480, stretch="always")
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

        # right (preview)
        self.preview_wrap = ctk.CTkFrame(paned, fg_color=("gray90", "gray17"), width=380)
        paned.add(self.preview_wrap, minsize=240, stretch="never", width=380)
        self.preview = PreviewPanel(
            self.preview_wrap, fg_color="transparent",
            on_lang_change=self._schedule_preview,
        )
        self.preview.pack(fill="both", expand=True)

        # ----- Status bar -----
        self._status = StatusBar(self)
        self._status.pack(side="bottom", fill="x")

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
        self.bind_all("<Control-f>", lambda _e: self.node_list.focus_search())
        self.bind_all("<Control-F>", lambda _e: self.node_list.focus_search())
        self.bind_all("<Control-z>", lambda _e: self._undo())
        self.bind_all("<Control-Z>", lambda _e: self._undo())
        self.bind_all("<Control-y>", lambda _e: self._redo())
        self.bind_all("<Control-Y>", lambda _e: self._redo())
        # Delete 只在焦點不在 Entry/Text 時才觸發批次刪除
        self.bind_all("<Delete>", self._on_delete_key)

    def _on_delete_key(self, _event):
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)):
            return
        # CTkEntry 內部其實是 tk.Entry 的子類，會被上面 isinstance 攔下
        self._delete_selected()

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

    # ---- live update from rail editor (cond / cycle / pulse / debounce) ----
    def _on_editor_change(self):
        """RailEditor 內任何欄位變動：debounced 更新 header summary、preview、validation。
        並標記 dirty，但不 push undo（避免每次 keystroke 都產生 snapshot）。"""
        if not self._dirty:
            self._mark_dirty()
        if self._editor_change_after_id is not None:
            try:
                self.after_cancel(self._editor_change_after_id)
            except Exception:
                pass
        self._editor_change_after_id = self.after(250, self._apply_editor_change)

    def _apply_editor_change(self):
        self._editor_change_after_id = None
        # 更新所有 header summary（cycle/init/deb 變動會改變 chip）
        for cf in self.collapsible_frames:
            if cf.editor is not None:
                # 用 widget 最新值更新 cf.rail，再 refresh header
                try:
                    cf.rail = cf.editor.get_rail()
                except Exception:
                    pass
                cf.update_summary()
        # 更新左側 list（順帶若 name 也變過則同步）
        primary = self.node_list.get_primary()
        # node_list 顯示是用 self.config_obj.rails 的 name；name 變動已透過 _handle_rename
        # 走另一條路徑，這裡只更新 cycle/init 等 chip，list 不需重建
        self._update_validation()
        self._schedule_preview()

    # ---- collect ----
    def _collect_config(self) -> PowerSeqConfig:
        return PowerSeqConfig(
            rails=[cf.get_rail() for cf in self.collapsible_frames],
            module_name=self.config_obj.module_name,
            clock_freq_mhz=self.config_obj.clock_freq_mhz,
            pulse_period_ns=self.config_obj.pulse_period_ns,
            pulses=getattr(self.config_obj, "pulses", None) or ["iPulse_1us"],
        )

    def _get_pulses(self) -> list[str]:
        return getattr(self.config_obj, "pulses", None) or ["iPulse_1us"]

    def _get_all_rails(self) -> list[PowerRail]:
        return self.config_obj.rails

    # ---- refresh ----
    def _refresh_all(self):
        # 收集當前 expanded 集合，refresh 後保留
        prev_expanded: set[str] = set()
        for cf in self.collapsible_frames:
            if cf._expanded:
                prev_expanded.add(cf.rail.name)

        for w in self.editor_scroll.winfo_children():
            w.destroy()
        self.collapsible_frames = []
        for r in self.config_obj.rails:
            is_expanded = r.name in prev_expanded
            cf = CollapsibleRailFrame(
                self.editor_scroll, r,
                get_all_rails=self._get_all_rails,
                get_pulses=self._get_pulses,
                on_rename=self._handle_rename,
                on_type_change=self._handle_type_change,
                on_change=self._on_editor_change,
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

    def _handle_rename(self, old_name: str, new_name: str):
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Notice", "Name cannot be empty")
            self._refresh_all()
            return
        if new_name != old_name and any(
            r.name == new_name for r in self.config_obj.rails if r.name != old_name
        ):
            messagebox.showerror("Error", f"Name '{new_name}' already exists")
            self._refresh_all()
            return
        target_idx = next(
            (i for i, r in enumerate(self.config_obj.rails) if r.name == old_name), None
        )
        if target_idx is None:
            return
        self._push_undo()
        # 只收集這張卡片的最新 widget 狀態（其它卡片的未提交編輯保留在 widget 中
        # 由下次 commit 點再讀取，這與 v1.1 行為一致）。
        new_rail = self.collapsible_frames[target_idx].get_rail()
        # widget 上的 entry_name 已是 new_name；暫時還原 old_name 讓 rename_rail
        # 能透過 old_name 找到目標並做 dep 替換。
        new_rail.name = old_name
        self.config_obj.rails[target_idx] = new_rail
        if self.config_obj.rename_rail(old_name, new_name):
            self._mark_dirty()
            self.after(50, self._refresh_all)

    def _handle_type_change(self, rail_name: str, old_type: str, new_type: str):
        if old_type == new_type:
            return
        target_idx = next(
            (i for i, r in enumerate(self.config_obj.rails) if r.name == rail_name), None
        )
        if target_idx is None:
            return
        self._push_undo()
        # 只收集這張卡片
        self.config_obj.rails[target_idx] = self.collapsible_frames[target_idx].get_rail()
        self._mark_dirty()
        self.after(50, self._refresh_all)

    # ---- pulses ----
    def _on_pulses_changed(self, new_pulses: list[str]):
        self._push_undo()
        self.config_obj = self._collect_config()
        old_pulses = list(self._get_pulses())
        self.config_obj.pulses = new_pulses
        fallback = new_pulses[0] if new_pulses else "iPulse_1us"
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

    def _toggle_preview(self):
        self._show_preview = bool(self._preview_var.get())
        if self._show_preview:
            self.preview_wrap.pack(side="left", fill="y", padx=(S_MD, 0))
            self._schedule_preview()
        else:
            self.preview_wrap.pack_forget()

    def _schedule_preview(self):
        if not self._show_preview:
            return
        if self._preview_after_id is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:
                pass
        self._preview_after_id = self.after(300, self._render_preview)

    def _preview_c_filename(self) -> str:
        """預覽 C 時決定 output_filename（影響 guard / 函式前綴）。"""
        if self._current_path and self._current_path.lower().endswith(".json"):
            return os.path.splitext(self._current_path)[0] + ".c"
        return "power.c"

    def _render_preview(self):
        self._preview_after_id = None
        if not self._show_preview:
            return
        try:
            cfg = self._collect_config()
            ok, errs = validate(cfg)
            status = "live" if ok else f"{len(errs)} error{'s' if len(errs) != 1 else ''}"
            if self.preview.get_lang() == "C":
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

    # ---- help ----
    def _open_help(self):
        shortcuts = [
            ("Ctrl+N",        "Add new node"),
            ("Delete",        "Delete selected nodes"),
            ("Ctrl+O",        "Open JSON"),
            ("Ctrl+S",        "Save (overwrite if path known)"),
            ("Ctrl+Shift+S",  "Save As..."),
            ("Ctrl+G",        "Generate Verilog"),
            ("Ctrl+Shift+G",  "Generate C"),
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
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
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
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile=os.path.basename(self._current_path) if self._current_path else "",
        )
        if not path:
            return
        return self._save_to(path, cfg)

    def _save_to(self, path: str, cfg: Optional[PowerSeqConfig] = None):
        if cfg is None:
            cfg = self._collect_config()
        try:
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

    def _export_drawio(self):
        cfg = self._collect_config()
        if not cfg.rails:
            self._status_msg("No nodes. Add rails first.", level="warn")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xml",
            filetypes=[("XML", "*.xml"), ("All", "*")],
        )
        if not path:
            return
        try:
            xml = generate_drawio(cfg)
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml)
            self._status_msg(f"Exported: {os.path.basename(path)}", level="success")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._status_msg(f"Export failed: {e}", level="error")


def run_gui():
    app = PowerSeqGUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
