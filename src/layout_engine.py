"""
Layout engine for Draw.io XML.

對 Draw.io XML 做自動版面調整，例如：
- 座標對齊格點（align to grid）
- 邊的 waypoints 對齊格點
- 可擴充：偵測並排除頂點重疊、走線與元件重疊等（依 DRAWIO_RULES.md）

注意：``generate_drawio()`` 匯出結尾會呼叫 ``freeze_edge_routing()``，將邊改為
``edgeStyle=none`` 並寫入 waypoints，避免 Draw.io 開檔時自動重算走線。
``layout_drawio()`` 仍供外部 XML 選用。
"""
import heapq
import math
import xml.etree.ElementTree as ET
from xml.dom import minidom

from drawio_export_options import DrawioExportOptions


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


def _extract_vertical_segments(root: ET.Element) -> list[tuple[ET.Element, list[ET.Element], float, float, float]]:
    """從邊的 waypoints 中提取垂直線段。

    回傳 [(edge_cell, [mxPoint_a, mxPoint_b], x, y_min, y_max), ...]
    每個 tuple 代表一條垂直線段（兩個相鄰 waypoint 的 x 相同、y 不同）。
    """
    segments = []
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        arr = geo.find("Array")
        if arr is None or arr.get("as") != "points":
            continue
        pts = arr.findall("mxPoint")
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            ax, ay = a.get("x"), a.get("y")
            bx, by = b.get("x"), b.get("y")
            if ax is None or ay is None or bx is None or by is None:
                continue
            try:
                fax, fay, fbx, fby = float(ax), float(ay), float(bx), float(by)
            except ValueError:
                continue
            if fax == fbx and fay != fby:
                segments.append((cell, [a, b], fax, min(fay, fby), max(fay, fby)))
    return segments


def _count_crossings(segments: list[tuple[ET.Element, list[ET.Element], float, float, float]]) -> int:
    """計算垂直線段之間的交叉數。

    兩條垂直線段交叉的條件：x 不同，且各自的 y 範圍有交集，
    且從一端到另一端的相對順序反轉（即一條在上方左邊、下方右邊，另一條反之）。
    """
    crossings = 0
    n = len(segments)
    for i in range(n):
        for j in range(i + 1, n):
            _, _, x1, y1_min, y1_max = segments[i]
            _, _, x2, y2_min, y2_max = segments[j]
            if x1 == x2:
                continue
            y_overlap_min = max(y1_min, y2_min)
            y_overlap_max = min(y1_max, y2_max)
            if y_overlap_min >= y_overlap_max:
                continue
            crossings += 1
    return crossings


def minimize_crossings(root: ET.Element, grid: int = 40, max_iterations: int = 20) -> int:
    """透過交換垂直走線的 x 座標來減少交叉數。

    使用 adjacent swap 啟發式：對每對有交叉的垂直線段，嘗試交換它們的 x 座標，
    若交叉數減少則保留交換。迭代直到無改善或達到上限。

    回傳減少的交叉數。
    """
    segments = _extract_vertical_segments(root)
    if len(segments) < 2:
        return 0

    initial_crossings = _count_crossings(segments)
    if initial_crossings == 0:
        return 0

    improved_total = 0
    for _ in range(max_iterations):
        improved = False
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                _, pts_i, xi, _, _ = segments[i]
                _, pts_j, xj, _, _ = segments[j]
                if xi == xj:
                    continue

                before = _count_crossings(segments)

                new_xi = _align_value(xj, grid) if grid > 0 else int(xj)
                new_xj = _align_value(xi, grid) if grid > 0 else int(xi)
                if new_xi is None or new_xj is None:
                    continue

                for pt in pts_i:
                    pt.set("x", str(new_xi))
                for pt in pts_j:
                    pt.set("x", str(new_xj))

                segments[i] = (segments[i][0], pts_i, float(new_xi), segments[i][3], segments[i][4])
                segments[j] = (segments[j][0], pts_j, float(new_xj), segments[j][3], segments[j][4])

                after = _count_crossings(segments)
                if after < before:
                    improved = True
                    improved_total += before - after
                else:
                    for pt in pts_i:
                        pt.set("x", str(int(xi)))
                    for pt in pts_j:
                        pt.set("x", str(int(xj)))
                    segments[i] = (segments[i][0], pts_i, xi, segments[i][3], segments[i][4])
                    segments[j] = (segments[j][0], pts_j, xj, segments[j][3], segments[j][4])

        if not improved:
            break

    return improved_total


