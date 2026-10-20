"""A4 群組批次操作測試。

rename/delete/move 整組作用，且 rename 後條件樹對 bit 的引用必須全數更新——
刻意把 hi/lo/force 的 groups、inv、use 與 input-wave groups、legacy depends_on
都放進斷言：實作若漏更新任何一個容器（退化），這裡就轉紅。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_edit import group_span, move_group
from core.config_models import PowerRail, PowerSeqConfig, VectorNode


def _config_with_group() -> PowerSeqConfig:
    vn = VectorNode(base="VOUT", seq_type="output", width_expr="2")
    rails = [
        PowerRail(
            "BAR",
            seq_type="output",
            depends_on_hi_groups=[["VOUT[0]"]],
            depends_on_hi_inv={"VOUT[0]": True},
            depends_on_hi_use={"VOUT[0]": "lo"},
            depends_on_lo_groups=[["VOUT[1]"]],
            depends_on_force_groups=[["VOUT[0]"]],
            depends_on=["VOUT[0]"],
            depends_on_hi=["VOUT[0]"],
        ),
        PowerRail(
            "IN",
            seq_type="input",
            hi_groups=[["VOUT[0]"]],
        ),
    ]
    rails = vn.elaborate() + rails
    return PowerSeqConfig(rails=rails)


class TestRenameGroup:
    def test_renames_all_bits_and_metadata(self):
        cfg = _config_with_group()
        assert cfg.rename_group("VOUT", "QUX") is True
        qux = [r for r in cfg.rails if r.group_base == "QUX"]
        assert [r.name for r in qux] == ["QUX[0]", "QUX[1]"]
        assert [r.name for r in cfg.rails if r.group_base == "VOUT"] == []

    def test_updates_all_reference_containers(self):
        cfg = _config_with_group()
        cfg.rename_group("VOUT", "QUX")
        bar = next(r for r in cfg.rails if r.name == "BAR")
        assert bar.depends_on_hi_groups == [["QUX[0]"]]
        assert bar.depends_on_lo_groups == [["QUX[1]"]]
        assert bar.depends_on_force_groups == [["QUX[0]"]]
        assert bar.depends_on_hi_inv == {"QUX[0]": True}
        assert bar.depends_on_hi_use == {"QUX[0]": "lo"}
        assert bar.depends_on == ["QUX[0]"]
        assert bar.depends_on_hi == ["QUX[0]"]
        in_node = next(r for r in cfg.rails if r.name == "IN")
        assert in_node.hi_groups == [["QUX[0]"]]

    def test_noop_when_base_missing_or_same(self):
        cfg = _config_with_group()
        assert cfg.rename_group("NOPE", "X") is False
        assert cfg.rename_group("VOUT", "VOUT") is False


class TestDeleteGroup:
    def test_removes_all_bits(self):
        cfg = _config_with_group()
        assert cfg.delete_group("VOUT") == 2
        assert [r.name for r in cfg.rails] == ["BAR", "IN"]
        assert cfg.delete_group("VOUT") == 0


class TestMoveGroup:
    def test_group_span_contiguous(self):
        cfg = _config_with_group()
        # VOUT[0], VOUT[1] 在最前
        assert group_span(cfg.rails, "VOUT") == (0, 2)
        assert group_span(cfg.rails, "NOPE") is None

    def test_move_group_block(self):
        items = ["a", "b", "c", "d"]
        assert move_group(items, 1, 2, 0) is True  # 把 [b,c] 移到最前
        assert items == ["b", "c", "a", "d"]

    def test_move_group_on_config(self):
        cfg = _config_with_group()
        # 原序: VOUT[0], VOUT[1], BAR, IN；把 VOUT 群組移到 index 1
        assert cfg.move_group("VOUT", 1) is True
        assert [r.name for r in cfg.rails] == ["BAR", "VOUT[0]", "VOUT[1]", "IN"]
