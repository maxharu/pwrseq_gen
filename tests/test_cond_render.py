"""各後端把 CondTree 組裝成運算式的結果（group 間 OR、intra_op、group_inv）。

`tests/golden/` 只鎖 `templates/demo_json.json`，而那份 config 全部是單一 group、
`intra_op` 預設 and、沒有任何 `group_inv`——換句話說 group 組裝那層沒有任何回歸保護。
把注入的 bug 餵給黃金測試時，「group 間改成 &」與「intra_op 一律 and」都照樣綠，
所以這裡用一份刻意覆蓋各種形狀的合成 config 補上。

下方期望值取自接 `core.cond_ir` *之前* 的輸出，逐字元對照過，因此是真正的回歸基準。
其餘後端改走 CondTree 時，照樣在這裡加一組。
"""
import pytest

from core.cond_ir import resolve_condition
from core.config_models import PowerRail, PowerSeqConfig
from core.constants import DEP_HIGH, DEP_LOW
from core.naming import internal_sig
from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog
from drawio.drawio_cell_export import _exported_hilo_keys, _parse_path_group_terms
from timing.timing_sim import _SimCond

SYNTH = PowerSeqConfig(
    module_name="synth",
    rails=[
        PowerRail(name="IN_DEB", seq_type="input", deb_enable=True),
        PowerRail(name="IN_RAW", seq_type="input", deb_enable=False),
        PowerRail(name="BASE", seq_type="output", depends_on_hi=[DEP_HIGH]),
        PowerRail(
            name="MIXED",
            seq_type="output",
            # 三個 group：xor + 整組反相 / 單一反相常數 / or + 整組反相，
            # 並混入單項 inv、input 殘留的 use=hi、output 的 use=force
            depends_on_hi_groups=[["IN_DEB", "BASE"], [DEP_HIGH], ["IN_RAW", "BASE", DEP_LOW]],
            depends_on_hi_inv_groups=[[True, False], [True], [False, True, True]],
            depends_on_hi_use_groups=[["self", "hi"], ["self"], ["hi", "force", "self"]],
            depends_on_hi_intra_op=["xor", "and", "or"],
            depends_on_hi_group_inv=[True, False, True],
            # 中間夾一個空 group，且該空 group 帶整組反相
            depends_on_lo_groups=[["BASE"], [], ["IN_RAW"]],
            depends_on_lo_use_groups=[["lo"], [], ["lo"]],
            depends_on_lo_group_inv=[False, True, False],
            depends_on_force_groups=[["BASE", "IN_DEB"]],
            depends_on_force_use_groups=[["force", "force"]],
            depends_on_force_intra_op=["or"],
        ),
        # 舊格式扁平 depends_on_*（inv / use 存在 dict 裡）
        PowerRail(
            name="LEGACY",
            seq_type="output",
            depends_on_hi=["BASE", "IN_RAW"],
            depends_on_hi_inv={"BASE": True},
            depends_on_hi_use={"BASE": "lo", "IN_RAW": "hi"},
        ),
        PowerRail(name="BARE", seq_type="output"),
    ],
)

EXPECTED_VERILOG_ASSIGNS = [
    "assign mixed_hi = !((~in_deb_deb) ^ base_hi) | (1'b0) | !(iIN_RAW | (~base_force) | 1'b1);",
    "assign mixed_lo = (base_lo) | !1'b0 | (iIN_RAW);",
    "assign mixed_force = (base_force | in_deb_deb);",
    "assign legacy_hi = ((~base_lo) & iIN_RAW);",
    "assign legacy_lo = 1'b0;  // No Lo condition (F-DEP-06)",
    "assign legacy_force = 1'b0;  // No Force condition",
    "assign bare_hi = 1'b1;  // No Hi condition",
    "assign bare_lo = 1'b0;  // No Lo condition (F-DEP-06)",
    "assign bare_force = 1'b0;  // No Force condition",
]


EXPECTED_C_CONDITIONS = [
    "synth_var.mixed .hi.condition    = !((!oemgpio_DI_Get(IN_DEB) ^ synth_var.base.hi.condition))"
    " | (0) | !((oemgpio_DI_Get(IN_RAW) | !synth_var.base.force.condition | 1));",
    "synth_var.mixed .lo.condition    = (synth_var.base.lo.condition) | !(0)"
    " | (oemgpio_DI_Get(IN_RAW));",
    "synth_var.mixed .force.condition = (synth_var.base.force.condition | oemgpio_DI_Get(IN_DEB));",
    "synth_var.legacy.hi.condition    = (!synth_var.base.lo.condition & oemgpio_DI_Get(IN_RAW));",
    "synth_var.legacy.lo.condition    = 0;",
    "synth_var.legacy.force.condition = 0;",
    "synth_var.bare  .hi.condition    = 1;",
    "synth_var.bare  .lo.condition    = 0;",
    "synth_var.bare  .force.condition = 0;",
]