def _parse_style(style: str | None) -> dict[str, str]:
    """將 mxCell style 字串解析為 dict（key=value;...）。"""
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _anchor_point(bbox: tuple[float, float, float, float], ax: float, ay: float) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + (x2 - x1) * ax, y1 + (y2 - y1) * ay)


MIN_HORIZ_STUB = 40
ROUTE_GRID_PRIMARY = 40
ROUTE_GRID_FALLBACK = 20


def _seg_overlap_allowed(
    options: DrawioExportOptions,
    *,
    cur_source_id: str | None,
    cur_dest_id: str | None,
    seg_source_id: str | None,
    seg_dest_id: str | None,
    horiz: bool,
) -> bool:
    if horiz:
        if options.same_source_horiz and cur_source_id and seg_source_id == cur_source_id:
            return True
        if options.same_dest_horiz and cur_dest_id and seg_dest_id == cur_dest_id:
            return True
    else:
        if options.same_source_vert and cur_source_id and seg_source_id == cur_source_id:
            return True
        if options.same_dest_vert and cur_dest_id and seg_dest_id == cur_dest_id:
            return True
    return False


def _style_float(st: dict[str, str], key: str, default: float) -> float:
    try:
        return float(st[key])
    except (KeyError, ValueError):
        return default


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


def _edge_uses_orthogonal_style(style: str | None) -> bool:
    st = _parse_style(style)
    return st.get("edgeStyle") == "orthogonalEdgeStyle"


def clear_orthogonal_edge_waypoints(
    root: ET.Element,
    parent_id: str = "1",
    skip_edge_ids: set[str] | None = None,
) -> int:
    """清除仍使用 ``orthogonalEdgeStyle`` 的邊之路徑點，交給 Draw.io 自動正交走線。

    ``edgeStyle=none``（A* 重繞）的邊不受影響。回傳已清除 waypoints 的邊數。
    """
    skip = skip_edge_ids or set()
    cleared = 0
    for cell in _collect_edges(root, parent_id):
        eid = cell.get("id")
        if eid is not None and eid in skip:
            continue
        if not _edge_uses_orthogonal_style(cell.get("style")):
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        had_points = False
        for arr in list(geo):
            if arr.tag == "Array" and arr.get("as") == "points":
                geo.remove(arr)
                had_points = True
        if had_points:
            cleared += 1
    return cleared


