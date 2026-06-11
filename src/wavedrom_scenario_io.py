"""
WaveDrom input settings (WaveDromScenario) JSON I/O.
"""
from __future__ import annotations

import json
import os

from config_models import PowerSeqConfig, apply_input_wave_dict, build_wavedrom_scenario
from wavedrom_sim import InputWaveSpec, WaveDromScenario, default_scenario_for_config


def merge_scenario_for_config(
    loaded: WaveDromScenario, config: PowerSeqConfig,
) -> WaveDromScenario:
    """Keep only input nodes that exist in the current project."""
    defaults = build_wavedrom_scenario(config)
    inputs: dict[str, InputWaveSpec] = {}
    for r in config.rails:
        if r.seq_type != "input":
            continue
        spec = loaded.inputs.get(r.name) or defaults.inputs.get(
            r.name, InputWaveSpec(),
        )
        inputs[r.name] = spec
        apply_input_wave_dict(r, spec.to_dict())
    return WaveDromScenario(
        steps=loaded.steps,
        inputs=inputs,
        hscale=loaded.hscale,
    )


def scenario_to_dict(scenario: WaveDromScenario) -> dict:
    return scenario.to_dict()


def scenario_from_dict(data: dict) -> WaveDromScenario:
    """接受 scenario 本體或含 wavedrom_scenario 包裝的專案 JSON 片段。"""
    if not isinstance(data, dict):
        raise ValueError("Invalid JSON: expected object")
    if "wavedrom_scenario" in data and isinstance(data["wavedrom_scenario"], dict):
        data = data["wavedrom_scenario"]
    if "inputs" not in data and "steps" not in data:
        raise ValueError("Not a WaveDrom scenario file (missing steps/inputs)")
    return WaveDromScenario.from_dict(data)


def load_scenario_file(path: str) -> WaveDromScenario:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        from excel_import import load_wavedrom_scenario_from_excel

        return load_wavedrom_scenario_from_excel(path)
    with open(path, encoding="utf-8") as f:
        return scenario_from_dict(json.load(f))


def save_scenario_file(path: str, scenario: WaveDromScenario) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenario_to_dict(scenario), f, indent=2, ensure_ascii=False)


def sidecar_path_for_project(project_json_path: str) -> str:
    return os.path.splitext(project_json_path)[0] + "_wavedrom_scenario.json"


def resolve_scenario(
    config: PowerSeqConfig,
    project_json_path: str | None = None,
) -> WaveDromScenario:
    """Project wavedrom_scenario, else *_wavedrom_scenario.json sidecar, else defaults."""
    embedded = config.wavedrom_scenario or {}
    if embedded.get("inputs"):
        return merge_scenario_for_config(
            WaveDromScenario.from_dict(embedded), config,
        )
    if project_json_path:
        sidecar = sidecar_path_for_project(project_json_path)
        if os.path.isfile(sidecar):
            return merge_scenario_for_config(load_scenario_file(sidecar), config)
    return build_wavedrom_scenario(config)
