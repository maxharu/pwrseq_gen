"""B5 產生器（整數寬度）測試。

守住兩件事：
  1. Verilog 遇群組 rail 只在 bit 0 收合輸出一條 bus（port/wire/cond wire/PSEQCELL/DEB 皆加寬
     WIDTH=k），其餘 bit 不另外產生訊號；但 condition assign 逐 bit 索引展開（每 bit 渲染自己的條件）。
  2. C 逐 rail 自然產生 N 個 pwrcell（扁平 rails 已是 N 個，零結構改動）。

無 vector 的 demo.v / demo.c byte 不變由 tests/test_golden_exports.py 把關，不在此重複。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog
from core.config_models import ConditionConfig, PowerRail, PowerSeqConfig, VectorNode


def _vector_config() -> PowerSeqConfig:
    """一個 scalar input（EN）、一個 vector input（VIN，含 debounce）、一個 vector output（VOUT）。"""
    en = PowerRail("EN", seq_type="input", deb_enable=False)
    vin = VectorNode(
        base="VIN",
        seq_type="input",
        width_expr="2",
        bit_conds=[ConditionConfig(), ConditionConfig()],
    )
    vout = VectorNode(
        base="VOUT",
        seq_type="output",
        width_expr="2",
        bit_conds=[
            ConditionConfig(depends_on_hi_groups=[["EN"]]),
            ConditionConfig(depends_on_hi_groups=[["EN"]]),
        ],
    )
    rails = [en] + vin.elaborate() + vout.elaborate()
    return PowerSeqConfig(rails=rails)


class TestVerilogVectorCollapse:
    def test_output_bus_port_and_wire(self):
        out = generate_verilog(_vector_config())
        # VOUT 為最後一個 port（結尾逗號會被去除），只斷言 bus 宣告本體
        assert "output [1:0] oVOUT" in out
        assert "wire [1:0] vout;" in out
        assert "wire [1:0] vout_hi" in out

    def test_single_pseqcell_width_k(self):
        out = generate_verilog(_vector_config())
        # 只有一個 PSEQCELL 實例代表整個群組，WIDTH=k
        assert out.count("u_vout ") == 1
        pseq_line = next(ln for ln in out.splitlines() if "u_vout " in ln)
        assert ".WIDTH(2)" in pseq_line
        # 其餘 bit 不另外產生訊號
        assert "vout_1" not in out
        assert "u_vout_0" not in out

    def test_output_body_assign_per_bit(self):
        out = generate_verilog(_vector_config())
        lines = out.splitlines()
        # 逐 bit 索引 assign（每 bit 三行），取代整條 bus 的單一 assign
        assert "    assign vout_hi[0] = (iEN);" in lines
        assert "    assign vout_hi[1] = (iEN);" in lines
        assert "    assign vout_lo[0] = 1'b0;  // No Lo condition (F-DEP-06)" in lines
        assert "    assign vout_force[1] = 1'b0;  // No Force condition" in lines
        # 舊的整條 bus assign 消失（condition wire 宣告行是 "vout_hi," 不含 " = "）
        assert "assign vout_hi = " not in out

    def test_continuous_assignment_bus(self):
        out = generate_verilog(_vector_config())
        assert re.search(r"assign oVOUT\s*=\s*vout;", out)

    def test_input_vector_deb_bus_width_k(self):
        out = generate_verilog(_vector_config())
        assert "input  [1:0] iVIN," in out
        assert "wire [1:0] vin_deb;" in out
        assert out.count("u_deb_vin ") == 1
        deb_line = next(ln for ln in out.splitlines() if "u_deb_vin " in ln)
        assert ".WIDTH(2)" in deb_line
        assert "vin_1" not in out


class TestCVectorArray:
    """甲案：群組收合成陣列宣告 `pwrcell_t base[N];` + 所有引用改索引 `base[i]`；條件仍逐 bit。"""

    def test_array_declaration_replaces_per_bit_members(self):
        out = generate_c(_vector_config())
        assert "pwrcell_t vout[2];" in out
        # 不再有逐 bit 的成員名
        assert "pwrcell_t vout_0" not in out
        assert "pwrcell_t vout_1" not in out
        assert "vout_0" not in out
        assert "vout_1" not in out

    def test_handle_loop_with_gpio_table(self):
        out = generate_c(_vector_config())
        # 專屬 typedef（自成一體，不要求改 firmware）
        assert "typedef struct { GPIO_T* port; UINT32 pin; } pwrseq_gpio_ref_t;" in out
        # 每個 vector base 一張 GPIO 表，用 header 既有的 _PORT / _BIT 符號
        assert (
            "static const pwrseq_gpio_ref_t vout_gpio[2] = "
            "{ { VOUT_0_PORT, VOUT_0_BIT }, { VOUT_1_PORT, VOUT_1_BIT } };"
        ) in out
        # for 迴圈取代 N 行離散 handle；GPIO 由表索引取代單一 macro
        assert "for (UINT8 i = 0; i < 2; i++)" in out
        assert "pwrcell_handle(&power_var.vout[i]," in out
        assert "vout_gpio[i].port, vout_gpio[i].pin" in out
        # 舊的逐行離散 handle 消失
        assert "pwrcell_handle(&power_var.vout[0]" not in out
        assert "pwrcell_handle(&power_var.vout[1]" not in out

    def test_per_bit_conditions_indexed(self):
        out = generate_c(_vector_config())
        # 逐 bit 各自一行條件賦值，用索引
        assert "power_var.vout[0].hi.condition" in out
        assert "power_var.vout[1].hi.condition" in out

    def test_indexed_init_calls(self):
        out = generate_c(_vector_config())
        assert "pwrcell_Init(&power_var.vout[0]" in out
        assert "pwrcell_Init(&power_var.vout[1]" in out


def _vector_diff_bits_config() -> PowerSeqConfig:
    """各 bit 條件不同的 vector：bit 0 無 Hi（恆真 + 注解），bit 1 Hi 依賴 scalar EN。"""
    en = PowerRail("EN", seq_type="input", deb_enable=False)
    vout = VectorNode(
        base="VOUT",
        seq_type="output",
        width_expr="2",
        bit_conds=[
            ConditionConfig(),
            ConditionConfig(depends_on_hi_groups=[["EN"]]),
        ],
    )
    return PowerSeqConfig(rails=[en] + vout.elaborate())


class TestVerilogVectorPerBitBody:
    """逐 bit assign 真正各渲染自己的條件（不是用 bit 0 代表整組）。"""

    def test_per_bit_conditions_differ(self):
        out = generate_verilog(_vector_diff_bits_config())
        lines = out.splitlines()
        # bit 0 無 Hi → 恆真 + No-condition 注解
        assert "    assign vout_hi[0] = 1'b1;  // No Hi condition" in lines
        # bit 1 有 Hi 依賴 EN（scalar）→ 無注解
        assert "    assign vout_hi[1] = (iEN);" in lines
        # 兩 bit 各自成立：bit 0 不是也渲染成 (iEN)
        assert "    assign vout_hi[0] = (iEN);" not in lines


def _vector_and_scalar_cond_config() -> PowerSeqConfig:
    """同時含 vector（有 width 前綴 `[1:0]`）與純量 cond head，用來驗證 condition wire 對齊。"""
    en_a = VectorNode(base="EN_A", seq_type="output", width_expr="2",
                      bit_conds=[ConditionConfig(), ConditionConfig()])
    en_b = PowerRail("EN_B", seq_type="output")
    return PowerSeqConfig(rails=en_a.elaborate() + [en_b])


class TestVerilogCondWireAlign:
    """condition signal wire 宣告：純量行在 `wire` 後補等寬空白，使 `_hi` 名稱與 vector 行對齊。"""

    def test_scalar_wire_aligns_with_vector(self):
        out = generate_verilog(_vector_and_scalar_cond_config())
        lines = out.splitlines()
        vline = next(line for line in lines if "en_a_hi" in line)
        sline = next(line for line in lines if "en_b_hi" in line)
        # 純量行 `wire` 後補了空白（不是緊接名稱）
        assert sline.startswith("wire  ")
        # 兩行的 `_hi` 名稱起始欄位相同
        assert vline.index("en_a_hi") == sline.index("en_b_hi")


def _vector_cross_bit_config() -> PowerSeqConfig:
    """某 vector output 的 bit 條件引用別 vector 的對應 bit，覆蓋四類葉節點：
    input-有-deb / input-無-deb / output-準位 / cond（use=force）。"""
    pg = VectorNode(base="PG", seq_type="input", width_expr="2",
                    bit_conds=[ConditionConfig(), ConditionConfig()])   # input 有 deb（預設 deb_enable=True）
    pg2 = VectorNode(base="PG2", seq_type="input", width_expr="2",
                     bit_conds=[ConditionConfig(), ConditionConfig()])  # 下面關掉 deb
    va = VectorNode(base="VA", seq_type="output", width_expr="2",
                    bit_conds=[ConditionConfig(), ConditionConfig()])
    vout = VectorNode(base="VOUT", seq_type="output", width_expr="2", bit_conds=[
        ConditionConfig(depends_on_hi_groups=[["PG[0]"]],       # input 有 deb → pg_deb[0]
                        depends_on_lo_groups=[["PG2[0]"]]),     # input 無 deb → iPG2[0]
        ConditionConfig(depends_on_hi_groups=[["VA[1]"]],       # output 準位 → va[1]
                        depends_on_force_groups=[["VA[1]"]],    # cond（use=force）→ va_force[1]
                        depends_on_force_use_groups=[["force"]]),
    ])
    pg2_rails = pg2.elaborate()
    for r in pg2_rails:
        r.deb_enable = False
    return PowerSeqConfig(rails=pg.elaborate() + pg2_rails + va.elaborate() + vout.elaborate())


class TestVerilogCrossBitLeaf:
    """跨 bit 葉節點參照：引用別 vector 的具體 bit → 收合 bus 的索引（非壞名稱 pg_0_deb）。"""

    def test_cross_bit_leaf_indexed(self):
        out = generate_verilog(_vector_cross_bit_config())
        lines = out.splitlines()
        assert "    assign vout_hi[0] = (pg_deb[0]);" in lines        # input 有 deb
        assert "    assign vout_lo[0] = (iPG2[0]);" in lines          # input 無 deb
        assert "    assign vout_hi[1] = (va[1]);" in lines            # output 準位
        assert "    assign vout_force[1] = (va_force[1]);" in lines   # cond（use=force）
        # 舊的壞名稱全部消失
        assert "pg_0_deb" not in out
        assert "iPG2_0" not in out
        assert "va_1" not in out
