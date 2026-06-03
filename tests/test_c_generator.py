"""Tests for c_generator.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig, PowerRail
from c_generator import (
    generate_c,
    _filename_to_c_names,
    _pulse_time_field,
)


class TestFilenameToCNames:
    def test_power_c(self):
        guard, prefix, var = _filename_to_c_names("power.c")
        assert guard == "POWER_C"
        assert prefix == "power"
        assert var == "power_var"

    def test_x15(self):
        guard, prefix, var = _filename_to_c_names("x15snw_pseq.c")
        assert guard == "X15SNW_PSEQ_C"
        assert prefix == "x15snw_pseq"
        assert var == "x15snw_pseq_var"


class TestPulseTimeField:
    def test_1ms(self):
        assert _pulse_time_field("iPulse_1ms") == "t_1ms"

    def test_high_none(self):
        assert _pulse_time_field("High") is None


class TestGenerateC:
    def test_guard_and_include(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1ms"],
            rails=[PowerRail("OUT1", depends_on_hi=["__HIGH__"], pulse_hi="iPulse_1ms")],
        )
        out = generate_c(cfg, output_filename="power.c")
        assert "#ifndef POWER_C" in out
        assert '#include "_user.h"' in out
        assert "pwrcell_t out1;" in out
        assert "void power_Init(void)" in out
        assert "void power_mainLoop(void)" in out

    def test_hi_lo_conditions(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B", depends_on_hi=["A"], depends_on_lo=["__LOW__"]),
        ])
        out = generate_c(cfg, output_filename="power.c")
        assert "oemgpio_DI_Get(A)" in out
        assert ".hi.condition" in out
        assert ".lo.condition" in out
        assert "pwrcell_handle(&power_var.b" in out

    def test_self_output_uses_actual_level(self):
        """self on output 應讀該 rail 的實際輸出準位（GPIO 讀回），對齊 Verilog/模擬器。"""
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", depends_on_hi=["__HIGH__"]),
            PowerRail("B", depends_on_lo=["A"]),
        ])
        out = generate_c(cfg, output_filename="power.c")
        assert "power_var.b.lo.condition    = (oemgpio_DI_Get(A));" in out

    def test_timer_isr(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1ms", "iPulse_10ms"],
            rails=[
                PowerRail("A", depends_on_hi=["__HIGH__"], pulse_hi="iPulse_1ms"),
                PowerRail("B", depends_on_hi=["__HIGH__"], pulse_hi="iPulse_10ms", pulse_lo="iPulse_1ms"),
            ],
        )
        out = generate_c(cfg, output_filename="power.c")
        assert "void power_timer_1ms_ISR(void)" in out
        assert "void power_timer_10ms_ISR(void)" in out
        assert "power_var.time.t_10ms" in out

    def test_groups_and_or(self):
        cfg = PowerSeqConfig(rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B", seq_type="input", deb_enable=False),
            PowerRail("C", depends_on_hi=["__HIGH__"], depends_on_hi_groups=[["A", "B"]]),
        ])
        out = generate_c(cfg, output_filename="power.c")
        assert "oemgpio_DI_Get(A) && oemgpio_DI_Get(B)" in out
