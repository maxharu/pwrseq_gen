"""
Cell-centric Draw.io export: one grid cell per output rail.

Each block is self-contained (inputs / cond labels → local AND/OR → PSEQCELL → output name).
Cross-cell references use Verilog-style cond signal names ({internal_sig}_{hi|lo}).
Force cond is not drawn.
"""
from __future__ import annotations

import math
import random
import string
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.dom import minidom

from config_models import PowerSeqConfig, PowerRail
from drawio_export_options import DrawioExportOptions
from verilog_generator import _internal_sig

from drawio_geometry import (  # noqa: E402
    AND_GATE_H,
    AND_GATE_W,
    CELL_GROUP_H,
    CELL_GROUP_W,
    CELL_H_DEB_H,
    CELL_H_DEB_W,
    CELL_H_DEB_Y,
    CELL_INNER_H,
    CELL_INNER_W,
    CELL_L_DEB_H,
    CELL_L_DEB_W,
    CELL_L_DEB_Y,
    CELL_O_H,
    CELL_O_W,
    CELL_O_X,
    CELL_O_Y,
    CONST_DEPS,
    GAP,
    GRID,
    INPUT_LABEL_H,
    OR_GATE_H,
    OR_GATE_W,
    STROKE_DEFAULT,
    STROKE_HI,
    STROKE_LO,
    _PSEQCELL_STYLE_H_DEB,
    _PSEQCELL_STYLE_INNER,
    _PSEQCELL_STYLE_L_DEB,
    _PSEQCELL_STYLE_O,
    _and_gate_style,
    _deb_port_label,
    _escape_xml,
    _intra_child_gate_style,
    _intra_merge_gate_style,
    _GATE_STYLE_OR,
    _or_gate_style,
)

LABEL_W = 100
LABEL_H = INPUT_LABEL_H
COND_COLOR = "rgb(166, 128, 184)"
BLOCK_PAD = GRID
BLOCK_MIN_H = 0
COL_GAP = 0
ROW_GAP = 0
OUT_LABEL_W = 100
GATE_CELL_GAP = GAP
LABEL_STACK_STEP = 20
GROUP_STACK_GAP = 0
AND_TREE_THRESHOLD = 8
EXPORT_CHAR_PT = 8.0
EXPORT_WIRE_PAD = 0
EXPORT_WIRE_MIN = 0


def _snap_grid(value: float, step: int = GRID) -> int:
    """Snap coordinate to step grid (Cell top-left aligns to 40pt)."""
    return int(round(value / step) * step)


def _snap_grid_up(value: float, step: int = GRID) -> int:
    """Round up to step grid (export wire reserve must not shrink below formula)."""
    return int(math.ceil(float(value) / step) * step)


_STYLE_LABEL = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=right;verticalAlign=middle;rounded=0;"
)
_STYLE_OUTPUT = (
    "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
    "align=left;verticalAlign=middle;rounded=0;"
)
_STYLE_EDGE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
    "html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
    "entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;"
    "strokeColor=%s;endArrow=classic;endFill=1;"
)
_STYLE_O_OUT = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
    "html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;endArrow=classic;endFill=1;"
)


def _cond_html(name: str) -> str:
    return (
        f'<b><font style="color: {COND_COLOR};">'
        f"{_escape_xml(name)}</font></b>"
    )


def _export_edge_label(name: str) -> str:
    return (
        '<b style="font-size: 12px; text-align: right; white-space: normal;">'
        f'<font style="color: {COND_COLOR};">{_escape_xml(name)}</font></b>'
    )


def _input_html(name: str) -> str:
    return f'<span style="text-align: left;">{_escape_xml(name)}</span>'


@dataclass
class _Term:
    text: str
    is_cond: bool = False


@dataclass
class _Builder:
    root: ET.Element
    next_id: int = 2

    def vid(self) -> str:
        i = self.next_id
        self.next_id += 1
        return str(i)

    def vertex(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        style: str,
        value: str = "",
        parent: str = "1",
    ) -> str:
        eid = self.vid()
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {
                "id": eid,
                "parent": parent,
                "style": style,
                "value": value,
                "vertex": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
                "as": "geometry",
            },
        )
        return eid

    def edge(
        self,
        src: str,
        tgt: str,
        *,
        stroke: str = STROKE_DEFAULT,
        value: str = "",
    ) -> str:
        eid = self.vid()
        attrs: dict[str, str] = {
            "id": eid,
            "parent": "1",
            "style": _STYLE_EDGE % stroke,
            "edge": "1",
            "source": src,
            "target": tgt,
        }
        if value:
            attrs["value"] = value
        cell = ET.SubElement(self.root, "mxCell", attrs)
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        return eid


