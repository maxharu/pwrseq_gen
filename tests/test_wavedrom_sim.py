"""Tests for wavedrom_sim / wavedrom_export"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig, PowerRail
from wavedrom_sim import (
    InputWaveSpec,
    WaveDromScenario,
    expand_wave_pattern,
    simulate,
    values_to_wave,
)
from wavedrom_export import generate_wavedrom, validate_wavedrom_doc
from wavedrom_sim import expand_binary_wave


class TestExpandWave:
    def test_constant(self):
        assert expand_wave_pattern("constant_0", 5) == [0, 0, 0, 0, 0]
        assert expand_wave_pattern("1", 3) == [1, 1, 1]

    def test_custom_pattern(self):
        assert expand_wave_pattern("0.1.", 4) == [0, 0, 1, 1]


class TestSimulate:
    def test_output_switches_next_step_after_input(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("A", seq_type="input"),
                PowerRail(
                    "B",
                    depends_on_hi=["A"],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    cycle_lo=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            inputs={
                "A": InputWaveSpec(
                    hi_mode="custom",
                    hi_wave="0.1.",
                ),
            },
        )
        result = simulate(cfg, scenario)
        b_sig = "b"
        a_high_step = next(i for i, v in enumerate(result.raw_inputs["A"]) if v == 1)
        b_high_step = next(i for i, v in enumerate(result.output_values[b_sig]) if v == 1)
        assert b_high_step == a_high_step + 1

    def test_generate_wavedrom_structure(self):
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("A", seq_type="input"),
                PowerRail("B", depends_on_hi=["__HIGH__"], cycle_hi=1),
            ],
        )
        doc = generate_wavedrom(cfg)
        assert "signal" in doc
        assert len(doc["signal"]) >= 2
        assert doc["signal"][0]["name"] == "iA"
        assert doc["signal"][1]["name"] == "oB"
        assert all(isinstance(lane, dict) and "name" in lane for lane in doc["signal"])
        assert doc.get("config", {}).get("skin") == "narrow"
        assert doc.get("config", {}).get("hscale", 1) == 1
        assert validate_wavedrom_doc(doc, steps=200) == []
        assert all("_deb" not in lane["name"] for lane in doc["signal"])
        assert len(expand_binary_wave(doc["signal"][0]["wave"], 200)) == 200


class TestValuesToWave:
    def test_all_high_bookended(self):
        w = values_to_wave([1] * 200)
        assert w == "1" + "." * 198 + "1"
        assert len(w) == 200
        assert expand_binary_wave(w, 200) == [1] * 200

    def test_all_low_bookended(self):
        w = values_to_wave([0] * 5)
        assert w == "0...0"
        assert expand_binary_wave(w, 5) == [0] * 5

    def test_mixed_uses_dots(self):
        w = values_to_wave([0, 0, 1, 1, 1])
        assert w == "0.1.."
        assert expand_binary_wave(w, 5) == [0, 0, 1, 1, 1]


class TestOutputDelayed:
    def test_hi_prev_step_rises_next_step(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail(
                    "B",
                    depends_on_hi=["__HIGH__"],
                    depends_on_lo=["__LOW__"],
                    init=0,
                ),
            ],
        )
        result = simulate(cfg, WaveDromScenario(steps=5))
        assert result.output_values["b"][:3] == [0, 1, 1]

    def test_hi_and_lo_both_prev_high_stays_high(self):
        """Hi&Lo 上一格同時成立時，高態不拉回低（避免 1010 抖盪）。"""
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail(
                    "EN",
                    depends_on_hi=["__HIGH__"],
                    depends_on_lo=["__HIGH__"],
                    init=0,
                ),
            ],
        )
        result = simulate(cfg, WaveDromScenario(steps=30))
        en = result.output_values["en"]
        first_hi = next(i for i, v in enumerate(en) if v)
        assert all(v == 1 for v in en[first_hi:])
        assert sum(1 for i in range(1, len(en)) if en[i] != en[i - 1]) <= 1


class TestInputDependsSignal:
    def test_input_follows_output_next_step(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("B", depends_on_hi=["__HIGH__"], cycle_hi=1, init=0),
                PowerRail("A", seq_type="input"),
            ],
        )
        scenario = WaveDromScenario(
            steps=15,
            inputs={
                "A": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["B"]],
                ),
            },
        )
        result = simulate(cfg, scenario)
        b_high = next(
            i for i, v in enumerate(result.output_values["b"]) if v == 1
        )
        a_high = next(
            i for i, v in enumerate(result.raw_inputs["A"]) if v == 1
        )
        assert a_high == b_high + 1
