"""Slice col 軸切片：資料模型、IR、Verilog 展開、驗證、後端佔位。

對照 PseqGeneratorNewFunction.txt §4.2／§4.3（row 軸規則原封換成 gv_col/NUM_COL）：
  - col 軸只適用 2D 訊號；SliceGroup.axis 記軸（預設 row，只有 col 才序列化 axis 鍵）。
  - 切軸行為是 GUI 的事（見 test_slice_gui）；本檔鎖資料模型與後端語意。
  - resolve_sliced_condition 依 axis 選 genvar：col → "gv_col==k"。
  - Verilog 以內層 for(gv_col) 內 if/else-if/else 展開 col 述詞（§4.3(2)）。
  - col 可達性比 NUM_COL（第二維）；axis=col 但非 2D → validate() 報錯。
  - 其餘後端遇 col slices → NotImplementedError 佔位（與 row 相同）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.cond_ir import resolve_condition, resolve_sliced_condition
from core.config_models import (
    ConditionConfig,
    Parameter,
    PowerRail,
    PowerSeqConfig,
    SliceGroup,
)


def _sliced_2d_config() -> PowerSeqConfig:
    """2D output VV[gv_row*M+gv_col]：else hi 依賴 BAR；col0 一組（A）hi 依賴 BOOT。"""
    rails = [
        PowerRail("BAR", "output", depends_on_hi=["__HIGH__"]),
        PowerRail("BOOT", "output", depends_on_hi=["__HIGH__"]),
    ]
    vv0 = PowerRail(
        "VV[0]", "output", group_base="VV", bit_index=0,
        width_expr="NUM_CPU*NUM_CPU_MEM", dim_params=["NUM_CPU", "NUM_CPU_MEM"],
        depends_on_hi=["BAR"], depends_on_hi_groups=[["BAR"]],
    )
    vv0.cond.slices = [
        SliceGroup(rows=[0], axis="col", cond=ConditionConfig(depends_on_hi_groups=[["BOOT"]])),
    ]
    rails.append(vv0)
    rails += [PowerRail(
        f"VV[{i}]", "output", group_base="VV", bit_index=i,
        width_expr="NUM_CPU*NUM_CPU_MEM", dim_params=["NUM_CPU", "NUM_CPU_MEM"])
        for i in range(1, 8)]
    return PowerSeqConfig(
        rails=rails,
        parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 4)],
        dimensions=["NUM_CPU", "NUM_CPU_MEM"])


class TestSliceGroupAxis:
    def test_default_axis_is_row(self):
        assert SliceGroup().axis == "row"

    def test_axis_col_settable(self):
        sg = SliceGroup(rows=[0], axis="col")
        assert sg.axis == "col"
        assert sg.rows == [0]


class TestColSliceSerialization:
    def test_col_round_trip_preserves_axis(self):
        back = PowerSeqConfig.from_dict(_sliced_2d_config().to_dict())
        vv0 = next(r for r in back.rails if r.name == "VV[0]")
        assert len(vv0.cond.slices) == 1
        sg = vv0.cond.slices[0]
        assert sg.axis == "col"
        assert sg.rows == [0]
        assert sg.cond.get_hi_groups() == [["BOOT"]]

    def test_col_emits_axis_key(self):
        d = _sliced_2d_config().to_dict()
        vv = next(r for r in d["rails"] if r["name"] == "VV")
        assert vv["bits"][0]["slices"][0]["axis"] == "col"

    def test_row_omits_axis_key_byte_stable(self):
        # row slice（預設軸）不輸出 axis 鍵，與既有 row V1 存檔 byte 不變。
        rail = PowerRail("A", "output", depends_on_hi=["B"], depends_on_hi_groups=[["B"]],
                         width_expr="NUM_CPU", dim_params=["NUM_CPU"])
        rail.cond.slices = [SliceGroup(rows=[0], cond=ConditionConfig(depends_on_hi_groups=[["B"]]))]
        d = PowerSeqConfig(rails=[rail, PowerRail("B", "output")],
                           parameters=[Parameter("NUM_CPU", 2)], dimensions=["NUM_CPU"]).to_dict()
        rail_d = next(r for r in d["rails"] if r["name"] == "A")
        assert "axis" not in rail_d["slices"][0]

    def test_old_json_slice_without_axis_defaults_row(self):
        d = {"parameters": [{"name": "NUM_CPU", "value": 2}],
             "dimensions": ["NUM_CPU"],
             "rails": [{"name": "A", "seq_type": "Output",
                        "width_expr": "NUM_CPU",
                        "slices": [{"rows": [0], "depends_on_hi": ["B"]}]},
                       {"name": "B", "seq_type": "Output"}]}
        back = PowerSeqConfig.from_dict(d)
        a = next(r for r in back.rails if r.name == "A[0]")
        assert a.cond.slices[0].axis == "row"


class TestResolveColSlicedCondition:
    def test_col_predicate_uses_gv_col(self):
        cfg = _sliced_2d_config()
        n2r = {r.name: r for r in cfg.rails}
        vv0 = n2r["VV[0]"]
        branches = resolve_sliced_condition(vv0, "hi", n2r)
        assert len(branches) == 2
        assert branches[0][0] == "gv_col==0"
        assert branches[-1][0] is None
        assert branches[0][1] == resolve_condition(vv0.cond.slices[0].cond, "hi", n2r)
        assert branches[-1][1] == resolve_condition(vv0, "hi", n2r)


class TestVerilogColSliceExpansion:
    def _verilog(self):
        from codegen.verilog_generator import generate_verilog
        return generate_verilog(_sliced_2d_config())

    def test_inner_col_if_emitted(self):
        out = self._verilog()
        assert "if (gv_col==0) begin" in out
        assert "end else begin" in out
        # row 述詞不應出現（這是 col 軸）
        assert "if (gv_row==" not in out

    def test_group_and_else_assigns(self):
        out = self._verilog()
        assert "assign vv_hi[gv_row*NUM_CPU_MEM + gv_col] = (boot);" in out
        assert "assign vv_hi[gv_row*NUM_CPU_MEM + gv_col] = (bar);" in out


class TestColSliceReachability:
    def test_reachable_col_no_warning(self):
        from core.validator import check_slice_reachability
        assert check_slice_reachability(_sliced_2d_config()) == []

    def test_unreachable_col_warns(self):
        from core.validator import check_slice_reachability
        cfg = _sliced_2d_config()
        vv0 = next(r for r in cfg.rails if r.name == "VV[0]")
        vv0.cond.slices[0].rows = [9]  # NUM_CPU_MEM 最大值 4 → col9 不可達
        warnings = check_slice_reachability(cfg)
        assert any("VV" in w and "9" in w for w in warnings)


class TestColSliceRequiresTwoDim:
    def test_col_axis_on_1d_is_error(self):
        from core.validator import validate
        rails = [
            PowerRail("B", "output"),
            PowerRail("A[0]", "output", group_base="A", bit_index=0,
                      width_expr="NUM_CPU", dim_params=["NUM_CPU"],
                      depends_on_hi=["B"], depends_on_hi_groups=[["B"]]),
            PowerRail("A[1]", "output", group_base="A", bit_index=1,
                      width_expr="NUM_CPU", dim_params=["NUM_CPU"]),
        ]
        rails[1].cond.slices = [SliceGroup(rows=[0], axis="col",
                                           cond=ConditionConfig(depends_on_hi_groups=[["B"]]))]
        cfg = PowerSeqConfig(rails=rails, parameters=[Parameter("NUM_CPU", 2)],
                             dimensions=["NUM_CPU"])
        ok, errors = validate(cfg)
        assert any("col" in e.lower() and "2" in e for e in errors)

    def test_col_axis_on_2d_is_valid(self):
        from core.validator import validate
        ok, errors = validate(_sliced_2d_config())
        assert not any("col" in e.lower() and "2-dim" in e.lower() for e in errors)


class TestColBackendSliceGuards:
    def test_c_backend_raises_on_col_slices(self):
        from codegen.c_generator import generate_c
        with pytest.raises(NotImplementedError):
            generate_c(_sliced_2d_config())

    def test_timing_sim_raises_on_col_slices(self):
        from timing.timing_sim import default_scenario_for_config, simulate
        cfg = _sliced_2d_config()
        with pytest.raises(NotImplementedError):
            simulate(cfg, default_scenario_for_config(cfg))

    def test_drawio_raises_on_col_slices(self):
        from drawio import generate_drawio
        with pytest.raises(NotImplementedError):
            generate_drawio(_sliced_2d_config())