def ensure_edge_horiz_stubs(
    root: ET.Element,
    parent_id: str = "1",
    min_stub: float = MIN_HORIZ_STUB,
) -> int:
    """確保每條邊在 source / destination 端以水平段連接，且水平段至少 ``min_stub`` pt。

    回傳有調整 waypoints 的邊數量。
    """
    vertices = _collect_vertices(root, parent_id)
    boxes_by_id: dict[str, tuple[float, float, float, float]] = {}
    for v in vertices:
        vid = v.get("id")
        bb = _bbox(v)
        if vid is not None and bb is not None:
            boxes_by_id[vid] = bb

    adjusted = 0
    for cell in _collect_edges(root, parent_id):
        sid = cell.get("source")
        tid = cell.get("target")
        if sid is None or tid is None:
            continue
        s_box = boxes_by_id.get(sid)
        t_box = boxes_by_id.get(tid)
        if s_box is None or t_box is None:
            continue
        st = _parse_style(cell.get("style"))
        exit_ax = _style_float(st, "exitX", 1.0)
        exit_ay = _style_float(st, "exitY", 0.5)
        entry_ax = _style_float(st, "entryX", 0.0)
        entry_ay = _style_float(st, "entryY", 0.5)
        ex, ey = _anchor_point(s_box, exit_ax, exit_ay)
        tx, ty = _anchor_point(t_box, entry_ax, entry_ay)
        es = _exit_stub_point(ex, ey, exit_ax, tx, min_stub)
        ist = _entry_stub_point(tx, ty, entry_ax, ex, min_stub)

        geo = cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        wps = _get_edge_waypoints(geo)
        changed = False

        if not wps:
            if abs(ey - ty) < 0.5:
                wps = [es, ist]
            else:
                wps = [es, (es[0], ty), ist]
            changed = True
        else:
            if not _exit_horiz_ok(ex, ey, wps[0][0], wps[0][1], exit_ax, min_stub):
                wps.insert(0, es)
                changed = True
            if not _entry_horiz_ok(tx, ty, wps[-1][0], wps[-1][1], entry_ax, ex, min_stub):
                wps.append(ist)
                changed = True

        if changed:
            wps = _collapse_collinear(wps)
            _set_edge_waypoints(geo, wps)
            adjusted += 1

    return adjusted


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
    """鎖定走線：補齊 stub／轉折 waypoints 後改 ``edgeStyle=none``。

    Draw.io 對 ``edgeStyle=none`` 的邊只沿 waypoints 與 anchor 畫折線，開檔時
    不會再跑 ``orthogonalEdgeStyle`` 自動路由。回傳已凍結的邊數。
    """
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


