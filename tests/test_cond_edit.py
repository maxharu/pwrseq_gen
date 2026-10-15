"""CondEditModel：條件編輯器的結構操作。

這些是從 `gui/widgets.py` 的 `CondSectionFrame` 抽出來的索引算術。原本它散在八支函式、
約 210 行，每支都要把九個平行集合（含 Tk 變數與 widget）一起重新索引，而且因為與 widget
銷毀綁在一起，headless 下一行都測不到。

重點不是個別操作會不會動，而是**每個依賴項的 inv / use 在結構變動後有沒有跟著它走**
——那正是 off-by-one 會出現的地方。
"""
import itertools
import json
import os

import pytest

from core.cond_edit import CondEditModel
from core.cond_ir import resolve_condition
from core.config_models import PowerRail, PowerSeqConfig

# 用可辨識的值，讓「跟著走」與「留在原位」一眼可分
BASE = dict(
    groups=[["A", "B", "C"], ["D", "E"], ["F"]],
    inv=[[True, False, True], [False, True], [True]],
    use=[["hi", "self", "lo"], ["force", "hi"], ["self"]],
    group_inv=[True, False, True],
    group_intra_op=["and", "or", "xor"],
)


def model() -> CondEditModel:
    return CondEditModel(**{k: [list(x) if isinstance(x, list) else x for x in v]
                            for k, v in BASE.items()})


def paired(m: CondEditModel) -> list[list[tuple[str, bool, str]]]:
    """把每個 group 壓成 (name, inv, use) 三元組，方便直接比對『有沒有跟著走』。"""
    return [list(zip(g, m.inv[gi], m.use[gi])) for gi, g in enumerate(m.groups)]


def assert_shape(m: CondEditModel) -> None:
    n = len(m.groups)
    assert n >= 1, "至少要留一個 group"
    assert len(m.inv) == n and len(m.use) == n
    assert len(m.group_inv) == n and len(m.group_intra_op) == n
    for gi, g in enumerate(m.groups):
        assert len(m.inv[gi]) == len(g), f"group {gi} 的 inv 長度對不上"
        assert len(m.use[gi]) == len(g), f"group {gi} 的 use 長度對不上"


class TestShapeInvariant:
    def test_normalize_pads_missing_parallel_data(self):
        m = CondEditModel(groups=[["A", "B"], ["C"]])
        assert_shape(m)
        assert m.inv == [[False, False], [False]]
        assert m.use == [["self", "self"], ["self"]]
        assert m.group_inv == [False, False]
        assert m.group_intra_op == ["and", "and"]

    def test_normalize_truncates_overlong_parallel_data(self):
        m = CondEditModel(
            groups=[["A"]],
            inv=[[True, True, True]],
            group_inv=[True, False, True],
            group_intra_op=["or", "and"],
        )
        assert_shape(m)
        assert m.inv == [[True]]
        assert m.group_inv == [True]
        assert m.group_intra_op == ["or"]

    def test_empty_groups_becomes_one_empty_group(self):
        assert CondEditModel(groups=[]).groups == [[]]

    def test_unknown_intra_op_is_normalized(self):
        assert CondEditModel(groups=[["A"]], group_intra_op=["NOPE"]).group_intra_op == ["and"]


class TestReorderGroups:
    def test_all_parallel_data_follows_the_group(self):
        m = model()
        before = paired(m)
        assert m.reorder_groups(0, 2)
        assert paired(m) == [before[1], before[2], before[0]]
        assert m.group_inv == [False, True, True]
        assert m.group_intra_op == ["or", "xor", "and"]

    def test_moving_backwards(self):
        m = model()
        before = paired(m)
        assert m.reorder_groups(2, 0)
        assert paired(m) == [before[2], before[0], before[1]]
        assert m.group_intra_op == ["xor", "and", "or"]

    @pytest.mark.parametrize("a,b", [(0, 0), (-1, 1), (0, 9), (9, 0)])
    def test_no_op_and_out_of_range_are_rejected(self, a, b):
        m = model()
        before = paired(m)
        assert m.reorder_groups(a, b) is False
        assert paired(m) == before


