"""
Timing input settings (TimingScenario) JSON I/O.
"""
from __future__ import annotations

import json
import os

from core.config_models import (
    PowerSeqConfig,
    build_timing_scenario,
    merge_scenario_for_config,
)
from core.timing_models import TimingScenario
from excel import load_timing_scenario_from_excel


def scenario_to_dict(scenario: TimingScenario) -> dict:
    return scenario.to_dict()


def scenario_from_dict(data: dict) -> TimingScenario:
    """接受 scenario 本體或含 timing_scenario 包裝的專案 JSON 片段。"""
    if not isinstance(data, dict):
        raise ValueError("Invalid JSON: expected object")
    if "timing_scenario" in data and isinstance(data["timing_scenario"], dict):
        data = data["timing_scenario"]
    if "inputs" not in data and "steps" not in data:
        raise ValueError("Not a timing scenario file (missing steps/inputs)")
    return TimingScenario.from_dict(data)


def load_scenario_file(path: str) -> TimingScenario:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return load_timing_scenario_from_excel(path)
    with open(path, encoding="utf-8") as f:
        return scenario_from_dict(json.load(f))


def save_scenario_file(path: str, scenario: TimingScenario) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenario_to_dict(scenario), f, indent=2, ensure_ascii=False)


def sidecar_path_for_project(project_json_path: str) -> str:
    return os.path.splitext(project_json_path)[0] + "_timing_scenario.json"


def resolve_scenario(
    config: PowerSeqConfig,
    project_json_path: str | None = None,
) -> TimingScenario:
    """Project timing_scenario, else *_timing_scenario.json sidecar, else defaults."""
    embedded = config.timing_scenario or {}
    if embedded.get("inputs"):
        return merge_scenario_for_config(
            TimingScenario.from_dict(embedded), config,
        )
    if project_json_path:
        sidecar = sidecar_path_for_project(project_json_path)
        if os.path.isfile(sidecar):
            return merge_scenario_for_config(load_scenario_file(sidecar), config)
    return build_timing_scenario(config)
