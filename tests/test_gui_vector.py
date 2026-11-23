"""B6 步驟 2：方案甲 Tk 殼層接線（需要顯示；無顯示則 skip）。

只驗接線：卡片 node 化（vector 一張卡）、[宣告|條件] 分頁、維度下拉＋Bits、Bit 選擇器、
NodeListPanel 一列一 node 的 vector 標記、左欄可收合標題。語意正確性由 core 層測試保證。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import ConditionConfig, Parameter, PowerRail, VectorNode


def _scalar_output() -> list[PowerRail]:
    return [PowerRail("A", seq_type="output", cycle_hi=3, cycle_lo=4,
                      depends_on_hi_groups=[["High"]])]


def _vector_output(width: int = 2) -> list[PowerRail]:
    conds = [ConditionConfig(depends_on_hi_groups=[[f"X{i}"]]) for i in range(width)]
    return VectorNode("V", "output", str(width), conds).elaborate()


def _mixed_rails() -> list[PowerRail]:
    """1 個 scalar (A) + 1 個 2-bit vector (V[0], V[1])。"""
    return [*_scalar_output(), *_vector_output(2)]


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

    def test_condition_tab_syncs_slice_selector_after_width_change(self, ctk_root):
        """切到條件分頁時維度 output 走 slice 面板（取代 per-bit），Row 分組須反映目前維度寬度。"""
        from gui.widgets import COND_TAB, RailEditorFrame

        ed = RailEditorFrame(ctk_root, _scalar_output(),
                             get_all_rails=lambda: _scalar_output(), get_pulses=lambda: ["PSEQ"],
                             get_parameters=lambda: [Parameter("NUM_CPU", 2)],
                             get_dimensions=lambda: ["NUM_CPU"])
        try:
            ed.var_dim_count.set("1")   # 改成 1 維（NUM_CPU=2），但刻意不呼叫 _on_dim_count_changed
            ed._render_dim_bits()        # 只重建 Bits 下拉，不做 _sync_bit_selector
            ed._on_mode_seg(COND_TAB)    # 點「條件」→ _sync_slice_selector 追上 → 2 個 row 分組
            assert ed._slice_active is True
            assert len(ed._row_group) == 2
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


class TestVectorDepCollapse:
    """甲：vector 相依下拉收合（base 一筆 + 消費模式）；GUI 層展開成具體 base[i]。"""

    def test_dep_options_collapsed(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _scalar_output(),
                             get_all_rails=_mixed_rails, get_pulses=lambda: ["PSEQ"])
        try:
            # vector V 只出現一筆 base；scalar A 照舊；末端 High/Low
            assert ed._dep_options() == ["A", "V", "High", "Low"]
        finally:
            ed.destroy()

    def test_dep_vector_width(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _scalar_output(),
                             get_all_rails=_mixed_rails, get_pulses=lambda: ["PSEQ"])
        try:
            assert ed._dep_vector_width("V") == 2
            assert ed._dep_vector_width("A") is None
            assert ed._dep_vector_width("High") is None
            assert ed._dep_vector_width("Low") is None
        finally:
            ed.destroy()

    def test_expand_dep_modes(self, ctk_root):
        from gui.widgets import (
            VEC_MODE_ALL,
            VEC_MODE_ANY,
            VEC_MODE_PICK,
            VEC_MODE_SAME,
            RailEditorFrame,
        )

        # owner 也是 2-bit vector；active bit 設為 1
        ed = RailEditorFrame(ctk_root, _vector_output(2),
                             get_all_rails=_mixed_rails, get_pulses=lambda: ["PSEQ"])
        try:
            ed._on_bit_selected("1")
            # legacy 向量（無 dim_params）續走逐 bit，take 恆為 None（第三元素）
            # 同索引 → 用 active bit（1）
            assert ed._expand_dep("V", VEC_MODE_SAME, 0) == (["V[1]"], None, None)
            # 全部/任一 → 全 bit + group_op
            assert ed._expand_dep("V", VEC_MODE_ALL, 0) == (["V[0]", "V[1]"], "and", None)
            assert ed._expand_dep("V", VEC_MODE_ANY, 0) == (["V[0]", "V[1]"], "or", None)
            # 指定 → base[k]
            assert ed._expand_dep("V", VEC_MODE_PICK, 0) == (["V[0]"], None, None)
            assert ed._expand_dep("V", VEC_MODE_PICK, 1) == (["V[1]"], None, None)
            # scalar / High / Low 原樣
            assert ed._expand_dep("A", VEC_MODE_PICK, 0) == (["A"], None, None)
            assert ed._expand_dep("High", VEC_MODE_SAME, 0) == (["High"], None, None)
        finally:
            ed.destroy()

    def test_add_vector_dep_via_combo_all_and(self, ctk_root):
        """接線：在條件分頁選 vector base + 全部(AND) 按 Add → 具體名 + group op。"""
        from gui.widgets import COND_TAB, VEC_MODE_ALL, RailEditorFrame

        # owner 用乾淨（空條件）的 2-bit vector，使群組內容斷言明確
        owner = VectorNode("W", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        ed = RailEditorFrame(ctk_root, owner,
                             get_all_rails=_mixed_rails, get_pulses=lambda: ["PSEQ"])
        try:
            ed._on_mode_seg(COND_TAB)
            sec = ed._cond_editor["sections"]["hi"]
            grp = sec._cond_section if hasattr(sec, "_cond_section") else sec
            gf = grp.group_frames[0]
            gf["combo"].set("V")
            grp._set_vec_mode(0, VEC_MODE_ALL)
            grp._add_cond_to_group(0)
            model = grp.model
            assert model.groups[0] == ["V[0]", "V[1]"]
            assert model.group_intra_op[0] == "and"
        finally:
            ed.destroy()


class TestVectorMultiBitLiveEdit:
    """同時設定多個 bit：複選框 + 即時共編（乙 + 自動同索引替換）。"""

    def _vec_WV(self):
        """get_all_rails：V(2 bit) + W(2 bit) + scalar A，供 reindex 判斷 vector base。"""
        v = VectorNode("V", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        w = VectorNode("W", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        return [*_scalar_output(), *v, *w]

    def test_reindex_name(self, ctk_root):
        from gui.widgets import RailEditorFrame

        ed = RailEditorFrame(ctk_root, _vector_output(2),
                             get_all_rails=self._vec_WV, get_pulses=lambda: ["PSEQ"])
        try:
            assert ed._reindex_name("V[0]", 0, 1) == "V[1]"   # 同索引 vector → 替換
            assert ed._reindex_name("W[1]", 0, 1) == "W[1]"   # 固定索引 ≠ src → 不變
            assert ed._reindex_name("A", 0, 1) == "A"          # scalar → 不變
            assert ed._reindex_name("High", 0, 1) == "High"    # 常數 → 不變
            assert ed._reindex_name("X[0]", 0, 1) == "X[0]"    # 非 vector base → 不變
        finally:
            ed.destroy()

    def test_copy_cond_reindexed(self, ctk_root):
        from gui.widgets import RailEditorFrame

        owner = VectorNode("Q", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        ed = RailEditorFrame(ctk_root, owner,
                             get_all_rails=self._vec_WV, get_pulses=lambda: ["PSEQ"])
        try:
            src, dst = ed._bit_rails[0], ed._bit_rails[1]
            src.depends_on_hi_groups = [["V[0]", "W[1]"]]
            src.depends_on_hi_inv_groups = [[True, False]]
            ed._copy_cond_reindexed(src, dst, 0, 1)
            assert dst.depends_on_hi_groups == [["V[1]", "W[1]"]]   # 同索引 V 替換、固定 W 不變
            assert dst.depends_on_hi_inv_groups == [[True, False]]  # 位置性欄位原樣
        finally:
            ed.destroy()

    def test_broadcast_to_linked(self, ctk_root):
        from gui.widgets import RailEditorFrame

        v3 = VectorNode("V", "output", "3", [ConditionConfig() for _ in range(3)]).elaborate()
        owner = VectorNode("Q", "output", "3", [ConditionConfig() for _ in range(3)]).elaborate()
        ed = RailEditorFrame(ctk_root, owner,
                             get_all_rails=lambda: v3, get_pulses=lambda: ["PSEQ"])
        try:
            ed._active_bit = 0
            ed._bit_rails[0].depends_on_hi_groups = [["V[0]"]]
            for var in ed._bit_link_vars:  # 勾選全部
                var.set(True)
            ed._broadcast_to_linked()
            assert ed._bit_rails[1].depends_on_hi_groups == [["V[1]"]]
            assert ed._bit_rails[2].depends_on_hi_groups == [["V[2]"]]
            # 取消勾選 bit2 後，再廣播只影響 bit1
            ed._bit_rails[0].depends_on_hi_groups = [["V[0]", "V[0]"]]
            ed._bit_link_vars[2].set(False)
            ed._broadcast_to_linked()
            assert ed._bit_rails[1].depends_on_hi_groups == [["V[1]", "V[1]"]]
            assert ed._bit_rails[2].depends_on_hi_groups == [["V[2]"]]  # 未動
        finally:
            ed.destroy()

    def test_bit_checkbox_shift_range(self, ctk_root):
        from gui.widgets import RailEditorFrame

        v4 = VectorNode("V", "output", "4", [ConditionConfig() for _ in range(4)]).elaborate()
        ed = RailEditorFrame(ctk_root, v4,
                             get_all_rails=lambda: v4, get_pulses=lambda: ["PSEQ"])

        class _E:
            def __init__(self, state):
                self.state = state

        try:
            # 先把預設勾選清掉，確保從已知狀態開始
            for var in ed._bit_link_vars:
                var.set(False)
            ed._anchor_idx = None
            ed._on_bit_checkbox_click(1, _E(0))   # 正常點擊 bit1 → anchor=1, 勾選 1
            assert ed._anchor_idx == 1
            assert ed._active_bit == 1
            assert [v.get() for v in ed._bit_link_vars] == [False, True, False, False]
            ed._on_bit_checkbox_click(3, _E(1))   # Shift+click bit3 → 區間 1..3 設為 True
            assert [v.get() for v in ed._bit_link_vars] == [False, True, True, True]
            assert ed._active_bit == 3
            assert ed._anchor_idx == 1             # anchor 不被 Shift 更新
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
    def _panel(self, ctk_root, params=None):
        from gui.panels import NodeListPanel

        def noop(*_a, **_k):
            return None

        return NodeListPanel(ctk_root, on_select=noop, on_reorder=noop,
                             on_multi_change=noop, on_add=noop, on_delete_btn=noop,
                             on_delete=noop, on_activate=noop, on_disarm=noop,
                             get_parameters=lambda: (params or []))

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

    def test_two_dim_node_shows_row_col(self, ctk_root):
        from core.config_edit import group_rails_into_nodes, set_group_metadata

        params = [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 4)]
        panel = self._panel(ctk_root, params)
        try:
            rails = [PowerRail(f"V[{i}]", seq_type="output") for i in range(8)]
            set_group_metadata(rails, "V", "NUM_CPU*NUM_CPU_MEM", ["NUM_CPU", "NUM_CPU_MEM"])
            panel.set_nodes(group_rails_into_nodes(rails), primary_idx=0)
            assert panel.node_labels() == ["V [2×4]"]
        finally:
            panel.destroy()