def test_verilog_group_assembly():
    lines = [
        ln.strip()
        for ln in generate_verilog(SYNTH, "synth.v").splitlines()
        if ln.strip().startswith(("assign mixed_", "assign legacy_", "assign bare_"))
    ]
    assert lines == EXPECTED_VERILOG_ASSIGNS


def test_c_group_assembly():
    lines = [
        ln.strip()
        for ln in generate_c(SYNTH, "synth.c").splitlines()
        if ".condition" in ln and ln.strip().startswith("synth_var.")
        and not ln.strip().startswith("synth_var.base")
    ]
    assert lines == EXPECTED_C_CONDITIONS


# ---- 模擬器 ------------------------------------------------------------

NAME_TO_RAIL = {r.name: r for r in SYNTH.rails}
BASE = internal_sig("BASE")


def _sim(rail_name, kind, raw=None, out_hi=None, out_lo=None, out_val=None):
    tree = resolve_condition(NAME_TO_RAIL[rail_name], kind, NAME_TO_RAIL)
    return tree.accept(
        _SimCond(NAME_TO_RAIL, raw or {}, out_hi or {}, out_lo or {}, out_val or {})
    )


@pytest.mark.parametrize("in_deb,base_hi,want", [(0, 0, 0), (1, 0, 1), (0, 1, 1), (1, 1, 0)])
def test_sim_mixed_hi_reduces_to_the_xor_group(in_deb, base_hi, want):
    """第 2 組是反相常數 1 → 0；第 3 組含常數 1 的 or 恆真、整組反相 → 0。
    因此整條只剩第 1 組：!((~IN_DEB) ^ BASE.hi)。"""
    got = _sim("MIXED", "hi", raw={"IN_DEB": in_deb}, out_hi={BASE: base_hi})
    assert got == want


@pytest.mark.parametrize("base_lo,in_raw", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_sim_mixed_lo_is_pinned_high_by_the_inverted_empty_group(base_lo, in_raw):
    """空 group 求值為 0，帶整組反相後變成 1，而 group 間是 OR。"""
    assert _sim("MIXED", "lo", raw={"IN_RAW": in_raw}, out_lo={BASE: base_lo}) == 1


@pytest.mark.parametrize("in_deb", [0, 1])
def test_sim_mixed_force_follows_in_deb_only(in_deb):
    """(BASE.force | IN_DEB)，而模擬器的 force 條件恆為 0（KNOWN_SIM_DIVERGENCE）。"""
    assert _sim("MIXED", "force", raw={"IN_DEB": in_deb}, out_val={BASE: 1}) == in_deb


@pytest.mark.parametrize("base_lo,in_raw,want", [(0, 0, 0), (0, 1, 1), (1, 0, 0), (1, 1, 0)])
def test_sim_legacy_hi_is_and_of_inverted_cond_and_level(base_lo, in_raw, want):
    got = _sim("LEGACY", "hi", raw={"IN_RAW": in_raw}, out_lo={BASE: base_lo})
    assert got == want


def test_sim_bare_uses_the_empty_condition_defaults():
    assert (_sim("BARE", "hi"), _sim("BARE", "lo"), _sim("BARE", "force")) == (1, 0, 0)


# ---- Draw.io ----------------------------------------------------------

def _drawio_groups(rail_name, hl):
    parsed = _parse_path_group_terms(NAME_TO_RAIL[rail_name], hl, NAME_TO_RAIL, set(NAME_TO_RAIL))
    return [[(t.text, t.is_cond) for t in group] for group in parsed]


def test_drawio_drops_undrawable_terms_and_empty_groups():
    """常數與 Force 條件畫不出來，整組只剩常數時該 group 不該留下空殼。"""
    assert _drawio_groups("MIXED", "hi") == [
        # 第 1 組：準位（帶 ~）+ 條件訊號
        [("~IN_DEB", False), ("base_hi", True)],
        # 第 2 組只有反相常數 → 整組消失；第 3 組的 BASE use=force 與 __LOW__ 也被丟掉，
        # IN_RAW 雖然帶 use=hi 但它是 input，退化為準位
        [("IN_RAW", False)],
    ]
    assert _drawio_groups("MIXED", "lo") == [[("base_lo", True)], [("IN_RAW", False)]]
    assert _drawio_groups("LEGACY", "hi") == [[("~base_lo", True), ("IN_RAW", False)]]


def test_drawio_no_condition_draws_no_gate():
    assert _drawio_groups("BARE", "hi") == []
    assert _drawio_groups("LEGACY", "lo") == []


def test_drawio_exported_cond_signals_exclude_force():
    """只有被當成條件引用的 xxx_hi / xxx_lo 要拉線出來，Force 不畫所以不算。"""
    assert _exported_hilo_keys(SYNTH) == {("BASE", "hi"), ("BASE", "lo")}
