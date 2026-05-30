"""
Build WaveJSON from PowerSeqConfig + WaveDromScenario (WaveDrom skill aligned).
"""
from __future__ import annotations

import json

from config_models import PowerSeqConfig
from wavedrom_sim import (
    WaveDromScenario,
    _internal_sig,
    default_scenario_for_config,
    expand_binary_wave,
    simulate,
    values_to_wave,
)

def _port_name(name: str, prefix: str) -> str:
    safe = name.replace(".", "_").replace("-", "_").replace(" ", "_")
    return prefix + safe


def _head_every(steps: int) -> int:
    if steps >= 200:
        return 20
    if steps >= 100:
        return 10
    if steps >= 40:
        return 5
    return 2


def _lane_dict(name: str, bits: list[int], steps: int) -> dict:
    if len(bits) < steps:
        bits = bits + [bits[-1] if bits else 0] * (steps - len(bits))
    elif len(bits) > steps:
        bits = bits[:steps]
    return {"name": name, "wave": values_to_wave(bits)}


def validate_wavedrom_doc(doc: dict, steps: int | None = None) -> list[str]:
    """Quick WaveJSON checks (see .cursor/skills/wavedrom/SKILL.md)."""
    errs: list[str] = []
    signal = doc.get("signal")
    if not isinstance(signal, list) or not signal:
        errs.append("signal must be a non-empty array")
        return errs

    hscale = (doc.get("config") or {}).get("hscale")
    if hscale is not None and (not isinstance(hscale, int) or hscale < 1):
        errs.append("config.hscale must be a positive integer")

    def check_lane(obj: dict, path: str) -> None:
        if "name" not in obj or "wave" not in obj:
            errs.append(f"{path}: lane needs name and wave")
            return
        if steps is not None:
            n = len(expand_binary_wave(str(obj["wave"]), steps))
            if n != steps:
                errs.append(f"{path}: wave length {n} != {steps} steps")

    def walk(entry, path: str) -> None:
        if isinstance(entry, dict) and not entry:
            return
        if isinstance(entry, dict):
            check_lane(entry, path)
        elif isinstance(entry, list):
            if entry and isinstance(entry[0], str):
                for i, child in enumerate(entry[1:], start=1):
                    walk(child, f"{path}[{i}]")
            else:
                for i, child in enumerate(entry):
                    walk(child, f"{path}[{i}]")

    for i, entry in enumerate(signal):
        walk(entry, f"signal[{i}]")
    return errs


def generate_wavedrom(
    config: PowerSeqConfig,
    scenario: WaveDromScenario | None = None,
) -> dict:
    """Produce WaveJSON: flat lanes, skin narrow (minimal vertical gap)."""
    scenario = scenario or default_scenario_for_config(config)
    result = simulate(config, scenario)
    steps = result.steps

    # Flat lanes in config.rails declaration order (top = first declared).
    signals: list = []
    for r in config.rails:
        if r.seq_type == "input":
            signals.append(
                _lane_dict(
                    _port_name(r.name, "i"),
                    result.raw_inputs.get(r.name, []),
                    steps,
                )
            )
        elif r.has_pseqcell:
            sig = _internal_sig(r.name)
            signals.append(
                _lane_dict(
                    _port_name(r.name, "o"),
                    result.output_values.get(sig, []),
                    steps,
                )
            )
    if not signals:
        signals = [{"name": "_empty", "wave": "0"}]

    doc: dict = {
        "head": {
            "text": f"{config.module_name} ({steps} steps, i*=in o*=out)",
            "tick": 0,
            "every": _head_every(steps),
        },
        "foot": {
            "text": (
                "Flat lanes, skin narrow. Cond true -> next step. Not RTL-accurate."
            ),
        },
        "signal": signals,
        "config": {"skin": "narrow"},
    }

    errs = validate_wavedrom_doc(doc, steps)
    if errs:
        doc["foot"]["text"] += " Validation: " + "; ".join(errs[:3])
    return doc


def generate_wavedrom_json(
    config: PowerSeqConfig,
    scenario: WaveDromScenario | None = None,
    *,
    indent: int = 2,
) -> str:
    return json.dumps(generate_wavedrom(config, scenario), indent=indent, ensure_ascii=False)
