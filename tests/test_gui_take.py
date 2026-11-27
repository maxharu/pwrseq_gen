"""B4/§6：條件頁 per-row 取法編輯器（需要顯示；無顯示則 skip）。

驗 GUI 糖衣：維度向量相依在相依列上以「取法」下拉＋子選項（n/m）授權 §6 形狀，
選項/預設/映射由 core.take_rules 決定；寫回 model.take、並隨 get_rails 帶出。
語意正確性（take→RHS）由 core 層（take_rules / take_expr / cond_ir / verilog）保證。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import PowerRail
from core.take_rules import (
    ALL_ROW_AND,
    ALL_ROW_OR,
    REL_ROW,
    ROWOFF_ALLCOL_AND,
    ROWOFF_COLOFF,
    ROWOFF_SPEC_COL,
    form_to_take,
    take_forms,
)


def _sig2_1d() -> list[PowerRail]:
    """owner/ dep：SIG2 1 維（NUM_CPU）。"""
    return [PowerRail(f"SIG2[{i}]", "output", group_base="SIG2", bit_index=i,
                      dim_params=["NUM_CPU"]) for i in range(2)]


def _sig4_2d() -> list[PowerRail]:
    """dep：SIG4 2 維（NUM_CPU × NUM_CPU_MEM）。"""
    return [PowerRail(f"SIG4[{i}]", "output", group_base="SIG4", bit_index=i,
                      dim_params=["NUM_CPU", "NUM_CPU_MEM"]) for i in range(8)]


def _sigc_2d() -> list[PowerRail]:
    """owner：SIGC 2 維。"""
    return [PowerRail(f"SIGC[{i}]", "output", group_base="SIGC", bit_index=i,
                      dim_params=["NUM_CPU", "NUM_CPU_MEM"]) for i in range(8)]


def _editor(ctk_root, owner_rails, all_rails):
    from gui.widgets import RailEditorFrame
    return RailEditorFrame(
        ctk_root, owner_rails,
        get_all_rails=lambda: all_rails,
        get_pulses=lambda: ["PSEQ"],
        get_dimensions=lambda: ["NUM_CPU", "NUM_CPU_MEM"],
    )


def _sec_add(ctk_root, owner_rails, all_rails, base):
    """開條件頁、在 group0 加入 base 相依，回 (ed, sec, cell)。"""
    from gui.widgets import COND_TAB
    ed = _editor(ctk_root, owner_rails, all_rails)
    ed._on_mode_seg(COND_TAB)
    sec = ed._cond_editor["sections"]["hi"]
    sec.group_frames[0]["combo"].set(base)
    sec._add_cond_to_group(0)
    return ed, sec, sec.take_cells[(0, 0)]


def _labels(out_ndim, dep_ndim):
    return [f.label for f in take_forms(out_ndim, dep_ndim)]


class TestTakeCellOptions:
    def test_1d_owner_2d_dep_three_forms(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            assert list(cell["menu"].cget("values")) == _labels(1, 2)
            assert sec.model.take[0][0] == form_to_take(ROWOFF_SPEC_COL, 0, 0)
        finally:
            ed.destroy()

    def test_1d_owner_1d_dep_four_forms(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG2")
        try:
            assert list(cell["menu"].cget("values")) == _labels(1, 1)
            assert sec.model.take[0][0] == form_to_take(REL_ROW, 0, 0)
        finally:
            ed.destroy()

    def test_2d_owner_2d_dep_has_coloff(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sigc_2d(), _sigc_2d() + _sig4_2d(), "SIG4")
        try:
            labels = list(cell["menu"].cget("values"))
            assert labels == _labels(2, 2)
            coloff_label = next(f.label for f in take_forms(2, 2) if f.id == ROWOFF_COLOFF)
            assert coloff_label in labels
        finally:
            ed.destroy()


class TestTakeCellEdit:
    def test_change_form_writes_model_take(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            label = next(f.label for f in take_forms(1, 2) if f.id == ROWOFF_ALLCOL_AND)
            cell["form_var"].set(label)
            assert sec.model.take[0][0] == form_to_take(ROWOFF_ALLCOL_AND, 0, 0)
        finally:
            ed.destroy()

    def test_offset_values_write_through(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            label = next(f.label for f in take_forms(1, 2) if f.id == ROWOFF_SPEC_COL)
            cell["form_var"].set(label)
            cell["n_var"].set("-1")
            cell["m_var"].set("2")
            assert sec.model.take[0][0] == form_to_take(ROWOFF_SPEC_COL, -1, 2)
        finally:
            ed.destroy()

    def test_allcol_exposes_col_lower_bound_field(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            label = next(f.label for f in take_forms(1, 2) if f.id == ROWOFF_ALLCOL_AND)
            cell["form_var"].set(label)
            # 全col AND 現有 n(row偏移) + m(col下界) → 子列 2 欄共 4 個 widget
            assert len(cell["sub"].winfo_children()) == 4
            cell["m_var"].set("1")  # col 下界寫入 col.lo
            assert sec.model.take[0][0] == form_to_take(ROWOFF_ALLCOL_AND, 0, 1)
        finally:
            ed.destroy()


class TestTakeCarriedByGetRails:
    def test_get_rails_has_take(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            label = next(f.label for f in take_forms(1, 2) if f.id == ROWOFF_ALLCOL_AND)
            cell["form_var"].set(label)
            rails = ed.get_rails()
            assert rails[0].depends_on_hi_take_groups == [[form_to_take(ROWOFF_ALLCOL_AND, 0, 0)]]
        finally:
            ed.destroy()


class TestScalarNoTakeCell:
    def test_high_dep_has_no_take_cell(self, ctk_root):
        ed, sec, _c = _sec_add(ctk_root, _sig2_1d(), _sig2_1d() + _sig4_2d(), "SIG4")
        try:
            # 另加 High（常數、非維度）→ 不建 take cell
            sec.group_frames[0]["combo"].set("High")
            sec._add_cond_to_group(0)
            assert (0, 1) not in sec.take_cells
        finally:
            ed.destroy()


class TestAllRowLowerBoundCell:
    """1D All 歸約的 n 欄即 row 下界 lo：|oneDim[NUM_ROW-1 : n]。"""

    def test_all_form_shows_lower_bound_entry(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d(), "SIG2")
        try:
            label = next(f.label for f in take_forms(1, 1) if f.id == ALL_ROW_OR)
            cell["form_var"].set(label)
            # 全部OR 只需下界 n → 子列有 1 個 (label + entry)
            assert len(cell["sub"].winfo_children()) == 2
        finally:
            ed.destroy()

    def test_lower_bound_writes_model_take(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d(), "SIG2")
        try:
            label = next(f.label for f in take_forms(1, 1) if f.id == ALL_ROW_OR)
            cell["form_var"].set(label)
            cell["n_var"].set("1")
            assert sec.model.take[0][0] == {"row": {"kind": "all", "op": "or", "lo": 1}}
        finally:
            ed.destroy()

    def test_lower_bound_carried_by_get_rails(self, ctk_root):
        ed, sec, cell = _sec_add(ctk_root, _sig2_1d(), _sig2_1d(), "SIG2")
        try:
            label = next(f.label for f in take_forms(1, 1) if f.id == ALL_ROW_AND)
            cell["form_var"].set(label)
            cell["n_var"].set("2")
            rails = ed.get_rails()
            assert rails[0].depends_on_hi_take_groups == [[form_to_take(ALL_ROW_AND, 2, 0)]]
        finally:
            ed.destroy()

