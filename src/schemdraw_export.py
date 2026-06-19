"""
Render power-sequence timing diagrams with Schemdraw (SVG / PNG / PDF).

Schemdraw cannot use WaveDrom single-character edge nodes (XML issues with
``&`` etc.).  Extended edges ``[lane:step]-~>[lane:step]`` are built directly
from simulation steps — never via node-letter lookup, which breaks when the
WaveDrom node pool is exhausted (duplicate ``z`` letters map to the wrong lane).
"""
from __future__ import annotations

import json
import os
import re

from config_models import PowerSeqConfig
from wavedrom_export import (
    ConditionEdgePending,
    WaveDromExportOptions,
    WAVEDROM_AUTHOR,
    WAVEDROM_EDGE_BOTH,
    WAVEDROM_EDGE_HI_ONLY,
    WAVEDROM_EDGE_LO_ONLY,
    _build_export_lanes,
    _collect_condition_edge_pending,
    _head_every,
    _head_title_from_filename,
    validate_wavedrom_doc,
)
from wavedrom_sim import (
    WaveDromScenario,
    _norm_hscale,
    default_scenario_for_config,
    simulate,
)

_SCHEMDRAW_OUTPUT_EXTS = frozenset({".svg", ".png", ".pdf"})
_SCHEMDRAW_MPL_EXTS = frozenset({".png", ".pdf"})
_SCHEMDRAW_EDGE_RE = re.compile(
    r"^\[(\d+):(\d+)\]-~>\[(\d+):(\d+)\](?:\s+(.*))?$",
)


def _timing_signals_flat(signals: list) -> list[dict]:
    """Flatten WaveJSON signal tree to individual lane dicts."""
    flat: list[dict] = []
    for item in signals:
        if isinstance(item, dict):
            flat.append(item)
        elif isinstance(item, list):
            flat.extend(_timing_signals_flat(item))
    return flat


def _timing_period_count(signals_flat: list[dict]) -> int:
    try:
        periods = max(len(w.get("wave", [])) for w in signals_flat if "async" not in w)
    except ValueError:
        periods = 0
    if signals_flat:
        async_max = max((w.get("async", [0])[-1] for w in signals_flat), default=0)
        periods = max(periods, async_max)
    return periods


class _TimingDiagramDualLabels:
    """Schemdraw TimingDiagram with signal names on both left and right."""

    @classmethod
    def from_json(cls, wave: str, **kwargs):
        from schemdraw import logic
        from schemdraw.segments import SegmentText

        element = logic.TimingDiagram.from_json(wave, **kwargs)
        signals_flat = _timing_signals_flat(element.wave.get("signal", []))
        periods = _timing_period_count(signals_flat)
        x_right = periods * 2 * element.yheight * element.hscale
        textpad = 0.2
        y0 = 0.0
        for signal in signals_flat:
            name = signal.get("name", "")
            if name:
                element.segments.append(
                    SegmentText(
                        (x_right + textpad, y0),
                        name,
                        align=("left", "bottom"),
                        fontsize=element.fontsize,
                        color=element.namecolor,
                    )
                )
            y0 -= element.yheight + element.ygap
        return element


def build_schemdraw_extended_edges(
    signals: list[dict],
    pending: list[ConditionEdgePending],
) -> list[str]:
    """Map condition edges to Schemdraw extended notation using sim step indices."""
    name_to_idx = {str(s["name"]): i for i, s in enumerate(signals)}
    edges: list[str] = []
    for dep_step, out_step, dep_lane, out_lane, _kind in pending:
        dsi = name_to_idx[str(dep_lane["name"])]
        osi = name_to_idx[str(out_lane["name"])]
        edges.append(f"[{dsi}:{dep_step}]-~>[{osi}:{out_step}]")
    return edges


