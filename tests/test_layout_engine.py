"""Layout engine 單元測試：對齊格點、waypoints、輸出為合法 XML"""
import xml.etree.ElementTree as ET

import pytest

from layout_engine import (
    layout_drawio,
    align_vertices_to_grid,
    align_edge_waypoints_to_grid,
    minimize_crossings,
    ensure_edge_horiz_stubs,
    freeze_edge_routing,
    restore_orthogonal_auto_routing,
    route_orthogonal,
    clear_orthogonal_edge_waypoints,
    _anchor_point,
    _bbox,
    _astar_orthogonal_with_fallback,
    MIN_HORIZ_STUB,
    ROUTE_GRID_PRIMARY,
    ROUTE_GRID_FALLBACK,
)


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" version="29.6.1">
  <diagram name="Test" id="test">
    <mxGraphModel dx="120" dy="40" grid="1" gridSize="10">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="2" parent="1" value="A" vertex="1">
          <mxGeometry x="163" y="92" width="80" height="20" as="geometry" />
        </mxCell>
        <mxCell id="3" parent="1" value="B" vertex="1">
          <mxGeometry x="400" y="240" width="80" height="40" as="geometry" />
        </mxCell>
        <mxCell id="4" parent="1" edge="1" source="2" target="3">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="420" y="102" />
              <mxPoint x="401" y="241" />
            </Array>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


class TestLayoutDrawio:
    """layout_drawio() 回傳值與副作用"""

    def test_returns_valid_xml(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=40, align_waypoints=True)
        root = ET.fromstring(out)
        assert root.tag == "mxfile"
        assert "encoding" in out or "version" in out

    def test_align_vertices_to_40(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=40, align_waypoints=True)
        root = ET.fromstring(out)
        geos = list(root.iter("mxGeometry"))
        vertex_geos = [g for g in geos if g.get("x") is not None and g.get("y") is not None]
        for g in vertex_geos:
            x, y = g.get("x"), g.get("y")
            if x and y:
                assert int(x) % 40 == 0, f"x={x} not aligned to 40"
                assert int(y) % 40 == 0, f"y={y} not aligned to 40"

    def test_align_waypoints_to_40(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=40, align_waypoints=True)
        root = ET.fromstring(out)
        for arr in root.iter("Array"):
            if arr.get("as") != "points":
                continue
            for pt in arr.findall("mxPoint"):
                x, y = pt.get("x"), pt.get("y")
                if x is not None:
                    assert int(x) % 40 == 0
                if y is not None:
                    assert int(y) % 40 == 0

    def test_align_to_grid_zero_skips_alignment(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=0)
        root = ET.fromstring(out)
        cell2 = root.find(".//mxCell[@id='2']")
        assert cell2 is not None
        geo = cell2.find("mxGeometry")
        assert geo is not None and geo.get("x") == "163"

    def test_nudge_overlap_optional(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=40, nudge_overlap=False)
        root = ET.fromstring(out)
        assert root.tag == "mxfile"

    def test_reduce_crossings_returns_valid_xml(self):
        out = layout_drawio(SAMPLE_XML, align_to_grid=40, reduce_crossings=True)
        root = ET.fromstring(out)
        assert root.tag == "mxfile"


CROSSING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" version="29.6.1">
  <diagram name="Test" id="test">
    <mxGraphModel dx="120" dy="40" grid="1" gridSize="10">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="10" parent="1" edge="1" source="2" target="3">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="300" y="40" />
              <mxPoint x="300" y="200" />
            </Array>
          </mxGeometry>
        </mxCell>
        <mxCell id="11" parent="1" edge="1" source="4" target="5">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="340" y="100" />
              <mxPoint x="340" y="160" />
            </Array>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


class TestMinimizeCrossings:
    """minimize_crossings 單元測試"""

    def test_no_crash_on_empty(self):
        root = ET.fromstring(SAMPLE_XML)
        result = minimize_crossings(root, grid=40)
        assert result >= 0

    def test_no_crash_on_crossing_xml(self):
        root = ET.fromstring(CROSSING_XML)
        result = minimize_crossings(root, grid=40)
        assert result >= 0

    def test_returns_valid_xml_after_minimize(self):
        root = ET.fromstring(CROSSING_XML)
        minimize_crossings(root, grid=40)
        out = ET.tostring(root, encoding="unicode")
        reparsed = ET.fromstring(out)
        assert reparsed.tag == "mxfile"


class TestModuleFunctions:
    """align_vertices_to_grid / align_edge_waypoints_to_grid 直接呼叫"""

    def test_align_vertices_inplace(self):
        root = ET.fromstring(SAMPLE_XML)
        align_vertices_to_grid(root, grid=40)
        cell2 = root.find(".//mxCell[@id='2']")
        geo = cell2.find("mxGeometry")
        assert int(geo.get("x")) % 40 == 0 and int(geo.get("y")) % 40 == 0

    def test_align_edge_waypoints_inplace(self):
        root = ET.fromstring(SAMPLE_XML)
        align_edge_waypoints_to_grid(root, grid=40)
        arr = root.find(".//Array[@as='points']")
        pts = arr.findall("mxPoint")
        assert len(pts) >= 1
        assert int(pts[0].get("x")) % 40 == 0


