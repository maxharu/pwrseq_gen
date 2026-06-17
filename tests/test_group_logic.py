"""Tests for group_logic.py (intra-op AND/OR/XOR)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from group_logic import (
    c_intra_expr,
    eval_intra_op,
    is_legacy_group_inv_cell,
    normalize_intra_op,
    parse_intra_op_cell,
    verilog_intra_expr,
)


class TestNormalizeIntraOp:
    def test_defaults(self):
        assert normalize_intra_op(None) == "and"
        assert normalize_intra_op("") == "and"
        assert normalize_intra_op("OR") == "or"
        assert normalize_intra_op("xor") == "xor"
        assert normalize_intra_op("invalid") == "and"


class TestEvalIntraOp:
    def test_and_or_xor(self):
        assert eval_intra_op("and", [1, 1, 0]) == 0
        assert eval_intra_op("or", [0, 1, 0]) == 1
        assert eval_intra_op("xor", [1, 1, 0]) == 0
        assert eval_intra_op("xor", [1, 0, 1]) == 0
        assert eval_intra_op("xor", [1, 0, 0]) == 1


class TestCodegen:
    def test_verilog_xor(self):
        assert verilog_intra_expr(["a", "b"], "xor") == "(a ^ b)"

    def test_verilog_or_uses_bitwise_pipe(self):
        assert verilog_intra_expr(["a", "b"], "or") == "(a | b)"

    def test_c_xor_chain(self):
        assert c_intra_expr(["a", "b", "c"], "xor") == "(a ^ b ^ c)"

    def test_c_and_or_use_bitwise(self):
        assert c_intra_expr(["a", "b"], "and") == "(a & b)"
        assert c_intra_expr(["a", "b"], "or") == "(a | b)"


class TestExcelMeta:
    def test_legacy_group_inv_cell(self):
        assert is_legacy_group_inv_cell("Y") is True
        assert is_legacy_group_inv_cell("OR") is False

    def test_parse_intra_op_cell(self):
        assert parse_intra_op_cell("XOR") == "xor"
