"""drawio_edge_freeze 單元測試：走線鎖定與 input 自動正交還原。"""
import xml.etree.ElementTree as ET

import pytest

from drawio_edge_freeze import (
    MIN_HORIZ_STUB,
    _orthogonalize_polyline,
    freeze_edge_routing,
    restore_orthogonal_auto_routing,
)


class TestOverlapRules:
    """相同 source：水平可重疊、垂直不可重疊（預設選項）。"""

    pytestmark = pytest.mark.skip(reason="_ChannelAllocator removed with layered layout")

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

    def test_orthogonalize_polyline_inserts_corners(self):
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

    def test_freeze_uses_min_horiz_stub(self):
        assert MIN_HORIZ_STUB == 40
