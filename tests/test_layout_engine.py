"""Layout engine 單元測試：對齊格點、waypoints、輸出為合法 XML"""
import xml.etree.ElementTree as ET

import pytest

from layout_engine import layout_drawio, align_vertices_to_grid, align_edge_waypoints_to_grid, minimize_crossings


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
