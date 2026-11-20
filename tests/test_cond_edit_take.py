"""階段D-B4（model 層）：CondEditModel 承載每項 take，round-trip 與結構操作。

take 與 inv/use 平行（per-group per-item），每項為 take dict 或 None。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.cond_edit import CondEditModel
from core.config_models import PowerRail

_TAKE = {"row": {"kind": "same"}, "col": {"kind": "all", "op": "or"}}


class TestTakeModel:
    def test_from_rail_loads_take(self):
        rail = PowerRail(
            "SIG2[0]", "output", group_base="SIG2", bit_index=0, dim_params=["NUM_CPU"],
            depends_on_hi_groups=[["SIG4[0]"]],
            depends_on_hi_use_groups=[["hi"]],
            depends_on_hi_take_groups=[[_TAKE]],
        )
        m = CondEditModel.from_rail(rail, "hi")
        assert m.to_take_groups() == [[_TAKE]]

    def test_add_dep_with_take(self):
        m = CondEditModel()
        m.add_dep(0, "SIG4[0]", take=_TAKE)
        assert m.to_take_groups() == [[_TAKE]]

    def test_normalize_fills_take_none(self):
        m = CondEditModel(groups=[["A", "B"]])
        assert m.to_take_groups() == [[None, None]]

    def test_remove_dep_keeps_take_aligned(self):
        m = CondEditModel()
        m.add_dep(0, "A")
        m.add_dep(0, "SIG4[0]", take=_TAKE)
        m.remove_dep(0, 0)
        assert m.to_take_groups() == [[_TAKE]]

    def test_reorder_dep_keeps_take_aligned(self):
        m = CondEditModel()
        m.add_dep(0, "A")
        m.add_dep(0, "SIG4[0]", take=_TAKE)
        m.reorder_dep(0, 1, 0)
        assert m.to_take_groups() == [[_TAKE, None]]
