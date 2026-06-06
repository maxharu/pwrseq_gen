"""整合測試：載入 JSON、驗證、產生 Verilog、Draw.io"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig
from validator import validate
from verilog_generator import generate_verilog
from drawio_export import STROKE_FEEDBACK, generate_drawio


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")


class TestLoadSampleConfigs:
    """載入專案內 JSON 設定檔"""

    def test_load_sample_config(self):
        path = os.path.join(OUTPUT_DIR, "sample_config.json")
        if not os.path.exists(path):
            pytest.skip("sample_config.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) > 0
        ok, _ = validate(cfg)
        assert ok, "sample_config should be valid"

    def test_load_debug_config(self):
        path = os.path.join(OUTPUT_DIR, "debug.json")
        if not os.path.exists(path):
            pytest.skip("debug.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) >= 3
        ok, errs = validate(cfg)
        assert ok, f"debug.json should be valid: {errs}"

    def test_load_test_deb_config(self):
        path = os.path.join(OUTPUT_DIR, "test_deb.json")
        if not os.path.exists(path):
            pytest.skip("test_deb.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        ok, errs = validate(cfg)
        assert ok, f"test_deb.json should be valid: {errs}"


class TestFullPipeline:
    """完整流程：JSON -> Config -> Validate -> Verilog"""

    def test_sample_config_to_verilog(self):
        path = os.path.join(OUTPUT_DIR, "sample_config.json")
        if not os.path.exists(path):
            pytest.skip("sample_config.json not found")
        with open(path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        ok, errs = validate(cfg)
        assert ok, errs
        out = generate_verilog(cfg, output_filename="sample.v")
        assert "`timescale" in out
        assert "module sample" in out
        assert "`ifndef SAMPLE_V" in out
        assert "endmodule" in out

    def test_debug_config_to_verilog(self):
        path = os.path.join(OUTPUT_DIR, "debug.json")
        if not os.path.exists(path):
            pytest.skip("debug.json not found")
        with open(path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        ok, errs = validate(cfg)
        assert ok, errs
        out = generate_verilog(cfg, output_filename="my_pwrseq.v")
        assert "module my_pwrseq" in out
        assert "PSEQCELL" in out
        assert "DEB" in out
        # 應有 SIG_2, SIG_3 的 output
        assert "oSIG_2" in out
        assert "oSIG_3" in out

    def test_debug_config_to_drawio_matches_golden_structure(self):
        """用 debug.json 產生 Draw.io，與 debug_golden.xml 比對：有 waypoints 的邊 (source,target) 一致"""
        json_path = os.path.join(OUTPUT_DIR, "debug.json")
        golden_path = os.path.join(OUTPUT_DIR, "debug_golden.xml")
        if not os.path.exists(json_path) or not os.path.exists(golden_path):
            pytest.skip("debug.json or debug_golden.xml not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        xml_out = generate_drawio(cfg)
        root = ET.fromstring(xml_out)

        def edges_with_waypoints(xml_root):
            out = set()
            for cell in xml_root.findall(".//mxCell[@edge='1']"):
                src, tgt = cell.get("source"), cell.get("target")
                if src is None or tgt is None:
                    continue
                # 反向標示邊（cell→input label，startArrow）已廢除：input→Cell 改走正向邊。
                if "startArrow" in (cell.get("style") or ""):
                    continue
                geo = cell.find("mxGeometry")
                if geo is not None and geo.find("Array") is not None:
                    out.add((src, tgt))
            return out

        golden_root = ET.parse(golden_path).getroot()
        got = edges_with_waypoints(root)
        want = edges_with_waypoints(golden_root)
        input_auto = {
            (cell.get("source"), cell.get("target"))
            for cell in root.findall(".//mxCell[@edge='1']")
            if "orthogonalEdgeStyle" in (cell.get("style") or "")
        }
        # input label 出發的邊不再寫 waypoints；golden 若仍有則不強制比對
        assert (want - input_auto) <= got, f"missing waypoint edges: {(want - input_auto) - got}"

    def test_drawio_export_freezes_edge_routing(self):
        """非 input 邊 freeze 為 none；input label 出發保留 orthogonal 且無 waypoints。"""
        json_path = os.path.join(OUTPUT_DIR, "debug.json")
        if not os.path.exists(json_path):
            pytest.skip("debug.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        ortho = 0
        none_style = 0
        for cell in root.findall(".//mxCell[@edge='1']"):
            sty = cell.get("style") or ""
            geo = cell.find("mxGeometry")
            has_pts = geo is not None and geo.find("Array") is not None
            if "orthogonalEdgeStyle" in sty or "elbowEdgeStyle" in sty:
                ortho += 1
                assert not has_pts, f"orthogonal edge {cell.get('id')} must have no waypoints"
            if "edgeStyle=none" in sty:
                none_style += 1
        assert ortho > 0
        assert none_style > 0

    def test_drawio_export_edges_are_axis_aligned(self):
        """edgeStyle=none 時每段必須水平或垂直，不可有斜線。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        def parse_style(s):
            out = {}
            for part in (s or "").split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k] = v
            return out

        def anchor(bb, ax, ay):
            x, y, w, h = bb
            return x + w * float(ax), y + h * float(ay)

        def bbox(cell):
            g = cell.find("mxGeometry")
            if g is None:
                return None
            return (
                float(g.get("x", 0)),
                float(g.get("y", 0)),
                float(g.get("width", 0)),
                float(g.get("height", 0)),
            )

        boxes = {}
        for c in root.iter("mxCell"):
            if c.get("vertex") == "1":
                b = bbox(c)
                if b and c.get("id"):
                    boxes[c.get("id")] = b

        diagonals = []
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            sty = c.get("style") or ""
            if "edgeStyle=none" not in sty:
                continue
            sid, tid = c.get("source"), c.get("target")
            if sid not in boxes or tid not in boxes:
                continue
            st = parse_style(c.get("style"))
            ex, ey = anchor(boxes[sid], st.get("exitX", 1), st.get("exitY", 0.5))
            tx, ty = anchor(boxes[tid], st.get("entryX", 0), st.get("entryY", 0.5))
            pts = [(ex, ey)]
            geo = c.find("mxGeometry")
            arr = geo.find("Array") if geo is not None else None
            if arr is not None:
                for p in arr.findall("mxPoint"):
                    pts.append((float(p.get("x")), float(p.get("y"))))
            pts.append((tx, ty))
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                if abs(ax - bx) > 0.5 and abs(ay - by) > 0.5:
                    diagonals.append((c.get("id"), sid, tid, i))
        assert diagonals == [], f"diagonal segments: {diagonals[:10]}"

    def test_non_feedback_lo_deb_keeps_emit_waypoints(self):
        """非佈局回授 Lo→Deb 保留 Rule 2 emit waypoints，不被 FB 五段覆寫。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        rule2_lo = 0
        for cell in root.findall(".//mxCell[@edge='1']"):
            sty = cell.get("style") or ""
            if "blockThin" not in sty or "#dc2626" not in sty:
                continue
            if STROKE_FEEDBACK in sty:
                continue
            geo = cell.find("mxGeometry")
            if geo is None or geo.find("Array") is None:
                continue
            rule2_lo += 1
        assert rule2_lo > 0, "expected non-feedback Lo→Deb edges with frozen waypoints"

    def test_pch_p1v25a_lo_and_from_rsmrst_nq_not_q(self):
        """PCH_P1V25A Lo = inv(RSMRST) & inv(PG)；第一腳從 RSMRST ~Q 輸出腳扇出，非 Q。"""
        golden = os.path.join(PROJECT_ROOT, "src", "reference", "golden.json")
        if not os.path.exists(golden):
            pytest.skip("golden.json not found")
        with open(golden, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        def _geom(cid: str) -> tuple[float, float] | None:
            for cell in root.iter("mxCell"):
                if cell.get("id") != cid:
                    continue
                g = cell.find("mxGeometry")
                if g is None:
                    return None
                return float(g.get("x", 0)), float(g.get("y", 0))
            return None

        def _rail_y(name: str) -> float:
            for cell in root.iter("mxCell"):
                if (cell.get("value") or "").strip() != name:
                    continue
                xy = _geom(cell.get("id") or "")
                if xy is not None:
                    return xy[1]
            raise AssertionError(f"{name} not found")

        pch1_y = _rail_y("PCH_P1V25A_EN")
        rsmrst_y = _rail_y("RSMRST_N")

        nq_on_rsmrst: str | None = None
        q_on_rsmrst: str | None = None
        for cell in root.iter("mxCell"):
            if cell.get("vertex") != "1":
                continue
            val = (cell.get("value") or "").strip()
            if val not in ("Q", "~Q"):
                continue
            xy = _geom(cell.get("id") or "")
            if xy is None or abs(xy[1] - rsmrst_y) > 50:
                continue
            if val == "~Q":
                nq_on_rsmrst = cell.get("id")
            else:
                q_on_rsmrst = cell.get("id")
        assert nq_on_rsmrst is not None

        lo_and_id: str | None = None
        lo_and_y = -1.0
        for cell in root.iter("mxCell"):
            sty = cell.get("style") or ""
            if cell.get("vertex") != "1" or "operation=and" not in sty:
                continue
            xy = _geom(cell.get("id") or "")
            if xy is None or abs(xy[1] - pch1_y) >= 120:
                continue
            if xy[1] > pch1_y and xy[1] > lo_and_y:
                lo_and_y = xy[1]
                lo_and_id = cell.get("id")
        assert lo_and_id is not None

        srcs = [
            c.get("source")
            for c in root.iter("mxCell")
            if c.get("edge") == "1" and c.get("target") == lo_and_id
        ]
        assert nq_on_rsmrst in srcs, f"Lo AND inputs {srcs} should include RSMRST ~Q output"
        if q_on_rsmrst is not None:
            assert q_on_rsmrst not in srcs, "Lo AND must not wire RSMRST Q (missing inv)"

        fb_edge_ids: list[str] = []
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1":
                continue
            if STROKE_FEEDBACK not in (cell.get("style") or ""):
                continue
            if cell.get("target") == lo_and_id:
                fb_edge_ids.append(cell.get("id") or "")
        assert nq_on_rsmrst in [
            c.get("source")
            for c in root.iter("mxCell")
            if c.get("id") in fb_edge_ids
        ], f"RSMRST ~Q → Lo AND should be FB (blue); fb edges {fb_edge_ids}"

    def test_rsmrst_q_to_downstream_and_is_q_fb_blue(self):
        """RSMRST Q use=self → 下游 hi AND 應為藍色 Q FB（先上 60pt，目標在下方亦然）。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        rsmrst_q_id = next(
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and (c.get("value") or "").strip() == "Q"
            and abs(
                float(c.find("mxGeometry").get("y", 0))
                - float(
                    next(
                        c2.find("mxGeometry").get("y", 0)
                        for c2 in root.iter("mxCell")
                        if (c2.get("value") or "").strip() == "RSMRST_N"
                    )
                )
            )
            < 80
        )
        psu_and_id = next(
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1"
            and "operation=and" in (c.get("style") or "")
            and abs(
                float(c.find("mxGeometry").get("y", 0))
                - float(
                    next(
                        c2.find("mxGeometry").get("y", 0)
                        for c2 in root.iter("mxCell")
                        if (c2.get("value") or "").strip() == "PSU_EN"
                    )
                )
            )
            < 120
        )
        q_to_psu = [
            c
            for c in root.iter("mxCell")
            if c.get("edge") == "1"
            and c.get("source") == rsmrst_q_id
            and c.get("target") == psu_and_id
        ]
        assert len(q_to_psu) == 1, "expected RSMRST Q → PSU hi AND"
        edge = q_to_psu[0]
        assert STROKE_FEEDBACK in (edge.get("style") or ""), "RSMRST Q→下游 AND 應為藍色 FB"
        pts = edge.find("mxGeometry").find("Array").findall("mxPoint")
        assert len(pts) >= 5, "Q FB 應有五段 waypoints"
        p1y = float(pts[0].get("y"))
        p2y = float(pts[1].get("y"))
        assert p2y < p1y and abs(p1y - p2y - 60.0) < 0.5

    def test_cell_q_feedback_second_segment_always_up(self):
        """Cell Q 回授：先右 40pt，第二段一律向上 40+20pt（目標在下方亦然）。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        q_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and (c.get("value") or "").strip() == "Q"
        }
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1" or cell.get("source") not in q_ids:
                continue
            if STROKE_FEEDBACK not in (cell.get("style") or ""):
                continue
            geo = cell.find("mxGeometry")
            arr = geo.find("Array") if geo is not None else None
            if arr is None:
                continue
            pts = arr.findall("mxPoint")
            if len(pts) < 2:
                continue
            p1y = float(pts[0].get("y"))
            p2y = float(pts[1].get("y"))
            assert p2y < p1y, f"edge {cell.get('id')}: Q FB 第二段應向上，得 p1y={p1y} p2y={p2y}"
            assert abs((p1y - p2y) - 60.0) < 0.5, (
                f"edge {cell.get('id')}: Q FB 向上應為 60pt，得 {p1y - p2y}"
            )

    def test_hi_use_upstream_and_exits_from_gate_right(self):
        """use=hi 且上游 logic_out 已存在時，→H_Deb 應從 AND 右側（exitX=1）出發。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        h_deb_by_rail: dict[str, str] = {}
        for cell in root.iter("mxCell"):
            if (cell.get("value") or "").strip() != "H_Deb":
                continue
            g = cell.find("mxGeometry")
            if g is None:
                continue
            y = float(g.get("y", 0))
            for c2 in root.iter("mxCell"):
                name = (c2.get("value") or "").strip()
                if not name or name in ("H_Deb", "L_Deb", "Q", "~Q"):
                    continue
                g2 = c2.find("mxGeometry")
                if g2 is None or float(g2.get("x", 0)) < 2000:
                    continue
                if abs(float(g2.get("y", 0)) - y) < 30:
                    h_deb_by_rail[name] = cell.get("id") or ""
                    break

        for rail in ("PVNNAON_EN", "PVCCIO_EN", "PVCC1V8_EN"):
            hid = h_deb_by_rail.get(rail)
            assert hid is not None, f"{rail} H_Deb not found"
            hi_edges = [
                c
                for c in root.iter("mxCell")
                if c.get("edge") == "1"
                and c.get("target") == hid
                and "#059669" in (c.get("style") or "")
            ]
            assert len(hi_edges) == 1, f"{rail} expected 1 hi→H_Deb edge, got {len(hi_edges)}"
            sty = hi_edges[0].get("style") or ""
            assert "exitX=1" in sty, f"{rail} hi→H_Deb must exit from AND right: {sty}"
            assert "exitX=0" not in sty.split("entryX")[0], (
                f"{rail} hi→H_Deb must not use left exit from logic gate"
            )

    def test_same_source_fb_shares_one_channel_x_per_layer(self):
        """同一 source 在每個 FB 目標層（and／cell）只佔 1 條 X 通道（同層水平共用）。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        deb_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and (c.get("value") or "").strip() in ("H_Deb", "L_Deb")
        }
        fb_src_ids: set[str] = set()
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1":
                continue
            geo = cell.find("mxGeometry")
            if geo is None or geo.find("Array") is None:
                continue
            sid = cell.get("source")
            if sid is not None:
                fb_src_ids.add(sid)

        for src_id in fb_src_ids:
            by_layer: dict[str, set[float]] = {"and": set(), "cell": set()}
            for cell in root.iter("mxCell"):
                if cell.get("edge") != "1" or cell.get("source") != src_id:
                    continue
                tid = cell.get("target")
                layer = "cell" if tid in deb_ids else "and"
                geo = cell.find("mxGeometry")
                arr = geo.find("Array") if geo is not None else None
                if arr is None or len(arr.findall("mxPoint")) < 3:
                    continue
                p3x = float(arr.findall("mxPoint")[2].get("x"))
                by_layer[layer].add(p3x)
            for layer, xs in by_layer.items():
                if not xs:
                    continue
                assert len(xs) == 1, (
                    f"source {src_id} layer {layer}: expected 1 FB channel X, got {xs}"
                )

    def test_cell_nq_feedback_second_segment_up_140pt(self):
        """Cell ~Q 回授：第二段向上 3×40+20 = 140pt（高於 Q 的 60pt，避免重疊）。"""
        json_path = os.path.join(OUTPUT_DIR, "power.json")
        if not os.path.exists(json_path):
            pytest.skip("power.json not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))

        nq_ids = {
            c.get("id")
            for c in root.iter("mxCell")
            if c.get("vertex") == "1" and (c.get("value") or "").strip() == "~Q"
        }
        checked = 0
        for cell in root.iter("mxCell"):
            if cell.get("edge") != "1" or cell.get("source") not in nq_ids:
                continue
            geo = cell.find("mxGeometry")
            arr = geo.find("Array") if geo is not None else None
            if arr is None:
                continue
            pts = arr.findall("mxPoint")
            if len(pts) < 2:
                continue
            p1y = float(pts[0].get("y"))
            p2y = float(pts[1].get("y"))
            assert p2y < p1y, f"edge {cell.get('id')}: ~Q FB 第二段應向上"
            assert abs((p1y - p2y) - 140.0) < 0.5, (
                f"edge {cell.get('id')}: ~Q FB 向上應為 140pt，得 {p1y - p2y}"
            )
            checked += 1
        assert checked > 0, "expected ~Q feedback edges with frozen waypoints"
