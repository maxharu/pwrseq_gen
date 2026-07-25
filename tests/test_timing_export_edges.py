"""Condition-edge pending: dep trigger polarity follows Inv, not Hi/Lo kind."""
from __future__ import annotations

from config_models import PowerRail, PowerSeqConfig
from timing_export import (
    _build_export_lanes,
    _collect_condition_edge_pending,
    _dep_trigger_step,
)
from timing_sim import InputWaveSpec, TimingScenario, simulate


def test_dep_trigger_step_uses_inv_not_kind():
    bits = [0, 0, 1, 1, 1, 0, 0]
    assert _dep_trigger_step(bits, inv=False) == 2  # rising
    assert _dep_trigger_step(bits, inv=True) == 5  # falling


def test_active_low_en_n_edges_use_inv_polarity():
    """P12V_AUX_EN_N-style: Hi=!PG (inv), Lo=PG; init=1.

    Lo out-fall is triggered by PG rise; Hi out-rise by PG fall.
    Old kind-based heuristic dropped the Lo arrow and mis-aimed Hi.
    """
    cfg = PowerSeqConfig(
        pulses=["Pulse_1us"],
        rails=[
            PowerRail("PG", seq_type="input"),
            PowerRail(
                "EN_N",
                seq_type="output",
                depends_on_hi_groups=[["PG"]],
                depends_on_hi_inv_groups=[[True]],
                depends_on_hi_use_groups=[["self"]],
                depends_on_lo_groups=[["PG"]],
                depends_on_lo_inv_groups=[[False]],
                depends_on_lo_use_groups=[["self"]],
                cycle_hi=1,
                cycle_lo=1,
                init=1,
            ),
        ],
    )
    scenario = TimingScenario(
        steps=24,
        inputs={
            "PG": InputWaveSpec(
                hi_mode="custom",
                hi_wave="0{4}1{20}",
                lo_mode="custom",
                lo_wave="0{12}1{12}",
            ),
        },
    )
    result = simulate(cfg, scenario)
    pg = result.raw_inputs["PG"]
    en = result.output_values["en_n"]
    pg_rise = _dep_trigger_step(pg, inv=False)
    pg_fall = _dep_trigger_step(pg, inv=True)
    en_fall = next(t for t in range(1, len(en)) if en[t - 1] == 1 and en[t] == 0)
    en_rise = next(t for t in range(1, len(en)) if en[t - 1] == 0 and en[t] == 1)
    assert pg_rise is not None and pg_fall is not None
    assert pg_rise < en_fall
    assert pg_fall < en_rise

    _, lanes = _build_export_lanes(cfg, result, None)
    pending = _collect_condition_edge_pending(cfg, result, lanes)
    en_edges = {
        (kind, dep_lane["name"], dep_step, out_lane["name"], out_step)
        for dep_step, out_step, dep_lane, out_lane, kind in pending
        if out_lane["name"] == "oEN_N"
    }
    assert ("lo", "iPG", pg_rise, "oEN_N", en_fall) in en_edges
    assert ("hi", "iPG", pg_fall, "oEN_N", en_rise) in en_edges
