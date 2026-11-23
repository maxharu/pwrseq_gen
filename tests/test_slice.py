"""Slice V1（row 軸切片）：資料模型、IR、Verilog 展開、驗證、後端佔位。

對照 PseqGeneratorNewFunction.txt §4：
  - 扁平 depends_on_* = else / catch-all 組；cond.slices 只裝非 else 群組。
  - 不切片時序列化位元不變（golden 不動）；舊檔缺 slices 鍵 → 不切片。
  - resolve_sliced_condition 回 [(pred, tree)...,(None, else_tree)]；不切片回單一 (None, tree)。
  - Verilog 以 generate-for 內 if/else-if/else 展開 row 述詞。
  - 其餘後端遇 slices → NotImplementedError 佔位。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.cond_ir import render_row_predicate, resolve_condition, resolve_sliced_condition
from core.config_models import (
    ConditionConfig,
    Parameter,
    PowerRail,
    PowerSeqConfig,
    SliceGroup,
)


def _sliced_1d_config() -> PowerSeqConfig:
    """1D output FOO[gv_row]：else hi 依賴 BAR；row0 一組（A）hi 依賴 BOOT。"""
    rails = [
        PowerRail("BAR", "output", depends_on_hi=["__HIGH__"]),
        PowerRail("BOOT", "output", depends_on_hi=["__HIGH__"]),
    ]
    foo0 = PowerRail(
        "FOO[0]", "output", group_base="FOO", bit_index=0,
        width_expr="NUM_CPU", dim_params=["NUM_CPU"],
        depends_on_hi=["BAR"], depends_on_hi_groups=[["BAR"]],
    )
    foo0.cond.slices = [
        SliceGroup(rows=[0], cond=ConditionConfig(depends_on_hi_groups=[["BOOT"]])),
    ]
    rails += [foo0, PowerRail(
        "FOO[1]", "output", group_base="FOO", bit_index=1,
        width_expr="NUM_CPU", dim_params=["NUM_CPU"])]
    return PowerSeqConfig(
        rails=rails, parameters=[Parameter("NUM_CPU", 4)], dimensions=["NUM_CPU"])


class TestSliceGroupModel:
    def test_slice_group_defaults(self):
        sg = SliceGroup()
        assert sg.rows == []
        assert isinstance(sg.cond, ConditionConfig)

    def test_condition_config_has_empty_slices_by_default(self):
        assert ConditionConfig().slices == []

    def test_rail_delegates_slices_to_cond(self):
        rail = PowerRail("A", "output")
        rail.cond.slices = [SliceGroup(rows=[0])]
        assert rail.slices == rail.cond.slices


class TestSliceSerialization:
    def test_round_trip_preserves_slices(self):
        back = PowerSeqConfig.from_dict(_sliced_1d_config().to_dict())
        foo0 = next(r for r in back.rails if r.name == "FOO[0]")
        assert len(foo0.cond.slices) == 1
        sg = foo0.cond.slices[0]
        assert sg.rows == [0]
        assert sg.cond.get_hi_groups() == [["BOOT"]]
        # else（flat）仍是 BAR
        assert foo0.get_hi_groups() == [["BAR"]]

    def test_serialized_contains_slices_key_on_head_only(self):
        d = _sliced_1d_config().to_dict()
        foo = next(r for r in d["rails"] if r["name"] == "FOO")
        assert "slices" in foo["bits"][0]
        assert foo["bits"][0]["slices"][0]["rows"] == [0]
        assert "slices" not in foo["bits"][1]

    def test_no_slices_omits_key_byte_stable(self):
        rail = PowerRail("A", "output", depends_on_hi=["B"], depends_on_hi_groups=[["B"]])
        d = PowerSeqConfig(rails=[rail, PowerRail("B", "output")]).to_dict()
        rail_d = next(r for r in d["rails"] if r["name"] == "A")
        assert "slices" not in rail_d

    def test_old_json_without_slices_is_not_sliced(self):
        d = {"rails": [{"name": "A", "seq_type": "Output",
                        "depends_on_hi": ["B"]}, {"name": "B", "seq_type": "Output"}]}
        back = PowerSeqConfig.from_dict(d)
        a = next(r for r in back.rails if r.name == "A")
        assert a.cond.slices == []


class TestRenderRowPredicate:
    def test_single_row(self):
        assert render_row_predicate([0]) == "gv_row==0"

    def test_multi_row(self):
        assert render_row_predicate([0, 1]) == "gv_row==0 || gv_row==1"

    def test_custom_genvar(self):
        assert render_row_predicate([2], gv_row="gv_cpu") == "gv_cpu==2"


class TestResolveSlicedCondition:
    def test_not_sliced_returns_single_else_branch(self):
        rail = PowerRail("A", "output", depends_on_hi=["B"], depends_on_hi_groups=[["B"]])
        branches = resolve_sliced_condition(rail, "hi", {"A": rail, "B": PowerRail("B", "output")})
        assert len(branches) == 1
        pred, tree = branches[0]
        assert pred is None
        assert tree == resolve_condition(rail, "hi", {"A": rail})

    def test_sliced_returns_group_then_else(self):
        cfg = _sliced_1d_config()
        n2r = {r.name: r for r in cfg.rails}
        foo0 = n2r["FOO[0]"]
        branches = resolve_sliced_condition(foo0, "hi", n2r)
        assert len(branches) == 2
        assert branches[0][0] == "gv_row==0"
        assert branches[-1][0] is None
        # group A 的 hi 樹來自 BOOT；else 來自 BAR
        assert branches[0][1] == resolve_condition(foo0.cond.slices[0].cond, "hi", n2r)
        assert branches[-1][1] == resolve_condition(foo0, "hi", n2r)


class TestVerilogSliceExpansion:
    def _verilog(self):
        from codegen.verilog_generator import generate_verilog
        return generate_verilog(_sliced_1d_config())

    def test_if_else_branches_emitted(self):
        out = self._verilog()
        assert "if (gv_row==0) begin" in out
        assert "end else begin" in out

    def test_group_and_else_assigns(self):
        out = self._verilog()
        # group A：hi = boot；else：hi = bar（單項 group 會加括號）
        assert "assign foo_hi[gv_row] = (boot);" in out
        assert "assign foo_hi[gv_row] = (bar);" in out

    def test_not_sliced_has_no_if(self):
        from codegen.verilog_generator import generate_verilog
        rails = [PowerRail(f"SIG[{i}]", "output", group_base="SIG", bit_index=i,
                           width_expr="NUM_CPU", dim_params=["NUM_CPU"]) for i in range(2)]
        rails[0].depends_on_hi = ["__HIGH__"]
        rails[0].depends_on_hi_groups = [["__HIGH__"]]
        cfg = PowerSeqConfig(rails=rails, parameters=[Parameter("NUM_CPU", 2)],
                             dimensions=["NUM_CPU"])
        out = generate_verilog(cfg)
        assert "if (gv_row==" not in out


class TestValidatorSliceReachability:
    def test_reachable_rows_no_warning(self):
        from core.validator import check_slice_reachability
        assert check_slice_reachability(_sliced_1d_config()) == []

    def test_unreachable_row_warns(self):
        from core.validator import check_slice_reachability
        cfg = _sliced_1d_config()
        foo0 = next(r for r in cfg.rails if r.name == "FOO[0]")
        foo0.cond.slices[0].rows = [5]  # NUM_CPU 最大值為 4 → row5 不可達
        warnings = check_slice_reachability(cfg)
        assert any("FOO" in w and "5" in w for w in warnings)

    def test_reachability_is_warning_not_blocking_error(self):
        from core.validator import validate
        cfg = _sliced_1d_config()
        foo0 = next(r for r in cfg.rails if r.name == "FOO[0]")
        foo0.cond.slices[0].rows = [5]
        ok, errors = validate(cfg)
        assert not any("row" in e.lower() and "5" in e for e in errors)


class TestBackendSliceGuards:
    def test_c_backend_raises_on_slices(self):
        from codegen.c_generator import generate_c
        with pytest.raises(NotImplementedError):
            generate_c(_sliced_1d_config())

    def test_timing_sim_raises_on_slices(self):
        from timing.timing_sim import default_scenario_for_config, simulate
        cfg = _sliced_1d_config()
        with pytest.raises(NotImplementedError):
            simulate(cfg, default_scenario_for_config(cfg))

    def test_drawio_raises_on_slices(self):
        from drawio import generate_drawio
        with pytest.raises(NotImplementedError):
            generate_drawio(_sliced_1d_config())
