"""take_rules 規則表測試（§3.4 / §3.5 / §6）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.take_expr import take_expr, take_from_dict
from core.take_rules import (
    ABS_ROW,
    ALL_ROW_AND,
    ALL_ROW_OR,
    REL_ROW,
    ROWOFF_ALLCOL_AND,
    ROWOFF_ALLCOL_OR,
    ROWOFF_COLOFF,
    ROWOFF_SPEC_COL,
    default_form,
    form_to_take,
    take_forms,
    take_to_form,
)


def _ids(out_ndim, dep_ndim):
    return [f.id for f in take_forms(out_ndim, dep_ndim)]


class TestTakeForms:
    def test_dep0_empty(self):
        assert take_forms(1, 0) == []
        assert take_forms(2, 0) == []

    def test_dep1_four_forms(self):
        for out in (1, 2):
            assert _ids(out, 1) == [REL_ROW, ABS_ROW, ALL_ROW_AND, ALL_ROW_OR]

    def test_dep2_out1_no_coloff(self):
        # §3.4：輸出 1 維沒有 gv_col，不得出現 col 偏移
        ids = _ids(1, 2)
        assert ids == [ROWOFF_SPEC_COL, ROWOFF_ALLCOL_OR, ROWOFF_ALLCOL_AND]
        assert ROWOFF_COLOFF not in ids

    def test_dep2_out2_has_coloff(self):
        ids = _ids(2, 2)
        assert ids == [ROWOFF_SPEC_COL, ROWOFF_ALLCOL_OR, ROWOFF_ALLCOL_AND, ROWOFF_COLOFF]

    def test_strided_all_row_never_listed(self):
        # §3.5：2 維 dep 的清單不含任何「All row」形狀
        for out in (1, 2):
            for f in take_forms(out, 2):
                assert "all_row" not in f.id


class TestDefault:
    def test_dep1_default_aligned_row(self):
        assert default_form(1, 1) == (REL_ROW, 0, 0)
        assert default_form(2, 1) == (REL_ROW, 0, 0)

    def test_dep2_default_specific_col0(self):
        assert default_form(1, 2) == (ROWOFF_SPEC_COL, 0, 0)
        assert default_form(2, 2) == (ROWOFF_SPEC_COL, 0, 0)

    def test_dep0_none(self):
        assert default_form(1, 0) == (None, 0, 0)


class TestRoundTrip:
    def test_1d_forms(self):
        for form, n in [(REL_ROW, 0), (REL_ROW, -1), (REL_ROW, 2), (ABS_ROW, 3),
                        (ALL_ROW_AND, 0), (ALL_ROW_OR, 0)]:
            take = form_to_take(form, n, 0)
            assert take_to_form(take) == (form, n, 0)

    def test_2d_forms(self):
        for form, n, m in [(ROWOFF_SPEC_COL, 0, 0), (ROWOFF_SPEC_COL, -1, 2),
                           (ROWOFF_ALLCOL_OR, 0, 0), (ROWOFF_ALLCOL_AND, -2, 0),
                           (ROWOFF_COLOFF, 0, 0), (ROWOFF_COLOFF, 1, -1)]:
            take = form_to_take(form, n, m)
            assert take_to_form(take) == (form, n, m)

    def test_none(self):
        assert form_to_take(None) is None
        assert take_to_form(None) == (None, 0, 0)


class TestTakeExprIntegration:
    """form_to_take → take_from_dict → take_expr 要產出 §6 的片段。"""

    def _expr(self, form, n, m, ref_ndim, bus="bus", col_size="C"):
        t = form_to_take(form, n, m)
        return take_expr(bus, ref_ndim,
                         take_from_dict(t.get("row")),
                         take_from_dict(t.get("col")) if "col" in t else None,
                         col_size=col_size)

    def test_1d(self):
        assert self._expr(REL_ROW, 0, 0, 1) == "bus[gv_row]"
        assert self._expr(REL_ROW, -1, 0, 1) == "bus[gv_row-1]"
        assert self._expr(ABS_ROW, 3, 0, 1) == "bus[3]"
        assert self._expr(ALL_ROW_AND, 0, 0, 1) == "&bus"
        assert self._expr(ALL_ROW_OR, 0, 0, 1) == "|bus"

    def test_2d(self):
        assert self._expr(ROWOFF_SPEC_COL, 0, 0, 2) == "bus[gv_row*C + 0]"
        assert self._expr(ROWOFF_SPEC_COL, -1, 2, 2) == "bus[(gv_row-1)*C + 2]"
        assert self._expr(ROWOFF_ALLCOL_OR, 0, 0, 2) == "|bus[gv_row*C +: C]"
        assert self._expr(ROWOFF_ALLCOL_AND, -1, 0, 2) == "&bus[(gv_row-1)*C +: C]"
        assert self._expr(ROWOFF_COLOFF, 0, 0, 2) == "bus[gv_row*C + gv_col]"
        assert self._expr(ROWOFF_COLOFF, 0, -1, 2) == "bus[gv_row*C + (gv_col-1)]"