class TestReorderDep:
    def test_inv_and_use_follow_the_dependency(self):
        m = model()
        assert m.reorder_dep(0, 0, 2)
        assert paired(m)[0] == [("B", False, "self"), ("C", True, "lo"), ("A", True, "hi")]

    def test_other_groups_are_untouched(self):
        m = model()
        before = paired(m)
        m.reorder_dep(0, 0, 2)
        assert paired(m)[1:] == before[1:]

    @pytest.mark.parametrize("gi,a,b", [(0, 0, 0), (0, 0, 5), (9, 0, 1)])
    def test_no_op_and_out_of_range_are_rejected(self, gi, a, b):
        m = model()
        before = paired(m)
        assert m.reorder_dep(gi, a, b) is False
        assert paired(m) == before


class TestRemove:
    def test_removing_a_dep_keeps_the_rest_aligned(self):
        m = model()
        assert m.remove_dep(0, 1)
        assert paired(m)[0] == [("A", True, "hi"), ("C", True, "lo")]
        assert_shape(m)

    def test_removing_a_group_keeps_the_rest_aligned(self):
        m = model()
        before = paired(m)
        assert m.remove_group(1)
        assert paired(m) == [before[0], before[2]]
        assert m.group_inv == [True, True]
        assert m.group_intra_op == ["and", "xor"]

    def test_removing_the_last_group_resets_to_one_empty_group(self):
        m = CondEditModel(groups=[["A"]], inv=[[True]], use=[["hi"]],
                          group_inv=[True], group_intra_op=["or"])
        assert m.remove_group(0)
        assert m.groups == [[]]
        assert m.group_inv == [False] and m.group_intra_op == ["and"]
        assert_shape(m)

    @pytest.mark.parametrize("gi,ii", [(0, 9), (9, 0), (0, -1)])
    def test_out_of_range_dep_removal_is_rejected(self, gi, ii):
        m = model()
        before = paired(m)
        assert m.remove_dep(gi, ii) is False
        assert paired(m) == before


class TestAdd:
    def test_added_group_is_empty_and_aligned(self):
        m = model()
        m.add_group()
        assert m.groups[-1] == []
        assert m.group_inv[-1] is False
        assert m.group_intra_op[-1] == "and"
        assert_shape(m)

    def test_added_dep_carries_its_inv_and_use(self):
        m = model()
        assert m.add_dep(1, "Z", inv=True, use="force")
        assert paired(m)[1][-1] == ("Z", True, "force")

    @pytest.mark.parametrize("name", ["__HIGH__", "__LOW__"])
    def test_constant_dep_never_carries_inv(self, name):
        """常數節點沒有準位可反相——原 widget 也不畫 Inv 核取方塊。"""
        m = model()
        m.add_dep(0, name, inv=True)
        assert paired(m)[0][-1] == (name, False, "self")

    def test_adding_to_a_missing_group_is_rejected(self):
        m = model()
        assert m.add_dep(9, "Z") is False


class TestFromInitial:
    @pytest.mark.parametrize("name", ["__HIGH__", "__LOW__"])
    def test_constant_dep_loses_inv_even_if_the_config_sets_it(self, name):
        """常數節點沒有準位可反相；舊設定檔若帶了 inv=True 也要忽略。"""
        from_groups = CondEditModel.from_initial(
            groups=[[name]], inv_groups=[[True]])
        from_flat = CondEditModel.from_initial(
            groups=[[name]], inv_flat={name: True})
        assert from_groups.inv == [[False]]
        assert from_flat.inv == [[False]]

    def test_groups_variant_wins_over_the_flat_dict(self):
        m = CondEditModel.from_initial(
            groups=[["A"]], inv_groups=[[False]], inv_flat={"A": True})
        assert m.inv == [[False]]

    def test_flat_dict_is_the_fallback_when_groups_run_short(self):
        """`inv_groups` 比 groups 短時，缺的那幾項退回以名稱查扁平版。"""
        m = CondEditModel.from_initial(
            groups=[["A", "B"]], inv_groups=[[True]], inv_flat={"B": True})
        assert m.inv == [[True, True]]

    def test_missing_everything_defaults_to_false_and_self(self):
        m = CondEditModel.from_initial(groups=[["A"]])
        assert m.inv == [[False]] and m.use == [["self"]]


