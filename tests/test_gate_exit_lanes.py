"""_GateExitLanes stub 深度：全圖 catalog 序 n → (1+n)×40pt。"""
import xml.etree.ElementTree as ET
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from drawio_export import _GateExitLanes, GRID


def test_catalog_stub_x_uses_one_plus_n_times_grid():
        lanes = _GateExitLanes()
        lanes.set_catalog_n(100, 1)
        lanes.set_catalog_n(200, 3)
        right = 480
        assert lanes.stub_x(100, right) == right + (1 + 1) * GRID
        assert lanes.stub_x(200, right) == right + (1 + 3) * GRID
        assert lanes.stub_x(100, right) == lanes.stub_x(100, right)


def test_wire_vertical_skips_same_y():
    lanes = _GateExitLanes()
    lanes.set_catalog_n(1, 1)
    geo = ET.Element("mxGeometry", {"relative": "1", "as": "geometry"})
    lanes.wire_vertical(geo, 1, 500, 100, 100)
    assert geo.find("Array") is None


def test_wire_vertical_adds_stub_then_vertical():
    lanes = _GateExitLanes()
    lanes.set_catalog_n(1, 2)
    geo = ET.Element("mxGeometry", {"relative": "1", "as": "geometry"})
    right = 480  # 40pt 對齊
    lanes.wire_vertical(geo, 1, right, 100, 200)
    pts = geo.find("Array").findall("mxPoint")
    assert len(pts) == 2
    assert int(pts[0].get("x")) == right + (1 + 2) * GRID
    assert int(pts[0].get("y")) == 100
    assert int(pts[1].get("y")) == 200


def test_wire_via_channel_uses_stub_lane_only():
    lanes = _GateExitLanes()
    lanes.set_catalog_n(1, 2)
    geo = ET.Element("mxGeometry", {"relative": "1", "as": "geometry"})
    right = 480
    entry_x, entry_y = 1200, 300
    lanes.wire_via_channel(geo, 1, right, 100, entry_x, entry_y)
    pts = geo.find("Array").findall("mxPoint")
    lx = right + (1 + 2) * GRID
    assert len(pts) == 3
    assert int(pts[0].get("x")) == lx
    assert int(pts[1].get("x")) == lx
    assert int(pts[1].get("y")) == entry_y
    assert int(pts[2].get("x")) == entry_x
    assert int(pts[2].get("y")) == entry_y
