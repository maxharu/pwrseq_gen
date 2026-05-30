"""Tests for wavedrom_scenario_io"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerSeqConfig, PowerRail
from wavedrom_sim import InputWaveSpec, WaveDromScenario
from wavedrom_scenario_io import (
    load_scenario_file,
    merge_scenario_for_config,
    resolve_scenario,
    save_scenario_file,
    scenario_from_dict,
)


def test_roundtrip_file():
    scenario = WaveDromScenario(
        steps=100,
        inputs={"A": InputWaveSpec(hi_mode="custom", hi_wave="0.1.")},
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_scenario_file(path, scenario)
        loaded = load_scenario_file(path)
        assert loaded.steps == 100
        assert loaded.inputs["A"].hi_wave == "0.1."
    finally:
        os.unlink(path)


def test_load_wrapped_in_project_dict():
    wrapped = {"wavedrom_scenario": {"steps": 50, "inputs": {}}}
    s = scenario_from_dict(wrapped)
    assert s.steps == 50


def test_to_dict_omits_unused_waves():
    spec = InputWaveSpec(hi_mode="constant_1", lo_mode="constant_0")
    d = spec.to_dict()
    assert d == {"hi_mode": "constant_1", "lo_mode": "constant_0"}
    assert "hi_wave" not in d


def test_resolve_sidecar(tmp_path):
    proj = tmp_path / "board_pseq.json"
    proj.write_text(json.dumps({"rails": [], "module_name": "T"}), encoding="utf-8")
    sidecar = tmp_path / "board_pseq_wavedrom_scenario.json"
    save_scenario_file(
        str(sidecar),
        WaveDromScenario(
            steps=10,
            inputs={"EKEY": InputWaveSpec(hi_mode="constant_1")},
        ),
    )
    cfg = PowerSeqConfig(
        rails=[PowerRail("EKEY", seq_type="input")],
        module_name="T",
    )
    resolved = resolve_scenario(cfg, str(proj))
    assert resolved.inputs["EKEY"].hi_mode == "constant_1"
