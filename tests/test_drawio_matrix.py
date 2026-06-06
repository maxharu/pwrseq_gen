"""Draw.io 回授矩陣範例：NOR 繪製與 OR/NOR 輸出回授。"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerSeqConfig
from drawio_export import (
    STROKE_DEFAULT,
    STROKE_FEEDBACK,
    _GATE_ENTRY_AY,
    _GATE_STYLE_AND,
    _GATE_STYLE_NAND,
    _GATE_STYLE_NOR,
    _GATE_STYLE_OR,
    _count_and_or_middle_slots,
    _count_cell_fb_to_deb,
    _count_or_cell_middle_slots,
    _style_float,
    _unique_cell_fb_to_deb_sources,
    generate_drawio,
)

MATRIX_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "reference",
    "drawio_fb_matrix.json",
)


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
            if c.get("vertex") != "1" or c.get("value") != "H_Deb":
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
            if c.get("vertex") == "1" and c.get("value") == "H_Deb"
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