def _astar_orthogonal(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[tuple[float, float, float, float]],
    grid: int,
    routed_v: list[tuple[float, float, float, str | None, str | None]],
    routed_h: list[tuple[float, float, float, str | None, str | None]],
    *,
    source_id: str | None = None,
    dest_id: str | None = None,
    overlap_options: DrawioExportOptions | None = None,
    clearance: float = 0.0,
    pad_x: float = 80.0,
    pad_y: float = 320.0,
    turn_penalty: float | None = None,
    overlap_penalty: float = 400.0,
    max_expansions: int = 120000,
) -> list[tuple[float, float]] | None:
    """正交避障路由（A*）。

    在 start/goal 周邊的局部 Hanan 格點上找一條只走水平/垂直、且不穿過任何
    ``obstacles``（元件外擴 clearance 後的矩形）的路徑，並以轉彎懲罰偏好折彎最少。
    垂直／水平段與已路由線段重疊時，依 ``overlap_options`` 決定是否懲罰
    （同 source / 同 destination 可分别允許水平或垂直重疊）。找不到回傳 None。
    """
    opts = overlap_options or DrawioExportOptions.defaults()
    sx, sy = start
    gx, gy = goal
    if turn_penalty is None:
        turn_penalty = float(grid)

    # 外擴障礙（含淨空）
    exp = [(x1 - clearance, y1 - clearance, x2 + clearance, y2 + clearance)
           for (x1, y1, x2, y2) in obstacles]

    rx1, rx2 = min(sx, gx) - pad_x, max(sx, gx) + pad_x
    ry1, ry2 = min(sy, gy) - pad_y, max(sy, gy) + pad_y

    xs: set[float] = {round(sx), round(gx)}
    ys: set[float] = {round(sy), round(gy)}
    x = math.ceil(rx1 / grid) * grid
    while x <= rx2:
        xs.add(float(x)); x += grid
    y = math.ceil(ry1 / grid) * grid
    while y <= ry2:
        ys.add(float(y)); y += grid
    for (x1, y1, x2, y2) in exp:
        for bx in (x1, x2):
            if rx1 <= bx <= rx2:
                xs.add(round(bx))
        for by in (y1, y2):
            if ry1 <= by <= ry2:
                ys.add(round(by))
    xs_l = sorted(xs)
    ys_l = sorted(ys)
    xi = {v: i for i, v in enumerate(xs_l)}
    yi = {v: i for i, v in enumerate(ys_l)}
    si, sj = xi[round(sx)], yi[round(sy)]
    gi, gj = xi[round(gx)], yi[round(gy)]

    def seg_blocked(ax: float, ay: float, bx: float, by: float) -> bool:
        x_lo, x_hi = (ax, bx) if ax <= bx else (bx, ax)
        y_lo, y_hi = (ay, by) if ay <= by else (by, ay)
        for (ox1, oy1, ox2, oy2) in exp:
            if x_hi <= ox1 or x_lo >= ox2 or y_hi <= oy1 or y_lo >= oy2:
                continue
            return True
        return False

    def v_overlap_pen(vx: float, ya: float, yb: float) -> float:
        lo, hi = (ya, yb) if ya <= yb else (yb, ya)
        for item in routed_v:
            rx, ra, rb = item[0], item[1], item[2]
            rs = item[3] if len(item) > 3 else None
            rd = item[4] if len(item) > 4 else None
            if abs(rx - vx) < 0.5 and not (hi <= ra or lo >= rb):
                if not _seg_overlap_allowed(
                    opts,
                    cur_source_id=source_id,
                    cur_dest_id=dest_id,
                    seg_source_id=rs,
                    seg_dest_id=rd,
                    horiz=False,
                ):
                    return overlap_penalty
        return 0.0

    def h_overlap_pen(hy: float, xa: float, xb: float) -> float:
        lo, hi = (xa, xb) if xa <= xb else (xb, xa)
        for item in routed_h:
            ry, ra, rb = item[0], item[1], item[2]
            rs = item[3] if len(item) > 3 else None
            rd = item[4] if len(item) > 4 else None
            if abs(ry - hy) < 0.5 and not (hi <= ra or lo >= rb):
                if not _seg_overlap_allowed(
                    opts,
                    cur_source_id=source_id,
                    cur_dest_id=dest_id,
                    seg_source_id=rs,
                    seg_dest_id=rd,
                    horiz=True,
                ):
                    return overlap_penalty
        return 0.0

    def h(i: int, j: int) -> float:
        return abs(xs_l[i] - gx) + abs(ys_l[j] - gy)

    # 狀態：(i, j, dir)；dir 0=無,1=水平,2=垂直
    start_state = (si, sj, 0)
    g_score: dict[tuple[int, int, int], float] = {start_state: 0.0}
    came: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    pq: list[tuple[float, int, int, int]] = [(h(si, sj), si, sj, 0)]
    expansions = 0
    goal_state: tuple[int, int, int] | None = None

    while pq:
        f, i, j, d = heapq.heappop(pq)
        expansions += 1
        if expansions > max_expansions:
            return None
        cur = (i, j, d)
        cur_g = g_score.get(cur, math.inf)
        if f - h(i, j) > cur_g + 1e-6:
            continue
        if i == gi and j == gj:
            goal_state = cur
            break
        ax, ay = xs_l[i], ys_l[j]
        for ni, nj, nd in ((i + 1, j, 1), (i - 1, j, 1), (i, j + 1, 2), (i, j - 1, 2)):
            if ni < 0 or ni >= len(xs_l) or nj < 0 or nj >= len(ys_l):
                continue
            bx, by = xs_l[ni], ys_l[nj]
            if seg_blocked(ax, ay, bx, by):
                continue
            step = abs(bx - ax) + abs(by - ay)
            cost = step
            if d != 0 and nd != d:
                cost += turn_penalty
            if nd == 1:
                cost += h_overlap_pen(ay, ax, bx)
            if nd == 2:
                cost += v_overlap_pen(bx, ay, by)
            ng = cur_g + cost
            ns = (ni, nj, nd)
            if ng < g_score.get(ns, math.inf) - 1e-6:
                g_score[ns] = ng
                came[ns] = cur
                heapq.heappush(pq, (ng + h(ni, nj), ni, nj, nd))

    if goal_state is None:
        return None

    path: list[tuple[float, float]] = []
    s = goal_state
    while True:
        i, j, _ = s
        path.append((xs_l[i], ys_l[j]))
        if s == start_state:
            break
        s = came[s]
    path.reverse()
    return path


