"""
Compare auto-export Draw.io XML against reference golden2.xml.

Golden2 uses a large canvas offset; comparison normalizes by anchoring the
rightmost input label (config rails order) so layout deltas are visible.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from config_models import PowerSeqConfig


@dataclass
class VertexInfo:
    vid: str
    kind: str
    label: str
    x: float
    y: float
    w: float
    h: float

    def stable_key(self, dx: float = 0, dy: float = 0) -> str:
        """Cross-file key: named nodes by label; gates/NOT by 40pt grid after offset."""
        if self.kind in ("input_label", "output_name", "cell_box") and self.label:
            return f"{self.kind}:{self.label}"
        if self.kind in ("H_Deb", "L_Deb", "O"):
            gx = round((self.x + dx) / 40)
            gy = round((self.y + dy) / 40)
            return f"{self.kind}@{gx},{gy}"
        if self.kind in ("NOT",) or self.kind.startswith("gate_"):
            gx = round((self.x + dx) / 40)
            gy = round((self.y + dy) / 40)
            return f"{self.kind}@{gx},{gy}"
        return f"{self.kind}:{self.vid}"

    @property
    def key(self) -> str:
        return self.stable_key()


@dataclass
class EdgeInfo:
    eid: str
    src_key: str
    tgt_key: str
    stroke: str
    edge_style: str
    n_pts: int
    pts: list[tuple[float, float]]


@dataclass
class DiagramSnapshot:
    vertices: dict[str, VertexInfo]
    edges: list[EdgeInfo]
    o_to_output: dict[str, str]

    def anchor_input(self, prefer_names: list[str]) -> VertexInfo | None:
        for name in reversed(prefer_names):
            k = f"input_label:{name}"
            if k in self.vertices:
                return self.vertices[k]
        for v in self.vertices.values():
            if v.kind == "input_label":
                return v
        return None


@dataclass
class DiffReport:
    offset_dx: float = 0.0
    offset_dy: float = 0.0
    vertex_only_ref: list[str] = field(default_factory=list)
    vertex_only_act: list[str] = field(default_factory=list)
    vertex_pos_delta: list[tuple[str, float, float, float, float]] = field(default_factory=list)
    edge_only_ref: list[str] = field(default_factory=list)
    edge_only_act: list[str] = field(default_factory=list)
    edge_wp_mismatch: list[tuple[str, int, int]] = field(default_factory=list)
    stub_x_ref: list[int] = field(default_factory=list)
    stub_x_act: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.vertex_only_ref
            or self.vertex_only_act
            or self.vertex_pos_delta
            or self.edge_only_ref
            or self.edge_only_act
            or self.edge_wp_mismatch
        )

    def format_text(self, *, tol: float = 0.5) -> str:
        lines = [
            "=== Draw.io golden2 diff ===",
            f"normalize offset: dx={self.offset_dx:.1f} dy={self.offset_dy:.1f} (tol={tol})",
            "",
        ]
        if self.vertex_only_ref:
            lines.append(f"vertices only in golden2 ({len(self.vertex_only_ref)}):")
            for k in self.vertex_only_ref[:20]:
                lines.append(f"  + {k}")
            if len(self.vertex_only_ref) > 20:
                lines.append(f"  ... +{len(self.vertex_only_ref) - 20} more")
        if self.vertex_only_act:
            lines.append(f"vertices only in export ({len(self.vertex_only_act)}):")
            for k in self.vertex_only_act[:20]:
                lines.append(f"  - {k}")
            if len(self.vertex_only_act) > 20:
                lines.append(f"  ... +{len(self.vertex_only_act) - 20} more")
        if self.vertex_pos_delta:
            lines.append(f"vertex position delta > {tol} ({len(self.vertex_pos_delta)}):")
            for k, rx, ry, ax, ay in sorted(
                self.vertex_pos_delta, key=lambda t: max(abs(t[3]), abs(t[4])), reverse=True
            )[:25]:
                lines.append(f"  {k}: ref=({rx:.0f},{ry:.0f}) act=({ax:.0f},{ay:.0f}) d=({ax:.0f},{ay:.0f})")
        if self.edge_only_ref:
            lines.append(f"edges only in golden2 ({len(self.edge_only_ref)}):")
            for k in self.edge_only_ref[:15]:
                lines.append(f"  + {k}")
        if self.edge_only_act:
            lines.append(f"edges only in export ({len(self.edge_only_act)}):")
            for k in self.edge_only_act[:15]:
                lines.append(f"  - {k}")
        if self.edge_wp_mismatch:
            lines.append(f"edge waypoint count mismatch ({len(self.edge_wp_mismatch)}):")
            for k, nr, na in self.edge_wp_mismatch[:20]:
                lines.append(f"  {k}: ref_pts={nr} act_pts={na}")
        if self.stub_x_ref or self.stub_x_act:
            lines.append("")
            lines.append("vertical bus x (waypoints, 40pt buckets):")
            lines.append(f"  golden2: {self.stub_x_ref[:12]}")
            lines.append(f"  export:  {self.stub_x_act[:12]}")
        lines.append("")
        lines.append("RESULT: " + ("PASS (within tolerance)" if self.ok else "DIFFERENCES FOUND"))
        return "\n".join(lines)


def _style_val(style: str, key: str, default: str = "") -> str:
    m = re.search(rf"(?:^|;){re.escape(key)}=([^;]+)", style)
    return m.group(1) if m else default


def _classify_vertex(style: str, value: str, w: float, h: float) -> str:
    if "rotation=90" in style and "align=right" in style and value:
        return "input_label"
    if "inverter_2" in style:
        return "NOT"
    if "logic_gate" in style:
        op = _style_val(style, "operation", "gate")
        return f"gate_{op}"
    if value == "Q":
        return "Q"
    if value == "~Q":
        return "QN"
    if value in ("H_Deb", "L_Deb"):
        return value
    if value and "align=left" in style:
        return "output_name"
    if not value and w == 80 and h == 80:
        return "cell_box"
    return "other"


def parse_drawio_xml(xml_text: str) -> DiagramSnapshot:
    root = ET.fromstring(xml_text)
    root_el = root.find(".//root")
    if root_el is None:
        raise ValueError("no mxGraph root")

    raw: dict[str, dict[str, Any]] = {}
    for c in root_el:
        if c.get("vertex") != "1":
            continue
        geo = c.find("mxGeometry")
        if geo is None:
            continue
        raw[c.get("id") or ""] = {
            "style": c.get("style") or "",
            "value": (c.get("value") or "").strip(),
            "x": float(geo.get("x", 0)),
            "y": float(geo.get("y", 0)),
            "w": float(geo.get("width", 0)),
            "h": float(geo.get("height", 0)),
        }

    o_to_output: dict[str, str] = {}
    for c in root_el:
        if c.get("edge") != "1":
            continue
        src, tgt = c.get("source"), c.get("target")
        if src and tgt and raw.get(src, {}).get("value") == "O":
            name = raw.get(tgt, {}).get("value", "")
            if name:
                o_to_output[src] = name

    vertices: dict[str, VertexInfo] = {}
    for vid, v in raw.items():
        kind = _classify_vertex(v["style"], v["value"], v["w"], v["h"])
        label = v["value"]
        if kind == "cell_box" and vid in o_to_output:
            label = o_to_output[vid]
        info = VertexInfo(vid, kind, label, v["x"], v["y"], v["w"], v["h"])
        sk = info.stable_key()
        vertices[sk] = info

    edges: list[EdgeInfo] = []
    for c in root_el:
        if c.get("edge") != "1":
            continue
        src, tgt = c.get("source"), c.get("target")
        if not src or not tgt:
            continue
        sk = _vertex_key_from_id(src, raw, o_to_output)
        tk = _vertex_key_from_id(tgt, raw, o_to_output)
        if sk is None or tk is None:
            continue
        sty = c.get("style") or ""
        geo = c.find("mxGeometry")
        pts: list[tuple[float, float]] = []
        if geo is not None:
            arr = geo.find("Array[@as='points']")
            if arr is not None:
                for p in arr:
                    pts.append((float(p.get("x", 0)), float(p.get("y", 0))))
        stroke = _style_val(sty, "strokeColor", "#000000")
        edges.append(
            EdgeInfo(
                c.get("id") or "",
                sk,
                tk,
                stroke,
                _style_val(sty, "edgeStyle", "?"),
                len(pts),
                pts,
            )
        )

    return DiagramSnapshot(vertices=vertices, edges=edges, o_to_output=o_to_output)


def _vertex_key_from_id(
    vid: str, raw: dict[str, dict[str, Any]], o_to_output: dict[str, str]
) -> str | None:
    v = raw.get(vid)
    if v is None:
        return None
    kind = _classify_vertex(v["style"], v["value"], v["w"], v["h"])
    label = v["value"]
    if kind == "cell_box" and vid in o_to_output:
        label = o_to_output[vid]
    info = VertexInfo(
        vid, kind, label, v["x"], v["y"], v["w"], v["h"]
    )
    if kind == "cell_box" and vid in o_to_output:
        info.label = o_to_output[vid]
    return info.stable_key()


def _edge_sig(e: EdgeInfo) -> str:
    return f"{e.src_key} -> {e.tgt_key} [{e.stroke}]"


def _collect_stub_x(edges: list[EdgeInfo]) -> list[int]:
    c: dict[int, int] = {}
    for e in edges:
        for x, _ in e.pts:
            bx = round(x / 40) * 40
            c[bx] = c.get(bx, 0) + 1
    return [x for x, _ in sorted(c.items(), key=lambda t: -t[1])]


def diff_diagrams(
    reference: DiagramSnapshot,
    actual: DiagramSnapshot,
    *,
    input_anchor_order: list[str],
    pos_tol: float = 0.5,
) -> DiffReport:
    rep = DiffReport()
    ref_a = reference.anchor_input(input_anchor_order)
    act_a = actual.anchor_input(input_anchor_order)
    if ref_a and act_a:
        rep.offset_dx = ref_a.x - act_a.x
        rep.offset_dy = ref_a.y - act_a.y

    ref_keys = set(reference.vertices)
    act_keys = set(actual.vertices)
    rep.vertex_only_ref = sorted(ref_keys - act_keys)
    rep.vertex_only_act = sorted(act_keys - ref_keys)

    for k in sorted(ref_keys & act_keys):
        rv = reference.vertices[k]
        av = actual.vertices[k]
        ax = av.x + rep.offset_dx
        ay = av.y + rep.offset_dy
        ddx = ax - rv.x
        ddy = ay - rv.y
        if abs(ddx) > pos_tol or abs(ddy) > pos_tol:
            rep.vertex_pos_delta.append((k, rv.x, rv.y, ddx, ddy))

    ref_edges = {_edge_sig(e): e for e in reference.edges}
    act_edges = {_edge_sig(e): e for e in actual.edges}
    rep.edge_only_ref = sorted(set(ref_edges) - set(act_edges))
    rep.edge_only_act = sorted(set(act_edges) - set(ref_edges))

    for sig in sorted(set(ref_edges) & set(act_edges)):
        re, ae = ref_edges[sig], act_edges[sig]
        if re.n_pts != ae.n_pts:
            rep.edge_wp_mismatch.append((sig, re.n_pts, ae.n_pts))

    rep.stub_x_ref = _collect_stub_x(reference.edges)
    rep.stub_x_act = _collect_stub_x(actual.edges)
    return rep


def diff_golden2_export(
    config: PowerSeqConfig,
    export_xml: str,
    golden2_path: str,
    *,
    pos_tol: float = 0.5,
) -> DiffReport:
    with open(golden2_path, encoding="utf-8") as f:
        ref_xml = f.read()
    ref = parse_drawio_xml(ref_xml)
    act = parse_drawio_xml(export_xml)
    inputs = [r.name for r in config.rails if r.seq_type == "input"]
    return diff_diagrams(ref, act, input_anchor_order=inputs, pos_tol=pos_tol)
