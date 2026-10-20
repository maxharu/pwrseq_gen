"""C10 parameter 驗證測試。

守住：
  1. parameter 名需為合法識別子、不重複；值需為正整數。
  2. width 公式僅能引用已宣告 parameter，且 eval_width > 0；未宣告 → 判為無效寬度。
  3. 正常（含公式寬度）config 不報錯。

錯誤訊息沿用 '<name>' 開頭的可點擊跳轉格式。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import Parameter, PowerRail, PowerSeqConfig
from core.validator import check_invalid_width, check_parameters, validate


def _scalar():
    return PowerRail("EN", seq_type="input")


def _group_rail(width_expr: str) -> PowerRail:
    return PowerRail(
        "FOO[0]", seq_type="output", depends_on_hi=["__HIGH__"],
        group_base="FOO", bit_index=0, width_expr=width_expr,
    )


class TestParameterNameValue:
    def test_illegal_name_rejected(self):
        cfg = PowerSeqConfig(rails=[_scalar()], parameters=[Parameter("2BAD", 2)])
        assert check_parameters(cfg)
        ok, errs = validate(cfg)
        assert ok is False
        assert any("2BAD" in e for e in errs)

    def test_duplicate_name_rejected(self):
        cfg = PowerSeqConfig(
            rails=[_scalar()],
            parameters=[Parameter("NUM", 2), Parameter("NUM", 3)],
        )
        assert check_parameters(cfg)
        ok, errs = validate(cfg)
        assert ok is False
        assert any("duplicate" in e.lower() for e in errs)

    def test_non_positive_value_rejected(self):
        cfg = PowerSeqConfig(rails=[_scalar()], parameters=[Parameter("NUM", 0)])
        assert check_parameters(cfg)
        ok, errs = validate(cfg)
        assert ok is False

    def test_valid_parameters_ok(self):
        cfg = PowerSeqConfig(rails=[_scalar()], parameters=[Parameter("NUM_CPU", 2)])
        assert check_parameters(cfg) == []


class TestParameterWidthFormula:
    def test_undeclared_param_in_width_rejected(self):
        cfg = PowerSeqConfig(rails=[_group_rail("MISSING")])
        assert check_invalid_width(cfg)
        ok, errs = validate(cfg)
        assert ok is False

    def test_declared_param_formula_width_ok(self):
        cfg = PowerSeqConfig(
            rails=[_group_rail("NUM_CPU*2")],
            parameters=[Parameter("NUM_CPU", 2)],
        )
        assert check_invalid_width(cfg) == []
        ok, _ = validate(cfg)
        assert ok is True
