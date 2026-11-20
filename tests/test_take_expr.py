"""階段D 第一步：take 取法運算式產生器（純函式，對照 PseqGeneratorNewFunction.txt 3.1~3.6）。

只驗「row/col take → RHS 字串」的字面輸出與不支援情形：
  - 0 維：直接引用。
  - 1 維：row take（Same / Specific(+相對偏移) / All AND|OR）。
  - 2 維：row×col 可用單一索引／part-select 表達的乾淨組合（3.5）。
  - 跨步歸約（All row 搭配逐 col，3.5 註明不能單一 part-select）此步明確不支援 → 報錯。

不碰既有 emission／後端；golden 不變。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.take_expr import ALL, SAME, SPECIFIC, Take, take_expr


class TestZeroDim:
    def test_direct_reference(self):
        assert take_expr("aaa", 0) == "aaa"

    def test_row_on_zero_dim_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 0, row=Take(SAME))


class TestOneDim:
    def test_same_row(self):
        assert take_expr("aaa", 1, row=Take(SAME)) == "aaa[gv_row]"

    def test_specific_absolute(self):
        assert take_expr("aaa", 1, row=Take(SPECIFIC, "0")) == "aaa[0]"

    def test_specific_relative_offset(self):
        assert take_expr("aaa", 1, row=Take(SPECIFIC, "gv_row-1")) == "aaa[gv_row-1]"

    def test_all_and(self):
        assert take_expr("aaa", 1, row=Take(ALL, op="and")) == "&aaa"

    def test_all_or(self):
        assert take_expr("aaa", 1, row=Take(ALL, op="or")) == "|aaa"

    def test_custom_genvar_name(self):
        assert take_expr("aaa", 1, row=Take(SAME), gv_row="gv_cpu") == "aaa[gv_cpu]"

    def test_col_on_one_dim_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take(SAME), col=Take(SAME))

    def test_missing_row_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1)


class TestTwoDim:
    M = "NUM_CPU_MEM"

    def test_same_same(self):
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(SAME),
                         col_size=self.M) == "aaa[gv_row*NUM_CPU_MEM + gv_col]"

    def test_same_specific_col(self):
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(SPECIFIC, "j"),
                         col_size=self.M) == "aaa[gv_row*NUM_CPU_MEM + j]"

    def test_same_all_col_or(self):
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(ALL, op="or"),
                         col_size=self.M) == "|aaa[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]"

    def test_same_all_col_and(self):
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(ALL, op="and"),
                         col_size=self.M) == "&aaa[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]"

    def test_specific_row_same_col(self):
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "0"), col=Take(SAME),
                         col_size=self.M) == "aaa[0*NUM_CPU_MEM + gv_col]"

    def test_specific_row_specific_col(self):
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "0"), col=Take(SPECIFIC, "0"),
                         col_size=self.M) == "aaa[0*NUM_CPU_MEM + 0]"

    def test_specific_row_all_col_and(self):
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "0"), col=Take(ALL, op="and"),
                         col_size=self.M) == "&aaa[0*NUM_CPU_MEM +: NUM_CPU_MEM]"

    def test_relative_row_offset_parenthesised(self):
        # 3.6：相對偏移進 *M 前需加括號
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "gv_row-1"), col=Take(SAME),
                         col_size=self.M) == "aaa[(gv_row-1)*NUM_CPU_MEM + gv_col]"

    def test_relative_both_offset_parenthesised(self):
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "gv_row-1"),
                         col=Take(SPECIFIC, "gv_col-1"),
                         col_size=self.M) == "aaa[(gv_row-1)*NUM_CPU_MEM + (gv_col-1)]"

    def test_all_row_all_col_same_op_is_whole_bus(self):
        assert take_expr("aaa", 2, row=Take(ALL, op="and"), col=Take(ALL, op="and"),
                         col_size=self.M) == "&aaa"
        assert take_expr("aaa", 2, row=Take(ALL, op="or"), col=Take(ALL, op="or"),
                         col_size=self.M) == "|aaa"

    def test_custom_genvars(self):
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(SAME), col_size=self.M,
                         gv_row="gv_cpu", gv_col="gv_mem") == "aaa[gv_cpu*NUM_CPU_MEM + gv_mem]"


class TestTwoDimUnsupported:
    M = "NUM_CPU_MEM"

    def test_strided_all_row_same_col_rejected(self):
        # 3.5：All row 搭配逐 col 是跨步歸約，不能用單一 part-select，此步不支援。
        with pytest.raises(ValueError, match="跨步|strided"):
            take_expr("aaa", 2, row=Take(ALL, op="and"), col=Take(SAME), col_size=self.M)

    def test_strided_all_row_specific_col_rejected(self):
        with pytest.raises(ValueError, match="跨步|strided"):
            take_expr("aaa", 2, row=Take(ALL, op="and"), col=Take(SPECIFIC, "0"),
                      col_size=self.M)

    def test_mixed_all_ops_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 2, row=Take(ALL, op="and"), col=Take(ALL, op="or"),
                      col_size=self.M)

    def test_missing_col_size_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 2, row=Take(SAME), col=Take(SAME))

    def test_missing_col_take_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 2, row=Take(SAME), col_size=self.M)


class TestInvalidInputs:
    def test_bad_ndim(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 3, row=Take(SAME))

    def test_bad_take_kind(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take("bogus"))
