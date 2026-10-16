"""各後端把 CondTree 組裝成運算式的結果（group 間 OR、intra_op、group_inv）。

`tests/golden/` 只鎖 `templates/demo_json.json`，而那份 config 全部是單一 group、
`intra_op` 預設 and、沒有任何 `group_inv`——換句話說 group 組裝那層沒有任何回歸保護。
把注入的 bug 餵給黃金測試時，「group 間改成 &」與「intra_op 一律 and」都照樣綠，
所以這裡用一份刻意覆蓋各種形狀的合成 config 補上。

下方期望值取自接 `core.cond_ir` *之前* 的輸出，逐字元對照過，因此是真正的回歸基準。
其餘後端改走 CondTree 時，照樣在這裡加一組。
"""
import pytest

from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog
from core.cond_ir import resolve_condition
from core.config_models import PowerRail, PowerSeqConfig
from core.constants import DEP_HIGH, DEP_LOW
from core.naming import internal_sig
from drawio.drawio_cell_export import _exported_hilo_keys, _parse_path_group_terms
from timing.timing_export import _condition_items, _leaf_deps_for_edge
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


def _sim(rail_name, kind, raw=None, out_hi=None, out_lo=None, out_force=None, out_val=None):
    tree = resolve_condition(NAME_TO_RAIL[rail_name], kind, NAME_TO_RAIL)
    return tree.accept(
        _SimCond(
            NAME_TO_RAIL, raw or {}, out_hi or {}, out_lo or {},
            out_force or {}, out_val or {},
        )
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


@pytest.mark.parametrize("in_deb,base_force,want", [(0, 0, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1)])
def test_sim_mixed_force_is_the_or_of_base_force_and_in_deb(in_deb, base_force, want):
    """`(BASE.force | IN_DEB)`——IN_DEB 是 input，`use=force` 退化為讀準位。

    `out_val` 刻意給相反值，確認 BASE 讀的是 force 條件而不是輸出準位。
    """
    got = _sim(
        "MIXED", "force",
        raw={"IN_DEB": in_deb},
        out_force={BASE: base_force},
        out_val={BASE: 1 - base_force},
    )
    assert got == want


@pytest.mark.parametrize("base_lo,in_raw,want", [(0, 0, 0), (0, 1, 1), (1, 0, 0), (1, 1, 0)])
def test_sim_legacy_hi_is_and_of_inverted_cond_and_level(base_lo, in_raw, want):
    got = _sim("LEGACY", "hi", raw={"IN_RAW": in_raw}, out_lo={BASE: base_lo})
    assert got == want


def test_sim_bare_uses_the_empty_condition_defaults():
    assert (_sim("BARE", "hi"), _sim("BARE", "lo"), _sim("BARE", "force")) == (1, 0, 0)


# ---- Draw.io ----------------------------------------------------------

def _drawio_groups(rail_name, hl):
    parsed = _parse_path_group_terms(NAME_TO_RAIL[rail_name], hl, NAME_TO_RAIL, set(NAME_TO_RAIL))
    return [[(t.text, t.is_cond) for t in group.terms] for group in parsed]


def test_drawio_drops_undrawable_terms_and_empty_groups():
    """常數與 Force 條件畫不出來，整組只剩常數時該 group 不該留下空殼。"""
    assert _drawio_groups("MIXED", "hi") == [
        # 第 1 組：準位（帶 ~）+ 條件訊號
        [("~IN_DEB", False), ("base_hi", True)],
        # 第 2 組只有反相常數 → 整組消失；第 3 組的 BASE use=force 與 __LOW__ 也被丟掉，
        # IN_RAW 雖然帶 use=hi 但它是 input，退化為準位。只剩一項時沒有 merge 閘可以掛
        # 整組反相的泡泡，所以 group_inv 下推到標籤變成 ~IN_RAW。
        [("~IN_RAW", False)],
    ]
    assert _drawio_groups("MIXED", "lo") == [[("base_lo", True)], [("IN_RAW", False)]]
    assert _drawio_groups("LEGACY", "hi") == [[("~base_lo", True), ("IN_RAW", False)]]


def test_drawio_no_condition_draws_no_gate():
    assert _drawio_groups("BARE", "hi") == []
    assert _drawio_groups("LEGACY", "lo") == []


def test_drawio_exported_cond_signals_exclude_force():
    """只有被當成條件引用的 xxx_hi / xxx_lo 要拉線出來，Force 不畫所以不算。"""
    assert _exported_hilo_keys(SYNTH) == {("BASE", "hi"), ("BASE", "lo")}


# ---- 時序圖箭頭追蹤 ----------------------------------------------------

# 鏈：GATE.hi ← IN_A（反相）；RELAY.hi ← GATE.hi；TOP.hi ← RELAY.hi
# 箭頭要一路追到 IN_A，因為只有它有波形可以當起點
CHAIN = PowerSeqConfig(
    module_name="chain",
    rails=[
        PowerRail(name="IN_A", seq_type="input"),
        PowerRail(name="IN_B", seq_type="input"),
        PowerRail(
            name="GATE",
            seq_type="output",
            depends_on_hi=["IN_A"],
            depends_on_hi_inv={"IN_A": True},
            # 給 GATE 一個 Force 條件，才能分辨「引用 force 時有沒有誤遞迴進去」
            depends_on_force=["IN_B"],
        ),
        PowerRail(
            name="RELAY",
            seq_type="output",
            depends_on_hi=["GATE"],
            depends_on_hi_use={"GATE": "hi"},
        ),
        PowerRail(
            name="TOP",
            seq_type="output",
            depends_on_hi=["RELAY", "IN_B"],
            depends_on_hi_inv={"RELAY": True},
            depends_on_hi_use={"RELAY": "hi"},
        ),
        # 自我參照：條件引用自己的 Hi，追蹤時必須在成環處停下
        PowerRail(
            name="LOOP",
            seq_type="output",
            depends_on_hi=["LOOP"],
            depends_on_hi_use={"LOOP": "hi"},
        ),
        # 引用 Force 條件：模擬器不發布它，所以只能指向 GATE 自己的波形
        PowerRail(
            name="FORCED",
            seq_type="output",
            depends_on_hi=["GATE"],
            depends_on_hi_use={"GATE": "force"},
        ),
        # 同一個依賴出現在兩個 group，inv 不同 → 只能取第一次出現的那個
        PowerRail(
            name="DUPED",
            seq_type="output",
            depends_on_hi_groups=[["IN_A"], ["IN_A"]],
            depends_on_hi_inv_groups=[[False], [True]],
        ),
    ],
)
CHAIN_RAILS = {r.name: r for r in CHAIN.rails}


def _leaves(rail_name, kind):
    rail = CHAIN_RAILS[rail_name]
    return [
        (leaf, item.inv ^ path_inv)
        for item in _condition_items(rail, kind, CHAIN_RAILS)
        for leaf, path_inv in _leaf_deps_for_edge(item, CHAIN_RAILS)
    ]


def test_edge_tracing_stops_at_an_input():
    assert _leaves("GATE", "hi") == [("IN_A", True)]


def test_edge_tracing_recurses_through_referenced_conditions():
    """RELAY.hi 讀 GATE.hi，而 GATE.hi 的葉節點是反相的 IN_A，inv 要一路累積。"""
    assert _leaves("RELAY", "hi") == [("IN_A", True)]
    # TOP 對 RELAY 又加一層反相 → 與 GATE 那層的反相互相抵消
    assert _leaves("TOP", "hi") == [("IN_A", False), ("IN_B", False)]


def test_edge_tracing_treats_self_reference_as_its_own_leaf():
    assert _leaves("LOOP", "hi") == [("LOOP", False)]


def test_edge_tracing_does_not_recurse_through_force():
    """模擬器不發布 force 條件，所以引用 force 時只能指向該節點自己的波形。

    GATE 確實有 Force 條件（來自 IN_B），誤遞迴的話葉節點會變成 IN_B。
    """
    assert _leaves("FORCED", "hi") == [("GATE", False)]


def test_edge_tracing_keeps_only_the_first_occurrence_of_a_dep():
    """同一個依賴出現兩次時只畫一次箭頭，inv 取第一次出現的。"""
    assert _leaves("DUPED", "hi") == [("IN_A", False)]


def test_edge_tracing_drops_constants():
    """常數沒有波形可以當箭頭起點。"""
    rails = {"OUT": PowerRail(name="OUT", seq_type="output", depends_on_hi=[DEP_HIGH])}
    assert _condition_items(rails["OUT"], "hi", rails) == []

