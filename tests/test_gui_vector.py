"""B6 步驟 2：方案甲 Tk 殼層接線（需要顯示；無顯示則 skip）。

只驗接線：卡片 node 化（vector 一張卡）、[宣告|條件] 分頁、Vector 勾選+寬度、Bit 選擇器、
NodeListPanel 一列一 node 的 vector 標記、左欄可收合標題。語意正確性由 core 層測試保證。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import ConditionConfig, PowerRail, VectorNode


def _scalar_output() -> list[PowerRail]:
    return [PowerRail("A", seq_type="output", cycle_hi=3, cycle_lo=4,
                      depends_on_hi_groups=[["High"]])]


def _vector_output(width: int = 2) -> list[PowerRail]:
    conds = [ConditionConfig(depends_on_hi_groups=[[f"X{i}"]]) for i in range(width)]
    return VectorNode("V", "output", str(width), conds).elaborate()


class TestRailEditorNode:
    def test_scalar_round_trip(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _scalar_output(),
                             get_all_rails=lambda: _scalar_output(), get_pulses=lambda: ["PSEQ"])
        try:
            rails = ed.get_rails()
            assert len(rails) == 1
            assert rails[0].name == "A"
            assert rails[0].group_base is None
            assert rails[0].cycle_hi == 3
            assert rails[0].depends_on_hi_groups == [["High"]]
        finally:
            ed.destroy()

    def test_vector_round_trip_preserves_per_bit(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _vector_output(2),
                             get_all_rails=lambda: _vector_output(2), get_pulses=lambda: ["PSEQ"])
        try:
            assert ed.is_vector() is True
            rails = ed.get_rails()
            assert [r.name for r in rails] == ["V[0]", "V[1]"]
            assert [r.group_base for r in rails] == ["V", "V"]
            assert [r.bit_index for r in rails] == [0, 1]
            # 每 bit 條件保持獨立（切 Bit 選擇器前後不互相覆蓋）
            assert rails[0].depends_on_hi_groups == [["X0"]]
            assert rails[1].depends_on_hi_groups == [["X1"]]
        finally:
            ed.destroy()

    def test_bit_selector_switch_keeps_edits(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _vector_output(2),
                             get_all_rails=lambda: _vector_output(2), get_pulses=lambda: ["PSEQ"])
        try:
            ed._on_bit_selected("1")  # 切到 bit 1 再切回
            ed._on_bit_selected("0")
            rails = ed.get_rails()
            assert rails[0].depends_on_hi_groups == [["X0"]]
            assert rails[1].depends_on_hi_groups == [["X1"]]
        finally:
            ed.destroy()

    def test_mode_switch_declaration_condition(self, ctk_root):
        from gui.widgets import COND_TAB, DECL_TAB, RailEditorFrame

        ed = RailEditorFrame(ctk_root, _scalar_output(),
                             get_all_rails=lambda: _scalar_output(), get_pulses=lambda: ["PSEQ"])
        try:
            # 以 winfo_manager()（packed→"pack"，forget→""）判斷，不依賴 root 真的顯示
            assert ed._decl_pane.winfo_manager() == "pack"
            assert ed._cond_pane.winfo_manager() == ""
            ed._on_mode_seg(COND_TAB)
            assert ed._cond_pane.winfo_manager() == "pack"
            assert ed._decl_pane.winfo_manager() == ""
            ed._on_mode_seg(DECL_TAB)
            assert ed._decl_pane.winfo_manager() == "pack"
        finally:
            ed.destroy()

    def test_base_rename_reflected(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _vector_output(2),
                             get_all_rails=lambda: _vector_output(2), get_pulses=lambda: ["PSEQ"])
        try:
            ed.entry_name.delete(0, "end")
            ed.entry_name.insert(0, "Q")
            rails = ed.get_rails()
            assert [r.name for r in rails] == ["Q[0]", "Q[1]"]
            assert [r.group_base for r in rails] == ["Q", "Q"]
        finally:
            ed.destroy()


class TestCollapsibleNode:
    def test_vector_header_marker(self, ctk_root):
        from gui.widgets import CollapsibleRailFrame

        cf = CollapsibleRailFrame(ctk_root, _vector_output(3),
                                  get_all_rails=lambda: _vector_output(3), get_pulses=lambda: ["PSEQ"])
        try:
            assert cf.base_name() == "V"
            assert cf.is_vector() is True
            assert cf.width_n() == 3
            assert cf.get_rails()[0].group_base == "V"
        finally:
            cf.destroy()

    def test_scalar_header(self, ctk_root):
        from gui.widgets import CollapsibleRailFrame

        cf = CollapsibleRailFrame(ctk_root, _scalar_output(),
                                  get_all_rails=lambda: _scalar_output(), get_pulses=lambda: ["PSEQ"])
        try:
            assert cf.base_name() == "A"
            assert cf.is_vector() is False
            assert cf.width_n() == 1
        finally:
            cf.destroy()


class TestNodeListPanelNodes:
    def _panel(self, ctk_root):
        from gui.panels import NodeListPanel

        def noop(*_a, **_k):
            return None

        return NodeListPanel(ctk_root, on_select=noop, on_reorder=noop,
                             on_multi_change=noop, on_add=noop, on_delete_btn=noop,
                             on_delete=noop, on_activate=noop, on_disarm=noop)

    def test_one_row_per_node_with_marker(self, ctk_root):
        from core.config_edit import group_rails_into_nodes

        panel = self._panel(ctk_root)
        try:
            rails = [*_scalar_output(), *_vector_output(2)]
            nodes = group_rails_into_nodes(rails)
            panel.set_nodes(nodes, primary_idx=0)
            labels = panel.node_labels()
            assert labels == ["A", "V [×2]"]
        finally:
            panel.destroy()
