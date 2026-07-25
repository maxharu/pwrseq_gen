"""
Shared timing-diagram export helpers (lanes, condition edges, WaveJSON checks).

Used by Schemdraw export. Simulation lives in timing_sim.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from config_models import PowerRail, PowerSeqConfig
from timing_sim import (
    DEP_HIGH,
    DEP_LOW,
    SimResult,
    _internal_sig,
    expand_binary_wave,
    values_to_wave,
)

TIMING_AUTHOR = "Haru"
TIMING_EDGE_BOTH = frozenset({"hi", "lo"})
TIMING_EDGE_HI_ONLY = frozenset({"hi"})
TIMING_EDGE_LO_ONLY = frozenset({"lo"})


def timing_edge_kinds_from_choice(choice: str) -> frozenset[str]:
    """Map GUI/API choice to edge kind set."""
    if choice == "hi":
        return TIMING_EDGE_HI_ONLY
    if choice == "lo":
        return TIMING_EDGE_LO_ONLY
    return TIMING_EDGE_BOTH


@dataclass(frozen=True)
class TimingExportOptions:
    include_rails: frozenset[str]
    edge_kinds: frozenset[str] = TIMING_EDGE_BOTH


def _port_name(name: str, prefix: str) -> str:
    safe = name.replace(".", "_").replace("-", "_").replace(" ", "_")
    return prefix + safe


def _port_for_rail(rail: PowerRail) -> str:
    prefix = "i" if rail.seq_type == "input" else "o"
    return _port_name(rail.name, prefix)


def _head_title_from_filename(output_filename: str | None, fallback: str) -> str:
    """Head title: output basename without extension, else module name."""
    if not output_filename:
        return fallback
    name = os.path.splitext(os.path.basename(output_filename))[0]
    return name if name else fallback


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
) -> list[tuple[str, bool]]:
    """Leaf deps with inv relative to making this condition term true.

    For use=self/force the leaf is ``dep_name`` with path_inv=False (caller
    XORs the owner's term inv). For use=hi/lo, recurse into the dependency
    rail's condition and accumulate per-term inv along the path.
    """
    dep_rail = name_to_rail.get(dep_name)
    if not dep_rail or dep_name in (DEP_HIGH, DEP_LOW):
        return []
    if dep_rail.seq_type == "input":
        return [(dep_name, False)]

    get_use = owner.get_hi_use if consumer_kind == "hi" else owner.get_lo_use
    use = get_use(group_idx, item_idx, dep_name)
    if use in ("self", "force"):
        return [(dep_name, False)]
    if use not in ("hi", "lo"):
        return [(dep_name, False)]

    visited = chain or frozenset()
    if dep_name in visited:
        return [(dep_name, False)]

    cond_kind = use
    groups = (
        dep_rail.get_hi_groups() if cond_kind == "hi" else dep_rail.get_lo_groups()
    )
    if not groups or not any(groups):
        return [(dep_name, False)]

    get_inv = dep_rail.get_hi_inv if cond_kind == "hi" else dep_rail.get_lo_inv
    leaves: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for gi, ii, sub in _unique_group_deps(groups):
        sub_inv = bool(get_inv(gi, ii, sub))
        for leaf, path_inv in _leaf_deps_for_edge(
            sub,
            dep_rail,
            gi,
            ii,
            cond_kind,
            name_to_rail,
            visited | {dep_name},
        ):
            effective = sub_inv ^ path_inv
            if leaf not in seen:
                seen.add(leaf)
                leaves.append((leaf, effective))
    return leaves if leaves else [(dep_name, False)]


def _dep_bits_series(
    dep_name: str,
    name_to_rail: dict[str, PowerRail],
    result: SimResult,
) -> list[int] | None:
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
    inv: bool,
) -> int | None:
    """Step where dep makes the (possibly inverted) condition become true."""
    if not dep_bits:
        return None
    # inv=False → true on high → trigger on rising; inv=True → on falling
    return _first_transition_step(dep_bits, rising=not inv)


def _build_export_lanes(
    config: PowerSeqConfig,
    result: SimResult,
    include_rails: frozenset[str] | None,
) -> tuple[list[dict], dict[str, dict]]:
    """Build exported signal lanes and port-name lookup."""
    lanes_by_port: dict[str, dict] = {}
    signals: list[dict] = []
    steps = result.steps
    for r in config.rails:
        if include_rails is not None and r.name not in include_rails:
            continue
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
    return signals, lanes_by_port


ConditionEdgePending = tuple[int, int, dict, dict, str]


def _collect_condition_edge_pending(
    config: PowerSeqConfig,
    result: SimResult,
    lanes_by_port: dict[str, dict],
    *,
    edge_kinds: frozenset[str] | None = None,
) -> list[ConditionEdgePending]:
    """Dep/out lane pairs with simulation step indices."""
    kinds = edge_kinds if edge_kinds is not None else TIMING_EDGE_BOTH
    pending: list[ConditionEdgePending] = []
    name_to_rail = {r.name: r for r in config.rails}

    for rail in config.rails:
        if not rail.has_pseqcell:
            continue
        sig = _internal_sig(rail.name)
        out_lane = lanes_by_port.get(_port_for_rail(rail))
        if not out_lane:
            continue
        out_bits = result.output_values.get(sig, [])

        specs: list[tuple[str, bool, int | None]] = []
        if "hi" in kinds:
            specs.append(("hi", True, _first_transition_step(out_bits, rising=True)))
        if "lo" in kinds:
            specs.append(("lo", False, _first_transition_step(out_bits, rising=False)))
        for kind, _out_rising, out_step in specs:
            if out_step is None:
                continue
            groups = rail.get_hi_groups() if kind == "hi" else rail.get_lo_groups()
            if not groups or not any(groups):
                continue

            for gi, ii, dep in _unique_group_deps(groups):
                get_inv = rail.get_hi_inv if kind == "hi" else rail.get_lo_inv
                term_inv = bool(get_inv(gi, ii, dep))
                for leaf, path_inv in _leaf_deps_for_edge(
                    dep, rail, gi, ii, kind, name_to_rail,
                ):
                    dep_rail = name_to_rail.get(leaf)
                    if not dep_rail:
                        continue
                    dep_lane = lanes_by_port.get(_port_for_rail(dep_rail))
                    if not dep_lane:
                        continue
                    dep_bits = _dep_bits_series(leaf, name_to_rail, result)
                    dep_step = _dep_trigger_step(
                        dep_bits, inv=term_inv ^ path_inv,
                    )
                    if dep_step is None:
                        continue
                    if dep_step > out_step:
                        continue
                    pending.append((dep_step, out_step, dep_lane, out_lane, kind))

    pending.sort(key=lambda item: (item[1], item[0]))
    return pending


def validate_timing_doc(doc: dict, steps: int | None = None) -> list[str]:
    """Quick WaveJSON checks for timing diagram docs."""
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
