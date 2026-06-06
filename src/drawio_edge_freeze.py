"""
Draw.io 邊走線鎖定（匯出結尾使用）。

``generate_drawio()`` 結尾呼叫 ``freeze_edge_routing()``：補齊 stub／轉折 waypoints
後改 ``edgeStyle=none``，避免 Draw.io 開檔時自動重算。input label 出發的邊改由
``restore_orthogonal_auto_routing()`` 交回 Draw.io 自動正交走線。
"""
import xml.etree.ElementTree as ET

MIN_HORIZ_STUB = 40


def _align_value(v: str | None, grid: int) -> int | None:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        x = float(v)
        return round(x / grid) * grid
    except (ValueError, TypeError):
        return None


def _collect_vertices(root: ET.Element, parent_id: str = "1") -> list[ET.Element]:
    out: list[ET.Element] = []
    for cell in root.iter("mxCell"):
        if cell.get("parent") == parent_id and cell.get("vertex") == "1":
            out.append(cell)
    return out


def _collect_edges(root: ET.Element, parent_id: str = "1") -> list[ET.Element]:
    out: list[ET.Element] = []
    for cell in root.iter("mxCell"):
        if cell.get("parent") == parent_id and cell.get("edge") == "1":
            out.append(cell)
    return out


def _bbox(cell: ET.Element) -> tuple[float, float, float, float] | None:
    geo = cell.find("mxGeometry")
    if geo is None:
        return None
    attrs = geo.attrib
    x = _align_value(attrs.get("x"), 1)
    y = _align_value(attrs.get("y"), 1)
    w = _align_value(attrs.get("width"), 1)
    h = _align_value(attrs.get("height"), 1)
    if x is None or y is None:
        return None
    w = w if w is not None else 0
    h = h if h is not None else 0
    return (float(x), float(y), float(x + w), float(y + h))


def _parse_style(style: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _style_float(st: dict[str, str], key: str, default: float) -> float:
    try:
        return float(st[key])
    except (KeyError, ValueError):
        return default


def _anchor_point(bbox: tuple[float, float, float, float], ax: float, ay: float) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + (x2 - x1) * ax, y1 + (y2 - y1) * ay)


def _exit_horiz_dir(exit_ax: float, ex: float, tx: float) -> int:
    if exit_ax >= 0.75:
        return 1
    if exit_ax <= 0.25:
        return -1
    return 1 if tx >= ex else -1


def _entry_horiz_dir(entry_ax: float, ex: float, tx: float) -> int:
    if entry_ax <= 0.25:
        return -1
    if entry_ax >= 0.75:
        return 1
    return -1 if tx >= ex else 1


def _exit_stub_point(
    ex: float, ey: float, exit_ax: float, tx: float, min_stub: float = MIN_HORIZ_STUB,
) -> tuple[float, float]:
    d = _exit_horiz_dir(exit_ax, ex, tx)
    return (ex + d * min_stub, ey)


def _entry_stub_point(
    tx: float, ty: float, entry_ax: float, ex: float, min_stub: float = MIN_HORIZ_STUB,
) -> tuple[float, float]:
    d = _entry_horiz_dir(entry_ax, ex, tx)
    return (tx + d * min_stub, ty)


def _exit_horiz_ok(
    ex: float, ey: float, px: float, py: float, exit_ax: float, min_stub: float,
) -> bool:
    if abs(py - ey) >= 0.5:
        return False
    d = _exit_horiz_dir(exit_ax, ex, px)
    return (px - ex) * d >= min_stub - 0.5


def _entry_horiz_ok(
    tx: float, ty: float, px: float, py: float, entry_ax: float, ex: float, min_stub: float,
) -> bool:
    if abs(py - ty) >= 0.5:
        return False
    d = _entry_horiz_dir(entry_ax, ex, tx)
    return (px - tx) * d >= min_stub - 0.5


def _get_edge_waypoints(geo: ET.Element | None) -> list[tuple[float, float]]:
    if geo is None:
        return []
    for arr in geo.findall("Array"):
        if arr.get("as") != "points":
            continue
        pts: list[tuple[float, float]] = []
        for pt in arr.findall("mxPoint"):
            try:
                pts.append((float(pt.get("x", 0)), float(pt.get("y", 0))))
            except (TypeError, ValueError):
                continue
        return pts
    return []


def _set_edge_waypoints(geo: ET.Element, points: list[tuple[float, float]]) -> None:
    for arr in list(geo):
        if arr.tag == "Array" and arr.get("as") == "points":
            geo.remove(arr)
    if not points:
        return
    arr = ET.SubElement(geo, "Array", {"as": "points"})
    for (px, py) in points:
        ET.SubElement(arr, "mxPoint", {"x": str(int(round(px))), "y": str(int(round(py)))})


