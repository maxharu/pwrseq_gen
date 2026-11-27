import copy
import os
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

from core.cond_edit import CondEditModel
from core.config_edit import (
    resize_list,
    set_group_metadata,
    vector_shape_label,
    width_expr_from_dims,
)
from core.config_models import (
    DEFAULT_PULSE,
    ConditionConfig,
    PowerRail,
    SliceGroup,
    apply_input_wave_dict,
    eval_width,
    rail_input_wave_spec,
)
from core.config_models import _bit_name as _bit_name
from core.group_logic import INTRA_OP_LABELS, intra_op_label, normalize_intra_op
from core.take_rules import default_form, form_to_take, take_forms, take_to_form
from core.timing_models import InputWaveSpec
from gui.theme import *

# vector 相依下拉的消費模式（方案甲 GUI 糖衣；僅影響「新增相依」時如何展開成具體 base[i]）。
VEC_MODE_SAME = "同索引"      # → base[active_bit]
VEC_MODE_ALL = "全部(AND)"    # → base[0..N-1]，整組 intra_op=and
VEC_MODE_ANY = "任一(OR)"     # → base[0..N-1]，整組 intra_op=or
VEC_MODE_PICK = "指定"        # → base[k]
VEC_MODES = (VEC_MODE_SAME, VEC_MODE_ALL, VEC_MODE_ANY, VEC_MODE_PICK)

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
                 model: CondEditModel,
                 show_group_inv: bool = True,
                 on_change: Optional[Callable[[], None]] = None,
                 get_self_name: Optional[Callable[[], str]] = None,
                 vec_dep=None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.kind = kind
        self.theme = COND_THEME[kind]
        self.get_dep_options = get_dep_options
        self.get_self_name = get_self_name
        self.is_pseqcell_for = is_pseqcell_for
        self.on_change = on_change
        self.show_group_inv = show_group_inv
        # vector 相依展開器（RailEditorFrame 注入；None=不收合，行為與過去一致）。
        self.vec_dep = vec_dep

        # 唯一的真實來源。結構操作一律先改它，再 _rebuild_groups_ui() 重繪；
        # 下面那些 *_vars / rows / group_frames 都只是當下畫面的對照表。
        self.model = model

        self.inv_vars: dict[tuple[int, int], ctk.BooleanVar] = {}
        self.use_vars: dict[tuple[int, int], ctk.StringVar] = {}
        self.take_cells: dict[tuple[int, int], dict] = {}
        self.group_inv_vars: dict[int, ctk.BooleanVar] = {}
        self.group_intra_op_vars: dict[int, ctk.StringVar] = {}
        self.rows: dict[tuple[int, int], ctk.CTkFrame] = {}
        self.group_frames: list[dict] = []

        self._cond_drag_state: Optional[dict] = None
        self._group_drag_state: Optional[dict] = None

        self._build_ui()

    @property
    def groups(self) -> list[list[str]]:
        return self.model.groups

    @property
    def group_inv(self) -> list[bool]:
        return self.model.group_inv

    @property
    def group_intra_op(self) -> list[str]:
        return self.model.group_intra_op

    def _fire_change(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:
                pass

    def refresh_dep_options(self) -> None:
        """只更新各 group 的 signal ComboBox values（不重建 UI）。"""
        opts = self.get_dep_options() or [""]
        for gi, gf in enumerate(self.group_frames):
            combo = gf.get("combo")
            if combo is None:
                continue
            cur = combo.get()
            combo.configure(values=opts)
            if cur in opts:
                combo.set(cur)
            else:
                combo.set(opts[0])
            self._refresh_vec_controls(gi)

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
        """依 self.model 重繪整個區塊。

        每項的 inv / use 存在 model 裡（不是只存在 Tk 變數裡），所以重建不會弄丟
        使用者的編輯——這正是結構操作能一律「改 model 再重繪」的前提。
        """
        for w in self.groups_container.winfo_children():
            w.destroy()
        self.group_frames.clear()
        self.inv_vars.clear()
        self.use_vars.clear()
        self.take_cells.clear()
        self.group_inv_vars.clear()
        self.group_intra_op_vars.clear()
        self.rows.clear()
        self.model.normalize()
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
        combo = ctk.CTkComboBox(
            header, values=dep_options, width=100,
            command=lambda _v, s=gi_slot: self._refresh_vec_controls(s[0]))
        combo.pack(side="left", padx=(0, S_SM))
        combo.set(dep_options[0])

        # vector 消費模式 + 指定 bit（固定佔位，選到 vector base 時才顯示內容，保持排序）
        vec_slot = ctk.CTkFrame(header, fg_color="transparent")
        vec_slot.pack(side="left", padx=(0, S_SM))
        mode_var = ctk.StringVar(value=VEC_MODE_PICK)
        mode_menu = ctk.CTkOptionMenu(
            vec_slot, values=list(VEC_MODES), variable=mode_var, width=96,
            command=lambda _v, s=gi_slot: self._refresh_bit_menu(s[0]))
        bit_var = ctk.StringVar(value="0")
        bit_menu = ctk.CTkOptionMenu(vec_slot, values=["0"], variable=bit_var, width=56)

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
            "vec_slot": vec_slot,
            "mode_menu": mode_menu,
            "mode_var": mode_var,
            "bit_menu": bit_menu,
            "bit_var": bit_var,
            "list_frame": list_frame,
            "gi_slot": gi_slot,
            "title_label": title_label,
        })

        for ii, name in enumerate(group):
            self._add_cond_row(gi, name, ii)

        self._refresh_vec_controls(gi)

    # ---- vector 相依下拉：模式 / bit 控制 ----
    def _refresh_vec_controls(self, gi: int):
        """依目前 combo 選取顯示/隱藏模式與 bit 控制：選到 vector base 才出現。"""
        if not (0 <= gi < len(self.group_frames)):
            return
        gf = self.group_frames[gi]
        mode_menu, bit_menu = gf["mode_menu"], gf["bit_menu"]
        sel = gf["combo"].get()
        width = self.vec_dep.width_of(sel) if self.vec_dep else None
        if width is None:
            mode_menu.pack_forget()
            bit_menu.pack_forget()
            return
        # 維度向量相依：取法改在相依列上編輯（§6），不顯示 header 模式/bit
        if self.vec_dep.owner_ndim() >= 1 and self.vec_dep.dep_ndim(sel) >= 1:
            mode_menu.pack_forget()
            bit_menu.pack_forget()
            return
        # legacy 非維度向量：維持原「模式＋bit」逐 bit 行為
        modes = list(VEC_MODES)
        if not self.vec_dep.owner_is_vector():
            modes = [m for m in modes if m != VEC_MODE_SAME]
        mode_menu.configure(values=modes)
        if gf["mode_var"].get() not in modes:
            gf["mode_var"].set(modes[0])
        mode_menu.pack(side="left", padx=(0, S_XS))
        bit_menu.configure(values=[str(i) for i in range(width)])
        if _safe_int(gf["bit_var"].get(), 0) >= width:
            gf["bit_var"].set("0")
        self._refresh_bit_menu(gi)

    def _refresh_bit_menu(self, gi: int):
        """bit 下拉僅在模式=指定且選取為 vector 時顯示。"""
        if not (0 <= gi < len(self.group_frames)):
            return
        gf = self.group_frames[gi]
        is_vec = self.vec_dep and self.vec_dep.width_of(gf["combo"].get()) is not None
        if is_vec and gf["mode_var"].get() == VEC_MODE_PICK:
            gf["bit_menu"].pack(side="left")
        else:
            gf["bit_menu"].pack_forget()

    def _set_vec_mode(self, gi: int, mode: str):
        """設定第 gi 組的消費模式（等同使用者操作模式下拉）。"""
        if 0 <= gi < len(self.group_frames):
            self.group_frames[gi]["mode_var"].set(mode)
            self._refresh_bit_menu(gi)

    def _add_cond_row(self, gi: int, name: str, ii: int | None = None):
        if ii is None:
            ii = len(self.groups[gi]) - 1
        key = (gi, ii)
        key_slot = [gi, ii]
        is_const = name in (DEP_HIGH, DEP_LOW)
        display_name = "High" if name == DEP_HIGH else ("Low" if name == DEP_LOW else name)
        can_use_hi_lo = (not is_const) and self.is_pseqcell_for(name)

        inv_val = False if is_const else bool(self.model.inv[gi][ii])
        use_val = USE_LABELS.get(self.model.use[gi][ii], "Node")
        allowed_use = self._allowed_use_labels(name)
        if use_val not in allowed_use:
            use_val = allowed_use[0] if allowed_use else "Node"
        # 自我參照時 use 會被限縮，把修正後的值寫回 model，重繪才不會又跳回原值
        self.model.inv[gi][ii] = inv_val
        self.model.use[gi][ii] = USE_REVERSE.get(use_val, "self")
        self.inv_vars[key] = ctk.BooleanVar(value=inv_val)
        self.use_vars[key] = ctk.StringVar(value=use_val)
        # trace 在初值設定後才註冊，避免初始化就觸發
        self.inv_vars[key].trace_add(
            "write", lambda *_, s=key_slot: self._on_inv_changed(s[0], s[1]))
        self.use_vars[key].trace_add(
            "write", lambda *_, s=key_slot: self._on_use_changed(s[0], s[1]))

        list_frame = self.group_frames[gi]["list_frame"]
        if not list_frame.winfo_ismapped():
            list_frame.pack(fill="x", padx=S_SM, pady=(0, S_XS))

        # 外層垂直容器：top（控制列）＋ sub（取法子選項列，僅維度向量取法需要時出現）
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        row._key_slot = key_slot  # type: ignore[attr-defined]
        self.rows[key] = row
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")

        rh = ctk.CTkLabel(top, text="\u2261", width=18,
                          text_color=("gray40", "gray70"), cursor="hand2")
        rh.pack(side="left", padx=(2, S_SM))
        rh.bind("<ButtonPress-1>",
                lambda _e, s=key_slot: self._on_cond_drag_start(s[0], s[1]))
        rh.bind("<B1-Motion>",
                lambda e, s=key_slot: self._on_cond_drag_motion(s[0], e))
        rh.bind("<ButtonRelease-1>",
                lambda _e, s=key_slot: self._on_cond_drag_release(s[0]))

        ctk.CTkLabel(top, text=display_name, width=120, anchor="w").pack(side="left", padx=(0, S_SM))
        if not is_const:
            ctk.CTkCheckBox(top, text="Inv", variable=self.inv_vars[key], width=50).pack(side="left", padx=(0, S_SM))
        if can_use_hi_lo:
            ctk.CTkComboBox(top, values=allowed_use,
                            variable=self.use_vars[key], width=100).pack(side="left", padx=(0, S_SM))
        if not is_const:
            self._build_take_cell(top, row, key, name)
        ctk.CTkButton(top, text="Del", width=50,
                      command=lambda s=key_slot: self._remove_cond_by_key((s[0], s[1]))).pack(side="left")

    # ---- per-row 取法（§6）：維度向量相依才出現 ----
    def _build_take_cell(self, top, row, key: tuple[int, int], name: str) -> None:
        """在相依列上建「取法」下拉＋第二行子選項（n/m），讀寫 model.take[gi][ii]。"""
        if self.vec_dep is None:
            return
        out_ndim = self.vec_dep.owner_ndim()
        dep_ndim = self.vec_dep.dep_ndim(name)
        if out_ndim < 1 or dep_ndim < 1:
            return  # scalar / legacy 非維度向量：無取法控制
        gi, ii = key
        forms = take_forms(out_ndim, dep_ndim)
        labels = [f.label for f in forms]
        id_by_label = {f.label: f.id for f in forms}
        label_by_id = {f.id: f.label for f in forms}
        needs_by_id = {f.id: f.needs for f in forms}

        cur = (self.model.take[gi][ii]
               if gi < len(self.model.take) and ii < len(self.model.take[gi]) else None)
        form_id, n, m = take_to_form(cur)
        if form_id not in label_by_id:  # None 或不在清單 → 套預設
            form_id, n, m = default_form(out_ndim, dep_ndim)
        form_var = ctk.StringVar(value=label_by_id.get(form_id, labels[0]))
        n_var = ctk.StringVar(value=str(n))
        m_var = ctk.StringVar(value=str(m))

        ctk.CTkLabel(top, text="\u53d6\u6cd5", font=FONT_HINT).pack(side="left", padx=(S_SM, 2))
        menu = ctk.CTkOptionMenu(top, values=labels, variable=form_var, width=150)
        menu.pack(side="left", padx=(0, S_SM))
        sub = ctk.CTkFrame(row, fg_color="transparent")

        cell = {"form_var": form_var, "n_var": n_var, "m_var": m_var, "sub": sub,
                "menu": menu, "id_by_label": id_by_label, "needs_by_id": needs_by_id}
        self.take_cells[key] = cell

        form_var.trace_add("write", lambda *_a, k=key: self._on_take_form_changed(k))
        n_var.trace_add("write", lambda *_a, k=key: self._commit_take(k))
        m_var.trace_add("write", lambda *_a, k=key: self._commit_take(k))
        self._render_take_sub(key)

    def _current_take_form_id(self, key: tuple[int, int]) -> str:
        cell = self.take_cells[key]
        return cell["id_by_label"].get(cell["form_var"].get(), "")

    def _render_take_sub(self, key: tuple[int, int]) -> None:
        """依目前取法重建第二行數字欄（偏移值 / 欄索引 / 欄偏移）。"""
        cell = self.take_cells[key]
        sub = cell["sub"]
        for w in sub.winfo_children():
            w.destroy()
        needs = cell["needs_by_id"].get(self._current_take_form_id(key), ())
        if needs:
            sub.pack(fill="x", padx=(40, 0))
            for field, label in needs:
                ctk.CTkLabel(sub, text=label, font=FONT_HINT).pack(side="left", padx=(0, 2))
                var = cell["n_var"] if field == "n" else cell["m_var"]
                ctk.CTkEntry(sub, textvariable=var, width=56).pack(side="left", padx=(0, S_SM))
        else:
            sub.pack_forget()

    def _on_take_form_changed(self, key: tuple[int, int]) -> None:
        self._render_take_sub(key)
        self._commit_take(key)

    def _commit_take(self, key: tuple[int, int]) -> None:
        """把目前取法寫回 model.take[gi][ii]。"""
        gi, ii = key
        if not (0 <= gi < len(self.model.take) and 0 <= ii < len(self.model.take[gi])):
            return
        cell = self.take_cells[key]
        form_id = self._current_take_form_id(key)
        self.model.take[gi][ii] = form_to_take(
            form_id, _safe_int(cell["n_var"].get(), 0), _safe_int(cell["m_var"].get(), 0))
        self._fire_change()

    def _on_inv_changed(self, gi: int, ii: int):
        if 0 <= gi < len(self.model.inv) and 0 <= ii < len(self.model.inv[gi]):
            try:
                self.model.inv[gi][ii] = bool(self.inv_vars[(gi, ii)].get())
            except Exception:
                self.model.inv[gi][ii] = False
        self._fire_change()

    def _on_use_changed(self, gi: int, ii: int):
        if 0 <= gi < len(self.model.use) and 0 <= ii < len(self.model.use[gi]):
            try:
                self.model.use[gi][ii] = USE_REVERSE.get(
                    self.use_vars[(gi, ii)].get(), "self")
            except Exception:
                self.model.use[gi][ii] = "self"
        self._fire_change()

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
        self.model.add_group()
        self._add_group_ui(len(self.groups) - 1)
        self._fire_change()

    def _add_cond_to_group(self, gi: int):
        gf = self.group_frames[gi]
        sel = gf["combo"].get()
        if not sel:
            return
        names, group_op, take = self._expand_selection(gf, sel)
        if group_op is not None and 0 <= gi < len(self.model.group_intra_op):
            # 全部/任一：reduction 由整組 intra_op 承載（and/or）
            self.model.group_intra_op[gi] = group_op
            var = self.group_intra_op_vars.get(gi)
            if var is not None:
                var.set(intra_op_label(group_op))
        added = False
        for name in names:
            dep_key = DEP_HIGH if name == "High" else (DEP_LOW if name == "Low" else name)
            if self.model.add_dep(gi, dep_key, take=take):
                self._add_cond_row(gi, dep_key)
                added = True
        if added:
            self._fire_change()

    def _expand_selection(
        self, gf: dict, sel: str
    ) -> tuple[list[str], str | None, dict | None]:
        """把 combo 選取（含 vector 模式/ bit）展開成具體相依名、group op 與 take。"""
        if self.vec_dep is None:
            return ([sel], None, None)
        mode = gf["mode_var"].get()
        bit = _safe_int(gf["bit_var"].get(), 0)
        return self.vec_dep.expand(sel, mode, bit)

    def _remove_cond_by_key(self, key: tuple[int, int]):
        if not self.model.remove_dep(*key):
            return
        self._rebuild_groups_ui()
        self._fire_change()

    def _remove_group(self, gi: int):
        if not self.model.remove_group(gi):
            return
        self._rebuild_groups_ui()
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
        if self.model.reorder_dep(gi, from_idx, to_idx):
            self._rebuild_groups_ui()

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
        if self.model.reorder_groups(from_idx, to_idx):
            self._rebuild_groups_ui()

    # ---- getters for RailEditorFrame.get_rail() ----
    def get_groups(self) -> list[list[str]]:
        return self.model.to_groups()

    def get_inv_groups(self) -> list[list[bool]]:
        return self.model.to_inv_groups()

    def get_use_groups(self) -> list[list[str]]:
        return self.model.to_use_groups()

    def get_take_groups(self) -> list[list[dict | None]]:
        return self.model.to_take_groups()

    def get_group_inv(self) -> list[bool]:
        """每個非空 group 的整組反相旗標，與 get_groups() 同序。"""
        return self.model.to_group_inv()

    def get_group_intra_op(self) -> list[str]:
        """每個非空 group 的區塊內運算，與 get_groups() 同序。"""
        return self.model.to_group_intra_op()

    def get_inv_flat(self) -> dict[str, bool]:
        return self.model.to_inv_flat()

    def get_use_flat(self) -> dict[str, str]:
        return self.model.to_use_flat()

    def get_flat_deps(self) -> list[str]:
        return self.model.to_flat_deps()


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
        vec_dep=None,
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

        self._cond_section = CondSectionFrame(
            self._opt_slot,
            kind=side,
            get_dep_options=get_dep_options,
            is_pseqcell_for=is_pseqcell_for,
            model=CondEditModel.from_initial(
                groups=groups,
                inv_groups=inv_groups,
                use_groups=use_groups,
                group_inv=group_inv,
                group_intra_op=intra_op,
            ),
            show_group_inv=True,
            on_change=self._fire_change,
            get_self_name=get_self_name,
            vec_dep=vec_dep,
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

    def refresh_dep_options(self) -> None:
        self._cond_section.refresh_dep_options()


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
        vec_dep=None,
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
                vec_dep=vec_dep,
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

    def refresh_dep_options(self) -> None:
        self._hi_panel.refresh_dep_options()
        self._lo_panel.refresh_dep_options()


# ============================================================
# RailEditorFrame — 單一 rail 的屬性編輯面板
# ============================================================

DECL_TAB = "宣告"
COND_TAB = "條件"


class _VecDepHelper:
    """注入 CondSectionFrame 的 vector 相依展開器。

    由 RailEditorFrame 建立（唯一知道 vector 結構／目前 active bit 的地方）。CondSectionFrame
    只透過這三個方法與 vector 互動，不自行理解群組結構。"""

    def __init__(self, width_of, owner_is_vector, expand,
                 owner_ndim=None, dep_ndim=None):
        self.width_of = width_of              # (sel) -> int | None
        self.owner_is_vector = owner_is_vector  # () -> bool
        self.expand = expand                  # (sel, mode, bit) -> (names, group_op, take)
        self.owner_ndim = owner_ndim or (lambda: 0)         # () -> int：owner 維度數
        self.dep_ndim = dep_ndim or (lambda _name: 0)       # (name) -> int：dep 維度數


def _node_base_of(rails: list[PowerRail]) -> tuple[str, bool]:
    """(base 名, 是否 vector)；vector 取 group_base，scalar 取節點名。"""
    head = rails[0]
    if head.group_base is not None:
        return head.group_base, True
    return head.name, False


class RailEditorFrame(ctk.CTkFrame):
    """節點編輯器（方案甲）：頂端 [宣告|條件] 分頁。

    一張卡片 = 一個節點（vector 亦同）。宣告分頁管 IO 身分＋共用實體參數（含 Vector 勾選＋
    寬度整數欄位）；條件分頁 per-bit（vector 以 Bit 選擇器切換，各 bit 條件獨立）。
    `_bit_rails` 是每 bit 條件的真實來源；同一時間只掛一個 bit 的條件編輯器，切 bit／切 Type
    時先收集回 `_bit_rails` 再重建，避免 N 份 widget。Apply 時 get_rails() 攤成 N 個 PowerRail。
    """

    def __init__(self, master, rails,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_apply: Optional[Callable[[], None]] = None,
                 get_parameters: Optional[Callable[[], list]] = None,
                 get_dimensions: Optional[Callable[[], list]] = None,
                 **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.get_all_rails = get_all_rails
        self.get_pulses = get_pulses
        self.get_parameters = get_parameters
        self.get_dimensions = get_dimensions
        self.on_apply = on_apply
        rails = list(rails) or [PowerRail(name="N0", seq_type="output")]
        self._base_init, self._is_vector_init = _node_base_of(rails)
        # 初始維度：由 head.dim_params 推（1D/2D）；legacy 向量（無 dim_params）骨架預設 1 維，
        # 寬度沿用載入時的 width_expr（無全域維度時仍能保留既有 bus 寬度）。
        init_dims = list(getattr(rails[0], "dim_params", None) or [])[:2]
        self._dim_params_init = init_dims
        self._dim_count_init = len(init_dims) if init_dims else (1 if self._is_vector_init else 0)
        self._width_expr_init = str(getattr(rails[0], "width_expr", "1") or "1")
        # 每 bit 一份獨立副本（條件來源）；編輯不動到 config，直到 Apply。
        self._bit_rails: list[PowerRail] = [copy.deepcopy(r) for r in rails]
        self._active_bit = 0
        self._cond_editor: Optional[dict] = None  # {"kind": "output"|"input", ...}
        # Slice（§4，row/col 軸）：維度 output 向量的條件頁用群組選擇器取代 per-bit。
        # _row_group[r] = 群組 id（0=else）；_slice_rails[gid] 持該組條件；扁平=else。
        # _slice_axis：目前切片軸 row/col；一次單軸（§4.2），col 僅 2D 可選。
        self._slice_active = False
        self._slice_axis = "row"
        self._row_group: list[int] = []
        self._slice_rails: dict[int, PowerRail] = {}
        self._active_group = 0
        self._next_gid = 1
        self._row_menus: list = []
        self._vec_dep = _VecDepHelper(
            self._dep_vector_width, self._owner_is_vector, self._expand_dep,
            self._owner_ndim, self._dep_ndim)
        self._build_ui()

    # ---- helpers ----
    def _dep_options(self) -> list[str]:
        """相依下拉選項：vector 收合成每個 base 一筆（不逐 bit 展開），scalar 用節點名，末端 High/Low。"""
        seen: set[str] = set()
        out: list[str] = []
        for r in self.get_all_rails():
            key = r.group_base if r.group_base is not None else r.name
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out + ["High", "Low"]

    def _dep_vector_width(self, sel: str) -> int | None:
        """sel 是 vector base 時回傳 bit 數，否則 None（scalar / High / Low）。"""
        n = sum(1 for r in self.get_all_rails() if r.group_base == sel)
        return n or None

    def _owner_is_vector(self) -> bool:
        return self.is_vector()

    def _dep_dim_params(self, sel: str) -> list[str]:
        """sel 對應的相依節點維度名清單（新維度模型向量才有；legacy 向量為空）。"""
        for r in self.get_all_rails():
            if r.group_base == sel:
                return list(getattr(r, "dim_params", None) or [])
        return []

    def _owner_ndim(self) -> int:
        """owner（本節點）維度數（0/1/2）。"""
        return len(self._selected_dim_params())

    def _dep_ndim(self, name: str) -> int:
        """相依 name（可為 base 或 base[i]）的維度數；非維度向量回 0。"""
        for r in self.get_all_rails():
            if r.name == name or r.group_base == name:
                return len(getattr(r, "dim_params", None) or [])
        return 0

    def _dim_vector_dep(self, sel: str) -> bool:
        """owner 與 dep 皆為維度向量（§6 取法的作用對象）。"""
        return bool(self._selected_dim_params()) and bool(self._dep_dim_params(sel))

    def _default_take_for(self, sel: str) -> dict | None:
        """維度向量相依的預設 take（由 take_rules 單一來源決定）。"""
        out_ndim = len(self._selected_dim_params())
        dep_ndim = len(self._dep_dim_params(sel))
        form, n, m = default_form(out_ndim, dep_ndim)
        return form_to_take(form, n, m)

    def _expand_dep(
        self, sel: str, mode: str, bit: int
    ) -> tuple[list[str], str | None, dict | None]:
        """把 (base, 模式, bit) 展開成具體相依名、需設定的 group op、以及 take（方案甲 GUI 糖衣）。

        scalar / High / Low 原樣回傳；維度向量（owner+dep 皆有 dim_params）只掛一個 base[0]
        把手、套 take_rules 預設 take（幾何之後在相依列上編輯）。其餘向量仍逐 bit 展開：
          同索引→目前 active bit；全部/任一→全 bit + and/or；指定→base[k]。"""
        if sel in ("High", "Low"):
            return ([sel], None, None)
        n = self._dep_vector_width(sel)
        if n is None:
            return ([sel], None, None)
        if self._dim_vector_dep(sel):
            return ([_bit_name(sel, 0)], None, self._default_take_for(sel))
        if mode == VEC_MODE_SAME:
            return ([_bit_name(sel, min(self._active_bit, n - 1))], None, None)
        if mode == VEC_MODE_ALL:
            return ([_bit_name(sel, i) for i in range(n)], "and", None)
        if mode == VEC_MODE_ANY:
            return ([_bit_name(sel, i) for i in range(n)], "or", None)
        # VEC_MODE_PICK（或未知模式）→ 指定 bit
        return ([_bit_name(sel, max(0, min(bit, n - 1)))], None, None)

    def refresh_dep_options(self) -> None:
        """刷新作用中 bit 的 Conditions / Input Timing 的 signal 下拉名單。"""
        ed = self._cond_editor
        if ed is None:
            return
        if ed["kind"] == "output":
            for sec in ed["sections"].values():
                sec.refresh_dep_options()
        else:
            ed["wave"].refresh_dep_options()

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

    def _make_section(self, parent, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        wrap = ctk.CTkFrame(parent, fg_color=("gray95", "gray19"), corner_radius=6)
        wrap.pack(fill="x", pady=(0, S_SM))
        header = ctk.CTkFrame(wrap, fg_color="transparent")
        header.pack(fill="x", padx=S_SM, pady=(S_SM, 0))
        ctk.CTkLabel(header, text=title, font=FONT_SECTION).pack(side="left")
        body = ctk.CTkFrame(wrap, fg_color="transparent")
        body.pack(fill="x")
        return wrap, body

    # ---- node identity ----
    def base_name(self) -> str:
        return self.entry_name.get().strip() or self._base_init

    def is_vector(self) -> bool:
        return self._dim_count() >= 1

    def seq_type(self) -> str:
        return self.var_type.get()

    def _parameters(self) -> list:
        return self.get_parameters() if self.get_parameters else []

    def _global_dims(self) -> list[str]:
        """目前已宣告的全域維度 parameter 名（維度1=row、維度2=col）。"""
        return list(self.get_dimensions()) if self.get_dimensions else []

    def _dim_count(self) -> int:
        return _safe_int(self.var_dim_count.get(), 0)

    def _selected_dim_params(self) -> list[str]:
        """依維度個數讀各 Bits 下拉，回有效（存在於全域維度）的維度名清單。"""
        dims = self._global_dims()
        out: list[str] = []
        for i in range(self._dim_count()):
            if i < len(self._dim_menus):
                val = self._dim_menus[i].get()
                if val in dims:
                    out.append(val)
        return out

    def _width_expr(self) -> str:
        """由所選維度推寬度公式（0→"1"、1→P1、2→P1*P2）。

        維度個數 ≥ 1 但尚無有效維度（legacy 向量，或全域維度未宣告）時，沿用載入時的 width_expr，
        避免把既有 bus 寬度塌成 1。"""
        dims = self._selected_dim_params()
        if dims:
            return width_expr_from_dims(dims)
        return self._width_expr_init if self.is_vector() else "1"

    def _parse_width(self) -> int:
        """由維度寬度公式求位元數 N（以具體 parameter 值代入 eval_width）。"""
        try:
            return max(1, eval_width(self._width_expr(), self._parameters()))
        except (ValueError, TypeError):
            return max(1, len(self._bit_rails) or 1)

    # ---- UI build ----
    def _build_ui(self):
        head = self._bit_rails[0]

        mode_row = ctk.CTkFrame(self, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, S_SM))
        self._mode_seg = ctk.CTkSegmentedButton(
            mode_row, values=[DECL_TAB, COND_TAB], command=self._on_mode_seg)
        self._mode_seg.set(DECL_TAB)
        self._mode_seg.pack(side="left")

        self._decl_pane = ctk.CTkFrame(self, fg_color="transparent")
        self._cond_pane = ctk.CTkFrame(self, fg_color="transparent")

        self._build_decl_pane(head)
        self._build_cond_pane()

        self.apply_row = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkButton(
            self.apply_row, text="Apply", width=88, command=self._on_apply_clicked,
        ).pack(side="right")

        self._on_type_toggle(initial=True)
        self._show_mode(DECL_TAB)

    def _build_decl_pane(self, head: PowerRail):
        parent = self._decl_pane
        # --- General ---
        _, gen_body = self._make_section(parent, "General")
        grid = ctk.CTkFrame(gen_body, fg_color="transparent")
        grid.pack(fill="x", padx=S_SM, pady=S_SM)
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ctk.CTkLabel(grid, text="Name:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_name = ctk.CTkEntry(grid, width=160)
        self.entry_name.insert(0, self._base_init)
        self.entry_name.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid, text="Type:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        type_row = ctk.CTkFrame(grid, fg_color="transparent")
        type_row.grid(row=0, column=3, sticky="w", pady=2)
        self.var_type = ctk.StringVar(value=head.seq_type)
        self._type_seg = ctk.CTkSegmentedButton(
            type_row,
            values=[SEQ_TYPE_LABELS["output"], SEQ_TYPE_LABELS["input"]],
            command=self._on_type_seg_selected,
        )
        self._type_seg.set(SEQ_TYPE_LABELS.get(head.seq_type, "Output"))
        self._type_seg.pack(side="left")

        # 維度個數 [0/1/2] + Bits 維度 parameter 下拉（取代舊 Vector 勾選＋自由公式 Width）
        self.var_dim_count = ctk.StringVar(value=str(self._dim_count_init))
        dim_row = ctk.CTkFrame(grid, fg_color="transparent")
        dim_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=(0, S_SM), pady=2)
        ctk.CTkLabel(dim_row, text="維度", font=FONT_BODY).pack(side="left", padx=(0, S_XS))
        ctk.CTkOptionMenu(
            dim_row, values=["0", "1", "2"], variable=self.var_dim_count, width=56,
            command=self._on_dim_count_changed).pack(side="left")
        ctk.CTkLabel(grid, text="Bits:", font=FONT_BODY).grid(
            row=1, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.dim_bits_row = ctk.CTkFrame(grid, fg_color="transparent")
        self.dim_bits_row.grid(row=1, column=3, sticky="w", pady=2)
        self._dim_menus: list[ctk.CTkOptionMenu] = []
        self._render_dim_bits()

        # --- Timing (output only) ---
        self.pseq_timing_wrap, timing_body = self._make_section(parent, "Timing")
        grid_t = ctk.CTkFrame(timing_body, fg_color="transparent")
        grid_t.pack(fill="x", padx=S_SM, pady=S_SM)
        for c in range(4):
            grid_t.grid_columnconfigure(c, weight=1 if c in (1, 3) else 0)

        ctk.CTkLabel(grid_t, text="CYCLE_HI:", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_hi = ctk.CTkEntry(grid_t, width=100)
        self.entry_hi.insert(0, str(head.cycle_hi))
        self.entry_hi.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_lo = ctk.CTkEntry(grid_t, width=100)
        self.entry_lo.insert(0, str(head.cycle_lo))
        self.entry_lo.grid(row=0, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_t, text="CYCLE_FORCE:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_cycle_force = ctk.CTkEntry(grid_t, width=100)
        self.entry_cycle_force.insert(0, str(getattr(head, "cycle_force", 2)))
        self.entry_cycle_force.grid(row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="INIT:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pseq_init = ctk.StringVar(value="1" if getattr(head, "init", 0) == 1 else "0")
        cmb_pseq_init = ctk.CTkComboBox(grid_t, values=["0", "1"], variable=self.var_pseq_init, width=100)
        cmb_pseq_init.grid(row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="FORCE:", font=FONT_BODY).grid(
            row=2, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_force_val = ctk.StringVar(
            value="1" if getattr(head, "force_val", 0) == 1 else "0")
        cmb_force_val = ctk.CTkComboBox(grid_t, values=["0", "1"], variable=self.var_force_val, width=100)
        cmb_force_val.grid(row=2, column=3, sticky="w", pady=2)

        pulses = self._pulse_values(
            getattr(head, "pulse_hi", DEFAULT_PULSE),
            getattr(head, "pulse_lo", DEFAULT_PULSE),
            getattr(head, "pulse_force", DEFAULT_PULSE),
        )
        ctk.CTkLabel(grid_t, text="Timing Hi:", font=FONT_BODY).grid(
            row=3, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_hi = ctk.StringVar(value=getattr(head, "pulse_hi", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_hi = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_hi, width=130)
        cmb_pulse_hi.grid(row=3, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_t, text="Timing Lo:", font=FONT_BODY).grid(
            row=3, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_lo = ctk.StringVar(value=getattr(head, "pulse_lo", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_lo = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_lo, width=130)
        cmb_pulse_lo.grid(row=3, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_t, text="Timing Force:", font=FONT_BODY).grid(
            row=4, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.var_pulse_force = ctk.StringVar(value=getattr(head, "pulse_force", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_pulse_force = ctk.CTkComboBox(grid_t, values=pulses, variable=self.var_pulse_force, width=130)
        cmb_pulse_force.grid(row=4, column=1, sticky="w", padx=(0, S_LG), pady=2)

        # --- Debounce (input only) ---
        self.deb_wrap, deb_body = self._make_section(parent, "Debounce")
        self.var_deb_enable = ctk.BooleanVar(value=getattr(head, "deb_enable", True))
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
        self.entry_deb_cycle_hi.insert(0, str(getattr(head, "deb_cycle_hi", 2)))
        self.entry_deb_cycle_hi.grid(row=0, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_d, text="CYCLE_LO:", font=FONT_BODY).grid(
            row=0, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_lo = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_lo.insert(0, str(getattr(head, "deb_cycle_lo", 2)))
        self.entry_deb_cycle_lo.grid(row=0, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_d, text="CYCLE_SYNC:", font=FONT_BODY).grid(
            row=1, column=0, sticky="w", padx=(0, S_SM), pady=2)
        self.entry_deb_cycle_sync = ctk.CTkEntry(grid_d, width=100)
        self.entry_deb_cycle_sync.insert(0, str(getattr(head, "deb_cycle_sync", 2)))
        self.entry_deb_cycle_sync.grid(row=1, column=1, sticky="w", padx=(0, S_LG), pady=2)

        ctk.CTkLabel(grid_d, text="INIT:", font=FONT_BODY).grid(
            row=1, column=2, sticky="w", padx=(0, S_SM), pady=2)
        self.var_deb_init = ctk.StringVar(value="1" if getattr(head, "deb_init", 0) == 1 else "0")
        cmb_deb_init = ctk.CTkComboBox(grid_d, values=["0", "1"], variable=self.var_deb_init, width=100)
        cmb_deb_init.grid(row=1, column=3, sticky="w", pady=2)

        ctk.CTkLabel(grid_d, text="Timing Deb:", font=FONT_BODY).grid(
            row=2, column=0, sticky="w", padx=(0, S_SM), pady=2)
        deb_pulses = self._pulse_values(getattr(head, "deb_pulse", DEFAULT_PULSE))
        self.var_deb_pulse = ctk.StringVar(value=getattr(head, "deb_pulse", DEFAULT_PULSE) or DEFAULT_PULSE)
        cmb_deb_pulse = ctk.CTkComboBox(grid_d, values=deb_pulses, variable=self.var_deb_pulse, width=130)
        cmb_deb_pulse.grid(row=2, column=1, sticky="w", padx=(0, S_LG), pady=2)

        for entry in (
            self.entry_name,
            self.entry_hi, self.entry_lo, self.entry_cycle_force,
            self.entry_deb_cycle_hi, self.entry_deb_cycle_lo, self.entry_deb_cycle_sync,
        ):
            self._bind_disarm_node_delete_on_focus(entry)

    def _build_cond_pane(self):
        parent = self._cond_pane
        self._bit_row = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(self._bit_row, text="Bit:", font=FONT_BODY).pack(side="left", padx=(0, S_SM))
        # 每 bit 一個複選框（勾選=連動）；_active_bit=顯示/編輯的錨點。
        self._bit_box = ctk.CTkFrame(self._bit_row, fg_color="transparent")
        self._bit_box.pack(side="left")
        ctk.CTkLabel(self._bit_row, text="連動編輯：勾選的 bit 會一起套用（Shift 連選）",
                     font=FONT_HINT, text_color="gray").pack(side="left", padx=(S_MD, 0))
        self._bit_link_vars: list[ctk.BooleanVar] = []
        self._bit_checkboxes: list[ctk.CTkCheckBox] = []
        self._anchor_idx: Optional[int] = None
        self._suspend_broadcast = False
        # Slice 面板（維度 output 向量時取代 Bit 選擇器）：上 切片軸、左 分組、右 群組選擇器。
        self._slice_row = ctk.CTkFrame(parent, fg_color="transparent")
        _axfr = ctk.CTkFrame(self._slice_row, fg_color="transparent")
        _axfr.pack(anchor="w", padx=S_SM)
        ctk.CTkLabel(_axfr, text="切片軸:", font=FONT_BODY).pack(side="left", padx=(0, S_SM))
        self._axis_menu = ctk.CTkOptionMenu(_axfr, values=["row"], width=80,
                                            command=self._on_axis_pick)
        self._axis_menu.pack(side="left")
        _body = ctk.CTkFrame(self._slice_row, fg_color="transparent")
        _body.pack(fill="x")
        _left = ctk.CTkFrame(_body, fg_color="transparent")
        _left.pack(side="left", anchor="n")
        self._axis_group_label = ctk.CTkLabel(_left, text="Row 分組", font=FONT_BODY)
        self._axis_group_label.pack(anchor="w")
        self._row_assign_box = ctk.CTkFrame(_left, fg_color="transparent")
        self._row_assign_box.pack(anchor="w")
        _right = ctk.CTkFrame(_body, fg_color="transparent")
        _right.pack(side="left", anchor="n", padx=(S_MD, 0))
        ctk.CTkLabel(_right, text="群組", font=FONT_BODY).pack(side="left", padx=(0, S_SM))
        self._group_sel = ctk.CTkOptionMenu(_right, values=["else"], width=90,
                                            command=self._on_group_sel)
        self._group_sel.pack(side="left")
        self._cond_host = ctk.CTkFrame(parent, fg_color="transparent")
        self._cond_host.pack(fill="x")
        self._sync_bit_selector()

    def _rebuild_bit_checkboxes(self, n: int):
        """重建 bit 複選框；寬度不變時沿用目前勾選，寬度改變時重設為只勾錨點。"""
        prev = [v.get() for v in self._bit_link_vars]
        keep = len(prev) == n
        for w in self._bit_box.winfo_children():
            w.destroy()
        self._bit_link_vars = []
        self._bit_checkboxes = []
        for i in range(n):
            checked = prev[i] if keep else (i == self._active_bit)
            var = ctk.BooleanVar(value=checked)
            cb = ctk.CTkCheckBox(self._bit_box, text=str(i), variable=var, width=44)
            cb.pack(side="left", padx=(0, S_XS))
            handler = lambda e, idx=i: self._on_bit_checkbox_click(idx, e)
            cb._canvas.bind("<Button-1>", handler)
            cb._text_label.bind("<Button-1>", handler)
            self._bit_link_vars.append(var)
            self._bit_checkboxes.append(cb)

    def _on_bit_checkbox_click(self, idx: int, event):
        """Explorer 風格 anchor + Shift 區間（取代 CTkCheckBox 內建 toggle）。"""
        shift = bool(event.state & 0x0001)
        if shift and self._bit_link_vars:
            anchor = self._anchor_idx if self._anchor_idx is not None else 0
            new_state = not self._bit_link_vars[idx].get()
            lo, hi = sorted((anchor, idx))
            for i in range(lo, hi + 1):
                self._bit_link_vars[i].set(new_state)
        else:
            self._bit_link_vars[idx].set(not self._bit_link_vars[idx].get())
            self._anchor_idx = idx
        self._view_bit(idx)

    def _view_bit(self, idx: int):
        """切換檢視/編輯的錨點 bit（只收集+重建，不廣播）。"""
        self._collect_active_bit()
        self._destroy_cond_editor()
        self._build_bit_editor(idx)

    def _bind_disarm_node_delete_on_focus(self, widget):
        def _on_focus_in(_event):
            top = self.winfo_toplevel()
            disarm = getattr(top, "_disarm_node_list_delete", None)
            if disarm:
                disarm()
        widget.bind("<FocusIn>", _on_focus_in, add="+")

    # ---- per-bit condition editor ----
    def _destroy_cond_editor(self):
        for w in self._cond_host.winfo_children():
            w.destroy()
        self._cond_editor = None

    def _build_bit_editor(self, bit_index: int):
        """為第 bit_index 個 bit 建條件編輯器（host 須已清空）。"""
        self._active_bit = bit_index
        bit = self._bit_rails[bit_index]
        # 建構期間暫停廣播：避免 widget 初始化觸發的 on_change 誤覆蓋其他 bit。
        self._suspend_broadcast = True
        try:
            if self.var_type.get() == "input":
                frame = InputWaveCondFrame(
                    self._cond_host, rail_input_wave_spec(bit),
                    get_dep_options=self._dep_options,
                    is_pseqcell_for=self._is_pseqcell_for,
                    get_self_name=self.base_name,
                    vec_dep=self._vec_dep,
                    on_change=self._on_cond_live_change,
                )
                frame.pack(fill="x", padx=S_SM, pady=S_SM)
                self._cond_editor = {"kind": "input", "wave": frame}
            else:
                self._cond_editor = self._mount_output_sections(bit, self._on_cond_live_change)
        finally:
            self._suspend_broadcast = False

    def _mount_output_sections(self, rail: PowerRail, on_change) -> dict:
        """在 _cond_host 掛 Hi/Lo/Force 三分頁（per-bit 與 slice 群組共用）。"""
        tabs = ctk.CTkTabview(self._cond_host, height=220)
        tabs.pack(fill="x", padx=S_SM, pady=S_SM)
        sections: dict[str, CondSectionFrame] = {}
        for kind in ("hi", "lo", "force"):
            theme = COND_THEME[kind]
            tabs.add(theme["name"])
            sec = CondSectionFrame(
                tabs.tab(theme["name"]), kind,
                get_dep_options=self._dep_options,
                is_pseqcell_for=self._is_pseqcell_for,
                model=CondEditModel.from_rail(rail, kind),
                get_self_name=self.base_name,
                vec_dep=self._vec_dep,
                on_change=on_change,
            )
            sec.pack(fill="both", expand=True, padx=S_SM, pady=S_SM)
            sections[kind] = sec
        return {"kind": "output", "tabs": tabs, "sections": sections}

    # ---- 多 bit 即時共編 ----
    def _on_cond_live_change(self):
        """條件編輯事件：收回錨點 bit，再把條件鏡射到其他勾選 bit（自動同索引替換）。"""
        if self._suspend_broadcast:
            return
        self._collect_active_bit()
        self._broadcast_to_linked()

    def _linked_targets(self) -> list[int]:
        checked = {i for i, v in enumerate(self._bit_link_vars) if v.get()}
        checked.add(self._active_bit)  # 錨點恆為來源
        return sorted(i for i in checked if i != self._active_bit)

    def _broadcast_to_linked(self):
        if not (0 <= self._active_bit < len(self._bit_rails)):
            return
        src = self._bit_rails[self._active_bit]
        for j in self._linked_targets():
            self._copy_cond_reindexed(src, self._bit_rails[j], self._active_bit, j)

    def _reindex_name(self, name: str, src: int, dst: int) -> str:
        """V[src] → V[dst]（僅當 V 是 vector base 且索引==src）；其餘（scalar/常數/固定索引）原樣。"""
        p = name.rfind("[")
        if p < 0 or not name.endswith("]"):
            return name
        base, idx = name[:p], name[p + 1:-1]
        if idx.isdigit() and int(idx) == src and self._dep_vector_width(base) is not None:
            return _bit_name(base, dst)
        return name

    def _copy_cond_reindexed(self, src: PowerRail, dst: PowerRail, src_bit: int, dst_bit: int):
        """把 src 的條件鏡射到 dst：名稱欄位做同索引替換，位置性欄位原樣複製。"""
        def r(nm: str) -> str:
            return self._reindex_name(nm, src_bit, dst_bit)

        if src.seq_type == "input":
            for side in ("hi", "lo"):
                setattr(dst, f"{side}_mode", getattr(src, f"{side}_mode"))
                setattr(dst, f"{side}_wave", getattr(src, f"{side}_wave"))
                setattr(dst, f"{side}_groups",
                        [[r(n) for n in g] for g in getattr(src, f"{side}_groups")])
                setattr(dst, f"{side}_inv_groups",
                        copy.deepcopy(getattr(src, f"{side}_inv_groups")))
                setattr(dst, f"{side}_use_groups",
                        copy.deepcopy(getattr(src, f"{side}_use_groups")))
                setattr(dst, f"{side}_group_inv", list(getattr(src, f"{side}_group_inv")))
                setattr(dst, f"{side}_intra_op", list(getattr(src, f"{side}_intra_op")))
            return
        for kind in ("hi", "lo", "force"):
            setattr(dst, f"depends_on_{kind}",
                    [r(n) for n in getattr(src, f"depends_on_{kind}")])
            setattr(dst, f"depends_on_{kind}_groups",
                    [[r(n) for n in g] for g in getattr(src, f"depends_on_{kind}_groups")])
            setattr(dst, f"depends_on_{kind}_inv",
                    {r(k): v for k, v in getattr(src, f"depends_on_{kind}_inv").items()})
            setattr(dst, f"depends_on_{kind}_use",
                    {r(k): v for k, v in getattr(src, f"depends_on_{kind}_use").items()})
            setattr(dst, f"depends_on_{kind}_inv_groups",
                    copy.deepcopy(getattr(src, f"depends_on_{kind}_inv_groups")))
            setattr(dst, f"depends_on_{kind}_use_groups",
                    copy.deepcopy(getattr(src, f"depends_on_{kind}_use_groups")))
            setattr(dst, f"depends_on_{kind}_group_inv",
                    list(getattr(src, f"depends_on_{kind}_group_inv")))
            setattr(dst, f"depends_on_{kind}_intra_op",
                    list(getattr(src, f"depends_on_{kind}_intra_op")))
        dst.depends_on = list(dst.depends_on_hi)

    def _collect_active_bit(self):
        """把作用中 bit 的條件編輯器內容收回 `_bit_rails[active]`。"""
        ed = self._cond_editor
        if ed is None or not (0 <= self._active_bit < len(self._bit_rails)):
            return
        rail = self._bit_rails[self._active_bit]
        if ed["kind"] == "input":
            apply_input_wave_dict(rail, ed["wave"].to_spec().to_dict())
        else:
            self._apply_output_sections(rail, ed["sections"])

    @staticmethod
    def _apply_output_sections(rail: PowerRail, secs: dict) -> None:
        hi, lo, fo = secs["hi"], secs["lo"], secs["force"]
        rail.depends_on = hi.get_flat_deps()
        rail.depends_on_hi = hi.get_flat_deps()
        rail.depends_on_lo = lo.get_flat_deps()
        rail.depends_on_force = fo.get_flat_deps()
        rail.depends_on_hi_groups = hi.get_groups()
        rail.depends_on_lo_groups = lo.get_groups()
        rail.depends_on_force_groups = fo.get_groups()
        rail.depends_on_hi_inv = hi.get_inv_flat()
        rail.depends_on_lo_inv = lo.get_inv_flat()
        rail.depends_on_force_inv = fo.get_inv_flat()
        rail.depends_on_hi_use = hi.get_use_flat()
        rail.depends_on_lo_use = lo.get_use_flat()
        rail.depends_on_force_use = fo.get_use_flat()
        rail.depends_on_hi_inv_groups = hi.get_inv_groups()
        rail.depends_on_lo_inv_groups = lo.get_inv_groups()
        rail.depends_on_force_inv_groups = fo.get_inv_groups()
        rail.depends_on_hi_use_groups = hi.get_use_groups()
        rail.depends_on_lo_use_groups = lo.get_use_groups()
        rail.depends_on_force_use_groups = fo.get_use_groups()
        rail.depends_on_hi_take_groups = hi.get_take_groups()
        rail.depends_on_lo_take_groups = lo.get_take_groups()
        rail.depends_on_force_take_groups = fo.get_take_groups()
        rail.depends_on_hi_group_inv = hi.get_group_inv()
        rail.depends_on_lo_group_inv = lo.get_group_inv()
        rail.depends_on_force_group_inv = fo.get_group_inv()
        rail.depends_on_hi_intra_op = hi.get_group_intra_op()
        rail.depends_on_lo_intra_op = lo.get_group_intra_op()
        rail.depends_on_force_intra_op = fo.get_group_intra_op()

    # ---- slice（維度 output 向量，V1 row 軸）----
    def _is_dim_slice_node(self) -> bool:
        """輸出且至少 1 維 → 條件頁走 slice 群組編輯（取代 per-bit）。"""
        return self.var_type.get() == "output" and len(self._selected_dim_params()) >= 1

    def _rep_axis_count(self) -> int:
        """目前切片軸的最大值畫布：row 取 dim_params[0]、col 取 dim_params[1]（§4.1／§4.2）。"""
        dims = self._selected_dim_params()
        idx = 1 if self._slice_axis == "col" else 0
        if idx >= len(dims):
            return 1
        name = dims[idx]
        for p in self._parameters():
            if getattr(p, "name", None) == name:
                return max(1, int(p.value))
        return max(1, len(self._bit_rails) or 1)

    def _present_group_ids(self) -> list[int]:
        """目前有 row 指派的非 else 群組 id（升冪＝建立序＝if/else-if 優先權）。"""
        return sorted({g for g in self._row_group if g != 0})

    def _group_labels(self) -> dict[int, str]:
        """群組 id → 顯示標籤：0→else，非 else 依升冪 A/B/...。"""
        labels = {0: "else"}
        for i, gid in enumerate(self._present_group_ids()):
            labels[gid] = chr(ord("A") + i) if i < 26 else f"G{gid}"
        return labels

    def _label_to_gid(self, label: str) -> int:
        for gid, lab in self._group_labels().items():
            if lab == label:
                return gid
        return 0

    def _load_slice_state_from_head(self) -> None:
        """首次進 slice 模式：由 head（bit0）的扁平條件＝else、cond.slices＝非 else 群組載入。

        軸由既存 slices 的 axis 還原（單軸，取第一組即可）；rep_n 依該軸的最大值畫布算。"""
        head = self._bit_rails[0] if self._bit_rails else PowerRail(
            name=self.base_name(), seq_type="output")
        stored = getattr(head.cond, "slices", None) or []
        self._slice_axis = "col" if (stored and getattr(stored[0], "axis", "row") == "col") else "row"
        rep_n = self._rep_axis_count()
        else_rail = copy.deepcopy(head)
        else_rail.cond.slices = []  # else 不帶 slices
        self._slice_rails = {0: else_rail}
        self._row_group = [0] * rep_n
        self._next_gid = 1
        for sg in stored:
            gid = self._next_gid
            self._next_gid += 1
            gr = PowerRail(name=f"{self.base_name()}~g{gid}", seq_type="output")
            gr.cond = copy.deepcopy(sg.cond)
            self._slice_rails[gid] = gr
            for r in sg.rows:
                if 0 <= r < rep_n:
                    self._row_group[r] = gid
        self._active_group = 0

    def _enter_slice_mode(self) -> None:
        if not self._slice_active:
            self._load_slice_state_from_head()
            self._slice_active = True
        else:
            rep_n = self._rep_axis_count()
            if len(self._row_group) < rep_n:
                self._row_group += [0] * (rep_n - len(self._row_group))
            elif len(self._row_group) > rep_n:
                del self._row_group[rep_n:]
            self._prune_empty_groups()

    def _on_axis_pick(self, value: str) -> None:
        """切片軸切換（§4.2）：Q8 清空目前軸的分組，新軸從全 else 重來（else 扁平條件保留）。"""
        if value == self._slice_axis or value not in ("row", "col"):
            return
        self._collect_active_group()
        self._slice_axis = value
        else_rail = self._slice_rails.get(0)
        self._slice_rails = {0: else_rail} if else_rail is not None else {}
        self._row_group = [0] * self._rep_axis_count()
        self._active_group = 0
        self._next_gid = 1
        self._destroy_cond_editor()
        self._render_slice_panel()
        self._build_group_editor(0)

    def _prune_empty_groups(self) -> None:
        present = set(self._present_group_ids())
        for gid in list(self._slice_rails):
            if gid != 0 and gid not in present:
                del self._slice_rails[gid]
        if self._active_group != 0 and self._active_group not in present:
            self._active_group = 0

    def _create_group(self) -> int:
        gid = self._next_gid
        self._next_gid += 1
        self._slice_rails[gid] = PowerRail(
            name=f"{self.base_name()}~g{gid}", seq_type="output")
        return gid

    def _collect_active_group(self) -> None:
        ed = self._cond_editor
        if ed is None or ed.get("kind") != "output":
            return
        rail = self._slice_rails.get(self._active_group)
        if rail is not None:
            self._apply_output_sections(rail, ed["sections"])

    def _build_group_editor(self, gid: int) -> None:
        self._active_group = gid
        rail = self._slice_rails.setdefault(
            gid, PowerRail(name=f"{self.base_name()}~g{gid}", seq_type="output"))
        self._suspend_broadcast = True
        try:
            self._cond_editor = self._mount_output_sections(rail, self._on_slice_cond_change)
        finally:
            self._suspend_broadcast = False

    def _on_slice_cond_change(self) -> None:
        if self._suspend_broadcast:
            return
        self._collect_active_group()

    def _on_row_group_pick(self, row: int, value: str) -> None:
        if value == "新增...":
            self._row_group[row] = self._create_group()
        elif value == "else":
            self._row_group[row] = 0
        else:
            self._row_group[row] = self._label_to_gid(value)
        self._prune_empty_groups()
        self._sync_slice_selector()

    def _on_group_sel(self, label: str) -> None:
        self._collect_active_group()
        self._destroy_cond_editor()
        self._build_group_editor(self._label_to_gid(label))

    def _render_slice_panel(self) -> None:
        for w in self._row_assign_box.winfo_children():
            w.destroy()
        # 切片軸下拉：2D 才提供 col（§4.2：1D 無 col 軸）。
        two_d = len(self._selected_dim_params()) >= 2
        self._axis_menu.configure(values=["row", "col"] if two_d else ["row"])
        self._axis_menu.set(self._slice_axis)
        self._axis_group_label.configure(text="Col 分組" if self._slice_axis == "col" else "Row 分組")
        labels = self._group_labels()
        present = self._present_group_ids()
        row_values = [labels[g] for g in present] + ["else", "新增..."]
        self._row_menus = []
        for r in range(len(self._row_group)):
            fr = ctk.CTkFrame(self._row_assign_box, fg_color="transparent")
            fr.pack(anchor="w")
            ctk.CTkLabel(fr, text=f"{self._slice_axis}{r}", font=FONT_BODY, width=48).pack(side="left")
            menu = ctk.CTkOptionMenu(
                fr, values=row_values, width=90,
                command=lambda val, rr=r: self._on_row_group_pick(rr, val))
            menu.set(labels.get(self._row_group[r], "else"))
            menu.pack(side="left")
            self._row_menus.append(menu)
        self._group_sel.configure(values=[labels[g] for g in present] + ["else"])
        self._group_sel.set(labels.get(self._active_group, "else"))

    def _sync_slice_selector(self) -> None:
        """維度 output 向量的條件頁：Row 分組 + 群組選擇器，取代 Bit 選擇器。"""
        self._collect_active_group()
        self._destroy_cond_editor()
        self._enter_slice_mode()
        self._bit_row.pack_forget()
        self._slice_row.pack(fill="x", padx=S_SM, pady=(0, S_SM), before=self._cond_host)
        self._render_slice_panel()
        if self._active_group != 0 and self._active_group not in self._present_group_ids():
            self._active_group = 0
        self._build_group_editor(self._active_group)

    def _build_slice_groups(self) -> list:
        groups = []
        for gid in self._present_group_ids():
            rows = [r for r in range(len(self._row_group)) if self._row_group[r] == gid]
            groups.append(SliceGroup(rows=rows, axis=self._slice_axis,
                                     cond=copy.deepcopy(self._slice_rails[gid].cond)))
        return groups

    def _get_rails_sliced(self) -> list[PowerRail]:
        """維度 output 向量：bit0（head）扁平＝else 組、cond.slices＝非 else 群組；其餘 bit 空。"""
        self._collect_active_group()
        base = self.base_name()
        dims = self._selected_dim_params()
        width_expr = self._width_expr()
        n = self._parse_width()
        out: list[PowerRail] = []
        for i in range(n):
            rail = PowerRail(name=f"{base}[{i}]", seq_type="output")
            self._apply_physical(rail, "output")
            out.append(rail)
        else_rail = self._slice_rails.get(0)
        if else_rail is not None:
            out[0].cond = copy.deepcopy(else_rail.cond)
        out[0].cond.slices = self._build_slice_groups()
        set_group_metadata(out, base, width_expr, dims)
        return out

    def _sync_bit_selector(self):
        """依 Vector 勾選＋寬度，調整 `_bit_rails` 長度與 Bit 選擇器，重建作用中 bit 編輯器。"""
        if self._is_dim_slice_node():
            self._sync_slice_selector()
            return
        self._slice_active = False
        self._slice_row.pack_forget()
        self._collect_active_bit()
        self._destroy_cond_editor()
        is_vec = self.is_vector()
        n = self._parse_width() if is_vec else 1
        base = self.base_name()
        seq_type = self.var_type.get()
        self._bit_rails = resize_list(
            self._bit_rails, n,
            lambda i: PowerRail(name=f"{base}[{i}]", seq_type=seq_type),
        )
        if self._active_bit >= n:
            self._active_bit = 0
        if is_vec:
            self._anchor_idx = self._active_bit
            self._rebuild_bit_checkboxes(n)
            self._bit_row.pack(fill="x", padx=S_SM, pady=(0, S_SM), before=self._cond_host)
        else:
            self._bit_row.pack_forget()
        self._build_bit_editor(self._active_bit)

    # ---- callbacks ----
    def _on_apply_clicked(self):
        if self.on_apply:
            self.on_apply()

    def _on_mode_seg(self, label: str):
        self._show_mode(label)

    def _show_mode(self, label: str):
        self._decl_pane.pack_forget()
        self._cond_pane.pack_forget()
        self.apply_row.pack_forget()
        if label == COND_TAB:
            self._cond_host.pack(fill="x")
            # 進條件分頁時依目前 Vector/width 重算 Bit 選擇器與每 bit 編輯器，
            # 否則 width 改後若未觸發 <FocusOut>/<Return>，Bit 選擇器會停在舊值。
            self._sync_bit_selector()
            self._cond_pane.pack(fill="x")
        else:
            self._decl_pane.pack(fill="x")
        self.apply_row.pack(fill="x", padx=S_SM, pady=(0, S_SM))

    def _on_bit_selected(self, value: str):
        # 相容舊呼叫端/測試：等同切換檢視 bit（不廣播）。
        self._view_bit(_safe_int(value, 0))

    def _render_dim_bits(self):
        """依維度個數重建 Bits 下拉（選項＝已宣告的全域維度）；無全域維度時顯示佔位。"""
        for w in self.dim_bits_row.winfo_children():
            w.destroy()
        self._dim_menus = []
        count = self._dim_count()
        dims = self._global_dims()
        for slot in range(count):
            values = dims or ["(宣告維度)"]
            cur = self._dim_params_init[slot] if slot < len(self._dim_params_init) else ""
            if cur not in dims:
                cur = dims[slot] if slot < len(dims) else (dims[0] if dims else values[0])
            if slot > 0:
                ctk.CTkLabel(self.dim_bits_row, text="×", font=FONT_BODY).pack(side="left", padx=2)
            menu = ctk.CTkOptionMenu(
                self.dim_bits_row, values=values, width=110,
                command=lambda _v: self._on_dim_pick())
            menu.set(cur)
            menu.pack(side="left")
            self._dim_menus.append(menu)

    def _on_dim_count_changed(self, _value: str):
        self._dim_params_init = self._selected_dim_params()
        self._render_dim_bits()
        self._sync_bit_selector()

    def _on_dim_pick(self):
        self._sync_bit_selector()

    def _on_vector_toggle(self):
        self._sync_bit_selector()

    def _on_type_seg_selected(self, label: str):
        rev = {v: k for k, v in SEQ_TYPE_LABELS.items()}
        new_type = rev.get(label, "output")
        if new_type != self.var_type.get():
            self.var_type.set(new_type)
        self._on_type_toggle()

    def _on_type_toggle(self, initial: bool = False):
        is_input = self.var_type.get() == "input"
        if is_input:
            self.pseq_timing_wrap.pack_forget()
            self.deb_wrap.pack(fill="x", pady=(0, S_SM))
            self._on_deb_toggle(initial=initial)
        else:
            self.deb_wrap.pack_forget()
            self.pseq_timing_wrap.pack(fill="x", pady=(0, S_SM))
        if not initial:
            # Type 改變 → 條件編輯器型態（Hi/Lo/Force ↔ Timing Hi/Lo）也要換
            self._slice_row.pack_forget()
            if self._is_dim_slice_node():
                self._sync_slice_selector()
            else:
                self._slice_active = False
                self._collect_active_bit()
                self._destroy_cond_editor()
                self._build_bit_editor(self._active_bit)

    def _on_deb_toggle(self, initial: bool = False):
        if self.var_deb_enable.get():
            self.deb_params.pack(fill="x")
        else:
            self.deb_params.pack_forget()

    # ---- physical (shared across bits) ----
    def _apply_physical(self, rail: PowerRail, seq_type: str) -> None:
        rail.seq_type = seq_type
        if seq_type == "input":
            rail.cycle_hi = 0
            rail.cycle_lo = 0
            rail.cycle_force = 2
            rail.init = 0
            rail.force_val = 0
            rail.pulse_hi = DEFAULT_PULSE
            rail.pulse_lo = DEFAULT_PULSE
            rail.pulse_force = DEFAULT_PULSE
            rail.deb_enable = self.var_deb_enable.get()
            rail.deb_init = 1 if self.var_deb_init.get() == "1" else 0
            rail.deb_cycle_hi = _safe_int(self.entry_deb_cycle_hi.get(), 2)
            rail.deb_cycle_lo = _safe_int(self.entry_deb_cycle_lo.get(), 2)
            rail.deb_cycle_sync = _safe_int(self.entry_deb_cycle_sync.get(), 2)
            rail.deb_pulse = self.var_deb_pulse.get()
            rail.cond = ConditionConfig()  # input 無 Verilog 條件；input-wave 保留
        else:
            rail.cycle_hi = _safe_int(self.entry_hi.get(), rail.cycle_hi)
            rail.cycle_lo = _safe_int(self.entry_lo.get(), rail.cycle_lo)
            rail.cycle_force = _safe_int(self.entry_cycle_force.get(), getattr(rail, "cycle_force", 2))
            rail.init = 1 if self.var_pseq_init.get() == "1" else 0
            rail.force_val = 1 if self.var_force_val.get() == "1" else 0
            rail.pulse_hi = self.var_pulse_hi.get()
            rail.pulse_lo = self.var_pulse_lo.get()
            rail.pulse_force = self.var_pulse_force.get()
            rail.deb_enable = False
            rail.deb_init = 0
            rail.deb_cycle_hi = 2
            rail.deb_cycle_lo = 2
            rail.deb_cycle_sync = 2
            rail.deb_pulse = DEFAULT_PULSE
            apply_input_wave_dict(rail, {})  # output 無 input-wave，歸零

    # ---- collect ----
    def get_rails(self) -> list[PowerRail]:
        """攤成 N 個 PowerRail（vector 帶群組 metadata，scalar 回單一 rail）。"""
        if self._is_dim_slice_node():
            return self._get_rails_sliced()
        base = self.base_name()
        seq_type = self.var_type.get()
        is_vec = self.is_vector()
        dims = self._selected_dim_params()
        width_expr = self._width_expr()
        n = self._parse_width() if is_vec else 1
        self._collect_active_bit()
        self._bit_rails = resize_list(
            self._bit_rails, n,
            lambda i: PowerRail(name=f"{base}[{i}]", seq_type=seq_type),
        )
        if self._active_bit >= n:
            self._active_bit = 0
        out: list[PowerRail] = []
        for i in range(n):
            rail = copy.deepcopy(self._bit_rails[i])
            rail.name = f"{base}[{i}]" if is_vec else base
            self._apply_physical(rail, seq_type)
            out.append(rail)
        set_group_metadata(
            out, base if is_vec else None, width_expr if is_vec else "1",
            dims if is_vec else None)
        return out


# ============================================================
# CollapsibleRailFrame — accordion 卡片，一張卡片 = 一個節點（方案甲）
# ============================================================

class CollapsibleRailFrame(ctk.CTkFrame):
    """Accordion wrapper：可點擊 header + 可摺疊 RailEditorFrame（節點 = N 個 bit rails）。"""

    def __init__(self, master, rails,
                 get_all_rails: Callable[[], list[PowerRail]],
                 get_pulses: Callable[[], list[str]],
                 on_apply: Optional[Callable[[], None]] = None,
                 expanded: bool = False,
                 get_parameters: Optional[Callable[[], list]] = None,
                 get_dimensions: Optional[Callable[[], list]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        self.rails = list(rails)
        self._expanded = expanded
        self._get_all_rails = get_all_rails
        self._get_pulses = get_pulses
        self._get_parameters = get_parameters
        self._get_dimensions = get_dimensions
        self._on_apply = on_apply
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

    # ---- node identity ----
    def base_name(self) -> str:
        if self.editor is not None:
            return self.editor.base_name()
        base, _ = _node_base_of(self.rails)
        return base

    def is_vector(self) -> bool:
        if self.editor is not None:
            return self.editor.is_vector()
        return self.rails[0].group_base is not None

    def width_n(self) -> int:
        return len(self.rails)

    def _head(self) -> PowerRail:
        return self.rails[0]

    def _refresh_header(self):
        base, is_vec = _node_base_of(self.rails)
        head = self._head()
        self._name_label.configure(text=base)
        for w in self._chips_holder.winfo_children():
            w.destroy()
        type_label = SEQ_TYPE_LABELS.get(head.seq_type, head.seq_type)
        pill = make_pill(self._chips_holder, type_label, head.seq_type)
        pill.pack(side="left", padx=(0, S_SM))
        pill.bind("<Button-1>", lambda _: self.toggle())
        if is_vec:
            params = self._get_parameters() if self._get_parameters else []
            marker = make_chip(self._chips_holder, vector_shape_label(self.rails, params),
                               fg=COND_THEME["force"]["text"])
            marker.pack(side="left", padx=(0, S_SM))
            marker.bind("<Button-1>", lambda _: self.toggle())
        chips: list[tuple[str, str | None, str | None]] = []
        if head.seq_type == "input":
            if getattr(head, "deb_enable", False):
                chips.append(("Deb:ON", None, None))
                chips.append((f"HI:{getattr(head, 'deb_cycle_hi', 2)}", None, None))
                chips.append((f"LO:{getattr(head, 'deb_cycle_lo', 2)}", None, None))
                chips.append((f"INIT:{getattr(head, 'deb_init', 0)}", None, None))
            else:
                chips.append(("Deb:OFF", ("gray40", "gray60"), None))
        else:
            chips.append((f"HI:{head.cycle_hi}", COND_THEME["hi"]["text"], None))
            chips.append((f"LO:{head.cycle_lo}", COND_THEME["lo"]["text"], None))
            chips.append((f"F:{head.cycle_force}", COND_THEME["force"]["text"], None))
            chips.append((f"INIT:{getattr(head, 'init', 0)}", None, None))
            if getattr(head, "force_val", 0) == 1:
                chips.append(("FORCE:1", COND_THEME["force"]["text"], None))
        for text, fg, bg in chips:
            c = make_chip(self._chips_holder, text, fg=fg, bg=bg)
            c.pack(side="left", padx=(0, S_XS))
            c.bind("<Button-1>", lambda _: self.toggle())

    def _ensure_body(self):
        if self.editor is not None:
            return
        self.editor = RailEditorFrame(
            self._body, self.rails,
            get_all_rails=self._get_all_rails,
            get_pulses=self._get_pulses,
            on_apply=self._on_apply,
            get_parameters=self._get_parameters,
            get_dimensions=self._get_dimensions,
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

    def get_rails(self) -> list[PowerRail]:
        if self.editor is not None:
            self.rails = self.editor.get_rails()
        return self.rails


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
        self._progress = ctk.CTkProgressBar(self, width=90, height=10, mode="indeterminate")
        self._msg_after_id: Optional[str] = None

    def set_busy(self, on: bool):
        """存檔等背景工作時顯示不定量進度條。"""
        try:
            if on:
                self._progress.pack(side="right", padx=(S_SM, 0))
                self._progress.start()
            else:
                self._progress.stop()
                self._progress.pack_forget()
        except Exception:
            pass

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


__all__ = [
    "CondSectionFrame", "InputWaveSidePanel", "InputWaveCondFrame",
    "RailEditorFrame", "CollapsibleRailFrame",
    "Tooltip", "DragGhost", "StatusBar",
]

