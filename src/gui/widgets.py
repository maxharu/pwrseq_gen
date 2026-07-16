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

        gi_slot = [gi]
        frame._gi_slot = gi_slot  # type: ignore[attr-defined]

        group_bg = _resolve_ctk_color(frame.cget("fg_color"))
        header = _make_hscroll_row(frame, bg_color=group_bg, row_height=34)

        handle = ctk.CTkLabel(header, text="\u2261", width=18,
                              text_color=("gray40", "gray70"), cursor="hand2")
        handle.pack(side="left", padx=(0, S_SM))
        handle.bind("<ButtonPress-1>",
                    lambda _e, s=gi_slot: self._on_group_drag_start(s[0]))
        handle.bind("<B1-Motion>",
                    lambda e: self._on_group_drag_motion(e))
        handle.bind("<ButtonRelease-1>",
                    lambda _e: self._on_group_drag_release())

        title_label = ctk.CTkLabel(header, text=f"Group {gi + 1}",
                     text_color=self.theme["text"],
                     font=FONT_CHIP, width=56)
        title_label.pack(side="left", padx=(0, S_SM))

        dep_options = self.get_dep_options() or [""]
        combo = ctk.CTkComboBox(header, values=dep_options, width=100)
        combo.pack(side="left", padx=(0, S_SM))
        combo.set(dep_options[0])

        ctk.CTkButton(header, text="+ Add", width=56,
                      command=lambda s=gi_slot: self._add_cond_to_group(s[0])).pack(
            side="left", padx=(0, S_SM)
        )
        ctk.CTkButton(header, text="Del Group", width=72,
                      command=lambda s=gi_slot: self._remove_group(s[0])).pack(
            side="left", padx=(0, S_SM)
        )

        op_init = intra_op_label(self.group_intra_op[gi] if gi < len(self.group_intra_op) else "and")
        op_var = ctk.StringVar(value=op_init)
        self.group_intra_op_vars[gi] = op_var
        op_var.trace_add("write", lambda *_a, s=gi_slot: self._on_group_intra_op_changed(s[0]))
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
            gvar.trace_add("write", lambda *_a, s=gi_slot: self._on_group_inv_changed(s[0]))
            ctk.CTkCheckBox(
                header, text="Inv", variable=gvar, width=72,
            ).pack(side="left", padx=(0, S_SM))

        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        # list_frame 在首列加入時才 pack
        self.group_frames.append({
            "frame": frame,
            "combo": combo,
            "list_frame": list_frame,
            "gi_slot": gi_slot,
            "title_label": title_label,
        })

        for ii, name in enumerate(group):
            self._add_cond_row(gi, name, ii)

    def _add_cond_row(self, gi: int, name: str, ii: int | None = None):
        if ii is None:
            ii = len(self.groups[gi]) - 1
        key = (gi, ii)
        key_slot = [gi, ii]
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
        row._key_slot = key_slot  # type: ignore[attr-defined]
        self.rows[key] = row

        rh = ctk.CTkLabel(row, text="\u2261", width=18,
                          text_color=("gray40", "gray70"), cursor="hand2")
        rh.pack(side="left", padx=(2, S_SM))
        rh.bind("<ButtonPress-1>",
                lambda _e, s=key_slot: self._on_cond_drag_start(s[0], s[1]))
        rh.bind("<B1-Motion>",
                lambda e, s=key_slot: self._on_cond_drag_motion(s[0], e))
        rh.bind("<ButtonRelease-1>",
                lambda _e, s=key_slot: self._on_cond_drag_release(s[0]))

        ctk.CTkLabel(row, text=display_name, width=120, anchor="w").pack(side="left", padx=(0, S_SM))
        if not is_const:
            ctk.CTkCheckBox(row, text="Inv", variable=self.inv_vars[key], width=50).pack(side="left", padx=(0, S_SM))
        if can_use_hi_lo:
            ctk.CTkComboBox(row, values=allowed_use,
                            variable=self.use_vars[key], width=100).pack(side="left", padx=(0, S_SM))
        ctk.CTkButton(row, text="Del", width=50,
                      command=lambda s=key_slot: self._remove_cond_by_key((s[0], s[1]))).pack(side="left")

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
        self._add_group_ui(len(self.groups) - 1)
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

    def _shift_cond_keys_after_delete(self, gi: int, deleted_ii: int) -> None:
        """刪除 (gi, deleted_ii) 後，把同 group 內較大的 ii 左移，並更新 key_slot。"""
        old_len = len(self.groups[gi]) + 1  # 刪除前長度
        for old_i in range(deleted_ii + 1, old_len):
            new_i = old_i - 1
            old_key = (gi, old_i)
            new_key = (gi, new_i)
            row = self.rows.pop(old_key, None)
            if row is not None:
                slot = getattr(row, "_key_slot", None)
                if slot is not None:
                    slot[0] = gi
                    slot[1] = new_i
                self.rows[new_key] = row
            if old_key in self.inv_vars:
                self.inv_vars[new_key] = self.inv_vars.pop(old_key)
            if old_key in self.use_vars:
                self.use_vars[new_key] = self.use_vars.pop(old_key)

    def _remove_cond_by_key(self, key: tuple[int, int]):
        gi, ii = key
        if gi >= len(self.groups) or ii >= len(self.groups[gi]):
            return
        row = self.rows.pop((gi, ii), None)
        if row is not None:
            try:
                row.destroy()
            except Exception:
                pass
        self.inv_vars.pop((gi, ii), None)
        self.use_vars.pop((gi, ii), None)
        del self.groups[gi][ii]
        self._shift_cond_keys_after_delete(gi, ii)
        if not self.groups[gi]:
            list_frame = self.group_frames[gi]["list_frame"]
            try:
                list_frame.pack_forget()
            except Exception:
                pass
        self._fire_change()

    def _remap_group_meta_after_delete(self, deleted_gi: int) -> None:
        """group 刪除後更新 group_frames 的 gi_slot／標題，以及 vars／rows 的 gi。"""
        for new_gi in range(deleted_gi, len(self.group_frames)):
            gf = self.group_frames[new_gi]
            gf["gi_slot"][0] = new_gi
            try:
                gf["title_label"].configure(text=f"Group {new_gi + 1}")
            except Exception:
                pass

        def _shift_var_dict(d: dict) -> None:
            d.pop(deleted_gi, None)
            for k in sorted([k for k in d if isinstance(k, int) and k > deleted_gi]):
                d[k - 1] = d.pop(k)

        _shift_var_dict(self.group_inv_vars)
        _shift_var_dict(self.group_intra_op_vars)

        new_rows: dict[tuple[int, int], ctk.CTkFrame] = {}
        for (old_gi, ii), row in self.rows.items():
            if old_gi == deleted_gi:
                continue
            new_gi = old_gi - 1 if old_gi > deleted_gi else old_gi
            slot = getattr(row, "_key_slot", None)
            if slot is not None:
                slot[0] = new_gi
                slot[1] = ii
            new_rows[(new_gi, ii)] = row
        self.rows = new_rows

        def _shift_kv(d: dict) -> dict:
            out = {}
            for (old_gi, ii), var in d.items():
                if old_gi == deleted_gi:
                    continue
                new_gi = old_gi - 1 if old_gi > deleted_gi else old_gi
                out[(new_gi, ii)] = var
            return out

        self.inv_vars = _shift_kv(self.inv_vars)
        self.use_vars = _shift_kv(self.use_vars)

    def _remove_group(self, gi: int):
        if gi >= len(self.groups):
            return
        if gi < len(self.group_frames):
            gf = self.group_frames.pop(gi)
            try:
                gf["frame"].destroy()
            except Exception:
                pass
        # 清掉該 group 的 row／var（frame.destroy 已銷毁 widget）
        for key in [k for k in self.rows if k[0] == gi]:
            self.rows.pop(key, None)
            self.inv_vars.pop(key, None)
            self.use_vars.pop(key, None)
        del self.groups[gi]
        if gi < len(self.group_inv):
            del self.group_inv[gi]
        if gi < len(self.group_intra_op):
            del self.group_intra_op[gi]
        if not self.groups:
            self.groups = [[]]
            self.group_inv = [False]
            self.group_intra_op = ["and"]
            self.group_inv_vars.clear()
            self.group_intra_op_vars.clear()
            self.rows.clear()
            self.inv_vars.clear()
            self.use_vars.clear()
            self._add_group_ui(0)
        else:
            self._remap_group_meta_after_delete(gi)
        self._fire_change()

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
        new_order = list(range(len(group)))
        moved = new_order.pop(from_idx)
        new_order.insert(to_idx, moved)
        self.groups[gi] = [group[old] for old in new_order]
        # 視覺已在 drag 時排好；只重編 key，不 destroy
        n = len(new_order)
        old_rows = {i: self.rows.pop((gi, i)) for i in range(n) if (gi, i) in self.rows}
        old_inv = {i: self.inv_vars.pop((gi, i)) for i in range(n) if (gi, i) in self.inv_vars}
        old_use = {i: self.use_vars.pop((gi, i)) for i in range(n) if (gi, i) in self.use_vars}
        for new_i, old_i in enumerate(new_order):
            row = old_rows.get(old_i)
            if row is not None:
                slot = getattr(row, "_key_slot", None)
                if slot is not None:
                    slot[0] = gi
                    slot[1] = new_i
                self.rows[(gi, new_i)] = row
            if old_i in old_inv:
                self.inv_vars[(gi, new_i)] = old_inv[old_i]
            if old_i in old_use:
                self.use_vars[(gi, new_i)] = old_use[old_i]

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
        new_order = list(range(len(self.groups)))
        moved = new_order.pop(from_idx)
        new_order.insert(to_idx, moved)
        self.groups[:] = [self.groups[old] for old in new_order]
        self._sync_group_inv_len()
        self.group_inv[:] = [self.group_inv[old] for old in new_order]
        self._sync_group_intra_op_len()
        self.group_intra_op[:] = [self.group_intra_op[old] for old in new_order]
        # 視覺已排好；只重排 group_frames 與 key
        self.group_frames[:] = [self.group_frames[old] for old in new_order]
        old_to_new = {old: new for new, old in enumerate(new_order)}

        new_rows: dict[tuple[int, int], ctk.CTkFrame] = {}
        for (old_gi, ii), row in self.rows.items():
            new_gi = old_to_new[old_gi]
            slot = getattr(row, "_key_slot", None)
            if slot is not None:
                slot[0] = new_gi
                slot[1] = ii
            new_rows[(new_gi, ii)] = row
        self.rows = new_rows

        def _remap_pair_dict(d: dict) -> dict:
            out = {}
            for (old_gi, ii), var in d.items():
                out[(old_to_new[old_gi], ii)] = var
            return out

        self.inv_vars = _remap_pair_dict(self.inv_vars)
        self.use_vars = _remap_pair_dict(self.use_vars)

        new_g_inv = {}
        for old_gi, var in self.group_inv_vars.items():
            new_g_inv[old_to_new[old_gi]] = var
        self.group_inv_vars = new_g_inv
        new_g_op = {}
        for old_gi, var in self.group_intra_op_vars.items():
            new_g_op[old_to_new[old_gi]] = var
        self.group_intra_op_vars = new_g_op

        for new_gi, gf in enumerate(self.group_frames):
            gf["gi_slot"][0] = new_gi
            try:
                gf["title_label"].configure(text=f"Group {new_gi + 1}")
            except Exception:
                pass

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
# InputWaveCondFrame — input 專用 Timing Hi/Lo Cond（主頁）
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
            text="Timing simulation only (not Verilog depends_on).",
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
    """Input 節點 Timing Hi/Lo Cond（Tab 風格與 Output Conditions 一致）。"""

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

        # --- Timing Hi/Lo (input only) ---
        self.timing_wrap, timing_body = self._make_section("Timing Hi/Lo")
        self.input_wave_frame = InputWaveCondFrame(
            timing_body,
            self._initial_input_wave_spec,
            get_dep_options=self._dep_options,
            is_pseqcell_for=self._is_pseqcell_for,
            get_self_name=lambda: self.rail.name,
        )
        self.input_wave_frame.pack(fill="x", padx=S_SM, pady=S_SM)

        apply_row = ctk.CTkFrame(self, fg_color="transparent")
        self.apply_row = apply_row
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

    def _repack_apply_row(self) -> None:
        """pack 順序：切換 Type 後 re-pack 的 section 會跑到 Apply 後面，需重排到底。"""
        self.apply_row.pack_forget()
        self.apply_row.pack(fill="x", padx=S_SM, pady=(0, S_SM))

    def _on_type_toggle(self, initial: bool = False):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.timing_wrap.pack_forget()
            self.cond_wrap.pack_forget()
            self.deb_wrap.pack(fill="x", pady=(0, S_SM))
            self.timing_wrap.pack(fill="x", pady=(0, S_SM))
            self._on_deb_toggle(initial=initial)
        else:
            self.deb_wrap.pack_forget()
            self.timing_wrap.pack_forget()
            self.timing_wrap.pack(fill="x", pady=(0, S_SM))
            self.cond_wrap.pack(fill="x", pady=(0, S_SM))
        self._repack_apply_row()

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