def _collapse_collinear(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(path) <= 2:
        return path[:]
    out = [path[0]]
    for k in range(1, len(path) - 1):
        ax, ay = out[-1]
        bx, by = path[k]
        cx, cy = path[k + 1]
        collinear = (abs(ax - bx) < 0.5 and abs(bx - cx) < 0.5) or (abs(ay - by) < 0.5 and abs(by - cy) < 0.5)
        if not collinear:
            out.append(path[k])
    out.append(path[-1])
    return out


def _orthogonalize_polyline(path: list[tuple[float, float]], tol: float = 0.5) -> list[tuple[float, float]]:
    """補轉角點，使相鄰兩點必為水平或垂直（``edgeStyle=none`` 不會自動正交）。"""
    if len(path) <= 1:
        return list(path)
    out = [path[0]]
    for nx, ny in path[1:]:
        ax, ay = out[-1]
        if abs(ax - nx) <= tol or abs(ay - ny) <= tol:
            if abs(ax - nx) > tol or abs(ay - ny) > tol:
                out.append((nx, ny))
            continue
        out.append((nx, ay))
        out.append((nx, ny))
    return _collapse_collinear(out)


def _style_to_frozen_none(style: str) -> str:
    """orthogonalEdgeStyle → edgeStyle=none（Draw.io 不再自動正交路由）。"""
    import re

    sty = style or ""
    if "edgeStyle=" in sty:
        sty = re.sub(r"edgeStyle=[^;]*", "edgeStyle=none", sty)
    else:
        sty = "edgeStyle=none;" + sty
    sty = re.sub(r"jettySize=[^;]*;?", "", sty)
    sty = re.sub(r"orthogonalLoop=[^;]*;?", "", sty)
    return sty


def _style_to_orthogonal(style: str) -> str:
    """``edgeStyle=none`` 或缺省 → ``orthogonalEdgeStyle``（Draw.io 自動正交路由）。"""
    import re

    sty = style or ""
    if "edgeStyle=" in sty:
        sty = re.sub(r"edgeStyle=[^;]*", "edgeStyle=orthogonalEdgeStyle", sty)
    else:
        sty = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
            "jettySize=auto;html=1;" + sty
        )
    if "orthogonalLoop=" not in sty:
        sty = sty.replace(
            "edgeStyle=orthogonalEdgeStyle",
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1",
            1,
        )
    return sty


def restore_orthogonal_auto_routing(
    root: ET.Element,
    source_ids: set[str],
    parent_id: str = "1",
    edge_ids: set[str] | None = None,
) -> int:
    """指定 source 或 edge id 的邊：改回 ``orthogonalEdgeStyle`` 並清除 waypoints。"""
    by_edge = edge_ids or set()
    restored = 0
    for cell in _collect_edges(root, parent_id):
        eid = cell.get("id")
        sid = cell.get("source")
        if sid not in source_ids and (eid is None or eid not in by_edge):
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        for arr in list(geo):
            if arr.tag == "Array" and arr.get("as") == "points":
                geo.remove(arr)
        cell.set("style", _style_to_orthogonal(cell.get("style") or ""))
        restored += 1
    return restored


def freeze_edge_routing(
    root: ET.Element,
    parent_id: str = "1",
    min_stub: float = MIN_HORIZ_STUB,
    skip_edge_ids: set[str] | None = None,
    skip_source_ids: set[str] | None = None,
    source_min_stub: dict[str, float] | None = None,
) -> int:
    """鎖定走線：補齊 stub／轉折 waypoints 後改 ``edgeStyle=none``。"""
    skip = skip_edge_ids or set()
    skip_src = skip_source_ids or set()
    boxes_by_id: dict[str, tuple[float, float, float, float]] = {}
    for v in _collect_vertices(root, parent_id):
        vid = v.get("id")
        bb = _bbox(v)
        if vid is not None and bb is not None:
            boxes_by_id[vid] = bb

    frozen = 0
    for cell in _collect_edges(root, parent_id):
        eid = cell.get("id")
        if eid is not None and eid in skip:
            continue
        st = _parse_style(cell.get("style"))
        edge_style = st.get("edgeStyle", "none")
        if edge_style not in ("orthogonalEdgeStyle", "elbowEdgeStyle"):
            continue
        sid = cell.get("source")
        tid = cell.get("target")
        if sid is not None and sid in skip_src:
            continue
        if sid is None or tid is None:
            continue
        s_box = boxes_by_id.get(sid)
        t_box = boxes_by_id.get(tid)
        if s_box is None or t_box is None:
            continue

        exit_ax = _style_float(st, "exitX", 1.0)
        exit_ay = _style_float(st, "exitY", 0.5)
        entry_ax = _style_float(st, "entryX", 0.0)
        entry_ay = _style_float(st, "entryY", 0.5)
        stub_len = min_stub
        if source_min_stub is not None and sid is not None:
            stub_len = source_min_stub.get(sid, min_stub)
        ex, ey = _anchor_point(s_box, exit_ax, exit_ay)
        tx, ty = _anchor_point(t_box, entry_ax, entry_ay)
        es_pt = _exit_stub_point(ex, ey, exit_ax, tx, stub_len)
        ist = _entry_stub_point(tx, ty, entry_ax, ex, min_stub)

        geo = cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        wps = _get_edge_waypoints(geo)
        if not wps:
            if abs(ey - ty) < 0.5:
                wps = [es_pt, ist]
            else:
                wps = [es_pt, (es_pt[0], ty), ist]
        else:
            if not _exit_horiz_ok(ex, ey, wps[0][0], wps[0][1], exit_ax, stub_len):
                wps.insert(0, es_pt)
            if not _entry_horiz_ok(tx, ty, wps[-1][0], wps[-1][1], entry_ax, ex, min_stub):
                wps.append(ist)
        wps = _collapse_collinear(wps)
        full = _orthogonalize_polyline([(ex, ey)] + wps + [(tx, ty)])
        _set_edge_waypoints(geo, full[1:-1])
        cell.set("style", _style_to_frozen_none(cell.get("style") or ""))
        frozen += 1
    return frozen