def generate_schemdraw_doc(
    config: PowerSeqConfig,
    scenario: WaveDromScenario | None = None,
    *,
    output_filename: str | None = None,
    include_rails: frozenset[str] | None = None,
    edge_kinds: frozenset[str] | None = None,
) -> dict:
    """WaveJSON body for Schemdraw: no node letters, extended edges from sim steps."""
    scenario = scenario or default_scenario_for_config(config)
    result = simulate(config, scenario)
    steps = result.steps
    signals, lanes_by_port = _build_export_lanes(config, result, include_rails)
    pending = _collect_condition_edge_pending(
        config, result, lanes_by_port, edge_kinds=edge_kinds,
    )
    edges = build_schemdraw_extended_edges(signals, pending)

    head_title = _head_title_from_filename(output_filename, config.module_name)

    kinds = edge_kinds if edge_kinds is not None else WAVEDROM_EDGE_BOTH
    edge_note = ""
    if kinds == WAVEDROM_EDGE_HI_ONLY:
        edge_note = ", arrows=Hi"
    elif kinds == WAVEDROM_EDGE_LO_ONLY:
        edge_note = ", arrows=Lo"
    lane_note = ""
    if include_rails is not None:
        exportable = sum(
            1 for r in config.rails
            if r.seq_type == "input" or r.has_pseqcell
        )
        lane_note = f", {len(signals)}/{exportable} lanes"

    doc: dict = {
        "head": {
            "text": (
                f"{head_title} ({steps} steps, hscale="
                f"{_norm_hscale(scenario.hscale)}, i*=in o*=out{lane_note}{edge_note})\n"
                f"Author: {WAVEDROM_AUTHOR}"
            ),
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
        "config": {
            "skin": "narrow",
            "hscale": _norm_hscale(scenario.hscale),
        },
    }
    if edges:
        doc["edge"] = edges

    errs = validate_wavedrom_doc(doc, steps)
    if errs:
        doc["foot"]["text"] += " Validation: " + "; ".join(errs[:3])
    return doc


def render_schemdraw_png_bytes(doc: dict, *, dpi: float = 96) -> bytes:
    """Render Schemdraw timing diagram to PNG bytes (for GUI preview)."""
    try:
        from schemdraw import Drawing
    except ImportError as e:
        raise ImportError(
            "Schemdraw is not installed. Run: pip install schemdraw"
        ) from e

    with Drawing(show=False) as drawing:
        _TimingDiagramDualLabels.from_json(json.dumps(doc))
        drawing.draw(show=False)
        return drawing.get_imagedata("png")


def render_schemdraw(doc: dict, output_path: str) -> None:
    """Write SVG, PNG, or PDF from a Schemdraw-ready WaveJSON *doc*."""
    try:
        from schemdraw import Drawing
    except ImportError as e:
        raise ImportError(
            "Schemdraw is not installed. Run: pip install schemdraw"
        ) from e

    ext = os.path.splitext(output_path)[1].lower()
    if ext not in _SCHEMDRAW_OUTPUT_EXTS:
        raise ValueError(
            f"Unsupported Schemdraw output format: {ext!r} (use .svg, .png, or .pdf)"
        )

    if ext in _SCHEMDRAW_MPL_EXTS:
        from schemdraw import use
        try:
            use("matplotlib")
        except ValueError as e:
            raise ImportError(
                f"Schemdraw {ext} export requires matplotlib. Run: pip install matplotlib"
            ) from e

    with Drawing(file=output_path, show=False) as _drawing:
        _TimingDiagramDualLabels.from_json(json.dumps(doc))


def export_schemdraw(
    config: PowerSeqConfig,
    scenario: WaveDromScenario | None = None,
    *,
    output_filename: str,
    include_rails: frozenset[str] | None = None,
    edge_kinds: frozenset[str] | None = None,
) -> None:
    """Simulate, build Schemdraw WaveJSON, render to *output_filename*."""
    doc = generate_schemdraw_doc(
        config,
        scenario,
        output_filename=output_filename,
        include_rails=include_rails,
        edge_kinds=edge_kinds,
    )
    render_schemdraw(doc, output_filename)


def export_schemdraw_from_options(
    config: PowerSeqConfig,
    scenario: WaveDromScenario | None,
    options: WaveDromExportOptions,
    output_filename: str,
) -> None:
    export_schemdraw(
        config,
        scenario,
        output_filename=output_filename,
        include_rails=options.include_rails,
        edge_kinds=options.edge_kinds,
    )


def schemdraw_edges_forward_in_time(doc: dict) -> list[tuple[str, int, str, int]]:
    """Return edges where dep period > out period (should be empty)."""
    signals = doc.get("signal", [])
    backward: list[tuple[str, int, str, int]] = []
    for edge in doc.get("edge") or []:
        m = _SCHEMDRAW_EDGE_RE.match(edge)
        if not m:
            continue
        dsi, dp, osi, op = (int(m.group(i)) for i in range(1, 5))
        if dp > op:
            backward.append((signals[dsi]["name"], dp, signals[osi]["name"], op))
    return backward
