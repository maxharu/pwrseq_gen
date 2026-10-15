"""
Shared timing-diagram export helpers (lanes, condition edges, WaveJSON checks).

Used by Schemdraw export. Simulation lives in timing_sim.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from core.cond_ir import CondVisitor, resolve_condition
from core.config_models import PowerRail, PowerSeqConfig
from core.constants import DEP_HIGH, DEP_LOW
from core.naming import internal_sig, safe_name
from timing.timing_sim import (
    SimResult,
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
    return prefix + safe_name(name)


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


def _first_transition_step(bits: list[int], rising: bool) -> int | None:
    for t in range(1, len(bits)):
        if rising and bits[t - 1] == 0 and bits[t] == 1:
            return t
        if not rising and bits[t - 1] == 1 and bits[t] == 0:
            return t
    return None


@dataclass(frozen=True)
class _EdgeItem:
    """One dependency item as the arrow tracer sees it."""

    name: str
    cond_kind: str | None  # None -> read this node's level; else its hi/lo/force condition
    inv: bool


class _EdgeItems(CondVisitor):
    """CondTree -> dependency items in order; constants carry no waveform to point at.

    Arrow placement only follows per-item `inv`; `intra_op` and `group_inv` say how the
    terms combine, which an arrow cannot express, so they are deliberately ignored.
    """

    def const(self, value: int) -> list[_EdgeItem]:
        return []

    def level(self, name: str) -> list[_EdgeItem]:
        return [_EdgeItem(name, None, False)]

    def cond(self, name: str, kind: str) -> list[_EdgeItem]:
        return [_EdgeItem(name, kind, False)]

    def invert(self, operand: list[_EdgeItem]) -> list[_EdgeItem]:
        return [_EdgeItem(i.name, i.cond_kind, not i.inv) for i in operand]

    def group(self, op: str, items: list[list[_EdgeItem]], inv: bool) -> list[_EdgeItem]:
        return [item for terms in items for item in terms]

    def any_group(self, groups: list[list[_EdgeItem]]) -> list[_EdgeItem]:
        return [item for terms in groups for item in terms]


def _condition_items(
    rail: PowerRail, kind: str, name_to_rail: dict[str, PowerRail]
) -> list[_EdgeItem]:
    """Deduplicated by name, first occurrence wins (its inv/use is the one used)."""
    items = resolve_condition(rail, kind, name_to_rail).accept(_EdgeItems())
    seen: set[str] = set()
    unique: list[_EdgeItem] = []
    for item in items:
        if item.name in seen:
            continue
        seen.add(item.name)
        unique.append(item)
    return unique


def _leaf_deps_for_edge(
    item: _EdgeItem,
    name_to_rail: dict[str, PowerRail],
    chain: frozenset[str] = frozenset(),
) -> list[tuple[str, bool]]:
    """Leaf deps with inv relative to making this condition term true.

    Reading a node's level makes it the leaf. Referencing another rail's Hi/Lo
    condition recurses into that rail and accumulates per-term inv along the path;
    a rail whose condition yields no leaf -- or which closes a cycle -- falls back
    to being its own leaf.

    Force stops at the leaf like a level does, because `_dep_bits_series` always
    reads the leaf's *level* waveform and Force takes effect on the same step it
    becomes true: the referenced rail's own waveform already shows the transition,
    so pointing the arrow at it is exact. Hi/Lo lag by one step, which is why only
    those recurse to find the real cause.
    """
    rail = name_to_rail.get(item.name)
    if rail is None:
        return []
    if item.cond_kind in (None, "force") or item.name in chain:
        return [(item.name, False)]

    leaves: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for sub in _condition_items(rail, item.cond_kind, name_to_rail):
        for leaf, path_inv in _leaf_deps_for_edge(
            sub, name_to_rail, chain | {item.name}
        ):
            effective = sub.inv ^ path_inv
            if leaf not in seen:
                seen.add(leaf)
                leaves.append((leaf, effective))
    return leaves if leaves else [(item.name, False)]


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
    sig = internal_sig(dep_name)
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
            sig = internal_sig(r.name)
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
        sig = internal_sig(rail.name)
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
            for item in _condition_items(rail, kind, name_to_rail):
                for leaf, path_inv in _leaf_deps_for_edge(item, name_to_rail):
                    dep_rail = name_to_rail.get(leaf)
                    if not dep_rail:
                        continue
                    dep_lane = lanes_by_port.get(_port_for_rail(dep_rail))
                    if not dep_lane:
                        continue
                    dep_bits = _dep_bits_series(leaf, name_to_rail, result)
                    dep_step = _dep_trigger_step(
                        dep_bits, inv=item.inv ^ path_inv,
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
