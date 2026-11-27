"""Slice V1 GUI：維度 output 向量的條件頁用 Row 分組 + 群組選擇器取代 per-bit。

需要顯示；headless 無 Tk 則 skip。語意正確性由 core 層（test_slice.py）保證，這裡只驗
GUI 糖衣：進 slice 模式、新增群組、指派 row、切群組編輯、get_rails 帶出 cond.slices。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import Parameter, PowerRail


class _P:
    def __init__(self, name, value):
        self.name = name
        self.value = value


def _sig2_1d():
    return [PowerRail(f"SIG2[{i}]", "output", group_base="SIG2", bit_index=i,
                      width_expr="NUM_CPU", dim_params=["NUM_CPU"]) for i in range(4)]


def _editor(ctk_root, owner_rails):
    from gui.widgets import RailEditorFrame
    all_rails = owner_rails + [PowerRail("BOOT", "output"), PowerRail("BAR", "output")]
    return RailEditorFrame(
        ctk_root, owner_rails,
        get_all_rails=lambda: all_rails,
        get_pulses=lambda: ["PSEQ"],
        get_parameters=lambda: [Parameter("NUM_CPU", 4)],
        get_dimensions=lambda: ["NUM_CPU"],
    )


def _open_cond(ed):
    from gui.widgets import COND_TAB
    ed._on_mode_seg(COND_TAB)


class TestEnterSliceMode:
    def test_dim_output_enters_slice_mode(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            assert ed._slice_active is True
            assert len(ed._row_group) == 4  # NUM_CPU 最大值畫布
            # Bit 選擇器收起、slice 面板顯示（withdraw 的 root 下用 pack 管理狀態判斷）
            assert ed._bit_row.winfo_manager() == ""
            assert ed._slice_row.winfo_manager() == "pack"
        finally:
            ed.destroy()

    def test_fresh_node_has_no_slices(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            out = ed.get_rails()
            assert out[0].cond.slices == []
        finally:
            ed.destroy()


class TestSliceGroupEditing:
    def _make_group_with_dep(self, ed, row, dep):
        """row 指派新群組，切到該群組，在 hi 加一個 dep。回群組 id。"""
        ed._on_row_group_pick(row, "新增...")
        gid = ed._present_group_ids()[-1]
        label = ed._group_labels()[gid]
        ed._on_group_sel(label)
        sec = ed._cond_editor["sections"]["hi"]
        sec.group_frames[0]["combo"].set(dep)
        sec._add_cond_to_group(0)
        return gid

    def test_create_group_and_assign_row(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            ed._on_row_group_pick(0, "新增...")
            assert ed._present_group_ids() == [1]
            assert ed._row_group[0] == 1
            assert ed._row_group[1] == 0  # 其餘落 else
        finally:
            ed.destroy()

    def test_empty_group_auto_removed(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            ed._on_row_group_pick(0, "新增...")
            assert ed._present_group_ids() == [1]
            ed._on_row_group_pick(0, "else")  # row0 收回 else → 群組 1 變空
            assert ed._present_group_ids() == []
        finally:
            ed.destroy()

    def test_get_rails_emits_slice_group(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            self._make_group_with_dep(ed, 0, "BOOT")
            out = ed.get_rails()
            head = out[0]
            assert len(head.cond.slices) == 1
            sg = head.cond.slices[0]
            assert sg.rows == [0]
            assert sg.cond.get_hi_groups() == [["BOOT"]]
        finally:
            ed.destroy()

    def test_else_stays_in_flat(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            # else 組（預設 active）加一個 BAR
            sec = ed._cond_editor["sections"]["hi"]
            sec.group_frames[0]["combo"].set("BAR")
            sec._add_cond_to_group(0)
            self._make_group_with_dep(ed, 0, "BOOT")
            out = ed.get_rails()
            head = out[0]
            assert head.get_hi_groups() == [["BAR"]]          # else = flat
            assert head.cond.slices[0].cond.get_hi_groups() == [["BOOT"]]
        finally:
            ed.destroy()


def _vv_2d():
    return [PowerRail(f"VV[{i}]", "output", group_base="VV", bit_index=i,
                      width_expr="NUM_CPU*NUM_CPU_MEM",
                      dim_params=["NUM_CPU", "NUM_CPU_MEM"]) for i in range(8)]


def _editor_2d(ctk_root, owner_rails):
    from gui.widgets import RailEditorFrame
    all_rails = owner_rails + [PowerRail("BOOT", "output"), PowerRail("BAR", "output")]
    return RailEditorFrame(
        ctk_root, owner_rails,
        get_all_rails=lambda: all_rails,
        get_pulses=lambda: ["PSEQ"],
        get_parameters=lambda: [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 4)],
        get_dimensions=lambda: ["NUM_CPU", "NUM_CPU_MEM"],
    )


class TestColAxisSlice:
    def test_1d_axis_menu_has_no_col(self, ctk_root):
        ed = _editor(ctk_root, _sig2_1d())
        try:
            _open_cond(ed)
            assert ed._axis_menu.cget("values") == ["row"]
        finally:
            ed.destroy()

    def test_2d_axis_menu_offers_col(self, ctk_root):
        ed = _editor_2d(ctk_root, _vv_2d())
        try:
            _open_cond(ed)
            assert "col" in ed._axis_menu.cget("values")
        finally:
            ed.destroy()

    def test_switch_to_col_resizes_canvas_and_emits_axis(self, ctk_root):
        ed = _editor_2d(ctk_root, _vv_2d())
        try:
            _open_cond(ed)
            ed._on_axis_pick("col")
            assert ed._slice_axis == "col"
            assert len(ed._row_group) == 4  # NUM_CPU_MEM 最大值畫布
            ed._on_row_group_pick(0, "新增...")
            gid = ed._present_group_ids()[-1]
            ed._on_group_sel(ed._group_labels()[gid])
            sec = ed._cond_editor["sections"]["hi"]
            sec.group_frames[0]["combo"].set("BOOT")
            sec._add_cond_to_group(0)
            out = ed.get_rails()
            head = out[0]
            assert len(head.cond.slices) == 1
            assert head.cond.slices[0].axis == "col"
            assert head.cond.slices[0].rows == [0]
        finally:
            ed.destroy()

    def test_switch_axis_clears_groups(self, ctk_root):
        ed = _editor_2d(ctk_root, _vv_2d())
        try:
            _open_cond(ed)
            ed._on_row_group_pick(0, "新增...")  # 在 row 軸建一組
            assert ed._present_group_ids() == [1]
            ed._on_axis_pick("col")              # 切 col → 清空
            assert ed._present_group_ids() == []
        finally:
            ed.destroy()