def _astar_orthogonal_with_fallback(
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacles: list[tuple[float, float, float, float]],
    routed_v: list[tuple[float, float, float, str | None, str | None]],
    routed_h: list[tuple[float, float, float, str | None, str | None]],
    *,
    source_id: str | None = None,
    dest_id: str | None = None,
    overlap_options: DrawioExportOptions | None = None,
    route_grid: int = ROUTE_GRID_PRIMARY,
    fallback_grid: int = ROUTE_GRID_FALLBACK,
) -> list[tuple[float, float]] | None:
    """先以 ``route_grid``（預設 40pt）格距 A*；失敗再以 ``fallback_grid``（預設 20pt）重試。"""
    grids: list[int] = []
    for g in (route_grid, fallback_grid):
        g = max(int(g), 1)
        if g not in grids:
            grids.append(g)
    for g in grids:
        path = _astar_orthogonal(
            start, goal, obstacles, g, routed_v, routed_h,
            source_id=source_id, dest_id=dest_id, overlap_options=overlap_options,
        )
        if path is not None:
            return path
    return None


def _collapse_collinear(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """移除共線的中間點，只保留轉彎點與端點。"""
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


def route_orthogonal(
    root: ET.Element,
    parent_id: str = "1",
    grid: int = 40,
    skip_edge_ids: set[str] | None = None,
    overlap_options: DrawioExportOptions | None = None,
) -> int:
    """後處理正交路由器（安全網版本）。

    僅針對「標準左→右」邊（source 右側出、target 左側進）重繞為乾淨的
    水平-垂直-水平折線；source / destination 端各保留至少 ``MIN_HORIZ_STUB``（40pt）
    水平段，並設 ``edgeStyle=none`` 讓 Draw.io 照 waypoints 畫、
    不再自動繞線。A* 先以 40pt 格距搜路，繞不出來再以 20pt 格距重試；仍失敗則
    回退保留原 style 與 waypoints。任何會穿過其他頂點、或與既繞線垂直段重疊、或非標準走向的邊，
    一律「回退」保留原本的 style 與 waypoints，確保只會變好不會變差。
    重疊規則由 ``overlap_options`` 控制（同 source / 同 destination 的水平或垂直重疊）。

    回傳成功重繞的邊數量。
    """
    opts = overlap_options or DrawioExportOptions.defaults()
    grid = max(grid, 1)
    vertices = _collect_vertices(root, parent_id)
    boxes_by_id: dict[str, tuple[float, float, float, float]] = {}
    for v in vertices:
        vid = v.get("id")
        bb = _bbox(v)
        if vid is not None and bb is not None:
            boxes_by_id[vid] = bb
    all_boxes = list(boxes_by_id.values())

    routed_v: list[tuple[float, float, float, str | None, str | None]] = []
    routed_h: list[tuple[float, float, float, str | None, str | None]] = []
    rerouted = 0

    skip = skip_edge_ids or set()

    for cell in _collect_edges(root, parent_id):
        eid = cell.get("id")
        if eid is not None and eid in skip:
            continue
        sid = cell.get("source")
        tid = cell.get("target")
        if sid is None or tid is None:
            continue
        s_box = boxes_by_id.get(sid)
        t_box = boxes_by_id.get(tid)
        if s_box is None or t_box is None:
            continue
        st = _parse_style(cell.get("style"))

        exit_ax = _style_float(st, "exitX", 1.0)
        exit_ay = _style_float(st, "exitY", 0.5)
        entry_ax = _style_float(st, "entryX", 0.0)
        entry_ay = _style_float(st, "entryY", 0.5)
        if exit_ax < 0.75 or entry_ax > 0.25:
            continue

        ex, ey = _anchor_point(s_box, exit_ax, exit_ay)
        tx, ty = _anchor_point(t_box, entry_ax, entry_ay)
        if ex >= tx - grid:  # 目標不在右方足夠距離，回退
            continue

        start_stub = _exit_stub_point(ex, ey, exit_ax, tx)
        end_stub = _entry_stub_point(tx, ty, entry_ax, ex)

        obstacles = [b for vid, b in boxes_by_id.items() if vid not in (sid, tid)]

        path = _astar_orthogonal_with_fallback(
            start_stub, end_stub, obstacles, routed_v, routed_h,
            source_id=sid, dest_id=tid, overlap_options=opts,
            route_grid=grid, fallback_grid=ROUTE_GRID_FALLBACK,
        )
        if path is None:
            continue  # 回退：保留原 style/waypoints（40pt 與 20pt 皆繞不出來）
        full_path = _collapse_collinear([(ex, ey), start_stub] + path[1:-1] + [end_stub, (tx, ty)])
        path = full_path
        for k in range(len(path) - 1):
            ax2, ay2 = path[k]
            bx2, by2 = path[k + 1]
            if abs(ax2 - bx2) < 0.5 and abs(ay2 - by2) >= 0.5:
                routed_v.append((ax2, min(ay2, by2), max(ay2, by2), sid, tid))
            elif abs(ay2 - by2) < 0.5 and abs(ax2 - bx2) >= 0.5:
                routed_h.append((ay2, min(ax2, bx2), max(ax2, bx2), sid, tid))
        # waypoints = 去掉端點（端點由 anchor 決定）後的轉彎點
        chosen = path[1:-1]

        # 套用：改 edgeStyle=none、重寫 waypoints
        sty = cell.get("style") or ""
        if "edgeStyle=" in sty:
            import re as _re
            sty = _re.sub(r"edgeStyle=[^;]*", "edgeStyle=none", sty)
        else:
            sty = "edgeStyle=none;" + sty
        cell.set("style", sty)

        geo = cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        for arr in list(geo):
            if arr.tag == "Array" and arr.get("as") == "points":
                geo.remove(arr)
        if chosen:
            arr = ET.SubElement(geo, "Array", {"as": "points"})
            for (px, py) in chosen:
                ET.SubElement(arr, "mxPoint", {"x": str(int(round(px))), "y": str(int(round(py)))})
        rerouted += 1

    return rerouted


def layout_drawio(
    xml: str,
    *,
    align_to_grid: int = 40,
    align_waypoints: bool = True,
    nudge_overlap: bool = False,
    overlap_gap: int = 80,
    reduce_crossings: bool = False,
) -> str:
    """
    對 Draw.io XML 做版面調整。

    - align_to_grid: 頂點 x,y 與（若 align_waypoints）waypoints 對齊的格距，0 表示不對齊。
    - align_waypoints: 是否將邊的 waypoints 對齊格點。
    - nudge_overlap: 是否嘗試將重疊的頂點錯開（僅對 parent="1" 的頂點）。
    - overlap_gap: nudge 時位移量（pt）。
    - reduce_crossings: 是否嘗試交換垂直走線 x 座標以減少交叉。

    回傳調整後的 XML 字串。
    """
    root = ET.fromstring(xml)
    if align_to_grid > 0:
        align_vertices_to_grid(root, align_to_grid)
        if align_waypoints:
            align_edge_waypoints_to_grid(root, align_to_grid)
    if nudge_overlap and align_to_grid > 0:
        nudge_overlapping_vertices(root, parent_id="1", grid=align_to_grid, gap=overlap_gap)
    if reduce_crossings:
        minimize_crossings(root, grid=max(align_to_grid, 1))

    rough = ET.tostring(root, encoding="unicode", default_namespace="")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
