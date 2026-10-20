"""C8：width 公式的白名單 ast 求值（core/param_expr.py）。

把「width_expr → N」升級成可引用 parameter 的算式後，求值規則只能有一份（給展開/收合/驗證/
產生器共用），且必須用 ast 白名單而非 eval()，避免任意程式碼執行。這支測試盯住白名單邊界。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import Parameter
from core.param_expr import ParamExprError, eval_width


class TestEvalWidthBackCompat:
    def test_plain_integer_without_parameters(self):
        assert eval_width("2") == 2
        assert eval_width("1") == 1
        assert eval_width(" 3 ") == 3

    def test_unary_negative_computes(self):
        # 允許算出負數；是否合法（>0）交給 validator（C10）
        assert eval_width("-3") == -3


class TestEvalWidthFormula:
    def test_single_parameter(self):
        assert eval_width("NUM_CPU", [Parameter("NUM_CPU", 4)]) == 4

    def test_multiplication(self):
        assert eval_width("NUM_CPU*2", [Parameter("NUM_CPU", 4)]) == 8

    def test_two_parameters_product(self):
        ps = [Parameter("NUM_CPU", 3), Parameter("NUM_CPU_MEM", 2)]
        assert eval_width("NUM_CPU*NUM_CPU_MEM", ps) == 6

    def test_parentheses_add_sub(self):
        assert eval_width("(NUM_CPU+1)*2 - 1", [Parameter("NUM_CPU", 3)]) == 7

    def test_floordiv(self):
        assert eval_width("NUM_CPU//2", [Parameter("NUM_CPU", 5)]) == 2

    def test_dict_parameters_accepted(self):
        assert eval_width("A+B", {"A": 1, "B": 2}) == 3


class TestEvalWidthRejections:
    def test_power_operator_rejected(self):
        with pytest.raises(ParamExprError):
            eval_width("2**3")

    def test_syntax_error_rejected(self):
        with pytest.raises(ParamExprError):
            eval_width("2 +")

    def test_undeclared_name_rejected(self):
        with pytest.raises(ParamExprError):
            eval_width("NUM_CPU*2", [])

    def test_no_eval_injection(self):
        with pytest.raises(ParamExprError):
            eval_width("__import__('os').system('echo hi')", [])

    def test_float_literal_rejected(self):
        with pytest.raises(ParamExprError):
            eval_width("1.5")

    def test_bool_literal_rejected(self):
        with pytest.raises(ParamExprError):
            eval_width("True")

    def test_param_expr_error_is_value_error(self):
        # 既有呼叫端用 except ValueError 接 width 無效；ParamExprError 必須相容
        assert issubclass(ParamExprError, ValueError)
