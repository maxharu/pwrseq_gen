"""
Layout engine for Draw.io XML.

對 Draw.io XML 做自動版面調整，例如：
- 座標對齊格點（align to grid）
- 邊的 waypoints 對齊格點
- 可擴充：偵測並排除頂點重疊、走線與元件重疊等（依 DRAWIO_RULES.md）

注意：本模組「未」在匯出時自動套用。generate_drawio() 已依規則算好座標與 waypoints，
若再強制對齊格點可能使走線錯位、看起來更亂；建議僅對手動編輯過或外部匯入的 XML 使用。
"""
import xml.etree.ElementTree as ET
from xml.dom import minidom


def _align_value(v: str | None, grid: int) -> int | None:
    """將字串數字對齊到 grid 的倍數；None 或空則回傳 None。"""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        x = float(v)
        return round(x / grid) * grid
    except (ValueError, TypeError):
        return None


def _get_geom_attrs(geo: ET.Element | None) -> dict[str, str]:
    """取得 mxGeometry 的屬性 dict（x, y, width, height 等）。"""
    if geo is None:
        return {}
    return geo.attrib


def _set_geom_attr(geo: ET.Element, key: str, value: int | str) -> None:
    """設定 mxGeometry 的屬性。"""
    geo.set(key, str(value))


def _collect_vertices(root: ET.Element, parent_id: str = "1") -> list[ET.Element]:
    """收集 parent 為 parent_id 且為 vertex 的 mxCell。"""
    out: list[ET.Element] = []
    for cell in root.iter("mxCell"):
        if cell.get("parent") == parent_id and cell.get("vertex") == "1":
            out.append(cell)
    return out


def _collect_edges(root: ET.Element, parent_id: str = "1") -> list[ET.Element]:
    """收集 parent 為 parent_id 且為 edge 的 mxCell。"""
    out: list[ET.Element] = []
    for cell in root.iter("mxCell"):
        if cell.get("parent") == parent_id and cell.get("edge") == "1":
            out.append(cell)
    return out


def align_vertices_to_grid(root: ET.Element, grid: int = 40) -> None:
    """將所有頂點（vertex）的 mxGeometry x, y 對齊到 grid 的倍數。"""
    for cell in root.iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        attrs = _get_geom_attrs(geo)
        x = _align_value(attrs.get("x"), grid)
        y = _align_value(attrs.get("y"), grid)
        if x is not None:
            _set_geom_attr(geo, "x", x)
        if y is not None:
            _set_geom_attr(geo, "y", y)


def align_edge_waypoints_to_grid(root: ET.Element, grid: int = 40) -> None:
    """將所有邊（edge）的 waypoints（Array/mxPoint）對齊到 grid。"""
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        arr = geo.find("Array")
        if arr is None or arr.get("as") != "points":
            continue
        for pt in arr.findall("mxPoint"):
            ax = pt.get("x")
            ay = pt.get("y")
            x = _align_value(ax, grid)
            y = _align_value(ay, grid)
            if x is not None:
                pt.set("x", str(x))
            if y is not None:
                pt.set("y", str(y))


def _bbox(cell: ET.Element) -> tuple[float, float, float, float] | None:
    """取得 vertex 的 (x, y, x2, y2)；無 geometry 或無 x,y 則回傳 None。"""
    geo = cell.find("mxGeometry")
    if geo is None:
        return None
    attrs = _get_geom_attrs(geo)
    x = _align_value(attrs.get("x"), 1)
    y = _align_value(attrs.get("y"), 1)
    w = _align_value(attrs.get("width"), 1)
    h = _align_value(attrs.get("height"), 1)
    if x is None or y is None:
        return None
    w = w if w is not None else 0
    h = h if h is not None else 0
    return (float(x), float(y), float(x + w), float(y + h))


def nudge_overlapping_vertices(root: ET.Element, parent_id: str = "1", grid: int = 40, gap: int = 80) -> int:
    """
    偵測同 parent 下頂點重疊，將後者往右或往下 nudge（grid 的倍數）。
    回傳被移動的頂點數量。
    """
    vertices = _collect_vertices(root, parent_id)
    nudge_count = 0
    for i, a in enumerate(vertices):
        box_a = _bbox(a)
        if box_a is None:
            continue
        for b in vertices[i + 1 :]:
            box_b = _bbox(b)
            if box_b is None:
                continue
            # 重疊：兩矩形相交
            if not (box_a[2] <= box_b[0] or box_b[2] <= box_a[0] or box_a[3] <= box_b[1] or box_b[3] <= box_a[1]):
                geo_b = b.find("mxGeometry")
                if geo_b is None:
                    continue
                x = _align_value(geo_b.get("x"), 1)
                y = _align_value(geo_b.get("y"), 1)
                if x is None and y is None:
                    continue
                # 往右或往下移 gap，並對齊 grid
                if x is not None:
                    new_x = _align_value(x + gap, grid)
                    if new_x is not None:
                        _set_geom_attr(geo_b, "x", new_x)
                        nudge_count += 1
                if y is not None:
                    new_y = _align_value(y + gap, grid)
                    if new_y is not None:
                        _set_geom_attr(geo_b, "y", new_y)
                        nudge_count += 1
                break  # 只 nudge 一次 per pair
    return nudge_count


def layout_drawio(
    xml: str,
    *,
    align_to_grid: int = 40,
    align_waypoints: bool = True,
    nudge_overlap: bool = False,
    overlap_gap: int = 80,
) -> str:
    """
    對 Draw.io XML 做版面調整。

    - align_to_grid: 頂點 x,y 與（若 align_waypoints）waypoints 對齊的格距，0 表示不對齊。
    - align_waypoints: 是否將邊的 waypoints 對齊格點。
    - nudge_overlap: 是否嘗試將重疊的頂點錯開（僅對 parent="1" 的頂點）。
    - overlap_gap: nudge 時位移量（pt）。

    回傳調整後的 XML 字串。
    """
    root = ET.fromstring(xml)
    if align_to_grid > 0:
        align_vertices_to_grid(root, align_to_grid)
        if align_waypoints:
            align_edge_waypoints_to_grid(root, align_to_grid)
    if nudge_overlap and align_to_grid > 0:
        nudge_overlapping_vertices(root, parent_id="1", grid=align_to_grid, gap=overlap_gap)

    rough = ET.tostring(root, encoding="unicode", default_namespace="")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
