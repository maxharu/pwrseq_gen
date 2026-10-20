"""C9 產生器 parameter 宣告與符號寬度測試。

Verilog：
  1. Parameter Declare 段輸出 #(parameter NAME = VAL, ...)；無 parameter 沿用佔位註解。
  2. group 收合 bus/WIDTH 由公式 width_expr 轉成符號形式 [(EXPR)-1:0] / .WIDTH((EXPR))。
C：
  1. 檔頭（#include 後、struct 前）輸出 parameter #define 區塊；無 parameter 不輸出。
  2. body 不引用 #define（仍用展開後的具體 N 個 pwrcell）。

無 parameter 的 demo.v/demo.c byte 不變由 tests/test_golden_exports.py 把關，不在此重複。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog
from core.config_models import PowerSeqConfig


def _param_config() -> PowerSeqConfig:
    """兩個 parameter（NUM_CPU=2, NUM_CPU_MEM=3），一個公式寬度 vector output（寬度 NUM_CPU*2=4）。"""
    return PowerSeqConfig.from_dict({
        "module_name": "PWRSEQ_TOP",
        "parameters": [
            {"name": "NUM_CPU", "value": 2},
            {"name": "NUM_CPU_MEM", "value": 3},
        ],
        "rails": [
            {"name": "EN", "seq_type": "input"},
            {
                "name": "VOUT",
                "seq_type": "output",
                "width_expr": "NUM_CPU*2",
                "bits": [{"depends_on_hi_groups": [["EN"]]} for _ in range(4)],
            },
        ],
    })


def _plain_config() -> PowerSeqConfig:
    """無 parameter、整數寬度 vector，用於確認符號化只在有公式時發生。"""
    return PowerSeqConfig.from_dict({
        "module_name": "PWRSEQ_TOP",
        "rails": [
            {"name": "EN", "seq_type": "input"},
            {
                "name": "VOUT",
                "seq_type": "output",
                "width_expr": "2",
                "bits": [{"depends_on_hi_groups": [["EN"]]} for _ in range(2)],
            },
        ],
    })


class TestVerilogParameterDeclare:
    def test_parameter_block_emitted(self):
        out = generate_verilog(_param_config())
        assert "#(" in out
        assert re.search(r"parameter NUM_CPU\s+= 2,", out)
        assert re.search(r"parameter NUM_CPU_MEM\s+= 3", out)

    def test_no_parameters_keeps_placeholder(self):
        out = generate_verilog(_plain_config())
        assert "//    No parameters" in out
        assert "parameter NUM_CPU" not in out


class TestVerilogSymbolicWidth:
    def test_bus_port_symbolic(self):
        out = generate_verilog(_param_config())
        assert "output [(NUM_CPU*2)-1:0] oVOUT" in out

    def test_wire_symbolic(self):
        out = generate_verilog(_param_config())
        assert "wire [(NUM_CPU*2)-1:0] vout;" in out

    def test_pseqcell_width_symbolic(self):
        out = generate_verilog(_param_config())
        pseq_line = next(ln for ln in out.splitlines() if "u_vout " in ln)
        assert ".WIDTH((NUM_CPU*2))" in pseq_line

    def test_integer_width_stays_numeric(self):
        out = generate_verilog(_plain_config())
        assert "output [1:0] oVOUT" in out
        pseq_line = next(ln for ln in out.splitlines() if "u_vout " in ln)
        assert ".WIDTH(2)" in pseq_line


class TestCParameterDefine:
    def test_define_block_emitted(self):
        out = generate_c(_param_config())
        assert re.search(r"#define NUM_CPU\s+2", out)
        assert re.search(r"#define NUM_CPU_MEM\s+3", out)

    def test_define_before_struct(self):
        out = generate_c(_param_config())
        assert out.index("#define NUM_CPU") < out.index("typedef struct")

    def test_no_parameters_no_define(self):
        out = generate_c(_plain_config())
        assert "#define NUM_CPU" not in out

    def test_body_uses_expanded_pwrcells(self):
        out = generate_c(_param_config())
        # 公式寬度 NUM_CPU*2=4 → body 展開成 4 個具體 pwrcell（不引用 #define）
        assert "pwrcell_t vout_0" in out
        assert "pwrcell_t vout_3" in out
