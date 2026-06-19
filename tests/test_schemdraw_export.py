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
from wavedrom_export import WAVEDROM_EDGE_HI_ONLY, WAVEDROM_EDGE_LO_ONLY

_DEMO_JSON = Path(__file__).resolve().parents[1] / "templates" / "demo_json.json"


def test_build_schemdraw_extended_edges_uses_sim_steps():
    signals = [
        {"name": "iDEP", "wave": "01"},
        {"name": "oOUT", "wave": "01"},
    ]
    pending = [(0, 1, signals[0], signals[1], "hi")]
    edges = build_schemdraw_extended_edges(signals, pending)
    assert edges == ["[0:0]-~>[1:1]"]


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


@pytest.mark.skipif(not _DEMO_JSON.is_file(), reason="demo_json.json missing")
def test_render_schemdraw_pdf(tmp_path):
    pytest.importorskip("schemdraw")
    pytest.importorskip("matplotlib")

    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(_DEMO_JSON.read_text(encoding="utf-8")))
    doc = generate_schemdraw_doc(cfg)
    out = tmp_path / "timing.pdf"
    render_schemdraw(doc, str(out))
    assert out.is_file()
    assert out.stat().st_size > 500
    assert out.read_bytes()[:4] == b"%PDF"


@pytest.mark.skipif(not _DEMO_JSON.is_file(), reason="demo_json.json missing")
def test_render_schemdraw_png_bytes(tmp_path):
    schemdraw = pytest.importorskip("schemdraw")
    del schemdraw
    pytest.importorskip("PIL")

    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(_DEMO_JSON.read_text(encoding="utf-8")))
    doc = generate_schemdraw_doc(cfg)
    png = render_schemdraw_png_bytes(doc)
    assert len(png) > 500


@pytest.mark.skipif(not _DEMO_JSON.is_file(), reason="demo_json.json missing")
def test_generate_schemdraw_doc_edges_never_go_backward_in_time():
    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(_DEMO_JSON.read_text(encoding="utf-8")))
    doc = generate_schemdraw_doc(cfg)
    assert schemdraw_edges_forward_in_time(doc) == []
    assert doc.get("edge")
    assert all(re.match(r"^\[\d+:\d+\]-~>\[\d+:\d+\]$", e) for e in doc["edge"])
    assert not any("node" in s for s in doc["signal"])


@pytest.mark.skipif(not _DEMO_JSON.is_file(), reason="demo_json.json missing")
def test_generate_schemdraw_include_rails_subset():
    from config_models import PowerRail, PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(_DEMO_JSON.read_text(encoding="utf-8")))
    first_out = next(r.name for r in cfg.rails if r.has_pseqcell)
    doc = generate_schemdraw_doc(cfg, include_rails=frozenset({first_out}))
    names = [s["name"] for s in doc["signal"]]
    assert len(names) == 1
    assert names[0].startswith("o")


@pytest.mark.skipif(not _DEMO_JSON.is_file(), reason="demo_json.json missing")
def test_generate_schemdraw_edge_kinds():
    from config_models import PowerSeqConfig

    cfg = PowerSeqConfig.from_dict(json.loads(_DEMO_JSON.read_text(encoding="utf-8")))
    doc_hi = generate_schemdraw_doc(cfg, edge_kinds=WAVEDROM_EDGE_HI_ONLY)
    doc_lo = generate_schemdraw_doc(cfg, edge_kinds=WAVEDROM_EDGE_LO_ONLY)
    doc_both = generate_schemdraw_doc(cfg)
    assert len(doc_hi.get("edge", [])) <= len(doc_both.get("edge", []))
    assert len(doc_lo.get("edge", [])) <= len(doc_both.get("edge", []))
