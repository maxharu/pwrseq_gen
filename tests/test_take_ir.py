"""階段D-B：take 進條件 IR 的儲存與解析。

B1（本檔）：ConditionConfig 承載 depends_on_{kind}_take_groups（與 use_groups 平行，
每 item 存 row/col 的 Take 選擇，不存幾何）：
  - 建構子 kwargs 路由進 cond、get_{kind}_take 存取器回傳該 item 的 take（無則 None）。
  - to_dict 僅在非空時輸出該鍵；from_dict 讀回 → round-trip。
  - 無 take 的 config to_dict 不含該鍵（舊檔 byte 不變）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.cond_ir import AnyGroup, TakeRef, resolve_condition
from core.config_models import PowerRail, PowerSeqConfig
from core.take_expr import Take
from core.take_rules import (
    REL_ROW,
    ROWOFF_ALLCOL_AND,
    ROWOFF_COLOFF,
    form_to_take,
)

_TAKE = {"row": {"kind": "same", "index": "", "op": "and"},
         "col": {"kind": "all", "index": "", "op": "or"}}


def _config_with_take() -> PowerSeqConfig:
    rail = PowerRail(
        "SIG2", "output",
        depends_on_hi=["SIG4"],
        depends_on_hi_groups=[["SIG4"]],
        depends_on_hi_take_groups=[[_TAKE]],
    )
    return PowerSeqConfig(rails=[rail])


class TestTakeGroupsAccessor:
    def test_constructor_routes_into_cond(self):
        rail = PowerRail(
            "SIG2", "output",
            depends_on_hi_groups=[["SIG4"]],
            depends_on_hi_take_groups=[[_TAKE]],
        )
        assert rail.get_hi_take(0, 0) == _TAKE

    def test_missing_take_returns_none(self):
        rail = PowerRail("SIG2", "output", depends_on_hi_groups=[["SIG4"]])
        assert rail.get_hi_take(0, 0) is None

    def test_out_of_range_returns_none(self):
        rail = PowerRail(
            "SIG2", "output",
            depends_on_hi_groups=[["SIG4"]],
            depends_on_hi_take_groups=[[_TAKE]],
        )
        assert rail.get_hi_take(5, 5) is None


class TestTakeGroupsRoundTrip:
    def test_round_trip_preserves_take(self):
        cfg = _config_with_take()
        back = PowerSeqConfig.from_dict(cfg.to_dict())
        sig2 = next(r for r in back.rails if r.name == "SIG2")
        assert sig2.get_hi_take(0, 0) == _TAKE

    def test_serialized_contains_take_key(self):
        d = _config_with_take().to_dict()
        rail_d = next(r for r in d["rails"] if r["name"] == "SIG2")
        assert rail_d["depends_on_hi_take_groups"] == [[_TAKE]]


class TestNoTakeByteStable:
    def test_no_take_config_omits_key(self):
        rail = PowerRail(
            "A", "output",
            depends_on_hi=["B"],
            depends_on_hi_groups=[["B"]],
        )
        d = PowerSeqConfig(rails=[rail]).to_dict()
        rail_d = next(r for r in d["rails"] if r["name"] == "A")
        assert "depends_on_hi_take_groups" not in rail_d
        assert "depends_on_lo_take_groups" not in rail_d
        assert "depends_on_force_take_groups" not in rail_d


# B2：resolve_condition 對維度引用產生 TakeRef；各後端材質化。
def _sig4_sig2(with_take: bool = True):
    """SIG4(2D 2x4) 被 SIG2(1D) 以 take 引用其 hi 條件。回 (sig2_head, name_to_rail)。"""
    sig4 = PowerRail(
        "SIG4[0]", "output", group_base="SIG4", bit_index=0,
        width_expr="NUM_CPU*NUM_CPU_MEM", dim_params=["NUM_CPU", "NUM_CPU_MEM"],
    )
    kwargs = dict(
        depends_on_hi=["SIG4[0]"],
        depends_on_hi_groups=[["SIG4[0]"]],
        depends_on_hi_use_groups=[["hi"]],
    )
    if with_take:
        kwargs["depends_on_hi_take_groups"] = [[
            {"row": {"kind": "same"}, "col": {"kind": "all", "op": "or"}}]]
    sig2 = PowerRail(
        "SIG2[0]", "output", group_base="SIG2", bit_index=0,
        width_expr="NUM_CPU", dim_params=["NUM_CPU"], **kwargs,
    )
    return sig2, {"SIG4[0]": sig4, "SIG2[0]": sig2}


class TestResolveTakeRef:
    def test_dim_ref_with_take_resolves_to_take_ref(self):
        sig2, n2r = _sig4_sig2(with_take=True)
        tree = resolve_condition(sig2, "hi", n2r)
        assert isinstance(tree, AnyGroup)
        item = tree.groups[0].items[0]
        assert isinstance(item, TakeRef)
        assert item.base == "SIG4"
        assert item.use == "hi"
        assert item.ref_ndim == 2
        assert item.col_size == "NUM_CPU_MEM"
        assert item.row == Take("same", "", "and")
        assert item.col == Take("all", "", "or")

    def test_row_size_from_first_dim(self):
        sig2, n2r = _sig4_sig2(with_take=True)
        item = resolve_condition(sig2, "hi", n2r).groups[0].items[0]
        assert item.row_size == "NUM_CPU"

    def test_row_lower_bound_passes_through(self):
        # 1D All 歸約的下界 lo 必須經 IR 原樣帶到 TakeRef.row（不得在 IR 丟掉）
        sig4 = PowerRail(
            "SIG4[0]", "output", group_base="SIG4", bit_index=0,
            width_expr="NUM_CPU", dim_params=["NUM_CPU"],
        )
        sig2 = PowerRail(
            "SIG2[0]", "output", group_base="SIG2", bit_index=0,
            width_expr="1", dim_params=[],
            depends_on_hi=["SIG4[0]"],
            depends_on_hi_groups=[["SIG4[0]"]],
            depends_on_hi_use_groups=[["hi"]],
            depends_on_hi_take_groups=[[{"row": {"kind": "all", "op": "or", "lo": 1}}]],
        )
        item = resolve_condition(sig2, "hi", {"SIG4[0]": sig4, "SIG2[0]": sig2}).groups[0].items[0]
        assert isinstance(item, TakeRef)
        assert item.row == Take("all", "", "or", 1)

    def test_dim_ref_without_take_stays_cond(self):
        sig2, n2r = _sig4_sig2(with_take=False)
        tree = resolve_condition(sig2, "hi", n2r)
        item = tree.groups[0].items[0]
        assert not isinstance(item, TakeRef)


class TestVerilogTakeLeaf:
    def test_renders_symbolic_take(self):
        from codegen.verilog_generator import _VerilogCond
        sig2, n2r = _sig4_sig2(with_take=True)
        item = resolve_condition(sig2, "hi", n2r).groups[0].items[0]
        assert item.accept(_VerilogCond(n2r)) == "|sig4_hi[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]"


class TestPlaceholderBackendsRaise:
    def test_c_backend_placeholder_raises(self):
        from codegen.c_generator import _CCond
        sig2, n2r = _sig4_sig2(with_take=True)
        item = resolve_condition(sig2, "hi", n2r).groups[0].items[0]
        with pytest.raises(NotImplementedError):
            item.accept(_CCond("x", n2r))


# B3：維度 vector 的條件改走 generate-for，修好 1D←2D 幾何 bug。
def _two_dim_bug_config():
    from core.config_models import Parameter

    rails = [
        PowerRail(f"SIG4[{i}]", "output", group_base="SIG4", bit_index=i,
                  width_expr="NUM_CPU*NUM_CPU_MEM",
                  dim_params=["NUM_CPU", "NUM_CPU_MEM"])
        for i in range(8)
    ]
    rails.append(PowerRail(
        "SIG2[0]", "output", group_base="SIG2", bit_index=0,
        width_expr="NUM_CPU", dim_params=["NUM_CPU"],
        depends_on_hi=["SIG4[0]"],
        depends_on_hi_groups=[["SIG4[0]"]],
        depends_on_hi_use_groups=[["hi"]],
        depends_on_hi_take_groups=[[{"row": {"kind": "same"},
                                     "col": {"kind": "all", "op": "or"}}]],
    ))
    rails.append(PowerRail("SIG2[1]", "output", group_base="SIG2", bit_index=1,
                           width_expr="NUM_CPU", dim_params=["NUM_CPU"]))
    return PowerSeqConfig(
        rails=rails,
        parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 4)],
        dimensions=["NUM_CPU", "NUM_CPU_MEM"],
    )


class TestVerilogGenerateFor:
    def _verilog(self):
        from codegen.verilog_generator import generate_verilog
        return generate_verilog(_two_dim_bug_config())

    def test_generate_for_loop_emitted(self):
        out = self._verilog()
        assert "genvar gv_row;" in out
        assert "genvar gv_col;" in out
        assert "for (gv_row=0; gv_row<NUM_CPU; gv_row=gv_row+1)" in out

    def test_sig2_take_rhs_correct(self):
        out = self._verilog()
        assert "assign sig2_hi[gv_row] =" in out
        assert "|sig4_hi[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]" in out

    def test_old_wrong_flat_index_gone(self):
        # 修前的錯誤形式 sig4_hi[1]（row0col1 當 row1）不應再出現
        assert "sig4_hi[1]" not in self._verilog()


def _sig4_2d_rails():
    return [PowerRail(f"SIG4[{i}]", "output", group_base="SIG4", bit_index=i,
                      width_expr="NUM_CPU*NUM_CPU_MEM",
                      dim_params=["NUM_CPU", "NUM_CPU_MEM"]) for i in range(8)]


def _params_dims():
    from core.config_models import Parameter
    return [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 4)], ["NUM_CPU", "NUM_CPU_MEM"]


def _cfg_1d_ref1d_ripple():
    """1D 輸出引用 1D，row 相對偏移 gv_row-1（ripple）。"""
    from core.config_models import Parameter
    rails = [PowerRail(f"SIGB[{i}]", "output", group_base="SIGB", bit_index=i,
                       width_expr="NUM_CPU", dim_params=["NUM_CPU"]) for i in range(2)]
    rails.append(PowerRail(
        "SIG1[0]", "output", group_base="SIG1", bit_index=0,
        width_expr="NUM_CPU", dim_params=["NUM_CPU"],
        depends_on_hi=["SIGB[0]"], depends_on_hi_groups=[["SIGB[0]"]],
        depends_on_hi_use_groups=[["hi"]],
        depends_on_hi_take_groups=[[form_to_take(REL_ROW, -1, 0)]]))
    rails.append(PowerRail("SIG1[1]", "output", group_base="SIG1", bit_index=1,
                           width_expr="NUM_CPU", dim_params=["NUM_CPU"]))
    return PowerSeqConfig(rails=rails, parameters=[Parameter("NUM_CPU", 2)],
                          dimensions=["NUM_CPU"])


def _cfg_2d_ref2d_coloff():
    """2D 輸出引用 2D，row/col 皆對齊 gv_col（ROWOFF_COLOFF n=m=0）。"""
    params, dims = _params_dims()
    rails = _sig4_2d_rails()
    owner = [PowerRail(f"SIGD[{i}]", "output", group_base="SIGD", bit_index=i,
                       width_expr="NUM_CPU*NUM_CPU_MEM",
                       dim_params=["NUM_CPU", "NUM_CPU_MEM"]) for i in range(8)]
    owner[0].depends_on_hi = ["SIG4[0]"]
    owner[0].depends_on_hi_groups = [["SIG4[0]"]]
    owner[0].depends_on_hi_use_groups = [["hi"]]
    owner[0].depends_on_hi_take_groups = [[form_to_take(ROWOFF_COLOFF, 0, 0)]]
    return PowerSeqConfig(rails=rails + owner, parameters=params, dimensions=dims)


def _cfg_1d_ref2d_allcol_and():
    """1D 輸出引用 2D，All col AND（連續窗）。"""
    params, dims = _params_dims()
    rails = _sig4_2d_rails()
    owner = [PowerRail(f"SIGE[{i}]", "output", group_base="SIGE", bit_index=i,
                       width_expr="NUM_CPU", dim_params=["NUM_CPU"]) for i in range(2)]
    owner[0].depends_on_hi = ["SIG4[0]"]
    owner[0].depends_on_hi_groups = [["SIG4[0]"]]
    owner[0].depends_on_hi_use_groups = [["hi"]]
    owner[0].depends_on_hi_take_groups = [[form_to_take(ROWOFF_ALLCOL_AND, 0, 0)]]
    return PowerSeqConfig(rails=rails + owner, parameters=params, dimensions=dims)


class TestVerilogSection6Forms:
    """§6 合法形狀端到端（take_rules → take_expr → generate-for emission）。"""

    def _v(self, cfg):
        from codegen.verilog_generator import generate_verilog
        return generate_verilog(cfg)

    def test_ripple_relative_row(self):
        out = self._v(_cfg_1d_ref1d_ripple())
        assert "assign sig1_hi[gv_row] = (sigb_hi[gv_row-1]);" in out

    def test_2d_output_col_aligned(self):
        out = self._v(_cfg_2d_ref2d_coloff())
        assert "genvar gv_col;" in out
        assert "assign sigd_hi[gv_row*NUM_CPU_MEM + gv_col] = (sig4_hi[gv_row*NUM_CPU_MEM + gv_col]);" in out

    def test_1d_ref_2d_all_col_and(self):
        out = self._v(_cfg_1d_ref2d_allcol_and())
        assert "assign sige_hi[gv_row] = (&sig4_hi[gv_row*NUM_CPU_MEM +: NUM_CPU_MEM]);" in out
