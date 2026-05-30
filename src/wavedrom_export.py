"""
Build WaveJSON from PowerSeqConfig + WaveDromScenario (WaveDrom skill aligned).
"""
from __future__ import annotations

import json
import string

from config_models import PowerRail, PowerSeqConfig
from wavedrom_sim import (
    DEP_HIGH,
    DEP_LOW,
    SimResult,
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


def _port_for_rail(rail: PowerRail) -> str:
    prefix = "i" if rail.seq_type == "input" else "o"
    return _port_name(rail.name, prefix)


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


def format_rail_condition(rail: PowerRail, kind: str) -> str:
    """Human-readable Hi/Lo condition for edge labels."""
    groups = rail.get_hi_groups() if kind == "hi" else rail.get_lo_groups()
    get_inv = rail.get_hi_inv if kind == "hi" else rail.get_lo_inv
    get_use = rail.get_hi_use if kind == "hi" else rail.get_lo_use
    if not groups or not any(groups):
        return "1" if kind == "hi" else "0"

    or_parts: list[str] = []
    for gi, group in enumerate(groups):
        if not group:
            continue
        terms = [
            _dep_label(dep, get_inv(gi, ii, dep), get_use(gi, ii, dep))
            for ii, dep in enumerate(group)
        ]
        or_parts.append(" & ".join(terms))
    return " | ".join(or_parts) if or_parts else ("1" if kind == "hi" else "0")


def _dep_label(dep: str, inv: bool, use: str) -> str:
    if dep == DEP_HIGH:
        return "0" if inv else "1"
    if dep == DEP_LOW:
        return "1" if inv else "0"
    prefix = "!" if inv else ""
    suffix = ""
    if use == "hi":
        suffix = ".hi"
    elif use == "lo":
        suffix = ".lo"
    elif use == "force":
        suffix = ".f"
    return f"{prefix}{dep}{suffix}"


class _NodeAllocator:
    def __init__(self) -> None:
        self._chars = list(string.ascii_lowercase + string.ascii_uppercase)
        self._i = 0

    def take(self) -> str:
        ch = self._chars[self._i % len(self._chars)]
        self._i += 1
        return ch


def _step_index_in_wave(wave: str, step: int, steps: int) -> int:
    """Map simulation step index to index in wave string (same period count)."""
    if step <= 0:
        return 0
    if step >= steps - 1:
        return max(0, len(wave) - 1)
    period = 0
    for i, ch in enumerate(wave):
        if period == step:
            return i
        if ch in "01.":
            period += 1
        elif ch.isdigit():
            period += 1
    return max(0, len(wave) - 1)


def _apply_node(lane: dict, steps: int, step: int, letter: str) -> None:
    wave = str(lane["wave"])
    n = len(wave)
    if n == 0:
        return
    node = list(lane.get("node") or ("." * n))
    if len(node) < n:
        node.extend("." * (n - len(node)))
    node = node[:n]
    idx = _step_index_in_wave(wave, step, steps)
    node[idx] = letter
    lane["node"] = "".join(node)


def _first_transition_step(bits: list[int], rising: bool) -> int | None:
    for t in range(1, len(bits)):
        if rising and bits[t - 1] == 0 and bits[t] == 1:
            return t
        if not rising and bits[t - 1] == 1 and bits[t] == 0:
            return t
    return None


def _unique_group_deps(groups: list[list[str]]) -> list[tuple[int, int, str]]:
    """(group_idx, term_idx, dep) preserving order, skip constants."""
    seen: set[str] = set()
    out: list[tuple[int, int, str]] = []
    for gi, group in enumerate(groups):
        for ii, dep in enumerate(group):
            if dep in (DEP_HIGH, DEP_LOW) or dep in seen:
                continue
            seen.add(dep)
            out.append((gi, ii, dep))
    return out


def _leaf_deps_for_edge(
    dep_name: str,
    owner: PowerRail,
    group_idx: int,
    item_idx: int,
    consumer_kind: str,
    name_to_rail: dict[str, PowerRail],
    chain: frozenset[str] | None = None,
) -> list[str]:
    """
    Arrow sources for one Hi/Lo term on owner.

    Input GPIO stays as-is. Output with use hi/lo expands to that rail's
    Hi/Lo condition leaves (e.g. PVNNAON Hi PCH_P0V85A_EN.hi -> EKEY, PRIM_VR_EN).
    Output with use self stays on that rail's GPIO.
    """
    dep_rail = name_to_rail.get(dep_name)
    if not dep_rail or dep_name in (DEP_HIGH, DEP_LOW):
        return []
    if dep_rail.seq_type == "input":
        return [dep_name]

    get_use = owner.get_hi_use if consumer_kind == "hi" else owner.get_lo_use
    use = get_use(group_idx, item_idx, dep_name)
    if use in ("self", "force"):
        return [dep_name]
    if use not in ("hi", "lo"):
        return [dep_name]

    visited = chain or frozenset()
    if dep_name in visited:
        return [dep_name]

    cond_kind = use
    groups = (
        dep_rail.get_hi_groups() if cond_kind == "hi" else dep_rail.get_lo_groups()
    )
    if not groups or not any(groups):
        return [dep_name]

    leaves: list[str] = []
    seen: set[str] = set()
    for gi, ii, sub in _unique_group_deps(groups):
        for leaf in _leaf_deps_for_edge(
            sub,
            dep_rail,
            gi,
            ii,
            cond_kind,
            name_to_rail,
            visited | {dep_name},
        ):
            if leaf not in seen:
                seen.add(leaf)
                leaves.append(leaf)
    return leaves if leaves else [dep_name]


def _dep_bits_series(
    dep_name: str,
    name_to_rail: dict[str, PowerRail],
    result: SimResult,
) -> list[int] | None:
    """Edge anchors: input GPIO; output GPIO (wave-visible), not hi/lo cond."""
    dep_rail = name_to_rail.get(dep_name)
    if not dep_rail or dep_name in (DEP_HIGH, DEP_LOW):
        return None
    if dep_rail.seq_type == "input":
        return result.raw_inputs.get(dep_name)
    sig = _internal_sig(dep_name)
    return result.output_values.get(sig)


def _dep_trigger_step(
    dep_bits: list[int] | None,
    *,
    kind: str,
) -> int | None:
    """First GPIO 0→1 (Hi edge) or 1→0 (Lo edge) on the dependency lane."""
    if not dep_bits:
        return None
    rising = kind == "hi"
    return _first_transition_step(dep_bits, rising=rising)


def _place_edge_node(
    lane: dict,
    steps: int,
    step: int,
    alloc: _NodeAllocator,
    at_index: dict[tuple[str, int], str],
) -> str:
    """One node letter per (lane, wave index); reuse if already placed."""
    name = str(lane["name"])
    idx = _step_index_in_wave(str(lane["wave"]), step, steps)
    key = (name, idx)
    if key in at_index:
        return at_index[key]
    letter = alloc.take()
    at_index[key] = letter
    _apply_node(lane, steps, step, letter)
    return letter


def _build_condition_edges(
    config: PowerSeqConfig,
    result: SimResult,
    lanes_by_port: dict[str, dict],
) -> list[str]:
    """One arrow per Hi/Lo dependency: dep transition → output transition."""
    edges: list[str] = []
    alloc = _NodeAllocator()
    at_index: dict[tuple[str, int], str] = {}
    name_to_rail = {r.name: r for r in config.rails}
    steps = result.steps

    for rail in config.rails:
        if not rail.has_pseqcell:
            continue
        sig = _internal_sig(rail.name)
        out_lane = lanes_by_port.get(_port_for_rail(rail))
        if not out_lane:
            continue
        out_bits = result.output_values.get(sig, [])

        specs = (
            ("hi", True, _first_transition_step(out_bits, rising=True)),
            ("lo", False, _first_transition_step(out_bits, rising=False)),
        )
        for kind, out_rising, out_step in specs:
            if out_step is None:
                continue
            groups = rail.get_hi_groups() if kind == "hi" else rail.get_lo_groups()
            if not groups or not any(groups):
                continue
            out_node = _place_edge_node(out_lane, steps, out_step, alloc, at_index)

            for gi, ii, dep in _unique_group_deps(groups):
                for leaf in _leaf_deps_for_edge(
                    dep, rail, gi, ii, kind, name_to_rail,
                ):
                    dep_rail = name_to_rail.get(leaf)
                    if not dep_rail:
                        continue
                    dep_lane = lanes_by_port.get(_port_for_rail(dep_rail))
                    if not dep_lane:
                        continue
                    dep_bits = _dep_bits_series(leaf, name_to_rail, result)
                    dep_step = _dep_trigger_step(dep_bits, kind=kind)
                    if dep_step is None:
                        continue
                    dep_node = _place_edge_node(
                        dep_lane, steps, dep_step, alloc, at_index,
                    )
                    edges.append(f"{dep_node}-~>{out_node}")
    return edges


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
        node = obj.get("node")
        if node is not None and len(str(node)) != len(str(obj["wave"])):
            errs.append(f"{path}: node length must match wave length")

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

    lanes_by_port: dict[str, dict] = {}
    signals: list = []
    for r in config.rails:
        if r.seq_type == "input":
            lane = _lane_dict(
                _port_name(r.name, "i"),
                result.raw_inputs.get(r.name, []),
                steps,
            )
            signals.append(lane)
            lanes_by_port[lane["name"]] = lane
        elif r.has_pseqcell:
            sig = _internal_sig(r.name)
            lane = _lane_dict(
                _port_name(r.name, "o"),
                result.output_values.get(sig, []),
                steps,
            )
            signals.append(lane)
            lanes_by_port[lane["name"]] = lane

    if not signals:
        signals = [{"name": "_empty", "wave": "0"}]

    edges = _build_condition_edges(config, result, lanes_by_port)

    doc: dict = {
        "head": {
            "text": f"{config.module_name} ({steps} steps, i*=in o*=out)",
            "tick": 0,
            "every": _head_every(steps),
        },
        "foot": {
            "text": (
                "Arrows: deps to output GPIO; .hi/.lo on outputs trace to cond inputs. "
                "Logic sim, not RTL."
            ),
        },
        "signal": signals,
        "config": {"skin": "narrow"},
    }
    if edges:
        doc["edge"] = edges

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