class TestOperationSequences:
    """任意操作序列之後，形狀不變量仍必須成立。

    單一操作各自正確不代表組合起來正確——實際的 bug 都是「刪了第 2 組之後再拖第 3 列」
    這種組合。
    """

    OPS = [
        ("add_group", lambda m: m.add_group()),
        ("remove_group_0", lambda m: m.remove_group(0)),
        ("remove_group_1", lambda m: m.remove_group(1)),
        ("add_dep", lambda m: m.add_dep(0, "Z", inv=True, use="hi")),
        ("remove_dep", lambda m: m.remove_dep(0, 0)),
        ("reorder_dep", lambda m: m.reorder_dep(0, 0, 1)),
        ("reorder_groups", lambda m: m.reorder_groups(0, 1)),
    ]

    @pytest.mark.parametrize(
        "combo", list(itertools.product(range(len(OPS)), repeat=3)),
        ids=lambda c: "-".join(str(i) for i in c) if isinstance(c, tuple) else str(c),
    )
    def test_shape_holds_after_any_three_operations(self, combo):
        m = model()
        for i in combo:
            self.OPS[i][1](m)
            assert_shape(m)

    def test_getters_stay_consistent_with_each_other(self):
        """to_* 系列都跳過空 group，所以彼此長度必須一致。"""
        m = model()
        m.add_group()
        m.remove_dep(2, 0)
        groups = m.to_groups()
        assert all(g for g in groups), "空 group 不該出現在輸出裡"
        assert len(m.to_inv_groups()) == len(groups)
        assert len(m.to_use_groups()) == len(groups)
        assert len(m.to_group_inv()) == len(groups)
        assert len(m.to_group_intra_op()) == len(groups)
        for gi, g in enumerate(groups):
            assert len(m.to_inv_groups()[gi]) == len(g)
            assert len(m.to_use_groups()[gi]) == len(g)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _demo_config() -> PowerSeqConfig:
    with open(os.path.join(ROOT, "templates", "demo_json.json"), encoding="utf-8") as f:
        return PowerSeqConfig.from_dict(json.load(f))


def _rail_from_model(rail: PowerRail, kind: str, m: CondEditModel) -> PowerRail:
    """只把某個 kind 的條件欄位換成模型的輸出，其餘沿用原 rail。"""
    clone = PowerRail(**{k: v for k, v in vars(rail).items()})
    setattr(clone, f"depends_on_{kind}", m.to_flat_deps())
    setattr(clone, f"depends_on_{kind}_groups", m.to_groups())
    setattr(clone, f"depends_on_{kind}_inv_groups", m.to_inv_groups())
    setattr(clone, f"depends_on_{kind}_use_groups", m.to_use_groups())
    setattr(clone, f"depends_on_{kind}_group_inv", m.to_group_inv())
    setattr(clone, f"depends_on_{kind}_intra_op", m.to_group_intra_op())
    setattr(clone, f"depends_on_{kind}_inv", m.to_inv_flat())
    setattr(clone, f"depends_on_{kind}_use", m.to_use_flat())
    return clone


OUTPUTS = [r.name for r in _demo_config().rails if r.seq_type == "output"]


class TestRailRoundTrip:
    """`from_rail` → 模型 → 寫回，解析出來的條件樹必須完全相同。

    比逐欄位比對更有力：條件樹正是五個後端實際消費的東西，樹一樣就代表
    Verilog / C / 模擬器 / Draw.io / Schemdraw 的輸出都不會變。
    """

    @pytest.mark.parametrize("rail_name", OUTPUTS)
    @pytest.mark.parametrize("kind", ["hi", "lo", "force"])
    def test_condition_tree_survives_the_round_trip(self, rail_name, kind):
        cfg = _demo_config()
        n2r = {r.name: r for r in cfg.rails}
        rail = n2r[rail_name]
        rebuilt = _rail_from_model(rail, kind, CondEditModel.from_rail(rail, kind))
        n2r_new = dict(n2r, **{rail_name: rebuilt})
        assert resolve_condition(rebuilt, kind, n2r_new) == resolve_condition(rail, kind, n2r)

    @pytest.mark.parametrize("kind", ["hi", "lo", "force"])
    def test_loaded_shape_is_always_valid(self, kind):
        for rail in _demo_config().rails:
            assert_shape(CondEditModel.from_rail(rail, kind))

    def test_use_is_read_from_the_groups_variant_not_only_the_flat_dict(self):
        """demo 的 `use=force` 只存在 `*_use_groups` 裡，扁平 dict 是空的。

        先前一支探針就是只查了扁平 dict，誤判成「沒有任何 use=force」。
        """
        rail = {r.name: r for r in _demo_config().rails}["PVCCDD2_EN"]
        assert not rail.depends_on_force_use, "前提變了：扁平 dict 不再是空的"
        assert "force" in CondEditModel.from_rail(rail, "force").use[0]
