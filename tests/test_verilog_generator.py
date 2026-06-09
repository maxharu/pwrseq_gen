"""Tests for verilog_generator.py"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig, PowerRail
from verilog_generator import generate_verilog, _filename_to_module_and_guard


class TestFilenameToModuleAndGuard:
    """依檔名產生 module name 與 guard"""

    def test_my_pwrseq(self):
        mod, guard = _filename_to_module_and_guard("my_pwrseq.v")
        assert mod == "my_pwrseq"
        assert guard == "MY_PWRSEQ_V"

    def test_x15_pseq(self):
        mod, guard = _filename_to_module_and_guard("x15_pseq.v")
        assert mod == "x15_pseq"
        assert guard == "X15_PSEQ_V"

    def test_with_path(self):
        mod, guard = _filename_to_module_and_guard(r"C:\foo\bar\PWRSEQ_TOP.v")
        assert mod == "PWRSEQ_TOP"
        assert guard == "PWRSEQ_TOP_V"

    def test_hyphen_to_underscore(self):
        mod, guard = _filename_to_module_and_guard("test-file.v")
        assert mod == "test_file"
        assert guard == "TEST_FILE_V"

    def test_empty_fallback(self):
        mod, guard = _filename_to_module_and_guard("")
        assert mod == "PWRSEQ_TOP"
        assert guard == "PWRSEQ_TOP_V"

    def test_no_extension(self):
        mod, guard = _filename_to_module_and_guard("my_module")
        assert mod == "my_module"
        assert guard == "MY_MODULE_V"


class TestGenerateVerilog:
    """generate_verilog 輸出測試"""

    def test_has_timescale(self):
        cfg = PowerSeqConfig(rails=[PowerRail("X", depends_on_hi=["__HIGH__"])])
        out = generate_verilog(cfg)
        assert "`timescale 1ns / 1ps" in out

    def test_uses_config_module_name_when_no_filename(self):
        cfg = PowerSeqConfig(
            module_name="MY_CUSTOM_MOD",
            rails=[PowerRail("X", depends_on_hi=["__HIGH__"])],
        )
        out = generate_verilog(cfg)
        assert "module MY_CUSTOM_MOD" in out
        assert "`ifndef MY_CUSTOM_MOD_V" in out
        assert "`define MY_CUSTOM_MOD_V" in out
        assert "endmodule //MY_CUSTOM_MOD" in out
        assert "`endif  //MY_CUSTOM_MOD_V" in out

    def test_uses_filename_when_provided(self):
        cfg = PowerSeqConfig(
            module_name="IGNORED",
            rails=[PowerRail("X", depends_on_hi=["__HIGH__"])],
        )
        out = generate_verilog(cfg, output_filename="my_pwrseq.v")
        assert "module my_pwrseq" in out
        assert "`ifndef MY_PWRSEQ_V" in out
        assert "`define MY_PWRSEQ_V" in out
        assert "endmodule //my_pwrseq" in out
        assert "`endif  //MY_PWRSEQ_V" in out

    def test_has_required_ports(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input"),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        out = generate_verilog(cfg)
        assert "input  iRst" in out
        assert "input  iClk_Core" in out
        assert "input  iA" in out
        assert "output oB" in out
        assert "input  iForce" not in out

    def test_has_pseqcell_for_output(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
        ])
        out = generate_verilog(cfg)
        assert "PSEQCELL" in out
        assert "wire a;" in out  # internal sig is lowercased

    def test_pseqcell_parameters_match_reference(self):
        """PSEQCELL 實例參數須對齊 src/reference/PSEQCELL.v（RECOVER/CYCLE_SYNC/OD 用模組預設）。"""
        cfg = PowerSeqConfig(rails=[
            PowerRail(
                "A",
                depends_on_hi=["__HIGH__"],
                recover=3,
                force_val=0,
                cycle_sync=2,
                od=1,
            ),
        ])
        out = generate_verilog(cfg)
        assert ".CYCLE_FORCE(2)" in out
        assert ".FORCE(0)" in out
        assert ".RECOVER(" not in out
        assert ".CYCLE_SYNC(" not in out
        assert ".OD(" not in out

    def test_pseqcell_cycle_force_and_force_val(self):
        """GUI / JSON 設定的 CYCLE_FORCE、FORCE 須反映於 Verilog PSEQCELL 參數。"""
        cfg = PowerSeqConfig(rails=[
            PowerRail(
                "A",
                depends_on_hi=["__HIGH__"],
                cycle_force=5,
                force_val=1,
            ),
        ])
        out = generate_verilog(cfg)
        assert ".CYCLE_FORCE(5)" in out
        assert ".FORCE(1)" in out

    def test_has_deb_for_input_with_debounce(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=True),
            PowerRail("B", depends_on_hi=["A"]),
        ])
        out = generate_verilog(cfg)
        assert "DEB" in out
        assert "_deb" in out

    def test_hi_lo_assignments(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_hi=["A"], depends_on_lo=["__LOW__"]),
        ])
        out = generate_verilog(cfg)
        assert "_hi =" in out
        assert "_lo =" in out

    def test_continuous_assignment(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("OUT1", depends_on_hi=["__HIGH__"]),
        ])
        out = generate_verilog(cfg)
        assert "assign oOUT1" in out

    def test_empty_rails(self):
        cfg = PowerSeqConfig(rails=[])
        out = generate_verilog(cfg)
        assert "module " in out
        assert "endmodule" in out


class TestGenerateVerilogPulse:
    """Pulse 相關"""

    def test_pulses_in_port(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us", "iPulse_1ms"],
            rails=[
                PowerRail("A", depends_on_hi=["__HIGH__"], pulse_hi="iPulse_1ms"),
            ],
        )
        out = generate_verilog(cfg)
        assert "iPulse_1us" in out
        assert "iPulse_1ms" in out


class TestForceCondition:
    """iForce 依賴條件相關"""

    def test_force_wire_declared(self):
        cfg = PowerSeqConfig(rails=[PowerRail("A", depends_on_hi=["__HIGH__"])])
        out = generate_verilog(cfg)
        assert re.search(r"wire\s+[^;]*\ba_force\b", out)

    def test_force_fallback_to_zero_when_empty(self):
        """無 force 條件時，wXXX_force 接 1'b0（不強制），PSEQCELL.iForce 接 wXXX_force"""
        cfg = PowerSeqConfig(rails=[PowerRail("A", depends_on_hi=["__HIGH__"])])
        out = generate_verilog(cfg)
        assert "assign a_force = 1'b0;" in out
        assert ".iForce(a_force)" in out
        assert "input  iForce" not in out

    def test_force_with_dependency(self):
        """設定 force 條件 → assign 由依賴項組成，PSEQCELL 接 wXXX_force"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B", depends_on_hi=["__HIGH__"], depends_on_force=["A"]),
        ])
        out = generate_verilog(cfg)
        assert "assign b_force = (iA);" in out
        assert ".iForce(b_force)" in out

    def test_force_groups_and_or(self):
        """group 內 &，group 間 |"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B", seq_type="input", deb_enable=False),
            PowerRail("C", seq_type="input", deb_enable=False),
            PowerRail("D",
                     depends_on_hi=["__HIGH__"],
                     depends_on_force_groups=[["A", "B"], ["C"]]),
        ])
        out = generate_verilog(cfg)
        assert "assign d_force = (iA & iB) || (iC);" in out

    def test_force_inverted(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B",
                     depends_on_hi=["__HIGH__"],
                     depends_on_force=["A"],
                     depends_on_force_inv={"A": True}),
        ])
        out = generate_verilog(cfg)
        assert re.search(r"assign b_force = .*~iA", out)

    def test_force_constants(self):
        """High/Low 常數應展開為 1'b1 / 1'b0"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"], depends_on_force=["__LOW__"]),
        ])
        out = generate_verilog(cfg)
        assert "assign a_force = (1'b0);" in out
