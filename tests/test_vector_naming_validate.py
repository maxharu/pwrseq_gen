"""A3 命名／驗證測試。

  1. safe_name 要能把 vector 的 [i] 轉成合法 identifier（FOO[2] -> FOO_2）。
  2. 展開後兩個不同節點名若 collapse 到同一個 identifier（FOO[2] vs FOO_2）要被擋。
  3. vector 的 width 非正整數要被擋。
錯誤訊息沿用「以 'name' 開頭」的可點擊跳轉格式。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import PowerRail, PowerSeqConfig
from core.naming import safe_name
from core.validator import (
    check_identifier_collisions,
    check_invalid_width,
    validate,
)


class TestSafeNameBrackets:
    def test_bit_index_becomes_underscore(self):
        assert safe_name("FOO[2]") == "FOO_2"

    def test_existing_rules_unchanged(self):
        assert safe_name("A.B-C D") == "A_B_C_D"


class TestIdentifierCollision:
    def test_bracket_and_underscore_collide(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("FOO[2]", seq_type="output", depends_on_hi=["__HIGH__"]),
            PowerRail("FOO_2", seq_type="output", depends_on_hi=["__HIGH__"]),
        ])
        assert check_identifier_collisions(cfg)
        ok, errs = validate(cfg)
        assert ok is False
        assert any("identifier" in e for e in errs)
        # 可點擊：訊息以 'name' 開頭
        assert any(e.startswith("'FOO") for e in errs)

    def test_no_collision_for_distinct_identifiers(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("FOO", seq_type="output", depends_on_hi=["__HIGH__"]),
            PowerRail("BAR", seq_type="output", depends_on_hi=["__HIGH__"]),
        ])
        assert check_identifier_collisions(cfg) == []


class TestInvalidWidth:
    def test_zero_width_rejected(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("FOO[0]", seq_type="output", depends_on_hi=["__HIGH__"],
                      group_base="FOO", bit_index=0, width_expr="0"),
        ])
        assert check_invalid_width(cfg)
        ok, errs = validate(cfg)
        assert ok is False
        assert any("width" in e for e in errs)

    def test_non_integer_width_rejected(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("FOO[0]", seq_type="output", depends_on_hi=["__HIGH__"],
                      group_base="FOO", bit_index=0, width_expr="abc"),
        ])
        assert check_invalid_width(cfg)

    def test_positive_width_ok(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("FOO[0]", seq_type="output", depends_on_hi=["__HIGH__"],
                      group_base="FOO", bit_index=0, width_expr="2"),
            PowerRail("FOO[1]", seq_type="output", depends_on_hi=["__HIGH__"],
                      group_base="FOO", bit_index=1, width_expr="2"),
        ])
        assert check_invalid_width(cfg) == []
