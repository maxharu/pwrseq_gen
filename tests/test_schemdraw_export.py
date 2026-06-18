"""Schemdraw export: extended edges from sim steps, render integration."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from schemdraw_export import (
    _TimingDiagramDualLabels,
    build_schemdraw_extended_edges,
    generate_schemdraw_doc,
    render_schemdraw,
    render_schemdraw_png_bytes,
    schemdraw_edges_forward_in_time,
)

_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "x15dot-f-wavedrom-ddr_hi.json"
_FULL_JSON = Path(__file__).resolve().parents[1] / "templates" / "x15dot-f-wavedrom.json"


def test_build_schemdraw_extended_edges_uses_sim_steps():
  signals = [
      {"name": "iDEP", "wave": "01"},
      {"name": "oOUT", "wave": "01"},
  ]
  pending = [(0, 1, signals[0], signals[1], "hi")]
  edges = build_schemdraw_extended_edges(signals, pending)
  assert edges == ["[0:0]-~>[1:1]"]


@pytest.mark.skipif(not _FULL_JSON.is_file(), reason="template json missing")
def test_node_collision_json_has_backward_edges_via_old_mapping():
    """x15dot-f-wavedrom.json exhausts node letters (duplicate z)."""
    doc = json.loads(_FULL_JSON.read_text(encoding="utf-8"))
    from collections import Counter

    chars = [
        ch
        for s in doc["signal"]
        for ch in s.get("node", "")
        if ch not in ".=|"
    ]
    dups = [ch for ch, n in Counter(chars).items() if n > 1]
    assert "z" in dups

    # Old node-letter remap would point SLPS4@44 -> RESET@42 (backward).
    loc: dict[str, tuple[int, int]] = {}
    for si, lane in enumerate(doc["signal"]):
        for wi, ch in enumerate(lane.get("node", "")):
            if ch not in ".=|":
                loc[ch] = (si, wi)

    def period(wave: str, wi: int) -> int:
        p = 0
        for i, ch in enumerate(wave):
            if i == wi:
                return p
            if ch in "01." or ch.isdigit():
                p += 1
        return p

    backward = []
    for raw in doc.get("edge", []):
        dep, out = raw.split("-~>")
        if dep not in loc or out not in loc:
            continue
        dsi, dwi = loc[dep]
        osi, owi = loc[out]
        dp = period(doc["signal"][dsi]["wave"], dwi)
        op = period(doc["signal"][osi]["wave"], owi)
        if dp > op:
            backward.append((doc["signal"][dsi]["name"], dp, doc["signal"][osi]["name"], op))
    assert any("SLPS4" in b[0] and "RESET" in b[2] for b in backward)


def test_dual_labels_add_right_side_signal_names():
    schemdraw = pytest.importorskip("schemdraw")
    from schemdraw import logic
    from schemdraw.segments import SegmentText

    del schemdraw

    doc = {
        "signal": [
            {"name": "iTEST", "wave": "01"},
            {"name": "oOUT", "wave": "10"},
        ],
        "config": {"hscale": 1},
    }
    base = logic.TimingDiagram.from_json(json.dumps(doc))
    dual = _TimingDiagramDualLabels.from_json(json.dumps(doc))

    def right_name_labels(element) -> list[SegmentText]:
        return [
            seg for seg in element.segments
            if isinstance(seg, SegmentText) and seg.xy[0] > 0
        ]

    assert len(right_name_labels(base)) == 0
    right = right_name_labels(dual)
    assert len(right) == 2
    assert {seg.text for seg in right} == {"iTEST", "oOUT"}


@pytest.mark.skipif(not _TEMPLATE.is_file(), reason="template json missing")
def test_render_schemdraw_png_bytes(tmp_path):
    schemdraw = pytest.importorskip("schemdraw")
    del schemdraw
    pytest.importorskip("PIL")

    demo = Path(__file__).resolve().parents[1] / "templates" / "demo_json.json"
    if not demo.is_file():
        pytest.skip("demo_json.json missing")
    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(demo.read_text(encoding="utf-8")))
    doc = generate_schemdraw_doc(cfg)
    png = render_schemdraw_png_bytes(doc)
    assert len(png) > 500


def test_generate_schemdraw_doc_edges_never_go_backward_in_time():
    demo = Path(__file__).resolve().parents[1] / "templates" / "demo_json.json"
    if not demo.is_file():
        pytest.skip("demo_json.json missing")
    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(demo.read_text(encoding="utf-8")))
    doc = generate_schemdraw_doc(cfg)
    assert schemdraw_edges_forward_in_time(doc) == []
    assert doc.get("edge")
    assert all(re.match(r"^\[\d+:\d+\]-~>\[\d+:\d+\]$", e) for e in doc["edge"])
    assert not any("node" in s for s in doc["signal"])
