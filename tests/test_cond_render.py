"""各後端把 CondTree 組裝成運算式的結果（group 間 OR、intra_op、group_inv）。

`tests/golden/` 只鎖 `templates/demo_json.json`，而那份 config 全部是單一 group、
`intra_op` 預設 and、沒有任何 `group_inv`——換句話說 group 組裝那層沒有任何回歸保護。
把注入的 bug 餵給黃金測試時，「group 間改成 &」與「intra_op 一律 and」都照樣綠，
所以這裡用一份刻意覆蓋各種形狀的合成 config 補上。

下方期望值取自接 `core.cond_ir` *之前* 的輸出，逐字元對照過，因此是真正的回歸基準。
其餘後端改走 CondTree 時，照樣在這裡加一組。
"""
from core.config_models import PowerRail, PowerSeqConfig
from core.constants import DEP_HIGH, DEP_LOW
from codegen.verilog_generator import generate_verilog

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


def test_verilog_group_assembly():
    lines = [
        ln.strip()
        for ln in generate_verilog(SYNTH, "synth.v").splitlines()
        if ln.strip().startswith(("assign mixed_", "assign legacy_", "assign bare_"))
    ]
    assert lines == EXPECTED_VERILOG_ASSIGNS