HORIZ_STUB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" version="29.6.1">
  <diagram name="Test" id="test">
    <mxGraphModel dx="120" dy="40" grid="1" gridSize="10">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="2" parent="1" value="A" vertex="1">
          <mxGeometry x="80" y="80" width="80" height="40" as="geometry" />
        </mxCell>
        <mxCell id="3" parent="1" value="B" vertex="1">
          <mxGeometry x="400" y="200" width="80" height="40" as="geometry" />
        </mxCell>
        <mxCell id="4" parent="1" edge="1" source="2" target="3"
          style="exitX=1;exitY=0.5;entryX=0;entryY=0.5;">
          <mxGeometry relative="1" as="geometry">
            <Array as="points">
              <mxPoint x="160" y="100" />
              <mxPoint x="160" y="220" />
            </Array>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
"""


class TestHorizStubs:
    """source/destination 水平連接（至少 40pt）"""

    def test_ensure_inserts_exit_stub_when_first_segment_vertical(self):
        root = ET.fromstring(HORIZ_STUB_XML)
        n = ensure_edge_horiz_stubs(root, min_stub=MIN_HORIZ_STUB)
        assert n == 1
        pts = root.find(".//Array[@as='points']").findall("mxPoint")
        assert len(pts) >= 2
        s_box = _bbox(root.find(".//mxCell[@id='2']"))
        ex, ey = _anchor_point(s_box, 1.0, 0.5)
        x0, y0 = float(pts[0].get("x")), float(pts[0].get("y"))
        assert abs(y0 - ey) < 0.5
        assert x0 - ex >= MIN_HORIZ_STUB - 0.5

    def test_route_orthogonal_includes_horiz_stubs(self):
        root = ET.fromstring(HORIZ_STUB_XML)
        route_orthogonal(root, grid=40)
        edge = root.find(".//mxCell[@id='4']")
        pts = edge.find(".//Array[@as='points']").findall("mxPoint")
        assert pts
        s_box = _bbox(root.find(".//mxCell[@id='2']"))
        t_box = _bbox(root.find(".//mxCell[@id='3']"))
        ex, ey = _anchor_point(s_box, 1.0, 0.5)
        tx, ty = _anchor_point(t_box, 0.0, 0.5)
        x0, y0 = float(pts[0].get("x")), float(pts[0].get("y"))
        xn, yn = float(pts[-1].get("x")), float(pts[-1].get("y"))
        assert abs(y0 - ey) < 0.5 and x0 - ex >= MIN_HORIZ_STUB - 0.5
        assert abs(yn - ty) < 0.5 and tx - xn >= MIN_HORIZ_STUB - 0.5


class TestOverlapRules:
    """相同 source：水平可重疊、垂直不可重疊（預設選項）"""

    def test_channel_same_source_overlapping_y_gets_different_x(self):
        from drawio_export import _ChannelAllocator

        ch = _ChannelAllocator(100, step=40)
        x1 = ch.allocate(100, 200, source_key="PG_A", dest_key="OUT1")
        x2 = ch.allocate(150, 250, source_key="PG_A", dest_key="OUT2")
        assert x1 != x2

    def test_channel_same_source_non_overlapping_y_shares_x(self):
        from drawio_export import _ChannelAllocator

        ch = _ChannelAllocator(100, step=40)
        x1 = ch.allocate(100, 200, source_key="PG_A", dest_key="OUT1")
        x2 = ch.allocate(200, 300, source_key="PG_A", dest_key="OUT2")
        assert x1 == x2

    def test_channel_same_source_vert_option_allows_overlap(self):
        from drawio_export import _ChannelAllocator
        from drawio_export_options import DrawioExportOptions

        opts = DrawioExportOptions(same_source_vert=True)
        ch = _ChannelAllocator(100, step=40, options=opts)
        x1 = ch.allocate(100, 200, source_key="PG_A", dest_key="OUT1")
        x2 = ch.allocate(150, 250, source_key="PG_A", dest_key="OUT2")
        assert x1 == x2


class TestRouteGridFallback:
    """A* 先 40pt 格距，失敗再 20pt。"""

    def test_open_path_succeeds_on_primary_grid(self):
        path = _astar_orthogonal_with_fallback(
            (0.0, 0.0), (200.0, 0.0), [], [], [],
            route_grid=ROUTE_GRID_PRIMARY, fallback_grid=ROUTE_GRID_FALLBACK,
        )
        assert path is not None

    def test_retries_with_fallback_when_primary_fails(self, monkeypatch):
        calls: list[int] = []

        def fake_astar(start, goal, obstacles, grid, rv, rh, **kwargs):
            calls.append(grid)
            return None if grid == ROUTE_GRID_PRIMARY else [(start[0], start[1]), (goal[0], goal[1])]

        monkeypatch.setattr("layout_engine._astar_orthogonal", fake_astar)
        path = _astar_orthogonal_with_fallback(
            (0.0, 0.0), (200.0, 0.0), [], [], [],
            route_grid=ROUTE_GRID_PRIMARY, fallback_grid=ROUTE_GRID_FALLBACK,
        )
        assert path is not None
        assert calls == [ROUTE_GRID_PRIMARY, ROUTE_GRID_FALLBACK]


class TestClearOrthogonalWaypoints:
    def test_clears_points_on_orthogonal_style_only(self):
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        ortho = ET.SubElement(root, "mxCell", {
            "id": "10", "parent": "1", "edge": "1", "source": "2", "target": "3",
            "style": "edgeStyle=orthogonalEdgeStyle;exitX=1;entryX=0;",
        })
        geo_o = ET.SubElement(ortho, "mxGeometry", {"relative": "1", "as": "geometry"})
        arr = ET.SubElement(geo_o, "Array", {"as": "points"})
        ET.SubElement(arr, "mxPoint", {"x": "100", "y": "200"})
        none_edge = ET.SubElement(root, "mxCell", {
            "id": "11", "parent": "1", "edge": "1", "source": "2", "target": "3",
            "style": "edgeStyle=none;exitX=1;entryX=0;",
        })
        geo_n = ET.SubElement(none_edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        arr2 = ET.SubElement(geo_n, "Array", {"as": "points"})
        ET.SubElement(arr2, "mxPoint", {"x": "300", "y": "400"})
        n = clear_orthogonal_edge_waypoints(root, parent_id="1")
        assert n == 1
        assert ortho.find(".//Array[@as='points']") is None
        assert none_edge.find(".//Array[@as='points']") is not None


class TestFreezeEdgeRouting:
    def test_freezes_orthogonal_to_none_with_waypoints(self):
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        ET.SubElement(root, "mxCell", {
            "id": "2", "parent": "1", "vertex": "1",
            "style": "rounded=0;whiteSpace=wrap;html=1;",
        }).append(ET.Element("mxGeometry", {
            "x": "0", "y": "0", "width": "40", "height": "40", "as": "geometry",
        }))
        ET.SubElement(root, "mxCell", {
            "id": "3", "parent": "1", "vertex": "1",
            "style": "rounded=0;whiteSpace=wrap;html=1;",
        }).append(ET.Element("mxGeometry", {
            "x": "200", "y": "0", "width": "40", "height": "40", "as": "geometry",
        }))
        edge = ET.SubElement(root, "mxCell", {
            "id": "10", "parent": "1", "edge": "1", "source": "2", "target": "3",
            "style": "edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
        })
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        n = freeze_edge_routing(root, parent_id="1")
        assert n == 1
        assert "edgeStyle=none" in (edge.get("style") or "")
        assert "orthogonalEdgeStyle" not in (edge.get("style") or "")
        # 同列純水平時 waypoints 可為空（exit→entry 已是水平段）

    def test_orthogonalize_polyline_inserts_corners(self):
        from layout_engine import _orthogonalize_polyline

        path = _orthogonalize_polyline([(0.0, 0.0), (100.0, 50.0)])
        assert path == [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)]

    def test_skip_source_ids_on_freeze(self):
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        for vid, x in (("2", "0"), ("3", "200")):
            ET.SubElement(root, "mxCell", {
                "id": vid, "parent": "1", "vertex": "1",
                "style": "rounded=0;whiteSpace=wrap;html=1;",
            }).append(ET.Element("mxGeometry", {
                "x": x, "y": "0", "width": "40", "height": "40", "as": "geometry",
            }))
        edge = ET.SubElement(root, "mxCell", {
            "id": "10", "parent": "1", "edge": "1", "source": "2", "target": "3",
            "style": "edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
        })
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        assert freeze_edge_routing(root, parent_id="1", skip_source_ids={"2"}) == 0
        assert "orthogonalEdgeStyle" in (edge.get("style") or "")

    def test_restore_orthogonal_auto_routing(self):
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        edge = ET.SubElement(root, "mxCell", {
            "id": "10", "parent": "1", "edge": "1", "source": "2", "target": "3",
            "style": "edgeStyle=none;exitX=1;entryX=0;",
        })
        geo = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        arr = ET.SubElement(geo, "Array", {"as": "points"})
        ET.SubElement(arr, "mxPoint", {"x": "50", "y": "50"})
        n = restore_orthogonal_auto_routing(root, {"2"}, parent_id="1")
        assert n == 1
        assert "orthogonalEdgeStyle" in (edge.get("style") or "")
        assert edge.find(".//Array[@as='points']") is None

    def test_restore_orthogonal_auto_routing_by_edge_id(self):
        root = ET.Element("root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        edge = ET.SubElement(root, "mxCell", {
            "id": "10", "parent": "1", "edge": "1", "source": "5", "target": "3",
            "style": "edgeStyle=none;exitX=1;entryX=0;",
        })
        geo = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
        arr = ET.SubElement(geo, "Array", {"as": "points"})
        ET.SubElement(arr, "mxPoint", {"x": "50", "y": "50"})
        n = restore_orthogonal_auto_routing(root, set(), edge_ids={"10"}, parent_id="1")
        assert n == 1
        assert "orthogonalEdgeStyle" in (edge.get("style") or "")
        assert edge.find(".//Array[@as='points']") is None
