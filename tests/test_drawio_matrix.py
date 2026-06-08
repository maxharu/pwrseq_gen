"""Draw.io 回授矩陣範例：NOR 繪製與 OR/NOR 輸出回授。"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerSeqConfig
from drawio_export import (
    AND_GATE_H,
    OR_GATE_H,
    CELL_GROUP_H,
    CELL_GROUP_W,
    CELL_H_DEB_Y,
    CELL_L_DEB_Y,
    CELL_NQ_X,
    CELL_Q_X,
    STROKE_DEFAULT,
    STROKE_FEEDBACK,
    STROKE_LO,
    _GATE_ENTRY_AY,
    _GATE_STYLE_AND,
    _GATE_STYLE_NAND,
    _GATE_STYLE_NOR,
    _GATE_STYLE_OR,
    _PSEQCELL_STYLE_H_DEB,
    _PSEQCELL_STYLE_INNER,
    _PSEQCELL_STYLE_L_DEB,
    _PSEQCELL_STYLE_Q,
    _count_and_or_middle_slots,
    _count_cell_fb_to_deb,
    _count_or_cell_middle_slots,
    _style_float,
    _unique_cell_fb_to_deb_sources,
    generate_drawio,
)

DEMO_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "doc",
    "demo_json.json",
)

MATRIX_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "reference",
    "drawio_fb_matrix.json",
)


def _is_h_deb_vertex(cell: ET.Element) -> bool:
    return cell.get("vertex") == "1" and (cell.get("style") or "") == _PSEQCELL_STYLE_H_DEB


def _is_l_deb_vertex(cell: ET.Element) -> bool:
    return cell.get("vertex") == "1" and (cell.get("style") or "") == _PSEQCELL_STYLE_L_DEB


class TestDrawioFbMatrix:
    def test_matrix_generates_without_error(self):
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        xml = generate_drawio(cfg)
        assert "<mxfile" in xml

    def test_nor_gate_rendered_for_rail_nor_try_lo(self):
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        nor_styles = [
            (c.get("style") or "")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
            and "negating=1" in (c.get("style") or "")
        ]
        assert len(nor_styles) >= 1, "RAIL_NOR_TRY Lo 應繪製至少一顆 NOR"

    def test_or_output_feedback_edges_exist(self):
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        or_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
        }
        fb_from_or = [
            c
            for c in root.iter("mxCell")
            if c.get("edge") == "1"
            and c.get("source") in or_ids
            and STROKE_FEEDBACK in (c.get("style") or "")
        ]
        assert len(fb_from_or) >= 1, "應有 OR 輸出回授邊（藍色）"

    def test_all_cells_align_when_diagram_has_or(self):
        """全圖有 OR 時，無 OR 列的 Cell 也應與有 OR 列同一 cell_start_x。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        h_deb_x: list[int] = []
        for c in root.iter("mxCell"):
            if not _is_h_deb_vertex(c):
                continue
            geo = c.find("mxGeometry")
            assert geo is not None
            h_deb_x.append(int(float(geo.get("x", "0"))))
        assert len(h_deb_x) >= 2
        assert len(set(h_deb_x)) == 1, f"所有 Cell H_Deb 應同一 x，實際 {sorted(set(h_deb_x))}"

    def test_cell_q_to_or_cross_row_is_feedback_blue(self):
        """Cell Q/~Q 跨列回授至 OR 應為藍色五段走線。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        q_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and c.get("value") == "Q"
        }
        or_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
        }
        q_to_or_fb = [
            c
            for c in root.iter("mxCell")
            if c.get("edge") == "1"
            and c.get("source") in q_ids
            and c.get("target") in or_ids
            and STROKE_FEEDBACK in (c.get("style") or "")
        ]
        assert len(q_to_or_fb) >= 1, "應有 Cell Q 跨列回授至 OR（藍色）"

    def test_same_row_and_to_or_not_feedback_blue(self):
        """同列 AND→OR 為正向走線，不應標成回授藍色。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        and_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=and" in (c.get("style") or "")
            and "negating=1" not in (c.get("style") or "")
        }
        or_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
        }
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            if c.get("source") not in and_ids or c.get("target") not in or_ids:
                continue
            src_geo = next(
                g for cell in root.iter("mxCell")
                if cell.get("id") == c.get("source")
                for g in [cell.find("mxGeometry")]
                if g is not None
            )
            tgt_geo = next(
                g for cell in root.iter("mxCell")
                if cell.get("id") == c.get("target")
                for g in [cell.find("mxGeometry")]
                if g is not None
            )
            if abs(float(src_geo.get("y", 0)) - float(tgt_geo.get("y", 0))) > 120:
                continue
            sty = c.get("style") or ""
            assert STROKE_FEEDBACK not in sty, (
                f"同列 AND→OR edge {c.get('id')} 不應為回授藍色: {sty}"
            )
            assert STROKE_DEFAULT in sty or "#000000" in sty

    def test_fb_cell_counts_use_self_cross_row_only(self):
        """DRAWIO_RULES §八：fb_cell 僅計 use=self 跨列→Deb。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        outputs = [r for r in cfg.rails if r.seq_type == "output"]
        valid = {r.name for r in cfg.rails}
        name_to_rail = {r.name: r for r in cfg.rails}
        output_to_row = {r.name: i for i, r in enumerate(outputs)}
        sources = _unique_cell_fb_to_deb_sources(
            outputs, output_to_row, name_to_rail, valid
        )
        for name in sources:
            found_use = False
            for r in outputs:
                for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
                    for gi, group in enumerate(groups):
                        if len(group) != 1 or group[0] != name:
                            continue
                        use = (
                            r.get_hi_use(gi, 0, name)
                            if hl == "hi"
                            else r.get_lo_use(gi, 0, name)
                        )
                        if use == "self":
                            found_use = True
            assert found_use, f"{name} 在 fb_cell 中但非 use=self"
        assert _count_cell_fb_to_deb(
            outputs, output_to_row, name_to_rail, valid
        ) == len(sources)

    def test_and_or_gap_seven_cells_or_cell_gap_eight_cells(self):
        """AND→OR 中間 5 格 + GAP×2 = 7；OR→Cell 中間 6 格 + GAP×2 = 8。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        outputs = [r for r in cfg.rails if r.seq_type == "output"]
        valid = {r.name for r in cfg.rails}
        name_to_rail = {r.name: r for r in cfg.rails}
        output_to_row = {r.name: i for i, r in enumerate(outputs)}
        assert _count_and_or_middle_slots(
            outputs, output_to_row, name_to_rail, valid
        ) == 5
        assert _count_or_cell_middle_slots(
            outputs, output_to_row, name_to_rail, valid
        ) == 6
        root = ET.fromstring(generate_drawio(cfg))
        and_col = min(
            int(float(c.find("mxGeometry").get("x", 0)))
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=and" in (c.get("style") or "")
            and "negating=1" not in (c.get("style") or "")
        )
        or_col = min(
            int(float(c.find("mxGeometry").get("x", 0)))
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
        )
        cell_col = min(
            int(float(c.find("mxGeometry").get("x", 0)))
            for c in root.iter("mxCell")
            if _is_h_deb_vertex(c)
        )
        assert (or_col - and_col - 80) // 40 == 7
        assert (cell_col - or_col - 80) // 40 == 8

    def test_nor_try_or_output_feedback_to_mix_or_is_blue(self):
        """OR 層 #5/#6（RAIL_NOR_TRY hi/lo）回授至 RAIL_MIX OR 應為藍色 FB。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        or_by_y = sorted(
            (
                int(float(c.find("mxGeometry").get("y", 0))),
                c.get("id"),
            )
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
        )
        nor_hi_id = next(oid for y, oid in or_by_y if y == or_by_y[4][0])
        nor_lo_id = next(oid for y, oid in or_by_y if y == or_by_y[5][0])
        mix_hi_y = or_by_y[2][0]
        mix_lo_y = or_by_y[3][0]
        mix_hi_id = next(oid for y, oid in or_by_y if y == mix_hi_y)
        mix_lo_id = next(oid for y, oid in or_by_y if y == mix_lo_y)
        for src, tgt in ((nor_lo_id, mix_hi_id), (nor_hi_id, mix_lo_id)):
            edge = next(
                c
                for c in root.iter("mxCell")
                if c.get("edge") == "1"
                and c.get("source") == src
                and c.get("target") == tgt
            )
            assert STROKE_FEEDBACK in (edge.get("style") or ""), (
                f"OR {src} -> OR {tgt} 應為藍色回授"
            )

    def test_or_to_or_feedback_uses_five_segment_routing_left_of_or_column(self):
        """OR→OR FB 應為五段凍結走線，③ 幹線在目標 OR 左緣 −40pt。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        or_col = min(
            int(float(c.find("mxGeometry").get("x", 0)))
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
        )
        or_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
        }
        gate_boxes = [
            (
                float(c.find("mxGeometry").get("x", 0)),
                float(c.find("mxGeometry").get("x", 0))
                + float(c.find("mxGeometry").get("width", 0)),
                float(c.find("mxGeometry").get("y", 0)),
                float(c.find("mxGeometry").get("y", 0))
                + float(c.find("mxGeometry").get("height", 0)),
            )
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "logic_gates.logic_gate" in (c.get("style") or "")
        ]
        seen = 0
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1":
                continue
            if cell.get("source") not in or_ids or cell.get("target") not in or_ids:
                continue
            if STROKE_FEEDBACK not in (cell.get("style") or ""):
                continue
            sty = cell.get("style") or ""
            assert "edgeStyle=none" in sty, f"edge {cell.get('id')} 應凍結 edgeStyle=none"
            geo = cell.find("mxGeometry")
            arr = geo.find("Array") if geo is not None else None
            assert arr is not None, f"edge {cell.get('id')} 缺少 waypoints"
            pts = arr.findall("mxPoint")
            assert len(pts) >= 5, f"edge {cell.get('id')} 應有五段 waypoints"
            p1y = float(pts[0].get("y"))
            p2x = float(pts[1].get("x"))
            p2y = float(pts[1].get("y"))
            p3x = float(pts[2].get("x"))
            assert p2y < p1y, f"edge {cell.get('id')}: gate FB ② 應向上"
            assert p3x < or_col, f"edge {cell.get('id')}: p3x={p3x} 應在目標 OR 左緣 {or_col} 左側"
            # clean_row：③ 水平列不得壓在橫線 x 區間內任何閘體/閘邊
            lo_x, hi_x = sorted((p2x, p3x))
            for gx0, gx1, gy0, gy1 in gate_boxes:
                if gx1 >= lo_x and gx0 <= hi_x:
                    assert not (gy0 <= p2y <= gy1), (
                        f"edge {cell.get('id')}: ③ 橫線 y={p2y} 壓在閘 "
                        f"[{gx0},{gx1}]x[{gy0},{gy1}] 上"
                    )
            seen += 1
        assert seen >= 4, f"預期至少 4 條 OR→OR FB，得 {seen}"

    def test_and_to_and_feedback_uses_clear_row_for_segment_two(self):
        """AND→AND gate FB：② 動態避讓相鄰閘，③ 橫線不壓閘體。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        and_col = min(
            int(float(c.find("mxGeometry").get("x", 0)))
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=and" in (c.get("style") or "")
        )
        and_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "logic_gates.logic_gate" in (c.get("style") or "")
            and "operation=and" in (c.get("style") or "")
        }
        gate_boxes = [
            (
                float(c.find("mxGeometry").get("x", 0)),
                float(c.find("mxGeometry").get("x", 0))
                + float(c.find("mxGeometry").get("width", 0)),
                float(c.find("mxGeometry").get("y", 0)),
                float(c.find("mxGeometry").get("y", 0))
                + float(c.find("mxGeometry").get("height", 0)),
            )
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "logic_gates.logic_gate" in (c.get("style") or "")
        ]
        seen = 0
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1":
                continue
            if cell.get("source") not in and_ids or cell.get("target") not in and_ids:
                continue
            if STROKE_FEEDBACK not in (cell.get("style") or ""):
                continue
            sty = cell.get("style") or ""
            assert "edgeStyle=none" in sty, f"edge {cell.get('id')} 應凍結 edgeStyle=none"
            geo = cell.find("mxGeometry")
            arr = geo.find("Array") if geo is not None else None
            assert arr is not None, f"edge {cell.get('id')} 缺少 waypoints"
            pts = arr.findall("mxPoint")
            assert len(pts) >= 5, f"edge {cell.get('id')} 應有五段 waypoints"
            p1y = float(pts[0].get("y"))
            p2x = float(pts[1].get("x"))
            p2y = float(pts[1].get("y"))
            p3x = float(pts[2].get("x"))
            assert p2y < p1y, f"edge {cell.get('id')}: gate FB ② 應向上"
            assert p3x <= and_col, (
                f"edge {cell.get('id')}: p3x={p3x} 應在目標 AND 左緣 {and_col} 左側"
            )
            lo_x, hi_x = sorted((p2x, p3x))
            for gx0, gx1, gy0, gy1 in gate_boxes:
                if gx1 >= lo_x and gx0 <= hi_x:
                    assert not (gy0 <= p2y <= gy1), (
                        f"edge {cell.get('id')}: ③ 橫線 y={p2y} 壓在閘 "
                        f"[{gx0},{gx1}]x[{gy0},{gy1}] 上"
                    )
            seen += 1
        assert seen >= 1, f"預期至少 1 條 AND→AND FB，得 {seen}"

    def test_nor_try_or_output_feedback_to_orfb_or_is_blue(self):
        """OR 層 #5/#6（RAIL_NOR_TRY hi/lo）回授至 RAIL_ORFB OR 應為藍色 FB。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        or_by_y = sorted(
            (
                int(float(c.find("mxGeometry").get("y", 0))),
                c.get("id"),
            )
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
        )
        nor_hi_id = next(oid for y, oid in or_by_y if y == or_by_y[4][0])
        nor_lo_id = next(oid for y, oid in or_by_y if y == or_by_y[5][0])
        orfb_hi_id = next(oid for y, oid in or_by_y if y == or_by_y[6][0])
        orfb_lo_id = next(oid for y, oid in or_by_y if y == or_by_y[7][0])
        for src, tgt in ((nor_lo_id, orfb_hi_id), (nor_hi_id, orfb_lo_id)):
            edge = next(
                c
                for c in root.iter("mxCell")
                if c.get("edge") == "1"
                and c.get("source") == src
                and c.get("target") == tgt
            )
            assert STROKE_FEEDBACK in (edge.get("style") or ""), (
                f"OR {src} -> OR {tgt} 應為藍色回授"
            )

    def test_forward_cross_row_and_to_or_not_feedback_blue(self):
        """正向跨列（上游→下游）AND/OR 邊不應標成回授藍色。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        gate_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "logic_gate" in (c.get("style") or "")
        }
        or_gate_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
        }
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            src, tgt = c.get("source"), c.get("target")
            if src not in gate_ids or tgt not in gate_ids:
                continue
            if src in or_gate_ids and tgt in or_gate_ids:
                continue
            src_y = float(
                next(
                    cell.find("mxGeometry").get("y")
                    for cell in root.iter("mxCell")
                    if cell.get("id") == src and cell.find("mxGeometry") is not None
                )
            )
            tgt_y = float(
                next(
                    cell.find("mxGeometry").get("y")
                    for cell in root.iter("mxCell")
                    if cell.get("id") == tgt and cell.find("mxGeometry") is not None
                )
            )
            if src_y >= tgt_y:
                continue
            assert STROKE_FEEDBACK not in (c.get("style") or ""), (
                f"正向跨列邊 {c.get('id')} 不應為回授藍色"
            )

    def test_pseqcell_layout_loaded_from_reference_xml(self):
        """Cell 幾何須自 PSEQCELL.xml 載入（對應 PSEQCELL.v）。"""
        assert CELL_GROUP_W == 80 and CELL_GROUP_H == 80
        assert CELL_Q_X == 60 and CELL_NQ_X == 60
        assert CELL_H_DEB_Y == 10 and CELL_L_DEB_Y == 50

    def test_pseqcell_vertex_styles_match_reference_xml(self):
        """Cell 各部件 style（含 points 連接點）須與 PSEQCELL.xml 一致。"""
        assert "points=" in _PSEQCELL_STYLE_H_DEB
        assert "points=" in _PSEQCELL_STYLE_L_DEB
        assert "points=" in _PSEQCELL_STYLE_Q
        assert _PSEQCELL_STYLE_H_DEB != _PSEQCELL_STYLE_L_DEB
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        by_role: dict[str, str] = {}
        for c in root.iter("mxCell"):
            if c.get("vertex") != "1":
                continue
            sty = c.get("style") or ""
            val = (c.get("value") or "").strip()
            if sty == _PSEQCELL_STYLE_INNER:
                by_role.setdefault("inner", sty)
            elif sty == _PSEQCELL_STYLE_H_DEB:
                by_role.setdefault("h_deb", sty)
            elif sty == _PSEQCELL_STYLE_L_DEB:
                by_role.setdefault("l_deb", sty)
            elif val == "Q":
                by_role.setdefault("q", sty)
            elif val == "~Q":
                by_role.setdefault("nq", sty)
        assert by_role.get("inner") == _PSEQCELL_STYLE_INNER
        assert by_role.get("h_deb") == _PSEQCELL_STYLE_H_DEB
        assert by_role.get("l_deb") == _PSEQCELL_STYLE_L_DEB
        assert by_role.get("q") == _PSEQCELL_STYLE_Q
        assert by_role.get("nq") == _PSEQCELL_STYLE_Q

    def test_logic_gate_styles_match_reference_xml(self):
        """匯出 AND/NAND/OR/NOR 的 style 須與 reference/*1.xml 一致。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        allowed = {_GATE_STYLE_AND, _GATE_STYLE_NAND, _GATE_STYLE_OR, _GATE_STYLE_NOR}
        for c in root.iter("mxCell"):
            if c.get("vertex") != "1":
                continue
            sty = c.get("style") or ""
            if "logic_gates.logic_gate" not in sty:
                continue
            assert sty in allowed, f"gate style must match *1.xml reference, got: {sty!r}"
            assert "numInputs=1" in sty

    def test_gate_input_edges_use_single_entry_anchor(self):
        """進 AND/OR/NAND/NOR 的邊須接唯一輸入錨點 entryY=0.5。"""
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        gate_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and "logic_gates.logic_gate" in (c.get("style") or "")
        }
        assert gate_ids
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            if c.get("target") not in gate_ids:
                continue
            sty = c.get("style") or ""
            ay = _style_float(sty, "entryY", -1.0)
            assert ay == _GATE_ENTRY_AY, (
                f"edge {c.get('id')} into gate must use entryY={_GATE_ENTRY_AY}, got {ay}"
            )


def _output_name_y(root: ET.Element, name: str) -> float:
    for c in root.iter("mxCell"):
        if (c.get("value") or "").strip() != name:
            continue
        g = c.find("mxGeometry")
        if g is None or float(g.get("x", 0)) < 2000:
            continue
        return float(g.get("y", 0))
    raise AssertionError(f"output name {name!r} not found")


def _deb_center_y_by_rail(root: ET.Element, rail: str, hl: str) -> float:
    name_y = _output_name_y(root, rail)
    pred = _is_h_deb_vertex if hl == "hi" else _is_l_deb_vertex
    for c in root.iter("mxCell"):
        if not pred(c):
            continue
        g = c.find("mxGeometry")
        if g is None:
            continue
        dy = abs(float(g.get("y", 0)) - name_y)
        if dy < 80:
            return float(g.get("y", 0)) + 10
    raise AssertionError(f"{rail} {hl} deb not found")


def _deb_id_by_rail(root: ET.Element, rail: str, hl: str) -> str:
    name_y = _output_name_y(root, rail)
    pred = _is_h_deb_vertex if hl == "hi" else _is_l_deb_vertex
    for c in root.iter("mxCell"):
        if not pred(c):
            continue
        g = c.find("mxGeometry")
        if g is None:
            continue
        if abs(float(g.get("y", 0)) - name_y) < 80:
            return c.get("id") or ""
    raise AssertionError(f"{rail} {hl} deb not found")


def _matrix_rail_name_y(root: ET.Element, rail: str) -> float:
    """fb matrix 圖幅較小，output name 的 x 可能 < 2000。"""
    for c in root.iter("mxCell"):
        if (c.get("value") or "").strip() != rail:
            continue
        g = c.find("mxGeometry")
        if g is not None:
            return float(g.get("y", 0))
    raise AssertionError(f"output name {rail!r} not found")


def _matrix_deb_center_y(root: ET.Element, rail: str, hl: str) -> float:
    name_y = _matrix_rail_name_y(root, rail)
    pred = _is_h_deb_vertex if hl == "hi" else _is_l_deb_vertex
    for c in root.iter("mxCell"):
        if not pred(c):
            continue
        g = c.find("mxGeometry")
        if g is None:
            continue
        if abs(float(g.get("y", 0)) - name_y) < 80:
            return float(g.get("y", 0)) + 10
    raise AssertionError(f"{rail} {hl} deb not found")


class TestOrDebAlignment:
    """OR／NOR 須對齊同列 H_Deb／L_Deb（與 AND 錨定規則一致）。"""

    @pytest.fixture
    def matrix_root(self):
        with open(MATRIX_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        return ET.fromstring(generate_drawio(cfg))

    @pytest.mark.parametrize("rail,hl", [("RAIL_NOR_TRY", "hi"), ("RAIL_NOR_TRY", "lo")])
    def test_or_center_aligns_with_deb(self, matrix_root, rail, hl):
        root = matrix_root
        deb_cy = _matrix_deb_center_y(root, rail, hl)
        name_y = _matrix_rail_name_y(root, rail)
        nor = hl == "lo" and rail == "RAIL_NOR_TRY"
        or_gates = [
            c
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=or" in (c.get("style") or "")
            and (("negating=1" in (c.get("style") or "")) == nor)
            and c.find("mxGeometry") is not None
        ]
        matched = None
        for c in or_gates:
            g = c.find("mxGeometry")
            ay = float(g.get("y", 0))
            cy = ay + OR_GATE_H / 2
            if abs(cy - deb_cy) < 3 and abs(ay - name_y) < 120:
                matched = c
                break
        assert matched is not None, f"{rail} {hl} OR/NOR at {deb_cy} not found"
        g = matched.find("mxGeometry")
        cy = float(g.get("y", 0)) + OR_GATE_H / 2
        assert abs(cy - deb_cy) < 3, f"{rail} {hl} gate center {cy} != Deb {deb_cy}"


class TestLoOnlyAndPlacement:
    """Lo-only AND（無同列 hi AND）須對齊 L_Deb，不可佔 hi 槽位。"""

    @pytest.fixture
    def demo_root(self):
        with open(DEMO_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        return ET.fromstring(generate_drawio(cfg))

    @pytest.mark.parametrize("rail", ["PVCCIO_EN", "PVCC1V8_EN"])
    def test_lo_and_center_aligns_with_l_deb(self, demo_root, rail):
        root = demo_root
        l_deb_cy = _deb_center_y_by_rail(root, rail, "lo")
        h_deb_cy = _deb_center_y_by_rail(root, rail, "hi")
        name_y = _output_name_y(root, rail)

        and_gates = [
            c
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=and" in (c.get("style") or "")
            and c.find("mxGeometry") is not None
        ]
        lo_and = None
        for c in and_gates:
            g = c.find("mxGeometry")
            ay = float(g.get("y", 0))
            cy = ay + AND_GATE_H / 2
            if abs(cy - l_deb_cy) < 3 and abs(ay - name_y) < 120:
                lo_and = c
                break
        assert lo_and is not None, f"{rail} lo AND at L_Deb height not found"
        g = lo_and.find("mxGeometry")
        cy = float(g.get("y", 0)) + AND_GATE_H / 2
        assert abs(cy - l_deb_cy) < 3, f"{rail} lo AND center {cy} != L_Deb {l_deb_cy}"
        assert abs(cy - h_deb_cy) > 10, f"{rail} lo AND must not sit on H_Deb center"

    @pytest.mark.parametrize("rail", ["PVCC1V8_EN"])
    def test_lo_and_to_l_deb_horizontal_when_aligned(self, demo_root, rail):
        root = demo_root
        l_deb_id = _deb_id_by_rail(root, rail, "lo")
        lo_edges = [
            c
            for c in root.iter("mxCell")
            if c.get("edge") == "1"
            and c.get("target") == l_deb_id
            and STROKE_LO in (c.get("style") or "")
        ]
        assert len(lo_edges) == 1, f"{rail} expected 1 lo→L_Deb edge"
        geo = lo_edges[0].find("mxGeometry")
        pts = geo.find("Array") if geo is not None else None
        assert pts is None, f"{rail} lo AND→L_Deb should be horizontal (no stub waypoints)"
