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
from wavedrom_export import format_rail_condition, generate_wavedrom, validate_wavedrom_doc
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

    def test_cond_step_delay_default_1(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("A", seq_type="input"),
                PowerRail(
                    "B",
                    depends_on_hi=["A"],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            cond_step_delay=1,
            inputs={"A": InputWaveSpec(hi_mode="custom", hi_wave="0.1.")},
        )
        result = simulate(cfg, scenario)
        a_hi = next(i for i, v in enumerate(result.raw_inputs["A"]) if v == 1)
        b_hi = next(i for i, v in enumerate(result.output_values["b"]) if v == 1)
        assert b_hi == a_hi + 1

    def test_cond_step_delay_2(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("A", seq_type="input"),
                PowerRail(
                    "B",
                    depends_on_hi=["A"],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            cond_step_delay=2,
            inputs={"A": InputWaveSpec(hi_mode="custom", hi_wave="0.1.")},
        )
        result = simulate(cfg, scenario)
        a_hi = next(i for i, v in enumerate(result.raw_inputs["A"]) if v == 1)
        b_hi = next(i for i, v in enumerate(result.output_values["b"]) if v == 1)
        assert b_hi == a_hi + 2

    def test_output_hi_seen_same_step_as_depend_input_gpio(self):
        """Depends inputs updated before output eval (PRIM H -> PCH EN +1 step, not +2)."""
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("EKEY", seq_type="input"),
                PowerRail("PRIM_VR_EN", seq_type="input"),
                PowerRail(
                    "PCH_P0V85A_EN",
                    depends_on_hi=["EKEY", "PRIM_VR_EN"],
                    depends_on_hi_groups=[["EKEY", "PRIM_VR_EN"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            cond_step_delay=1,
            inputs={
                "EKEY": InputWaveSpec(hi_mode="custom", hi_wave="01"),
                "PRIM_VR_EN": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["EKEY"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
            },
        )
        result = simulate(cfg, scenario)
        sig = "pch_p0v85a_en"
        prim_hi = next(
            i for i, v in enumerate(result.raw_inputs["PRIM_VR_EN"]) if v == 1
        )
        pch_hi = next(i for i, v in enumerate(result.output_values[sig]) if v == 1)
        assert pch_hi == prim_hi + 1

    def test_pch_p125_hi_same_step_as_pg_inputs(self):
        """Topo + per-output PG refresh: both PG high -> hi same step, gpio +1 delay."""
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("EKEY", seq_type="input"),
                PowerRail("PRIM_VR_EN", seq_type="input"),
                PowerRail("PCH_P0V85A_PG", seq_type="input"),
                PowerRail("PVNNAON_PG", seq_type="input"),
                PowerRail(
                    "PCH_P0V85A_EN",
                    depends_on_hi=["EKEY", "PRIM_VR_EN"],
                    depends_on_hi_groups=[["EKEY", "PRIM_VR_EN"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
                PowerRail(
                    "PVNNAON_EN",
                    depends_on_hi=["PCH_P0V85A_EN"],
                    depends_on_hi_groups=[["PCH_P0V85A_EN"]],
                    depends_on_hi_use={"PCH_P0V85A_EN": "hi"},
                    depends_on_hi_use_groups=[["hi"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
                PowerRail(
                    "PCH_P1V25A_EN",
                    depends_on_hi=["PCH_P0V85A_PG", "PVNNAON_PG"],
                    depends_on_hi_groups=[["PCH_P0V85A_PG", "PVNNAON_PG"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=30,
            cond_step_delay=1,
            inputs={
                "EKEY": InputWaveSpec(hi_mode="custom", hi_wave="01"),
                "PRIM_VR_EN": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["EKEY"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
                "PCH_P0V85A_PG": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["PCH_P0V85A_EN"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
                "PVNNAON_PG": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["PVNNAON_EN"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
            },
        )
        result = simulate(cfg, scenario)
        sig = "pch_p1v25a_en"
        pg_step = max(
            next(i for i, v in enumerate(result.raw_inputs["PCH_P0V85A_PG"]) if v),
            next(i for i, v in enumerate(result.raw_inputs["PVNNAON_PG"]) if v),
        )
        hi_step = next(i for i, v in enumerate(result.output_hi_cond[sig]) if v)
        gpio_step = next(i for i, v in enumerate(result.output_values[sig]) if v)
        assert hi_step == pg_step
        assert gpio_step == hi_step + 1

    def test_slps4_one_step_after_slps5(self):
        """SLPS4 depends SLPS5; each level uses cond_step_delay=1 (not same step)."""
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("RSMRST_N", depends_on_hi=["__HIGH__"], cycle_hi=1, init=0),
                PowerRail("SLPS5_N", seq_type="input"),
                PowerRail("SLPS4_N", seq_type="input"),
            ],
        )
        scenario = WaveDromScenario(
            steps=30,
            cond_step_delay=1,
            inputs={
                "SLPS5_N": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["RSMRST_N"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
                "SLPS4_N": InputWaveSpec(
                    hi_mode="depends",
                    hi_groups=[["SLPS5_N"]],
                    hi_inv_groups=[[False]],
                    hi_use_groups=[["self"]],
                ),
            },
        )
        result = simulate(cfg, scenario)
        s5 = next(i for i, v in enumerate(result.raw_inputs["SLPS5_N"]) if v)
        s4 = next(i for i, v in enumerate(result.raw_inputs["SLPS4_N"]) if v)
        assert s4 == s5 + 1

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
        doc2 = generate_wavedrom(
            cfg,
            WaveDromScenario(steps=20, hscale=3, inputs={}),
        )
        assert doc2["config"]["hscale"] == 3
        assert validate_wavedrom_doc(doc, steps=200) == []
        assert all("_deb" not in lane["name"] for lane in doc["signal"])
        assert len(expand_binary_wave(doc["signal"][0]["wave"], 200)) == 200

    def test_edges_per_hi_dep_to_output_rise(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("A", seq_type="input"),
                PowerRail("C", seq_type="input"),
                PowerRail(
                    "B",
                    depends_on_hi=["A", "C"],
                    depends_on_hi_groups=[["A", "C"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            inputs={
                "A": InputWaveSpec(hi_mode="custom", hi_wave="0.1."),
                "C": InputWaveSpec(hi_mode="custom", hi_wave="0..1"),
            },
        )
        doc = generate_wavedrom(cfg, scenario)
        assert "edge" in doc
        assert len(doc["edge"]) >= 2
        assert all("-~>" in e and " Hi " not in e and " Lo " not in e for e in doc["edge"])
        b = cfg.rails[2]
        assert "A" in format_rail_condition(b, "hi")
        assert "C" in format_rail_condition(b, "hi")

    def test_edges_expand_output_hi_cond_to_inputs(self):
        cfg = PowerSeqConfig(
            pulses=["iPulse_1us"],
            rails=[
                PowerRail("EKEY", seq_type="input"),
                PowerRail("PRIM", seq_type="input"),
                PowerRail(
                    "PCH_EN",
                    depends_on_hi=["EKEY", "PRIM"],
                    depends_on_hi_groups=[["EKEY", "PRIM"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
                PowerRail(
                    "PVNN",
                    depends_on_hi=["PCH_EN"],
                    depends_on_hi_groups=[["PCH_EN"]],
                    depends_on_hi_use={"PCH_EN": "hi"},
                    depends_on_hi_use_groups=[["hi"]],
                    depends_on_lo=["__LOW__"],
                    cycle_hi=1,
                    init=0,
                ),
            ],
        )
        scenario = WaveDromScenario(
            steps=20,
            inputs={
                "EKEY": InputWaveSpec(hi_mode="custom", hi_wave="0.1."),
                "PRIM": InputWaveSpec(hi_mode="custom", hi_wave="0..1"),
            },
        )
        doc = generate_wavedrom(cfg, scenario)
        assert doc.get("edge")
        assert not any("PCH_EN" in e for e in doc["edge"])


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
