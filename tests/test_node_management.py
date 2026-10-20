"""B6 步驟 1：節點↔rail 管理的 core 純函式（不依 Tk）。

GUI 以「節點」為單位操作（vector 一張卡片、左側一列）；config.rails 卻是扁平的 bit。
這層把兩者的 index 換算、整節點搬移/刪除、群組 metadata 蓋章、card↔config 收合/展開
集中到 core，讓 Tk 只負責畫面、正確性由這裡的模型層測試保證。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_edit import (
    delete_nodes,
    flatten_node_rails,
    group_rails_into_nodes,
    move_node,
    node_index_to_rail_span,
    node_spans,
    rail_index_to_node_index,
    resize_list,
    set_group_metadata,
)
from core.config_models import ConditionConfig, PowerRail, PowerSeqConfig, VectorNode


def _mixed_rails() -> list[PowerRail]:
    """A(scalar) / V[0..1](vector) / B(scalar) / W[0..2](vector)。"""
    a = PowerRail("A", seq_type="output", depends_on_hi=["__HIGH__"])
    v = VectorNode("V", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
    b = PowerRail("B", seq_type="input", deb_enable=False)
    w = VectorNode("W", "output", "3", [ConditionConfig()] * 3).elaborate()
    return [a, *v, b, *w]


class TestNodeSpansAndMapping:
    def test_node_spans(self):
        assert node_spans(_mixed_rails()) == [(0, 1), (1, 2), (3, 1), (4, 3)]

    def test_rail_index_to_node_index(self):
        rails = _mixed_rails()
        got = [rail_index_to_node_index(rails, i) for i in range(len(rails))]
        assert got == [0, 1, 1, 2, 3, 3, 3]
        assert rail_index_to_node_index(rails, 99) is None

    def test_node_index_to_rail_span(self):
        rails = _mixed_rails()
        assert node_index_to_rail_span(rails, 0) == (0, 1)
        assert node_index_to_rail_span(rails, 1) == (1, 2)
        assert node_index_to_rail_span(rails, 3) == (4, 3)
        assert node_index_to_rail_span(rails, 9) is None


class TestMoveNode:
    def test_move_vector_to_front(self):
        rails = _mixed_rails()
        assert move_node(rails, 1, 0) is True
        assert [r.name for r in rails] == ["V[0]", "V[1]", "A", "B", "W[0]", "W[1]", "W[2]"]

    def test_move_last_vector_to_front(self):
        rails = _mixed_rails()
        assert move_node(rails, 3, 0) is True
        assert [r.name for r in rails] == ["W[0]", "W[1]", "W[2]", "A", "V[0]", "V[1]", "B"]

    def test_noop_and_out_of_range(self):
        rails = _mixed_rails()
        assert move_node(rails, 1, 1) is False
        assert move_node(rails, 9, 0) is False
        assert [r.name for r in rails] == ["A", "V[0]", "V[1]", "B", "W[0]", "W[1]", "W[2]"]

    def test_matches_actual_node_list_move(self):
        """以「真的搬 node 清單再攤平」當 oracle，避免測試抄一遍實作。"""
        rails = _mixed_rails()
        n = len(node_spans(rails))
        for frm in range(n):
            for to in range(n):
                if frm == to:
                    continue
                work = _mixed_rails()
                nodes = group_rails_into_nodes(work)
                block = nodes.pop(frm)
                nodes.insert(to, block)
                expected = [r.name for node in nodes for r in node]
                move_node(work, frm, to)
                assert [r.name for r in work] == expected, f"{frm}->{to}"


class TestDeleteNodes:
    def test_delete_vectors(self):
        rails = _mixed_rails()
        removed = delete_nodes(rails, {1, 3})
        assert removed == [3, 1]  # 由大到小
        assert [r.name for r in rails] == ["A", "B"]

    def test_delete_scalar_keeps_vector_intact(self):
        rails = _mixed_rails()
        delete_nodes(rails, {0})
        assert [r.name for r in rails] == ["V[0]", "V[1]", "B", "W[0]", "W[1]", "W[2]"]

    def test_out_of_range_ignored(self):
        rails = _mixed_rails()
        assert delete_nodes(rails, {9, -1}) == []
        assert len(rails) == 7


class TestSetGroupMetadata:
    def test_stamp_vector(self):
        bits = [PowerRail("V[0]", seq_type="output"), PowerRail("V[1]", seq_type="output")]
        set_group_metadata(bits, "V", "2")
        assert [b.group_base for b in bits] == ["V", "V"]
        assert [b.bit_index for b in bits] == [0, 1]
        assert all(b.width_expr == "2" for b in bits)

    def test_clear_to_scalar(self):
        bits = [PowerRail("X", seq_type="output", group_base="V", bit_index=3, width_expr="4")]
        set_group_metadata(bits, None, "1")
        assert bits[0].group_base is None
        assert bits[0].bit_index == 0
        assert bits[0].width_expr == "1"


class TestResizeList:
    def test_grow_preserves_existing(self):
        items = ["a", "b"]
        out = resize_list(items, 4, lambda i: f"new{i}")
        assert out == ["a", "b", "new2", "new3"]

    def test_shrink_truncates(self):
        assert resize_list(["a", "b", "c"], 1, lambda i: "x") == ["a"]

    def test_same_length_unchanged(self):
        assert resize_list(["a", "b"], 2, lambda i: "x") == ["a", "b"]


class TestFlattenNodeRails:
    def test_flatten_round_trips_with_grouping(self):
        rails = _mixed_rails()
        nodes = group_rails_into_nodes(rails)
        assert [r.name for r in flatten_node_rails(nodes)] == [r.name for r in rails]


class TestVectorGroupReferenceIntegrity:
    """整組 rename/delete 後，其它節點的條件引用保持一致（接 A4）。"""

    def _cfg(self) -> PowerSeqConfig:
        v = VectorNode("V", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        bar = PowerRail("BAR", seq_type="output", depends_on_hi_groups=[["V[0]"], ["V[1]"]])
        return PowerSeqConfig(rails=[*v, bar])

    def test_rename_group_updates_refs(self):
        cfg = self._cfg()
        assert cfg.rename_group("V", "Q") is True
        bar = next(r for r in cfg.rails if r.name == "BAR")
        assert bar.depends_on_hi_groups == [["Q[0]"], ["Q[1]"]]

    def test_delete_group_leaves_other_nodes(self):
        cfg = self._cfg()
        assert cfg.delete_group("V") == 2
        assert [r.name for r in cfg.rails] == ["BAR"]
