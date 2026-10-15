"""core.cond_ir：條件樹的形狀與葉節點語意。

這裡的期望值是照文件（F-DEP-06/07/08、timing-sim-behavior.mdc §2）手寫的，
不從 cond_ir 推導——`test_condition_consistency.py` 拿 cond_ir 當 oracle 檢查各下游，
所以 cond_ir 本身必須有一份獨立的對照。
"""
import pytest

from core.cond_ir import (
    AnyGroup,
    Const,
    Cond,
    CondVisitor,
    Group,
    Level,
    Not,
    resolve_condition,
    resolve_dep,
)
from core.config_models import PowerRail
from core.constants import DEP_HIGH, DEP_LOW

RAILS = {
    "IN": PowerRail(name="IN", seq_type="input"),
    "OUT": PowerRail(name="OUT", seq_type="output"),
}


# ---- 葉節點 ------------------------------------------------------------

@pytest.mark.parametrize("use", ["self", "hi", "lo", "force"])
def test_constants_ignore_use(use):
    assert resolve_dep(DEP_HIGH, use, RAILS) == Const(1)
    assert resolve_dep(DEP_LOW, use, RAILS) == Const(0)


@pytest.mark.parametrize("use", ["self", "hi", "lo", "force"])
def test_input_is_always_a_level(use):
    """input 沒有 PSEQCELL，殘留的 use=hi/lo/force 要退化為讀準位。"""
    assert resolve_dep("IN", use, RAILS) == Level("IN")


def test_unknown_dep_is_a_level():
    """名稱不在 config 裡（外部訊號）時當 input 處理。"""
    assert resolve_dep("NOBODY", "hi", RAILS) == Level("NOBODY")


def test_output_self_is_a_level():
    assert resolve_dep("OUT", "self", RAILS) == Level("OUT")


@pytest.mark.parametrize("use", ["hi", "lo", "force"])
def test_output_with_use_is_a_condition_signal(use):
    assert resolve_dep("OUT", use, RAILS) == Cond("OUT", use)


# ---- 樹的組裝 ----------------------------------------------------------

@pytest.mark.parametrize("kind,value", [("hi", 1), ("lo", 0), ("force", 0)])
def test_no_group_falls_back_to_constant(kind, value):
    assert resolve_condition(PowerRail(name="R"), kind, RAILS) == Const(value)


def test_empty_group_stays_an_empty_group():
    """空 group 由渲染端決定（三個下游都算成 0），IR 不代為摺疊。"""
    rail = PowerRail(name="R", depends_on_hi_groups=[[]])
    assert resolve_condition(rail, "hi", RAILS) == AnyGroup((Group("and", ()),))


def test_groups_are_or_joined_and_items_use_intra_op():
    rail = PowerRail(
        name="R",
        depends_on_hi_groups=[["IN", "OUT"], ["OUT"]],
        depends_on_hi_use_groups=[["self", "hi"], ["lo"]],
        depends_on_hi_intra_op=["xor", "or"],
    )
    assert resolve_condition(rail, "hi", RAILS) == AnyGroup((
        Group("xor", (Level("IN"), Cond("OUT", "hi"))),
        Group("or", (Cond("OUT", "lo"),)),
    ))


def test_item_inv_and_group_inv_are_separate_nots():
    rail = PowerRail(
        name="R",
        depends_on_lo_groups=[["IN", "OUT"]],
        depends_on_lo_inv_groups=[[True, False]],
        depends_on_lo_group_inv=[True],
    )
    assert resolve_condition(rail, "lo", RAILS) == AnyGroup((
        Not(Group("and", (Not(Level("IN")), Level("OUT")))),
    ))


def test_legacy_flat_depends_on_is_read_through_the_same_path():
    """舊格式沒有 *_groups，inv/use 存在 dict 裡。"""
    rail = PowerRail(
        name="R",
        depends_on_force=["OUT"],
        depends_on_force_inv={"OUT": True},
        depends_on_force_use={"OUT": "hi"},
    )
    assert resolve_condition(rail, "force", RAILS) == AnyGroup((
        Group("and", (Not(Cond("OUT", "hi")),)),
    ))


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        resolve_condition(PowerRail(name="R"), "deb", RAILS)


# ---- visitor -----------------------------------------------------------

class _Renderer(CondVisitor):
    def const(self, value):
        return str(value)

    def level(self, name):
        return name

    def cond(self, name, kind):
        return f"{name}.{kind}"

    def invert(self, operand):
        return f"!{operand}"

    def group(self, op, items):
        return "(" + f" {op} ".join(items) + ")"

    def any_group(self, groups):
        return " | ".join(groups)


def test_accept_folds_children_before_the_visitor_sees_them():
    rail = PowerRail(
        name="R",
        depends_on_hi_groups=[["IN", DEP_LOW], ["OUT"]],
        depends_on_hi_use_groups=[["self", "self"], ["lo"]],
        depends_on_hi_inv_groups=[[True, False], [False]],
        depends_on_hi_group_inv=[False, True],
    )
    tree = resolve_condition(rail, "hi", RAILS)
    assert tree.accept(_Renderer()) == "(!IN and 0) | !(OUT.lo)"


def test_visitor_missing_a_node_type_cannot_be_instantiated():
    """新增節點型別時，沒跟上的下游要在建構當下就壞掉，而不是默默漏掉語意。"""

    class Partial(CondVisitor):
        def const(self, value):
            return ""

        def level(self, name):
            return ""

        def cond(self, name, kind):
            return ""

        def invert(self, operand):
            return ""

        def group(self, op, items):
            return ""

        # any_group 故意不實作

    with pytest.raises(TypeError):
        Partial()
