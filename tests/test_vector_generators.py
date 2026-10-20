"""B5 產生器（整數寬度）測試。

守住兩件事：
  1. Verilog 遇群組 rail 只在 bit 0 收合輸出一條 bus（port/wire/cond wire/PSEQCELL/DEB 皆加寬
     WIDTH=k），其餘 bit 不另外產生訊號。body assign 用 bit 0 的條件代表。
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

    def test_output_body_assign_uses_bit0_condition(self):
        out = generate_verilog(_vector_config())
        assert "assign vout_hi = (iEN);" in out

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


class TestCVectorExpands:
    def test_n_members_and_handles(self):
        out = generate_c(_vector_config())
        # 扁平 rails → 逐 bit 各一個 pwrcell member / handle
        assert "pwrcell_t vout_0" in out
        assert "pwrcell_t vout_1" in out
        assert out.count("pwrcell_handle(&power_var.vout_0") == 1
        assert out.count("pwrcell_handle(&power_var.vout_1") == 1
