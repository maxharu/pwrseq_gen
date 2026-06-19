"""Cell-centric Draw.io export tests."""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerSeqConfig, PowerRail
from drawio_cell_export import (
    AND_TREE_THRESHOLD,
    EXPORT_WIRE_MIN,
    LABEL_STACK_STEP,
    _Term,
    _child_merge_channel,
    _export_wire_extra_for_name,
    _merge_lane_label_w,
)
from drawio_export import (
    AND_GATE_H,
    AND_GATE_W,
    CELL_O_H,
    CELL_O_W,
    CELL_O_X,
    CELL_O_Y,
    GAP,
    GRID,
    STROKE_HI,
    STROKE_LO,
    _PSEQCELL_STYLE_H_DEB,
    _PSEQCELL_STYLE_INNER,
    _PSEQCELL_STYLE_O,
    generate_drawio,
)

DEMO_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "doc",
    "demo_json.json",
)


def _load_demo():
    with open(DEMO_JSON, encoding="utf-8") as f:
        return PowerSeqConfig.from_dict(json.load(f))


def _cell_by_id(root, cid):
    return next(c for c in root.iter("mxCell") if c.get("id") == cid)


class TestCellCentricDrawio:
    def test_each_output_has_cell_group(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        groups = [c for c in root.iter("mxCell") if c.get("connectable") == "0"]
        outputs = [r for r in _load_demo().rails if r.seq_type == "output"]
        assert len(groups) == len(outputs)

    def test_cell_group_contains_h_deb_and_o(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        groups = {c.get("id") for c in root.iter("mxCell") if c.get("connectable") == "0"}
        h_deb_in_group = o_in_group = False
        for c in root.iter("mxCell"):
            if c.get("parent") not in groups:
                continue
            if (c.get("style") or "") == _PSEQCELL_STYLE_H_DEB:
                h_deb_in_group = True
            if (c.get("value") or "").strip() == "O":
                o_in_group = True
        assert h_deb_in_group and o_in_group

    def test_output_edge_from_o_right(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        o_cells = [
            c for c in root.iter("mxCell")
            if (c.get("value") or "").strip() == "O"
        ]
        assert o_cells
        o_id = o_cells[0].get("id")
        edge = next(
            e for e in root.iter("mxCell")
            if e.get("edge") == "1" and e.get("source") == o_id
        )
        assert "exitX=1" in (edge.get("style") or "")
        o_parent = next(c for c in root.iter("mxCell") if c.get("id") == o_cells[0].get("parent"))
        g_grp = o_parent.find("mxGeometry")
        g_o = o_cells[0].find("mxGeometry")
        cell_x = float(g_grp.get("x", 0))
        cell_y = float(g_grp.get("y", 0))
        o_right = cell_x + float(g_o.get("x", 0)) + float(g_o.get("width", 0))
        tgt = next(c for c in root.iter("mxCell") if c.get("id") == edge.get("target"))
        out_x = float(tgt.find("mxGeometry").get("x", 0))
        assert abs(out_x - (o_right + GAP)) < 1.5
        o_cy = cell_y + float(g_o.get("y", 0)) + float(g_o.get("height", 0)) / 2
        out_y = float(tgt.find("mxGeometry").get("y", 0)) + 10
        assert abs(out_y - o_cy) < 1.5

    def test_edges_use_orthogonal_auto_only(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            sty = c.get("style") or ""
            assert "orthogonalEdgeStyle" in sty
            assert "edgeStyle=none" not in sty

    def test_cell_inner_geometry_matches_pseqcell(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        inners = []
        for c in root.iter("mxCell"):
            if (c.get("style") or "") != _PSEQCELL_STYLE_INNER:
                continue
            g = c.find("mxGeometry")
            inners.append((float(g.get("width", 0)), float(g.get("height", 0))))
        assert inners
        assert all(w == 80 and h == 80 for w, h in inners)

    def test_label_to_gate_gap_40pt(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        for c in root.iter("mxCell"):
            if "logic_gate" not in (c.get("style") or ""):
                continue
            gx = float(c.find("mxGeometry").get("x", 0))
            for e in root.iter("mxCell"):
                if e.get("edge") != "1" or e.get("target") != c.get("id"):
                    continue
                src = e.get("source")
                sc = next(x for x in root.iter("mxCell") if x.get("id") == src)
                if "strokeColor=none" not in (sc.get("style") or ""):
                    continue
                lx = float(sc.find("mxGeometry").get("x", 0))
                lw = float(sc.find("mxGeometry").get("width", 0))
                assert abs(gx - (lx + lw) - 40) < 1.5
                break
            break

    def test_multi_label_stacks_20pt_from_gate_input(self):
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("IN_A", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail("IN_B", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_hi_groups=[["IN_A", "IN_B"]],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        gate = next(c for c in root.iter("mxCell") if "logic_gate" in (c.get("style") or ""))
        gg = gate.find("mxGeometry")
        gate_cy = float(gg.get("y")) + AND_GATE_H / 2
        labels = []
        for e in root.iter("mxCell"):
            if e.get("edge") != "1" or e.get("target") != gate.get("id"):
                continue
            src = _cell_by_id(root, e.get("source"))
            if "strokeColor=none" not in (src.get("style") or ""):
                continue
            lg = src.find("mxGeometry")
            labels.append((float(lg.get("y")), float(lg.get("x"))))
        labels.sort(key=lambda t: t[0])
        assert len(labels) == 2
        assert labels[0][1] == labels[1][1]
        centers = sorted(y + 10 for y, _ in labels)
        assert abs(centers[-1] - gate_cy) < 1.5
        assert abs(centers[-1] - centers[0] - LABEL_STACK_STEP) < 1.5

    def test_export_wire_longer_than_gate_cell_gap(self):
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("IN_A", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail("IN_B", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail(
                    "PROD",
                    seq_type="output",
                    depends_on_hi_groups=[["IN_A", "IN_B"]],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
                PowerRail(
                    "CONS",
                    seq_type="output",
                    depends_on_hi_groups=[["PROD"]],
                    depends_on_hi_use_groups=[["hi"]],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        export_edge = next(
            e
            for e in root.iter("mxCell")
            if e.get("edge") == "1"
            and "prod_hi" in (e.get("value") or "").lower()
        )
        gate = _cell_by_id(root, export_edge.get("source"))
        deb = _cell_by_id(root, export_edge.get("target"))
        group = _cell_by_id(root, deb.get("parent"))
        cell_x = float(group.find("mxGeometry").get("x"))
        gate_right = float(gate.find("mxGeometry").get("x")) + AND_GATE_W
        gap = cell_x - gate_right
        assert gap >= GAP + EXPORT_WIRE_MIN - 1

    def test_long_export_name_gets_wider_wire(self):
        long_name = "pld_cpu1_mem_ik_pwrgd_od_lo"
        extra = _export_wire_extra_for_name(long_name)
        assert extra > EXPORT_WIRE_MIN
        assert extra % GRID == 0
        assert GAP + extra >= len(long_name) * 7

    def test_export_wire_extra_on_40pt_grid(self):
        for name in ("prod_lo", "a", "pld_cpu1_mem_ik_pwrgd_od_lo"):
            extra = _export_wire_extra_for_name(name)
            assert extra % GRID == 0
            assert (GAP + extra) % GRID == 0

    def test_label_to_deb_direct_gap_40pt(self):
        """Single input, no gate: label right edge → Cell is GATE_CELL_GAP (40pt)."""
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("IN_A", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_hi=["IN_A"],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        gates = [c for c in root.iter("mxCell") if "logic_gate" in (c.get("style") or "")]
        assert not gates
        label = next(
            c
            for c in root.iter("mxCell")
            if "strokeColor=none" in (c.get("style") or "")
            and (c.get("value") or "").find("IN_A") >= 0
        )
        deb = next(
            c
            for c in root.iter("mxCell")
            if c.get("parent") != "1" and "fillColor=#f8cecc" in (c.get("style") or "")
        )
        group = next(c for c in root.iter("mxCell") if c.get("id") == deb.get("parent"))
        cell_x = float(group.find("mxGeometry").get("x"))
        lx = float(label.find("mxGeometry").get("x"))
        lw = float(label.find("mxGeometry").get("width"))
        gap = cell_x - (lx + lw)
        assert abs(gap - GAP) < 1.5

    def test_direct_export_wire_long_enough(self):
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("IN_A", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail(
                    "PROD",
                    seq_type="output",
                    depends_on_lo=["IN_A"],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
                PowerRail(
                    "CONS",
                    seq_type="output",
                    depends_on_lo=["PROD"],
                    depends_on_lo_use={"PROD": "lo"},
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        export_edge = next(
            e
            for e in root.iter("mxCell")
            if e.get("edge") == "1"
            and "prod_lo" in (e.get("value") or "").lower()
        )
        deb = _cell_by_id(root, export_edge.get("target"))
        group = _cell_by_id(root, deb.get("parent"))
        cell_x = float(group.find("mxGeometry").get("x"))
        src = _cell_by_id(root, export_edge.get("source"))
        src_x = float(src.find("mxGeometry").get("x"))
        src_w = float(src.find("mxGeometry").get("width"))
        gap = cell_x - (src_x + src_w)
        assert gap >= GAP + _export_wire_extra_for_name("prod_lo") - 1
        assert gap % GRID == 0

    def test_two_level_and_tree_for_many_inputs(self):
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
        cfg = PowerSeqConfig(
            rails=[
                *[PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1) for n in deps],
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_hi_groups=[deps],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        and_gates = [
            c for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "") and "operation=and" in (c.get("style") or "")
        ]
        assert len(and_gates) == 2
        merge = max(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        child = min(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        merge_x = float(merge.find("mxGeometry").get("x"))
        child_x = float(child.find("mxGeometry").get("x"))
        assert merge_x > child_x
        child_out = next(
            e for e in root.iter("mxCell")
            if e.get("edge") == "1"
            and e.get("source") == child.get("id")
            and e.get("target") == merge.get("id")
        )
        assert child_out is not None
        left_labels = {
            e.get("source")
            for e in root.iter("mxCell")
            if e.get("edge") == "1" and e.get("target") == child.get("id")
        }
        right_labels = {
            e.get("source")
            for e in root.iter("mxCell")
            if e.get("edge") == "1" and e.get("target") == merge.get("id")
            and "logic_gate" not in (_cell_by_id(root, e.get("source")).get("style") or "")
        }
        assert len(left_labels) == AND_TREE_THRESHOLD // 2 + AND_TREE_THRESHOLD % 2
        assert len(right_labels) == AND_TREE_THRESHOLD // 2
        for lid in left_labels:
            lx = float(_cell_by_id(root, lid).find("mxGeometry").get("x"))
            for rid in right_labels:
                rx = float(_cell_by_id(root, rid).find("mxGeometry").get("x"))
                assert lx < rx
        left_ys = sorted(
            float(_cell_by_id(root, lid).find("mxGeometry").get("y"))
            for lid in left_labels
        )
        right_ys = sorted(
            float(_cell_by_id(root, rid).find("mxGeometry").get("y"))
            for rid in right_labels
        )
        gate_cy = float(child.find("mxGeometry").get("y")) + AND_GATE_H / 2
        assert abs(left_ys[-1] + 10 - gate_cy) < 1.5
        assert abs(right_ys[-1] + 10 - gate_cy) > LABEL_STACK_STEP - 1

    def test_child_merge_channel_on_40pt_grid(self):
        long_name = "PLD_CPU1_MEM_IK_PWRGD_OD"
        right = [_Term(f"IN_{i}") for i in range(4)] + [_Term(long_name)]
        ch = _child_merge_channel(right)
        assert ch % GRID == 0
        assert ch >= GAP + _merge_lane_label_w(right) + GAP - 1

    def test_and_tree_child_merge_gap_fits_long_merge_labels(self):
        long_name = "PLD_CPU1_MEM_IK_PWRGD_OD"
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD - 1)] + [long_name]
        cfg = PowerSeqConfig(
            rails=[
                *[PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1) for n in deps],
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_hi_groups=[deps],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        and_gates = [
            c for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "") and "operation=and" in (c.get("style") or "")
        ]
        merge = max(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        child = min(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        merge_x = float(merge.find("mxGeometry").get("x"))
        child_x = float(child.find("mxGeometry").get("x"))
        channel = merge_x - (child_x + AND_GATE_W)
        assert channel % GRID == 0
        assert channel >= GAP + _merge_lane_label_w([_Term(long_name)]) + GAP - 1
        merge_labels = [
            _cell_by_id(root, e.get("source"))
            for e in root.iter("mxCell")
            if e.get("edge") == "1"
            and e.get("target") == merge.get("id")
            and "logic_gate"
            not in (_cell_by_id(root, e.get("source")).get("style") or "")
        ]
        long_label = next(
            c for c in merge_labels if long_name in (c.get("value") or "")
        )
        lw = float(long_label.find("mxGeometry").get("width"))
        assert lw >= len(long_name) * 7
        assert lw % GRID == 0
        assert child_x + AND_GATE_W + GAP <= float(long_label.find("mxGeometry").get("x")) + 1.5

    def test_group_inv_and_tree_child_and_merge_nand(self):
        """group_inv + ≥8 inputs: child AND, merge NAND (~(child & rights))."""
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
        cfg = PowerSeqConfig(
            rails=[
                *[
                    PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1)
                    for n in deps
                ],
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_lo_groups=[deps],
                    depends_on_lo_group_inv=[True],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        and_gates = [
            c
            for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "")
            and "operation=and" in (c.get("style") or "")
        ]
        assert len(and_gates) == 2
        merge = max(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        child = min(and_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        assert "negating=1" not in (child.get("style") or "")
        assert "negating=1" in (merge.get("style") or "")

    def test_group_inv_xor_tree_child_xor_merge_xnor(self):
        """group_inv + XOR + ≥8 inputs: child XOR, merge XNOR (~(child ^ rights))."""
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
        cfg = PowerSeqConfig(
            rails=[
                *[
                    PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1)
                    for n in deps
                ],
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_lo_groups=[deps],
                    depends_on_lo_group_inv=[True],
                    depends_on_lo_intra_op=["xor"],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        xor_gates = [
            c
            for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "")
            and "operation=xor" in (c.get("style") or "")
        ]
        assert len(xor_gates) == 2
        merge = max(xor_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        child = min(xor_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        assert "negating=1" not in (child.get("style") or "")
        assert "negating=1" in (merge.get("style") or "")

    def test_or_output_not_tree_child_or_merge_nor(self):
        """_or_output_not + ≥8 single-term groups: child OR, merge NOR."""
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
        cfg = PowerSeqConfig(
            rails=[
                *[
                    PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1)
                    for n in deps
                ],
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_lo_groups=[[n] for n in deps],
                    depends_on_lo_group_inv=[True] * len(deps),
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        or_gates = [
            c
            for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "")
            and "operation=or" in (c.get("style") or "")
        ]
        assert len(or_gates) == 2
        merge = max(or_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        child = min(or_gates, key=lambda c: float(c.find("mxGeometry").get("x")))
        assert "negating=1" not in (child.get("style") or "")
        assert "negating=1" in (merge.get("style") or "")

    def test_multi_group_vertical_stack_same_gate_x(self):
        """Multi-group: OR is GAP right of branch column; groups share X, stack on Y."""
        deps = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
        cfg = PowerSeqConfig(
            rails=[
                *[PowerRail(n, seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1) for n in deps],
                PowerRail("G2", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail("G3A", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail("G3B", seq_type="input", deb_cycle_hi=1, deb_cycle_lo=1),
                PowerRail(
                    "OUT",
                    seq_type="output",
                    depends_on_hi_groups=[deps, ["G2"], ["G3A", "G3B"]],
                    cycle_hi=1,
                    cycle_lo=1,
                ),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        or_gate = next(
            c
            for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "")
            and "operation=or" in (c.get("style") or "")
        )
        and_gates = [
            c
            for c in root.iter("mxCell")
            if "logic_gate" in (c.get("style") or "")
            and "operation=and" in (c.get("style") or "")
            and "negating=1" not in (c.get("style") or "")
        ]
        og = or_gate.find("mxGeometry")
        or_x = float(og.get("x"))
        or_y = float(og.get("y"))
        merge_right = or_x - GAP
        merge_gates = [
            g
            for g in and_gates
            if abs(float(g.find("mxGeometry").get("x")) + AND_GATE_W - merge_right) < 1.5
        ]
        assert len(merge_gates) >= 2
        merge_xs = {float(g.find("mxGeometry").get("x")) for g in merge_gates}
        assert len(merge_xs) == 1
        merge_y = [float(g.find("mxGeometry").get("y")) for g in merge_gates]
        assert len({round(y) for y in merge_y}) >= 2
        assert min(merge_y) < or_y - 1

    def test_outputs_follow_declaration_order(self):
        cfg = PowerSeqConfig(
            rails=[
                PowerRail("A", seq_type="output", depends_on_hi=["__HIGH__"], cycle_hi=1),
                PowerRail("B", seq_type="output", depends_on_hi=["__HIGH__"], cycle_hi=1),
                PowerRail("C", seq_type="output", depends_on_hi=["__HIGH__"], cycle_hi=1),
            ]
        )
        root = ET.fromstring(generate_drawio(cfg))
        positions = []
        for name in ("A", "B", "C"):
            out = next(
                c for c in root.iter("mxCell")
                if (c.get("value") or "") == name
            )
            g = out.find("mxGeometry")
            positions.append((float(g.get("x")), float(g.get("y"))))
        order = sorted(range(3), key=lambda i: (positions[i][1], positions[i][0]))
        assert order == [0, 1, 2]

    def test_hi_lo_stroke_colors_to_deb(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        counts = {STROKE_HI: 0, STROKE_LO: 0}
        deb_ids = set()
        for c in root.iter("mxCell"):
            sty = c.get("style") or ""
            if "fillColor=#f8cecc" in sty or "fillColor=#d5e8d4" in sty:
                deb_ids.add(c.get("id"))
        for c in root.iter("mxCell"):
            if c.get("edge") != "1" or c.get("target") not in deb_ids:
                continue
            sty = c.get("style") or ""
            for color in counts:
                if color in sty:
                    counts[color] += 1
        assert counts[STROKE_HI] > 0
        assert counts[STROKE_LO] > 0

    def test_cell_top_left_on_40pt_grid(self):
        root = ET.fromstring(generate_drawio(_load_demo()))
        for c in root.iter("mxCell"):
            if c.get("connectable") != "0":
                continue
            g = c.find("mxGeometry")
            x = float(g.get("x", 0))
            y = float(g.get("y", 0))
            assert x % GRID == 0, f"cell x={x} not on {GRID}pt grid"
            assert y % GRID == 0, f"cell y={y} not on {GRID}pt grid"
