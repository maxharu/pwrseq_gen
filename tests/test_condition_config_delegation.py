"""退化測試：PowerRail 對 ConditionConfig 的委派不可漏接。

A1 把條件欄位（depends_on_{hi,lo,force}_* 與其 get_* 存取器）抽到
`ConditionConfig`，PowerRail 改用 @property / 方法委派。若某個條件欄位或存取器
忘了委派（property/method 沒接到 cond），這裡的斷言就會轉紅——這正是本測試存在的理由：
它替「下游呼叫端零改動」把關，而不是等五個後端的 golden 才發現。

本檔的欄位清單刻意**獨立硬寫**（不 import config_models 的內部清單），這樣即使實作端
的委派迴圈漏了一項，這份 oracle 仍會抓到。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest

from core.config_models import ConditionConfig, PowerRail

# 每個條件欄位配一個「與預設不同」的樣本值，型別對齊 ConditionConfig 的宣告。
COND_FIELD_SAMPLES = {
    "depends_on": ["ZDEP"],
    "depends_on_hi": ["ZHI"],
    "depends_on_lo": ["ZLO"],
    "depends_on_hi_inv": {"ZHI": True},
    "depends_on_lo_inv": {"ZLO": True},
    "depends_on_hi_use": {"ZHI": "lo"},
    "depends_on_lo_use": {"ZLO": "hi"},
    "depends_on_hi_inv_groups": [[True]],
    "depends_on_lo_inv_groups": [[True]],
    "depends_on_hi_use_groups": [["lo"]],
    "depends_on_lo_use_groups": [["hi"]],
    "depends_on_hi_groups": [["ZHI"]],
    "depends_on_lo_groups": [["ZLO"]],
    "depends_on_hi_group_inv": [True],
    "depends_on_lo_group_inv": [True],
    "depends_on_hi_intra_op": ["or"],
    "depends_on_lo_intra_op": ["or"],
    "depends_on_force": ["ZF"],
    "depends_on_force_inv": {"ZF": True},
    "depends_on_force_use": {"ZF": "hi"},
    "depends_on_force_inv_groups": [[True]],
    "depends_on_force_use_groups": [["hi"]],
    "depends_on_force_groups": [["ZF"]],
    "depends_on_force_group_inv": [True],
    "depends_on_force_intra_op": ["or"],
}


@pytest.mark.parametrize("field_name,sample", list(COND_FIELD_SAMPLES.items()))
def test_read_delegates_to_cond(field_name, sample):
    """在底層 cond 設值，透過 PowerRail 讀到的必須一致（漏接時會讀到 sentinel/預設→紅）。"""
    rail = PowerRail(name="X")
    setattr(rail.cond, field_name, sample)
    assert getattr(rail, field_name) == sample


@pytest.mark.parametrize("field_name,sample", list(COND_FIELD_SAMPLES.items()))
def test_write_delegates_to_cond(field_name, sample):
    """透過 PowerRail 設值，底層 cond 必須同步（漏 setter 時 cond 不變→紅）。"""
    rail = PowerRail(name="X")
    setattr(rail, field_name, sample)
    assert getattr(rail.cond, field_name) == sample


def test_constructor_routes_condition_kwargs_into_cond():
    """既有呼叫端用 PowerRail(depends_on_hi=...) 建構 → 值要落在 cond。"""
    rail = PowerRail(name="X", depends_on_hi=["A", "B"], depends_on_hi_inv={"A": True})
    assert rail.cond.depends_on_hi == ["A", "B"]
    assert rail.cond.depends_on_hi_inv == {"A": True}
    # 讀回也一致
    assert rail.depends_on_hi == ["A", "B"]


# cond_ir / 後端透過 getattr(rail, "get_<kind>_*") 取用這些存取器，必須全數委派。
ACCESSOR_CHECKS = {
    "get_hi_groups": lambda c: c.__setattr__("depends_on_hi_groups", [["A"], ["B"]]),
    "get_lo_groups": lambda c: c.__setattr__("depends_on_lo_groups", [["C"]]),
    "get_force_groups": lambda c: c.__setattr__("depends_on_force_groups", [["D"]]),
}


@pytest.mark.parametrize("method_name,setup", list(ACCESSOR_CHECKS.items()))
def test_group_accessors_delegate(method_name, setup):
    rail = PowerRail(name="X")
    setup(rail.cond)
    assert getattr(rail, method_name)() == getattr(rail.cond, method_name)()


def test_inv_use_group_inv_intra_accessors_delegate():
    """逐一比對 get_*_inv / get_*_use / get_*_group_inv / get_*_intra_op 與 cond 一致。"""
    rail = PowerRail(name="X")
    c = rail.cond
    c.depends_on_hi_groups = [["A", "B"]]
    c.depends_on_hi_inv_groups = [[True, False]]
    c.depends_on_hi_use_groups = [["lo", "hi"]]
    c.depends_on_hi_group_inv = [True]
    c.depends_on_hi_intra_op = ["or"]
    assert rail.get_hi_inv(0, 0, "A") == c.get_hi_inv(0, 0, "A")
    assert rail.get_hi_use(0, 1, "B") == c.get_hi_use(0, 1, "B")
    assert rail.get_hi_group_inv(0) == c.get_hi_group_inv(0)
    assert rail.get_hi_intra_op(0) == c.get_hi_intra_op(0)
    assert rail.get_depends_on_hi_flat() == c.get_depends_on_hi_flat()


def test_cond_is_condition_config_instance():
    rail = PowerRail(name="X")
    assert isinstance(rail.cond, ConditionConfig)


def test_distinct_rails_do_not_share_cond():
    r1 = PowerRail(name="A")
    r2 = PowerRail(name="B")
    r1.depends_on_hi = ["X"]
    assert r2.depends_on_hi == []
    assert r1.cond is not r2.cond