def _exported_hilo_keys(config: PowerSeqConfig) -> set[tuple[str, str]]:
    """(dep_rail, hi|lo) referenced as cond by any consumer output."""
    keys: set[tuple[str, str]] = set()
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail)
    for tgt in config.rails:
        if tgt.seq_type != "output":
            continue
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                for ii, d in enumerate(group):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use in ("hi", "lo"):
                        keys.add((d, use))
    return keys


def _resolve_term(
    dep: str,
    inv: bool,
    use: str,
    name_to_rail: dict[str, PowerRail],
) -> _Term | None:
    if dep in CONST_DEPS:
        return None
    if use == "force":
        return None
    if use in ("hi", "lo"):
        return _Term(f"{_internal_sig(dep)}_{use}", is_cond=True)
    text = dep
    if inv:
        text = f"~{text}"
    return _Term(text, is_cond=False)


def _and_columns(n: int) -> int:
    if n < 2:
        return 0
    if n < AND_TREE_THRESHOLD:
        return 1
    return 2


def _effective_stack_inputs(n: int) -> int:
    if n <= 0:
        return 0
    if n < AND_TREE_THRESHOLD:
        return n
    left = (n + 1) // 2
    right = n // 2
    return max(left, right + 1)


def _max_effective_stack(groups: list[list[str]]) -> int:
    if not groups:
        return 0
    return max(_effective_stack_inputs(len(g)) for g in groups)


def _or_columns(n: int) -> int:
    if n < 2:
        return 0
    if n < AND_TREE_THRESHOLD:
        return 1
    return 2


def _gate_depth(groups: list[list[str]]) -> int:
    """Horizontal gate columns: widest intra-group tree + inter-group OR (not summed per group)."""
    nonempty = [g for g in groups if g]
    if not nonempty:
        return 0
    max_and = max(_and_columns(len(g)) for g in nonempty)
    return max_and + _or_columns(len(nonempty))


def _group_vertical_extents(hl: str, n_terms: int) -> tuple[int, int]:
    """(extent_above, extent_below) from anchor center — above = −Y, below = +Y."""
    if n_terms <= 0:
        return 0, 0
    label_half = LABEL_H // 2
    gate_half = AND_GATE_H // 2
    if n_terms == 1:
        return label_half, label_half
    if n_terms < AND_TREE_THRESHOLD:
        stack = label_half + max(0, n_terms - 1) * LABEL_STACK_STEP
        gate = max(gate_half, label_half)
        if hl == "hi":
            return stack, gate
        return gate, stack
    stack = label_half + max(0, _effective_stack_inputs(n_terms) - 1) * LABEL_STACK_STEP
    if hl == "hi":
        return stack, gate_half
    return gate_half, stack


def _stacked_groups_extent(hl: str, group_sizes: list[int]) -> int:
    """Extra vertical span for groups 1..n-1 stacked beyond group 0 (touching bboxes)."""
    if len(group_sizes) <= 1:
        return 0
    extra = 0
    for n in group_sizes[1:]:
        above, below = _group_vertical_extents(hl, n)
        extra += above + below
    return extra


def _group_branch_attach_right(gate_right: float, n_groups: int) -> float:
    """Right edge of each group's merge / single gate column (OR is GAP further right)."""
    if n_groups < 2:
        return gate_right
    return gate_right - OR_GATE_W - GAP


def _merge_lane_label_w(right_terms: list[_Term]) -> int:
    """Label column width for inputs wired directly into merge (40pt grid)."""
    if not right_terms:
        return LABEL_W
    max_len = max(len(t.text) for t in right_terms)
    text_w = max_len * EXPORT_CHAR_PT + EXPORT_WIRE_PAD
    return _snap_grid_up(max(LABEL_W, int(math.ceil(text_w))))


def _child_merge_channel(right_terms: list[_Term]) -> int:
    """Horizontal gap child output → merge input: GAP + label column + GAP (40pt grid)."""
    label_w = _merge_lane_label_w(right_terms)
    return _snap_grid_up(GAP + label_w + GAP)


