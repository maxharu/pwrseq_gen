"""Tests for validator.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import Parameter, PowerRail, PowerSeqConfig
from core.validator import (
    check_circular_dependency,
    check_duplicate_names,
    check_missing_deps,
    check_take_lower_bounds,
    validate,
)


def _row_bound_config(lo, dims=("NUM_CPU",), max_value=4, row_kind="all", take_op="or"):
    """SIG2 以 1D All 歸約引用 SIG4（dims 維度向量）的 hi 條件，row 下界為 lo。"""
    sig4 = PowerRail(
        "SIG4[0]", "output", group_base="SIG4", bit_index=0,
        width_expr="NUM_CPU", dim_params=list(dims),
    )
    row = {"kind": row_kind, "op": take_op, "lo": lo}
    sig2 = PowerRail(
        "SIG2[0]", "output",
        depends_on_hi=["SIG4[0]"],
        depends_on_hi_groups=[["SIG4[0]"]],
        depends_on_hi_use_groups=[["hi"]],
        depends_on_hi_take_groups=[[{"row": row}]],
    )
    return PowerSeqConfig(
        parameters=[Parameter("NUM_CPU", max_value)],
        dimensions=["NUM_CPU"],
        rails=[sig4, sig2],
    )


def _col_bound_config(lo, col_max=4, col_kind="all", dims=("NUM_CPU", "NUM_CPU_MEM")):
    """SIG2（1D）以 All col 歸約引用 SIG4（2D）的 hi 條件，col 下界為 lo。"""
    sig4 = PowerRail(
        "SIG4[0]", "output", group_base="SIG4", bit_index=0,
        width_expr="NUM_CPU*NUM_CPU_MEM", dim_params=list(dims),
    )
    take = {"row": {"kind": "same"}, "col": {"kind": col_kind, "op": "or", "lo": lo}}
    sig2 = PowerRail(
        "SIG2[0]", "output",
        depends_on_hi=["SIG4[0]"],
        depends_on_hi_groups=[["SIG4[0]"]],
        depends_on_hi_use_groups=[["hi"]],
        depends_on_hi_take_groups=[[take]],
    )
    return PowerSeqConfig(
        parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", col_max)],
        dimensions=["NUM_CPU", "NUM_CPU_MEM"],
        rails=[sig4, sig2],
    )


class TestCheckDuplicateNames:
    def test_no_duplicates(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("B"),
        ])
        assert check_duplicate_names(cfg) == []

    def test_has_duplicates(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("B"),
            PowerRail("A"),
        ])
        assert check_duplicate_names(cfg) == ["A"]


class TestCheckMissingDeps:
    def test_all_exist(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_missing_deps(cfg) == []

    def test_missing_dep(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["NOT_EXIST"]),
        ])
        assert check_missing_deps(cfg) == [("A", "NOT_EXIST")]

    def test_high_low_constants_ignored(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"], depends_on_lo=["__LOW__"]),
        ])
        assert check_missing_deps(cfg) == []


class TestCheckCircularDependency:
    def test_no_cycle(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_circular_dependency(cfg) is False

    def test_cycle_in_hi(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["B"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        assert check_circular_dependency(cfg) is True

    def test_cycle_in_lo(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"], depends_on_lo=["B"]),
            PowerRail("B", depends_on_hi=["__HIGH__"], depends_on_lo=["A"]),
        ])
        assert check_circular_dependency(cfg) is True

    def test_hi_lo_cross_no_cycle(self):
        """SIG_3 iHi 依賴 SIG_2、SIG_2 iLo 依賴 SIG_3 不形成環"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("SIG_2", depends_on_hi=["__HIGH__"], depends_on_lo=["SIG_3"]),
            PowerRail("SIG_3", depends_on_hi=["SIG_2"], depends_on_lo=["__LOW__"]),
        ])
        assert check_circular_dependency(cfg) is False


class TestValidate:
    def test_valid_config(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        ok, errs = validate(cfg)
        assert ok is True
        assert errs == []

    def test_duplicate_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A"),
            PowerRail("A"),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("Duplicate" in e for e in errs)

    def test_missing_dep_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["MISSING"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("non-existent" in e for e in errs)

    def test_circular_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["B"]),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("Circular" in e for e in errs)

    def test_empty_name_fails(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("", depends_on_hi=["__HIGH__"]),
        ])
        ok, errs = validate(cfg)
        assert ok is False
        assert any("empty" in e for e in errs)

class TestTakeLowerBound:
    """1D All 歸約的 row 下界 lo：|oneDim[NUM_ROW-1 : lo]，需 0 <= lo < 最大 NUM_ROW。"""

    def test_valid_lower_bound_passes(self):
        assert check_take_lower_bounds(_row_bound_config(lo=1)) == []

    def test_zero_lower_bound_passes(self):
        assert check_take_lower_bounds(_row_bound_config(lo=0)) == []

    def test_lower_bound_at_max_rejected(self):
        # NUM_ROW > lo：lo == 最大值時範圍為空，不允許
        errs = check_take_lower_bounds(_row_bound_config(lo=4, max_value=4))
        assert len(errs) == 1 and "SIG2[0]" in errs[0]

    def test_negative_lower_bound_rejected(self):
        errs = check_take_lower_bounds(_row_bound_config(lo=-1))
        assert len(errs) == 1

    def test_non_integer_lower_bound_rejected(self):
        errs = check_take_lower_bounds(_row_bound_config(lo="1"))
        assert len(errs) == 1

    def test_validate_surfaces_lower_bound_error(self):
        ok, errors = validate(_row_bound_config(lo=9, max_value=4))
        assert not ok
        assert any("SIG2[0]" in e for e in errors)

    def test_non_all_kind_with_lower_bound_rejected(self):
        errs = check_take_lower_bounds(_row_bound_config(lo=1, row_kind="specific"))
        assert len(errs) == 1

    def test_two_dim_source_rejected(self):
        # 2D row 範圍是跨步歸約（3.5），不允許
        cfg = _row_bound_config(lo=1, dims=("NUM_CPU", "NUM_CPU"))
        cfg.parameters.append(Parameter("NUM_CPU_MEM", 8))
        cfg.dimensions = ["NUM_CPU", "NUM_CPU_MEM"]
        cfg.rails[0].dim_params = ["NUM_CPU", "NUM_CPU_MEM"]
        errs = check_take_lower_bounds(cfg)
        assert len(errs) == 1


class TestTakeColLowerBound:
    """2D All col 歸約的 col 下界 lo：|bus[...NUM_COL-1 : ...lo]，需 0 <= lo < 最大 NUM_COL。"""

    def test_valid_col_lower_bound_passes(self):
        assert check_take_lower_bounds(_col_bound_config(lo=1)) == []

    def test_zero_col_lower_bound_passes(self):
        assert check_take_lower_bounds(_col_bound_config(lo=0)) == []

    def test_col_lower_bound_at_max_rejected(self):
        errs = check_take_lower_bounds(_col_bound_config(lo=4, col_max=4))
        assert len(errs) == 1 and "SIG2[0]" in errs[0]

    def test_negative_col_lower_bound_rejected(self):
        errs = check_take_lower_bounds(_col_bound_config(lo=-1))
        assert len(errs) == 1

    def test_non_all_col_kind_with_lower_bound_rejected(self):
        errs = check_take_lower_bounds(_col_bound_config(lo=1, col_kind="specific"))
        assert len(errs) == 1

    def test_validate_surfaces_col_lower_bound_error(self):
        ok, errors = validate(_col_bound_config(lo=9, col_max=4))
        assert not ok
        assert any("SIG2[0]" in e for e in errors)
