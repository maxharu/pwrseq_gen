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

    def test_all_or_with_lower_bound(self):
        # 3.6 延伸：|oneDim[NUM_ROW-1 : n]，n 為 row 下界（NUM_ROW > n >= 0）
        assert take_expr("aaa", 1, row=Take(ALL, op="or", lo=1),
                         row_size="NUM_ROW") == "|aaa[NUM_ROW-1 : 1]"

    def test_all_and_with_lower_bound(self):
        assert take_expr("aaa", 1, row=Take(ALL, op="and", lo=2),
                         row_size="NUM_ROW") == "&aaa[NUM_ROW-1 : 2]"

    def test_lower_bound_zero_is_whole_bus(self):
        # n=0 必須與舊輸出 byte 相同，黃金輸出不變的前提
        assert take_expr("aaa", 1, row=Take(ALL, op="or", lo=0)) == "|aaa"

    def test_lower_bound_without_row_size_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take(ALL, op="or", lo=1))

    def test_negative_lower_bound_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take(ALL, op="or", lo=-1), row_size="NUM_ROW")

    def test_lower_bound_on_non_all_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take(SAME, lo=1), row_size="NUM_ROW")

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

    def test_all_col_or_with_lower_bound(self):
        # Q7：col 下界比照 1D 的 ranged part-select（上界固定 NUM_COL-1）
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(ALL, op="or", lo=1),
                         col_size=self.M) == (
            "|aaa[gv_row*NUM_CPU_MEM + NUM_CPU_MEM-1 : gv_row*NUM_CPU_MEM + 1]")

    def test_all_col_and_with_lower_bound_specific_row(self):
        assert take_expr("aaa", 2, row=Take(SPECIFIC, "0"), col=Take(ALL, op="and", lo=2),
                         col_size=self.M) == (
            "&aaa[0*NUM_CPU_MEM + NUM_CPU_MEM-1 : 0*NUM_CPU_MEM + 2]")

    def test_all_col_lower_bound_zero_is_whole_window(self):
        # lo=0 必須與舊輸出 byte 相同（黃金不變前提）
        assert take_expr("aaa", 2, row=Take(SAME), col=Take(ALL, op="or", lo=0),
                         col_size=self.M) == "|aaa[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]"

    def test_col_lower_bound_on_non_all_rejected(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 2, row=Take(SAME), col=Take(SAME, lo=1), col_size=self.M)

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

    def test_row_lower_bound_on_two_dim_rejected(self):
        # 範圍只作用於 1D；2D 的 row 範圍是跨步歸約，不支援
        with pytest.raises(ValueError):
            take_expr("aaa", 2, row=Take(ALL, op="or", lo=1), col=Take(ALL, op="or"),
                      col_size=self.M, row_size="NUM_ROW")


class TestInvalidInputs:
    def test_bad_ndim(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 3, row=Take(SAME))

    def test_bad_take_kind(self):
        with pytest.raises(ValueError):
            take_expr("aaa", 1, row=Take("bogus"))