def _parse_path_group_terms(
    rail: PowerRail,
    hl: str,
    groups: list[list[str]],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> list[list[_Term]]:
    parsed: list[list[_Term]] = []
    for gi, group in enumerate(groups):
        terms: list[_Term] = []
        for ii, d in enumerate(group):
            if d not in valid or d in CONST_DEPS:
                continue
            inv = rail.get_hi_inv(gi, ii, d) if hl == "hi" else rail.get_lo_inv(gi, ii, d)
            use = rail.get_hi_use(gi, ii, d) if hl == "hi" else rail.get_lo_use(gi, ii, d)
            t = _resolve_term(d, inv, use, name_to_rail)
            if t is not None:
                terms.append(t)
        if terms:
            parsed.append(terms)
    return parsed


def _intra_group_gate_width(terms: list[_Term]) -> int:
    n = len(terms)
    if n < 2:
        return 0
    if n < AND_TREE_THRESHOLD:
        return AND_GATE_W
    mid = (n + 1) // 2
    return AND_GATE_W + _child_merge_channel(terms[mid:]) + AND_GATE_W


def _path_horizontal_gate_width(
    rail: PowerRail,
    groups: list[list[str]],
    hl: str,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    parsed = _parse_path_group_terms(rail, hl, groups, name_to_rail, valid)
    if not parsed:
        return 0
    intra = max(_intra_group_gate_width(t) for t in parsed)
    if len(parsed) < 2:
        return intra
    or_cols = _or_columns(len(parsed))
    or_w = or_cols * OR_GATE_W + max(0, or_cols - 1) * GAP
    return intra + GAP + or_w


def _group_left_x(
    branch_attach_right: float,
    n_terms: int,
    *,
    child_merge_channel: int = 2 * GAP,
) -> float:
    if n_terms <= 1:
        return branch_attach_right - LABEL_W
    if n_terms < AND_TREE_THRESHOLD:
        return branch_attach_right - AND_GATE_W - GAP - LABEL_W
    merge_gx = branch_attach_right - AND_GATE_W
    child_gx = merge_gx - AND_GATE_W - child_merge_channel
    return child_gx - GAP - LABEL_W


def _max_group_inputs(groups: list[list[str]]) -> int:
    return _max_effective_stack(groups)


def _export_wire_extra_for_name(export_name: str) -> int:
    """Horizontal segment gate→Deb must fit the purple export label (40pt grid)."""
    text_w = len(export_name) * EXPORT_CHAR_PT + EXPORT_WIRE_PAD
    raw = max(EXPORT_WIRE_MIN, int(math.ceil(text_w - GATE_CELL_GAP)))
    return _snap_grid_up(raw)


def _max_export_wire_extra(
    rail: PowerRail,
    exported_hilo: set[tuple[str, str]],
) -> int:
    extra = 0
    for hl in ("hi", "lo"):
        if (rail.name, hl) not in exported_hilo:
            continue
        name = f"{_internal_sig(rail.name)}_{hl}"
        extra = max(extra, _export_wire_extra_for_name(name))
    return extra


def _block_vertical_layout(
    hi_count: int,
    lo_count: int,
    *,
    hi_group_sizes: list[int] | None = None,
    lo_group_sizes: list[int] | None = None,
) -> tuple[int, int, int]:
    """Return (top_extent, bottom_extent, block_height). Hi stacks up, Lo stacks down."""
    h_deb_center = CELL_H_DEB_Y + CELL_H_DEB_H // 2
    l_deb_center = CELL_L_DEB_Y + CELL_L_DEB_H // 2
    hi_sizes = hi_group_sizes or []
    lo_sizes = lo_group_sizes or []

    top_extent = 0
    if hi_count > 0:
        top_extent = (
            _stacked_groups_extent("hi", hi_sizes)
            + h_deb_center
            - LABEL_H // 2
            + max(0, hi_count - 1) * LABEL_STACK_STEP
        )

    bottom_extent = 0
    if lo_count > 0:
        bottom_extent = (
            _stacked_groups_extent("lo", lo_sizes)
            + CELL_GROUP_H
            - l_deb_center
            + LABEL_H // 2
            + max(0, lo_count - 1) * LABEL_STACK_STEP
        )

    block_h = max(
        BLOCK_MIN_H,
        BLOCK_PAD * 2 + top_extent + CELL_GROUP_H + bottom_extent,
    )
    return top_extent, bottom_extent, block_h


def _cell_y_in_block(
    oy: float,
    hi_count: int,
    hi_group_sizes: list[int] | None = None,
) -> float:
    if hi_count <= 0:
        return oy + BLOCK_PAD
    h_deb_center = CELL_H_DEB_Y + CELL_H_DEB_H // 2
    return (
        oy
        + BLOCK_PAD
        + _stacked_groups_extent("hi", hi_group_sizes or [])
        - h_deb_center
        + LABEL_H // 2
        + max(0, hi_count - 1) * LABEL_STACK_STEP
    )


def _path_has_gate(groups: list[list[str]]) -> bool:
    return len(groups) >= 2 or any(len(g) >= 2 for g in groups)


def _estimate_block_size(
    rail: PowerRail,
    exported_hilo: set[tuple[str, str]],
    *,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> tuple[int, int]:
    hi_g = rail.get_hi_groups()
    lo_g = rail.get_lo_groups()
    hi_sizes = [len(g) for g in hi_g]
    lo_sizes = [len(g) for g in lo_g]
    hi_count = _max_group_inputs(hi_g)
    lo_count = _max_group_inputs(lo_g)
    gate_w = max(
        _path_horizontal_gate_width(rail, hi_g, "hi", name_to_rail, valid),
        _path_horizontal_gate_width(rail, lo_g, "lo", name_to_rail, valid),
    )
    wire_extra = _max_export_wire_extra(rail, exported_hilo)
    _, _, block_h = _block_vertical_layout(
        hi_count,
        lo_count,
        hi_group_sizes=hi_sizes,
        lo_group_sizes=lo_sizes,
    )
    w = (
        BLOCK_PAD
        + LABEL_W
        + (GAP + gate_w if gate_w > 0 else 0)
        + GATE_CELL_GAP
        + wire_extra
        + CELL_GROUP_W
        + GAP
        + OUT_LABEL_W
        + BLOCK_PAD
    )
    return w, block_h


def _declaration_order_outputs(config: PowerSeqConfig) -> list[PowerRail]:
    return [r for r in config.rails if r.seq_type == "output"]


def _label_y_for_input(hl: str, anchor_y: float, index: int) -> float:
    """First label aligns with gate/deb input; later labels stack ±20pt (Hi up, Lo down)."""
    base = anchor_y - LABEL_H / 2
    step = LABEL_STACK_STEP if hl == "lo" else -LABEL_STACK_STEP
    return base + index * step


def _add_term_label(
    b: _Builder,
    label_x: float,
    y: float,
    term: _Term,
    *,
    w: float = LABEL_W,
) -> str:
    val = _cond_html(term.text) if term.is_cond else _input_html(term.text)
    return b.vertex(label_x, y, w, LABEL_H, style=_STYLE_LABEL, value=val)


def _place_gate(
    b: _Builder,
    gate_right: float,
    gy: float,
    w: int,
    h: int,
    style: str,
) -> tuple[str, float]:
    gx = gate_right - w
    gid = b.vertex(gx, gy, w, h, style=style, value="")
    return gid, gx


def _wire_and_branch(
    b: _Builder,
    rail: PowerRail,
    hl: str,
    terms: list[_Term],
    gi: int,
    deb_anchor_y: float,
    attach_right: float,
) -> tuple[str, float]:
    """Wire one group (intra AND/OR/XOR); attach_right is the right edge to abut."""
    if len(terms) == 1:
        # Direct label→Deb: same clearance as gate output→Cell (GATE_CELL_GAP only).
        label_right = attach_right
        label_x = label_right - LABEL_W
        lid = _add_term_label(
            b, label_x, _label_y_for_input(hl, deb_anchor_y, 0), terms[0]
        )
        return lid, label_x

    gy = deb_anchor_y - AND_GATE_H / 2
    merge_style = _intra_merge_gate_style(rail, hl, gi)

    if len(terms) < AND_TREE_THRESHOLD:
        gid, gx = _place_gate(b, attach_right, gy, AND_GATE_W, AND_GATE_H, merge_style)
        label_x = gx - GAP - LABEL_W
        for ii, term in enumerate(terms):
            ly = _label_y_for_input(hl, deb_anchor_y, ii)
            lid = _add_term_label(b, label_x, ly, term)
            b.edge(lid, gid, stroke=STROKE_DEFAULT)
        return gid, label_x

    # 2-level cascade: child gate (left, 不反相) → merge gate (right；group_inv 時 XNOR/NAND/NOR)。
    mid = (len(terms) + 1) // 2
    left_terms, right_terms = terms[:mid], terms[mid:]

    merge_id, merge_gx = _place_gate(b, attach_right, gy, AND_GATE_W, AND_GATE_H, merge_style)
    merge_lane_w = _merge_lane_label_w(right_terms)
    merge_channel = _child_merge_channel(right_terms)
    child_id, child_gx = _place_gate(
        b,
        merge_gx - merge_channel,
        gy,
        AND_GATE_W,
        AND_GATE_H,
        _intra_child_gate_style(rail, hl, gi),
    )

    left_label_x = child_gx - GAP - LABEL_W
    for ii, term in enumerate(left_terms):
        ly = _label_y_for_input(hl, deb_anchor_y, ii)
        lid = _add_term_label(b, left_label_x, ly, term)
        b.edge(lid, child_id, stroke=STROKE_DEFAULT)
    b.edge(child_id, merge_id, stroke=STROKE_DEFAULT)

    right_label_x = merge_gx - GAP - merge_lane_w
    for ii, term in enumerate(right_terms):
        # merge 閘 input 0 保留給 child 輸出（example (2).xml）。
        ly = _label_y_for_input(hl, deb_anchor_y, ii + 1)
        lid = _add_term_label(b, right_label_x, ly, term, w=merge_lane_w)
        b.edge(lid, merge_id, stroke=STROKE_DEFAULT)

    return merge_id, left_label_x


def _wire_or_fanin(
    b: _Builder,
    rail: PowerRail,
    hl: str,
    branch_ids: list[str],
    deb_id: str,
    deb_anchor_y: float,
    gate_right: float,
    stroke: str,
    edge_val: str,
) -> None:
    """Wire OR groups: single OR, or 2-level tree (child OR → merge OR/NOR)."""
    if len(branch_ids) == 1:
        b.edge(branch_ids[0], deb_id, stroke=stroke, value=edge_val)
        return

    gy = deb_anchor_y - OR_GATE_H / 2
    merge_style = _or_gate_style(rail, hl)

    if len(branch_ids) < AND_TREE_THRESHOLD:
        or_id, _ = _place_gate(b, gate_right, gy, OR_GATE_W, OR_GATE_H, merge_style)
        for bid in branch_ids:
            b.edge(bid, or_id, stroke=STROKE_DEFAULT)
        b.edge(or_id, deb_id, stroke=stroke, value=edge_val)
        return

    # 2-level: child OR (left) → merge OR/NOR (right); invert only at merge when NOR.
    mid = (len(branch_ids) + 1) // 2
    left_ids, right_ids = branch_ids[:mid], branch_ids[mid:]

    merge_id, merge_gx = _place_gate(
        b, gate_right, gy, OR_GATE_W, OR_GATE_H, merge_style
    )
    child_id, _ = _place_gate(
        b,
        merge_gx - OR_GATE_W - 2 * GAP,
        gy,
        OR_GATE_W,
        OR_GATE_H,
        _GATE_STYLE_OR,
    )
    for bid in left_ids:
        b.edge(bid, child_id, stroke=STROKE_DEFAULT)
    b.edge(child_id, merge_id, stroke=STROKE_DEFAULT)
    for bid in right_ids:
        b.edge(bid, merge_id, stroke=STROKE_DEFAULT)
    b.edge(merge_id, deb_id, stroke=stroke, value=edge_val)


def _wire_path_v2(
    b: _Builder,
    rail: PowerRail,
    hl: str,
    groups: list[list[str]],
    deb_id: str,
    deb_anchor_y: float,
    cell_x: float,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    exported_hilo: set[tuple[str, str]],
) -> None:
    """Labels (right-aligned) → gates (OR nearest cell, ANDs left) → Deb."""
    stroke = STROKE_HI if hl == "hi" else STROKE_LO
    gate_right = cell_x - GATE_CELL_GAP

    parsed_groups: list[list[_Term]] = _parse_path_group_terms(
        rail, hl, groups, name_to_rail, valid
    )

    if not parsed_groups:
        return

    has_export = (rail.name, hl) in exported_hilo
    if has_export:
        gate_right -= _export_wire_extra_for_name(
            f"{_internal_sig(rail.name)}_{hl}"
        )

    multi_group = len(parsed_groups) >= 2
    branch_attach = _group_branch_attach_right(gate_right, len(parsed_groups))

    branch_ids: list[str] = []
    stack_edge: float | None = None
    for gi, terms in enumerate(parsed_groups):
        if gi == 0:
            anchor_y = deb_anchor_y
        elif hl == "hi":
            assert stack_edge is not None
            _, below = _group_vertical_extents(hl, len(terms))
            anchor_y = stack_edge - below
        else:
            assert stack_edge is not None
            above, _ = _group_vertical_extents(hl, len(terms))
            anchor_y = stack_edge + above

        attach = branch_attach if multi_group else gate_right
        out_id, _ = _wire_and_branch(
            b, rail, hl, terms, gi, anchor_y, attach
        )
        branch_ids.append(out_id)

        above, below = _group_vertical_extents(hl, len(terms))
        if hl == "hi":
            stack_edge = anchor_y - above
        else:
            stack_edge = anchor_y + below

    edge_val = ""
    if has_export:
        edge_val = _export_edge_label(f"{_internal_sig(rail.name)}_{hl}")

    if multi_group:
        _wire_or_fanin(
            b,
            rail,
            hl,
            branch_ids,
            deb_id,
            deb_anchor_y,
            gate_right,
            stroke,
            edge_val,
        )
    else:
        b.edge(branch_ids[0], deb_id, stroke=stroke, value=edge_val)


def _add_pseqcell_group(
    b: _Builder,
    rail: PowerRail,
    cell_x: float,
    cell_y: float,
) -> tuple[str, str, str, str]:
    """PSEQCELL.xml geometry; returns (group_id, h_deb_id, l_deb_id, o_id)."""
    group_id = b.vid()
    gcell = ET.SubElement(
        b.root,
        "mxCell",
        {
            "id": group_id,
            "parent": "1",
            "style": "group;points=[[0,0.25,0,0,0],[0,0.75,0,0,0],[1,0.25,0,0,0],[1,0.75,0,0,0]];",
            "value": "",
            "vertex": "1",
            "connectable": "0",
        },
    )
    ET.SubElement(
        gcell,
        "mxGeometry",
        {
            "x": str(cell_x),
            "y": str(cell_y),
            "width": str(CELL_GROUP_W),
            "height": str(CELL_GROUP_H),
            "as": "geometry",
        },
    )

    def part(style: str, val: str, px: float, py: float, pw: float, ph: float) -> str:
        eid = b.vid()
        c = ET.SubElement(
            b.root,
            "mxCell",
            {"id": eid, "parent": group_id, "style": style, "value": val, "vertex": "1"},
        )
        ET.SubElement(
            c,
            "mxGeometry",
            {"x": str(px), "y": str(py), "width": str(pw), "height": str(ph), "as": "geometry"},
        )
        return eid

    part(_PSEQCELL_STYLE_INNER, "", 0, 0, CELL_INNER_W, CELL_INNER_H)
    h_deb_id = part(
        _PSEQCELL_STYLE_H_DEB,
        _deb_port_label("H", rail.cycle_hi, rail.pulse_hi),
        0,
        CELL_H_DEB_Y,
        CELL_H_DEB_W,
        CELL_H_DEB_H,
    )
    l_deb_id = part(
        _PSEQCELL_STYLE_L_DEB,
        _deb_port_label("L", rail.cycle_lo, rail.pulse_lo),
        0,
        CELL_L_DEB_Y,
        CELL_L_DEB_W,
        CELL_L_DEB_H,
    )
    o_id = part(_PSEQCELL_STYLE_O, "O", CELL_O_X, CELL_O_Y, CELL_O_W, CELL_O_H)
    return group_id, h_deb_id, l_deb_id, o_id


def _build_cell_block(
    b: _Builder,
    rail: PowerRail,
    ox: float,
    oy: float,
    bw: int,
    bh: int,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    exported_hilo: set[tuple[str, str]],
) -> None:
    hi_groups = rail.get_hi_groups()
    lo_groups = rail.get_lo_groups()
    hi_sizes = [len(g) for g in hi_groups]
    hi_count = _max_group_inputs(hi_groups)
    cell_x = _snap_grid(ox + bw - BLOCK_PAD - OUT_LABEL_W - GAP - CELL_GROUP_W)
    cell_y = _snap_grid(_cell_y_in_block(oy, hi_count, hi_sizes))
    h_deb_y = cell_y + CELL_H_DEB_Y + CELL_H_DEB_H / 2
    l_deb_y = cell_y + CELL_L_DEB_Y + CELL_L_DEB_H / 2

    _, h_deb_id, l_deb_id, o_id = _add_pseqcell_group(b, rail, cell_x, cell_y)

    out_x = cell_x + CELL_O_X + CELL_O_W + GAP
    out_y = cell_y + CELL_O_Y + CELL_O_H / 2 - LABEL_H / 2
    out_id = b.vertex(
        out_x, out_y, OUT_LABEL_W, LABEL_H,
        style=_STYLE_OUTPUT,
        value=_escape_xml(rail.name),
    )
    eid = b.vid()
    ec = ET.SubElement(
        b.root,
        "mxCell",
        {
            "id": eid,
            "parent": "1",
            "style": _STYLE_O_OUT,
            "edge": "1",
            "source": o_id,
            "target": out_id,
        },
    )
    ET.SubElement(ec, "mxGeometry", {"relative": "1", "as": "geometry"})

    if hi_groups:
        _wire_path_v2(
            b, rail, "hi", hi_groups, h_deb_id, h_deb_y, cell_x,
            name_to_rail, valid, exported_hilo,
        )
    if lo_groups:
        _wire_path_v2(
            b, rail, "lo", lo_groups, l_deb_id, l_deb_y, cell_x,
            name_to_rail, valid, exported_hilo,
        )


def _grid_columns(n: int, options: DrawioExportOptions) -> int:
    if options.grid_columns is not None:
        return max(1, min(6, options.grid_columns))
    return max(2, min(6, math.ceil(math.sqrt(n))))


def _random_diagram_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=20))


def generate_drawio(
    config: PowerSeqConfig,
    *,
    options: DrawioExportOptions | None = None,
) -> str:
    """Generate cell-centric Draw.io XML (single page, multi-column grid)."""
    opts = options or DrawioExportOptions.defaults()
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail)
    exported_hilo = _exported_hilo_keys(config)
    outputs = _declaration_order_outputs(config)

    n = len(outputs)
    n_cols = _grid_columns(n, opts) if n else 1
    n_rows = math.ceil(n / n_cols) if n else 1

    sizes = [
        _estimate_block_size(r, exported_hilo, name_to_rail=name_to_rail, valid=valid)
        for r in outputs
    ]
    col_widths: list[int] = [0] * n_cols
    row_heights: list[int] = [0] * n_rows
    for i, (w, h) in enumerate(sizes):
        col = i % n_cols
        row = i // n_cols
        col_widths[col] = max(col_widths[col], w)
        row_heights[row] = max(row_heights[row], h)

    col_x = [_snap_grid(opts.margin)]
    for c in range(1, n_cols):
        col_x.append(_snap_grid(col_x[c - 1] + col_widths[c - 1] + COL_GAP))
    row_y = [_snap_grid(opts.margin)]
    for r in range(1, n_rows):
        row_y.append(_snap_grid(row_y[r - 1] + row_heights[r - 1] + ROW_GAP))

    page_w = col_x[-1] + col_widths[-1] + opts.margin if n else 827
    page_h = row_y[-1] + row_heights[-1] + opts.margin if n else 1169

    diagram_id = _random_diagram_id()
    mxfile = ET.Element(
        "mxfile",
        {"host": "app.diagrams.net", "agent": "pwrseq_gen", "version": "1.0"},
    )
    diagram = ET.SubElement(
        mxfile,
        "diagram",
        {"name": config.module_name or "Page-1", "id": diagram_id},
    )
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1200",
            "dy": "800",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(int(page_w)),
            "pageHeight": str(int(page_h)),
            "math": "0",
            "shadow": "0",
        },
    )
    root_el = ET.SubElement(model, "root")
    ET.SubElement(root_el, "mxCell", {"id": "0"})
    ET.SubElement(root_el, "mxCell", {"id": "1", "parent": "0"})

    builder = _Builder(root_el)

    for i, rail in enumerate(outputs):
        col, row = i % n_cols, i // n_cols
        bw, bh = sizes[i]
        _build_cell_block(
            builder,
            rail,
            col_x[col],
            row_y[row],
            col_widths[col],
            row_heights[row],
            name_to_rail,
            valid,
            exported_hilo,
        )

    rough = ET.tostring(mxfile, encoding="unicode")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
