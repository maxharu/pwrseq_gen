"""
Export Power Sequence dependency as Draw.io XML.

版面與樣式依專案內 DRAWIO_RULES.md 實作，摘要如下：
- 規則一（輸入）：最左側、命名含 ~ 表反向；每條輸入線垂直對齊其第一個連接的閘輸入端。
- 規則二（邏輯閘）：AND 在左、OR 在右，層級間 80pt；or_col_x = and_col_x + GAP + AND_GATE_W。
- 規則三（H_Deb/L_Deb）：每路徑一對垂直堆疊；連到 H_Deb 實心綠、連到 L_Deb 虛線紅。
- 規則四（輸出）：匯合點與輸出名稱之間有小圓圈；inner → 小圓圈 → 輸出名稱。
- 規則五（連接線）：預設黑、Hi 綠、Lo 虛線紅；正交、少交叉；不穿越元件、繞開元件；走線不重疊；waypoint 處與輸入同高可不對齊 40pt。
- 規則六：走線間不重疊、箭頭與分岔清楚；常數見 DRAWIO_RULES.md。
"""
import random
import string
import xml.etree.ElementTree as ET
from xml.dom import minidom

from config_models import PowerSeqConfig, PowerRail

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"
CONST_DEPS = {DEP_HIGH, DEP_LOW}

# Power Sequence Cell 尺寸 (與 node_example.xml 一致)
CELL_GROUP_W = 160
CELL_GROUP_H = 80
CELL_INNER_X = 40
CELL_INNER_W = 80
CELL_INNER_H = 80
CELL_H_DEB_W = 50
CELL_H_DEB_H = 20
CELL_L_DEB_W = 50
CELL_L_DEB_H = 20
CELL_H_DEB_Y = 10
CELL_L_DEB_Y = 50
# 版面規則：每個元件上下左右至少間隔 GAP pt，座標為 GRID 的倍數
GRID = 40
GAP = 80

def _align40(v: int | float) -> int:
    """將座標對齊到 40 的倍數。"""
    return round(float(v) / GRID) * GRID


def _align10(v: int | float) -> int:
    """將座標對齊到 10 的倍數（文字框垂直位置用）。"""
    return round(float(v) / 10) * 10

# 欄位式版面（左→右）：輸入欄 | AND 欄 | OR 欄(80pt 間隔) | Cell 欄 | 輸出名稱欄
# AND/OR 分層：愈前一級愈左，輸入→AND→OR→Cell，每級左右間隔 80pt
MARGIN = _align40(GAP)           # 40
INPUT_COL_X = _align40(GAP * 2)  # 160：所有輸入文字框同一垂直線
INPUT_LABEL_W = _align40(80)
INPUT_LABEL_H = 20
INPUT_VERTICAL_DY = GAP         # 每個 input 垂直間距 80pt（用於反相 output 等）
GATE_COL_X = _align40(GAP * 5)  # 400：OR 與 AND 同一欄
CELL_START_X = _align40(GAP * 8)    # 640
OUTPUT_NAME_OFFSET_X = CELL_GROUP_W + _align40(GAP // 2)  # 200
# 輸出名稱 y 與 cell 垂直置中對齊，使 O 線（inner→名稱）為水平直線、無轉角
OUTPUT_NAME_OFFSET_Y = (CELL_GROUP_H - INPUT_LABEL_H) // 2
# 匯合點到輸出訊號之間的小圓圈符號（規則四）
OUTPUT_CIRCLE_SIZE = 8
# 連接線顏色：Hi 實心綠、Lo 虛線紅、預設實心黑
STROKE_HI = "#059669"
STROKE_LO = "#dc2626"
STROKE_DEFAULT = "#000000"
AND_GATE_W = 80
AND_GATE_H = 40
OR_GATE_W = 80
OR_GATE_H = 40
# 由欄位推算的相對偏移（AND 在左、OR 在右，generate_drawio 內動態計算 and_col_x / or_col_x）
AND_GATE_DY = GAP               # 多個 AND 垂直間距 80pt
# OR 閘與該行 Cell 同高，放在左側（不放到 Cell 下方）
OR_GATE_OFFSET_HI_Y = 0
OR_GATE_OFFSET_LO_Y = GRID  # 40，若同時有 Hi/Lo 兩個 OR 則垂直錯開 40pt


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _random_diagram_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _topological_order_outputs(outputs: list[PowerRail], name_to_rail: dict) -> list[PowerRail]:
    """依賴關係拓撲排序：被依賴的 output 排在前面，使圖從左到右/上到下較清晰。"""
    out_names = {r.name for r in outputs}
    result: list[PowerRail] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        rail = name_to_rail.get(name)
        if rail and rail in outputs:
            for dep in rail.get_depends_on_hi_flat() + rail.get_depends_on_lo_flat():
                if dep not in CONST_DEPS and dep in out_names and dep in name_to_rail:
                    visit(dep)
            result.append(rail)

    for r in outputs:
        visit(r.name)
    return result


# 走線通道 x（規則五／六：線經通道轉向、繞開元件、避免交叉與線段重疊；generate_drawio 內依 and_col_x 重算 channel_x_left）
CHANNEL_X_LEFT = (INPUT_COL_X + INPUT_LABEL_W + GATE_COL_X) // 2
CHANNEL_X_RIGHT = (GATE_COL_X + AND_GATE_W + CELL_START_X) // 2


def _orthogonalize_points(
    points: list[tuple[int | float, int | float]],
    align: bool | list[bool],
) -> tuple[list[tuple[int | float, int | float]], list[bool]]:
    """在對角線的相鄰兩點間插入中間點，使每段皆為水平或垂直（規則五：正交走線）。"""
    if len(points) <= 1:
        al = [align] * len(points) if isinstance(align, bool) else align
        return list(points), al
    if isinstance(align, bool):
        align = [align] * len(points)
    expanded: list[tuple[int | float, int | float]] = []
    align_expanded: list[bool] = []
    for i, p in enumerate(points):
        if expanded:
            a, b = expanded[-1], p
            ax, ay, bx, by = a[0], a[1], b[0], b[1]
            if ax != bx and ay != by:
                # 對角線：先水平再垂直，插入 (bx, ay)
                expanded.append((bx, ay))
                align_expanded.append(True)
        expanded.append(p)
        align_expanded.append(align[i] if i < len(align) else True)
    return expanded, align_expanded


def _add_edge_points(
    geo: ET.Element,
    points: list[tuple[int | float, int | float]],
    align: bool | list[bool] = True,
) -> None:
    """為邊加入 waypoints（規則五：正交、與輸入標籤同高之端點可 align=False；對角線會自動插入中間點）。"""
    if not points:
        return
    points, align = _orthogonalize_points(points, align)
    arr = ET.SubElement(geo, "Array", {"as": "points"})
    for k, (px, py) in enumerate(points):
        do_align = align[k] if k < len(align) else True
        x = _align40(px) if do_align else round(float(px))
        y = _align40(py) if do_align else round(float(py))
        ET.SubElement(arr, "mxPoint", {"x": str(x), "y": str(y)})


def _add_edge_waypoint(
    geo: ET.Element,
    cell_xy: tuple[int, int],
    label_xy: tuple[int, int],
    waypoint_x: int | None = None,
    gate_right_x: int | None = None,
    row_py: int | None = None,
) -> None:
    """為 cell→input 的邊加 waypoints（依 golden 原則：垂直 only，(channel_x, cy)→(channel_x, ly)）。"""
    cy = cell_xy[1] + CELL_GROUP_H // 2
    ly = label_xy[1] + INPUT_LABEL_H // 2
    wx = waypoint_x if waypoint_x is not None else CHANNEL_X_LEFT
    _add_edge_points(geo, [(wx, cy), (wx, ly)], align=[True, False])


def _gap_for_lines(n_lines: int) -> int:
    """元件間隔：基礎 80pt，當中有走線時每多一條加 40pt。"""
    if n_lines <= 0:
        return GAP
    return GAP + GRID * (n_lines - 1)


def _count_edges_in_column_gaps(
    outputs: list[PowerRail], name_to_rail: dict, valid: set[str]
) -> tuple[int, int, int]:
    """
    回傳 (輸入↔閘 走線數, 閘↔Cell 走線數, Cell↔輸出名稱 走線數)。
    用於依「每多一條走線間隔加 40pt」計算欄位間距。
    """
    n_input_gate = 0
    n_gate_cell = 0
    n_cell_out = len(outputs)
    for r in outputs:
        hi_groups = r.get_hi_groups()
        lo_groups = r.get_lo_groups()
        n_or_hi = 1 if len(hi_groups) >= 2 else 0
        n_or_lo = 1 if len(lo_groups) >= 2 else 0
        n_and_hi = sum(1 for g in hi_groups if len(g) >= 2)
        n_and_lo = sum(1 for g in lo_groups if len(g) >= 2)
        # 輸入依賴數（input→閘 + cell→input 都經過輸入↔閘間隙）
        for g in hi_groups + lo_groups:
            for d in g:
                if d in valid and d not in CONST_DEPS and name_to_rail[d].seq_type == "input":
                    n_input_gate += 2  # input→gate 一條, cell→input 一條
        # 閘↔Cell：僅計入 cell→input（經 waypoint 橫越間隙）。OR/AND→cell、output→gate 皆為直接水平線、無垂直走線，不計入
        for g in hi_groups + lo_groups:
            for d in g:
                if d in valid and d not in CONST_DEPS and name_to_rail[d].seq_type == "input":
                    n_gate_cell += 1
    return (n_input_gate, n_gate_cell, n_cell_out)


def _row_height_for_output(r: PowerRail) -> int:
    """單一 output 左側邏輯（AND/OR）所需垂直高度，用於動態行高。"""
    hi_groups = r.get_hi_groups()
    lo_groups = r.get_lo_groups()
    n_and_hi = sum(1 for g in hi_groups if len(g) >= 2)
    n_and_lo = sum(1 for g in lo_groups if len(g) >= 2)
    n_or_hi = 1 if len(hi_groups) >= 2 else 0
    n_or_lo = 1 if len(lo_groups) >= 2 else 0
    and_stack = (n_and_hi + n_and_lo) * AND_GATE_DY
    or_span = max(OR_GATE_OFFSET_HI_Y + OR_GATE_H, OR_GATE_OFFSET_LO_Y + OR_GATE_H) if (n_or_hi or n_or_lo) else 0
    return max(CELL_GROUP_H, and_stack + or_span + 16)


def generate_drawio(config: PowerSeqConfig) -> str:
    """
    Generate Draw.io XML per node_example.xml:
    - Only output rails become nodes (Power Sequence Cell: group + edge O + inner + H_Deb + L_Deb).
    - Input rails are text labels only; edges go from cell inner to input label (H/L) or to another output cell.
    """
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail.keys())
    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs_raw = [r for r in config.rails if r.seq_type == "output"]
    # Cell 依 config 順序由上而下擺放（不改成拓撲序，方便使用者對應表格）
    outputs = list(outputs_raw)

    # 規則二：層級間距 80pt（GAP）。間隔基礎 80pt，走線多時每條加 40pt；閘↔Cell 固定 80pt
    n_ig, _, n_co = _count_edges_in_column_gaps(outputs, name_to_rail, valid)
    gap_ig = _align40(_gap_for_lines(n_ig))
    gap_ig = max(gap_ig, _align40(GAP + AND_GATE_W))  # AND 欄在 OR 左 80pt，預留空間
    gap_gc = _align40(GAP)
    gap_co = _align40(_gap_for_lines(n_co))
    input_right = INPUT_COL_X + INPUT_LABEL_W
    gate_col_x = input_right + gap_ig
    # OR 欄（最右側閘）；AND 欄在 OR 左邊 80pt，愈前一級愈左
    or_col_x = gate_col_x
    and_col_x = gate_col_x - GAP - AND_GATE_W
    cell_start_x = gate_col_x + OR_GATE_W + gap_gc
    output_name_offset_x = CELL_GROUP_W + gap_co
    channel_x_left = (INPUT_COL_X + INPUT_LABEL_W + and_col_x) // 2
    channel_x_right = (gate_col_x + OR_GATE_W + cell_start_x) // 2
    or_gate_offset_x = or_col_x - cell_start_x
    and_gate_offset_x = and_col_x - cell_start_x

    # 動態行高：每行高度依該 output 左側 AND/OR 數量預留，對齊 40pt、行間距 GAP
    row_heights: list[int] = [_align40(_row_height_for_output(r)) for r in outputs]
    row_y_base: list[int] = []
    acc = MARGIN
    for h in row_heights:
        row_y_base.append(_align40(acc))
        acc += h + GAP

    positions_out: dict[str, tuple[int, int]] = {}
    output_to_row: dict[str, int] = {}
    for j, r in enumerate(outputs):
        y = _align40(row_y_base[j])
        positions_out[r.name] = (cell_start_x, y)
        output_to_row[r.name] = j

    # 僅建立「有被使用」的 input 標籤，並記錄每個 input 被哪些 output 使用（供對齊）
    used_inputs_normal = set()
    inv_input_names = set()
    inv_output_names = set()
    input_first_output: dict[str, str] = {}  # input name -> 第一個使用它的 output name（依拓撲序）
    for r in outputs:
        for d in r.get_depends_on_hi_flat():
            if d not in valid or d in CONST_DEPS:
                continue
            if name_to_rail[d].seq_type == "input":
                if d not in input_first_output:
                    input_first_output[d] = r.name
                if r.depends_on_hi_inv.get(d, False):
                    inv_input_names.add(d)
                else:
                    used_inputs_normal.add(d)
            else:
                if r.depends_on_hi_inv.get(d, False):
                    inv_output_names.add(d)
        for d in r.get_depends_on_lo_flat():
            if d not in valid or d in CONST_DEPS:
                continue
            if name_to_rail[d].seq_type == "input":
                if d not in input_first_output:
                    input_first_output[d] = r.name
                if r.depends_on_lo_inv.get(d, False):
                    inv_input_names.add(d)
                else:
                    used_inputs_normal.add(d)
            else:
                if r.depends_on_lo_inv.get(d, False):
                    inv_output_names.add(d)
    _input_order = lambda n: next(i for i, r in enumerate(config.rails) if r.name == n)
    used_inputs_list = sorted(used_inputs_normal, key=_input_order)
    all_input_names = sorted(used_inputs_normal | inv_input_names, key=_input_order)

    # Input 標籤：同一垂直線（INPUT_COL_X），y 對齊所連閘的列，使「輸入→閘」至少一條線無轉角
    # 依「第一個使用該 input 的 output 所在列」分組，同列內依 config 序；每列第一個 input 對齊該列 OR 高
    row_to_inputs: dict[int, list[str]] = {}
    for name in all_input_names:
        row = output_to_row.get(input_first_output.get(name, ""), 0)
        row_to_inputs.setdefault(row, []).append(name)
    for row in row_to_inputs:
        row_to_inputs[row].sort(key=_input_order)

    # 預先計算每個 output 的 AND 閘索引與 y（與後續繪製一致：先 Hi 再 Lo）
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]] = {}  # (r.name, "hi"|"lo", gi) -> (row, and_index)
    for j, r in enumerate(outputs):
        hi_groups = r.get_hi_groups()
        lo_groups = r.get_lo_groups()
        idx = 0
        for gi, g in enumerate(hi_groups):
            if len(g) >= 2:
                and_index_per_key[(r.name, "hi", gi)] = (j, idx)
                idx += 1
        for gi, g in enumerate(lo_groups):
            if len(g) >= 2:
                and_index_per_key[(r.name, "lo", gi)] = (j, idx)
                idx += 1

    def _and_gate_center_y(row: int, and_index: int) -> int:
        """AND 閘中心 y（與後續繪製時一致）。"""
        return row_y_base[row] + and_index * AND_GATE_DY + AND_GATE_H // 2

    def _and_pin_y(and_center_y: int, pin_index: int, total_pins: int) -> int:
        """AND 閘左側第 pin_index 個輸入 pin 的 y（entryY 0.25/0.75 等對應的實際座標）。"""
        entry_rel = (0.5 if total_pins <= 1 else 0.25 + (0.5 * pin_index / max(1, total_pins - 1)))
        return _align10(and_center_y + (entry_rel - 0.5) * AND_GATE_H)

    def _first_connection_y(inp_name: str) -> int:
        """該 input 第一個要連接的點的 y（OR 中心或 AND 的對應 pin），使輸入可水平對齊。"""
        out_name = input_first_output.get(inp_name)
        if not out_name:
            return _align10(row_y_base[0] + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2)
        j = output_to_row.get(out_name, 0)
        r = name_to_rail.get(out_name)
        if not r:
            return _align10(row_y_base[j] + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2)
        hi_groups = r.get_hi_groups()
        lo_groups = r.get_lo_groups()
        # Hi 先找
        for gi, group in enumerate(hi_groups):
            if inp_name not in group:
                continue
            if len(group) == 1:
                return _align10(row_y_base[j] + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2)
            row, and_idx = and_index_per_key.get((r.name, "hi", gi), (j, 0))
            and_center = _and_gate_center_y(row, and_idx)
            pin_index = group.index(inp_name)
            return _and_pin_y(and_center, pin_index, len(group))
        for gi, group in enumerate(lo_groups):
            if inp_name not in group:
                continue
            if len(group) == 1:
                return _align10(row_y_base[j] + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2)
            row, and_idx = and_index_per_key.get((r.name, "lo", gi), (j, 0))
            and_center = _and_gate_center_y(row, and_idx)
            pin_index = group.index(inp_name)
            return _and_pin_y(and_center, pin_index, len(group))
        return _align10(row_y_base[j] + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2)

    # 規則一（對齊必守）：每條輸入線垂直對齊其第一個連接的閘輸入端
    positions_in: dict[str, tuple[int, int]] = {}
    for name in all_input_names:
        conn_y = _first_connection_y(name)
        # 標籤垂直置中對齊連接點
        label_y = _align10(conn_y - INPUT_LABEL_H // 2)
        positions_in[name] = (INPUT_COL_X, label_y)

    cell_id = 2
    out_group_id: dict[str, int] = {}
    out_inner_id: dict[str, int] = {}
    in_label_id: dict[str, int] = {}
    inv_in_label_id: dict[str, int] = {}
    inv_out_label_id: dict[str, int] = {}
    # (rail_name, "hi"|"lo", group_index) -> AND gate cell id（僅當該 group 有 2+ 訊號時）
    and_gate_id: dict[tuple[str, str, int], int] = {}

    mxfile = ET.Element(
        "mxfile",
        {"host": "app.diagrams.net", "agent": "PowerSeqGen", "version": "29.6.0"},
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "PowerSeq", "id": _random_diagram_id()})
    model = ET.SubElement(diagram, "mxGraphModel", {
        "dx": "1579", "dy": "459", "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1", "pageWidth": "827", "pageHeight": "1169",
        "math": "0", "shadow": "0"
    })
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    style_edge_h_internal = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.25;exitDx=0;exitDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_edge_l_internal = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.75;exitDx=0;exitDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_inner = "rounded=0;whiteSpace=wrap;html=1;"
    style_deb = "rounded=1;whiteSpace=wrap;html=1;"
    style_input_label = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=right;verticalAlign=middle;rounded=0;"
    style_output_name = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;rounded=0;"
    style_edge_o_to_name = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % STROKE_DEFAULT
    style_edge_h_to_label = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.25;exitDx=0;exitDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_edge_l_to_label = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.75;exitDx=0;exitDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_and_gate = "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;verticalAlign=top;shape=mxgraph.electrical.logic_gates.logic_gate;operation=and;"
    style_or_gate = "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;verticalAlign=top;shape=mxgraph.electrical.logic_gates.logic_gate;operation=or;"
    # 邏輯閘左側輸入 pin：2 輸入用 0.25/0.75，3+ 輸入均分 (對齊 mxgraph logic_gate)
    def _style_edge_to_gate_entry(entry_y: float) -> str:
        return (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
            "entryX=0;entryY=%.2f;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % (entry_y, STROKE_DEFAULT)
        )
    def _gate_entry_y(index: int, total: int) -> float:
        if total <= 1:
            return 0.5
        return 0.25 + (0.5 * index / max(1, total - 1))
    # 規則三：連到 H_Deb 實心綠、連到 L_Deb 虛線紅
    style_and_to_cell_hi = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_and_to_cell_lo = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;dashed=1;strokeColor=%s;" % STROKE_LO
    style_or_to_cell_hi = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_or_to_cell_lo = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;dashed=1;strokeColor=%s;" % STROKE_LO

    # 1) Input 文字標籤（僅有被依賴的 input）
    for name in used_inputs_list:
        ix, iy = positions_in[name]
        nid = cell_id
        cell_id += 1
        in_label_id[name] = nid
        cell = ET.SubElement(root, "mxCell", {
            "id": str(nid), "parent": "1", "style": style_input_label,
            "value": _escape_xml(name), "vertex": "1"
        })
        ET.SubElement(cell, "mxGeometry", {
            "height": str(INPUT_LABEL_H), "width": str(INPUT_LABEL_W), "x": str(ix), "y": str(iy),
            "as": "geometry"
        })

    # 1b) 反相 input 文字標籤 "~Name"（同左欄垂直排列，positions_in 已含其位置）
    for name in sorted(inv_input_names, key=lambda n: next(i for i, r in enumerate(config.rails) if r.name == n)):
        ix, iy = positions_in.get(name, (INPUT_COL_X, MARGIN))
        inv_in_label_id[name] = cell_id
        cell = ET.SubElement(root, "mxCell", {
            "id": str(cell_id), "parent": "1", "style": style_input_label,
            "value": "~" + _escape_xml(name), "vertex": "1"
        })
        cell_id += 1
        ET.SubElement(cell, "mxGeometry", {
            "height": str(INPUT_LABEL_H), "width": str(INPUT_LABEL_W), "x": str(ix), "y": str(iy),
            "as": "geometry"
        })

    # 2) Output 節點：Power Sequence Cell（group, edge H/L 連到左側埠, inner, H_Deb, L_Deb）+ 小圓圈 + O 連到文字（規則四）
    for r in outputs:
        px, py = positions_out.get(r.name, (cell_start_x, MARGIN))
        gid = cell_id
        inner_id = gid + 3
        name_label_id = gid + 6
        circle_id = gid + 8
        cell_id += 10
        out_group_id[r.name] = gid
        out_inner_id[r.name] = inner_id

        group = ET.SubElement(root, "mxCell", {
            "id": str(gid), "connectable": "0", "parent": "1", "style": "group", "value": "", "vertex": "1"
        })
        ET.SubElement(group, "mxGeometry", {
            "height": str(CELL_GROUP_H), "width": str(CELL_GROUP_W), "x": str(px), "y": str(py),
            "as": "geometry"
        })

        edge_h_internal = ET.SubElement(root, "mxCell", {
            "id": str(gid + 1), "edge": "1", "parent": str(gid), "source": str(inner_id),
            "style": style_edge_h_internal, "value": "H"
        })
        geo_h = ET.SubElement(edge_h_internal, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(geo_h, "mxPoint", {"y": "20.103448275862092", "as": "targetPoint"})
        geo_h.text = "\n            "
        geo_h.tail = "\n          "

        edge_l_internal = ET.SubElement(root, "mxCell", {
            "id": str(gid + 2), "edge": "1", "parent": str(gid), "source": str(inner_id),
            "style": style_edge_l_internal, "value": "L"
        })
        geo_l = ET.SubElement(edge_l_internal, "mxGeometry", {"relative": "1", "as": "geometry"})
        ET.SubElement(geo_l, "mxPoint", {"y": "60.10344827586209", "as": "targetPoint"})
        geo_l.text = "\n            "
        geo_l.tail = "\n          "

        inner = ET.SubElement(root, "mxCell", {
            "id": str(inner_id), "parent": str(gid), "style": style_inner, "value": "", "vertex": "1"
        })
        ET.SubElement(inner, "mxGeometry", {
            "height": str(CELL_INNER_H), "width": str(CELL_INNER_W), "x": str(CELL_INNER_X),
            "as": "geometry"
        })

        h_deb = ET.SubElement(root, "mxCell", {
            "id": str(gid + 4), "parent": str(gid), "style": style_deb, "value": "H_Deb", "vertex": "1"
        })
        ET.SubElement(h_deb, "mxGeometry", {
            "height": str(CELL_H_DEB_H), "width": str(CELL_H_DEB_W), "x": str(CELL_INNER_X), "y": str(CELL_H_DEB_Y),
            "as": "geometry"
        })

        l_deb = ET.SubElement(root, "mxCell", {
            "id": str(gid + 5), "parent": str(gid), "style": style_deb, "value": "L_Deb", "vertex": "1"
        })
        ET.SubElement(l_deb, "mxGeometry", {
            "height": str(CELL_L_DEB_H), "width": str(CELL_L_DEB_W), "x": str(CELL_INNER_X), "y": str(CELL_L_DEB_Y),
            "as": "geometry"
        })

        name_label = ET.SubElement(root, "mxCell", {
            "id": str(name_label_id), "parent": "1", "style": style_output_name,
            "value": _escape_xml(r.name), "vertex": "1"
        })
        ET.SubElement(name_label, "mxGeometry", {
            "height": str(INPUT_LABEL_H), "width": str(INPUT_LABEL_W),
            "x": str(_align40(px + output_name_offset_x)), "y": str(_align10(py + OUTPUT_NAME_OFFSET_Y)),
            "as": "geometry"
        })

        # 規則四：匯合點到輸出訊號之間的小圓圈符號（橢圓 8pt，固定長寬比）
        inner_right_x = px + CELL_INNER_X + CELL_INNER_W
        name_left_x = px + output_name_offset_x
        mid_x = (inner_right_x + name_left_x) // 2
        center_y = py + CELL_GROUP_H // 2
        circle_x = mid_x - OUTPUT_CIRCLE_SIZE // 2
        circle_y = center_y - OUTPUT_CIRCLE_SIZE // 2
        style_circle = "ellipse;whiteSpace=wrap;html=1;aspect=fixed;fillColor=%s;strokeColor=%s;" % (STROKE_DEFAULT, STROKE_DEFAULT)
        circle_cell = ET.SubElement(root, "mxCell", {
            "id": str(circle_id), "parent": "1", "style": style_circle, "value": "", "vertex": "1"
        })
        ET.SubElement(circle_cell, "mxGeometry", {
            "width": str(OUTPUT_CIRCLE_SIZE), "height": str(OUTPUT_CIRCLE_SIZE),
            "x": str(circle_x), "y": str(circle_y), "as": "geometry"
        })

        # 規則四：O 線 inner → 小圓圈 → 輸出名稱，兩段皆正交、水平
        edge_o_to_circle = ET.SubElement(root, "mxCell", {
            "id": str(gid + 7), "edge": "1", "parent": "1", "source": str(inner_id), "target": str(circle_id),
            "style": style_edge_o_to_name, "value": "O"
        })
        ET.SubElement(edge_o_to_circle, "mxGeometry", {"relative": "1", "as": "geometry"})
        edge_circle_to_name = ET.SubElement(root, "mxCell", {
            "id": str(gid + 9), "edge": "1", "parent": "1", "source": str(circle_id), "target": str(name_label_id),
            "style": style_edge_o_to_name, "value": ""
        })
        ET.SubElement(edge_circle_to_name, "mxGeometry", {"relative": "1", "as": "geometry"})

    # 2b) 反相 output 文字標籤 "~Name"：與 SIG_1、~SIG_4 同一垂直線（INPUT_COL_X），接在輸入下方
    inv_out_y: dict[str, int] = {}
    inv_out_order = sorted(inv_output_names, key=lambda n: next(i for i, r in enumerate(config.rails) if r.name == n))
    for i, name in enumerate(inv_out_order):
        inv_out_label_id[name] = cell_id
        ox = INPUT_COL_X
        oy = _align10(MARGIN + len(all_input_names) * INPUT_VERTICAL_DY + i * INPUT_VERTICAL_DY)
        inv_out_y[name] = oy
        cell = ET.SubElement(root, "mxCell", {
            "id": str(cell_id), "parent": "1", "style": style_input_label,
            "value": "~" + _escape_xml(name), "vertex": "1"
        })
        cell_id += 1
        ET.SubElement(cell, "mxGeometry", {
            "height": str(INPUT_LABEL_H), "width": str(INPUT_LABEL_W),
            "x": str(ox), "y": str(oy), "as": "geometry"
        })

    # 每個 cell id 的垂直中心 y（用於 AND/OR 依垂直位置接 input pin，減少走線交叉）
    id_to_y_center: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_y_center[nid] = positions_in[name][1] + INPUT_LABEL_H // 2
    for name, nid in inv_in_label_id.items():
        id_to_y_center[nid] = positions_in[name][1] + INPUT_LABEL_H // 2
    for name, nid in inv_out_label_id.items():
        id_to_y_center[nid] = inv_out_y[name] + INPUT_LABEL_H // 2
    for name, nid in out_inner_id.items():
        id_to_y_center[nid] = positions_out[name][1] + CELL_GROUP_H // 2

    # 每個 label id 所屬的 row（僅在「不同 row」時加 waypoints，與 debug_golden 一致）
    id_to_row: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_row[nid] = output_to_row.get(input_first_output.get(name, ""), 0)
    for name, nid in inv_in_label_id.items():
        id_to_row[nid] = output_to_row.get(input_first_output.get(name, ""), 0)
    for name, nid in inv_out_label_id.items():
        id_to_row[nid] = output_to_row.get(name, 0)
    inner_id_to_row: dict[int, int] = {out_inner_id[name]: output_to_row[name] for name in output_to_row}
    inner_id_to_output: dict[int, str] = {v: k for k, v in out_inner_id.items()}

    and_idx_by_rail: dict[str, int] = {}
    and_gate_y: dict[int, int] = {}  # AND gate id -> y 中心，供排序用

    # 3) 依賴邊：依 group 繪製；單一訊號直連 H/L，兩訊號以上經 AND 閘。規則五：走線經 waypoint 繞開元件、不重疊；Hi 綠、Lo 虛線紅。
    style_hi_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_lo_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;dashed=1;strokeColor=%s;" % STROKE_LO

    def _source_id(d: str, inv: bool, is_hi: bool) -> int | None:
        """依賴來源的 cell id。輸出節點用 inner id，使線起點與 O 線相同（exitX=1, exitY=0.5）。"""
        if name_to_rail[d].seq_type == "input":
            return (inv_in_label_id if inv else in_label_id).get(d)
        if inv:
            return inv_out_label_id.get(d)
        return out_inner_id.get(d)  # 輸出→他節點：用 inner，與 O 線起點相同

    for r in outputs:
        to_gid = out_group_id.get(r.name)
        to_inner = out_inner_id.get(r.name)
        if to_gid is None:
            continue

        hi_groups = r.get_hi_groups()
        if len(hi_groups) >= 2:
            group_outputs_hi: list[int] = []
            for gi, group in enumerate(hi_groups):
                if not group:
                    continue
                inv_list = [r.depends_on_hi_inv.get(d, False) for d in group]
                if len(group) == 1:
                    d = group[0]
                    if d in valid and d not in CONST_DEPS:
                        from_id = _source_id(d, inv_list[0], True)
                        if from_id is not None:
                            group_outputs_hi.append(from_id)
                else:
                    key_hi = (r.name, "hi", gi)
                    if key_hi not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_hi] = aid
                        idx = and_idx_by_rail.get(r.name, 0)
                        and_idx_by_rail[r.name] = idx + 1
                        _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": style_and_gate, "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + and_gate_offset_x), "y": str(_py + idx * AND_GATE_DY),
                            "as": "geometry"
                        })
                        _ay = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                    # 依來源垂直位置排序，由上而下接 AND 的 input pin，減少走線交叉
                    and_srcs = []
                    for i, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        from_id = _source_id(d, inv_list[i], True)
                        if from_id is not None:
                            and_srcs.append((from_id, d, inv_list[i]))
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)))
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_hi])})
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _add_edge_points(geo, [(channel_x_left, lab_y), (channel_x_left, gy)], align=[False, True])
                        else:
                            # inner→AND：依 golden 原則，矩形走線 (cell_right, cy)→(cell_right, turn_y)→(and_col_x, turn_y)→(and_col_x, and_y)
                            out_name = inner_id_to_output.get(from_id)
                            if out_name:
                                cell_x, cell_y = positions_out.get(out_name, (0, 0))
                                cell_right_x = cell_x + CELL_INNER_X + CELL_INNER_W
                                cy = cell_y + CELL_GROUP_H // 2
                                and_y = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                turn_y = _align40((cy + and_y) // 2)
                                _add_edge_points(geo, [(cell_right_x, cy), (cell_right_x, turn_y), (and_col_x, turn_y), (and_col_x, and_y)], align=[False, True, True, True])
                        geo.text = "\n            "
                    group_outputs_hi.append(and_gate_id[key_hi])
            if group_outputs_hi:
                or_id = cell_id
                cell_id += 1
                _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                _oy = _py + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2
                id_to_y_center[or_id] = _oy
                or_cell = ET.SubElement(root, "mxCell", {
                    "id": str(or_id), "parent": "1", "style": style_or_gate, "value": "", "vertex": "1"
                })
                ET.SubElement(or_cell, "mxGeometry", {
                    "height": str(OR_GATE_H), "width": str(OR_GATE_W),
                    "x": str(_px + or_gate_offset_x), "y": str(_py + OR_GATE_OFFSET_HI_Y),
                    "as": "geometry"
                })
                sorted_hi = sorted(group_outputs_hi, key=lambda sid: id_to_y_center.get(sid, 0))
                and_ids_hi = {and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "hi"}
                for idx, src_id in enumerate(sorted_hi):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_hi)))
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _oy = _py + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2
                    if src_id in and_ids_hi:
                        # AND→OR：依 golden 原則，同列無 waypoints，直接水平
                        pass
                    elif src_id in id_to_row:
                        # 輸入→OR：依 golden 原則，無 waypoints，由 Draw.io 自動路由
                        pass
                    else:
                        src_row = inner_id_to_row.get(src_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            if src_row < tgt_row:
                                # 來源在上方：先右再下，避免「先上再下」的曲折
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (channel_x_right, id_to_y_center[src_id]), (channel_x_right, _oy)], align=[False, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, _oy)], align=[False, True, True])
                        else:
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, _oy)], align=[False, True])
                    geo.text = "\n            "
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_hi, "edge": "1", "parent": "1", "source": str(or_id), "target": str(to_gid + 4)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                geo.text = "\n            "
        else:
            for gi, group in enumerate(hi_groups):
                if not group:
                    continue
                inv_list = [r.depends_on_hi_inv.get(d, False) for d in group]
                if len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    from_id = _source_id(d, inv_list[0], True)
                    if from_id is None:
                        continue
                    _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                    if name_to_rail[d].seq_type == "input":
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_edge_h_to_label, "edge": "1", "parent": "1", "source": str(to_inner), "target": str(from_id)})
                    else:
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_hi_to_cell, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_gid + 4)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if name_to_rail[d].seq_type == "input":
                        label_pos = positions_in.get(d)
                        if label_pos:
                            _add_edge_waypoint(geo, positions_out[r.name], label_pos, waypoint_x=channel_x_left, gate_right_x=or_col_x + OR_GATE_W, row_py=_py)
                    else:
                        deb_y = _py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
                        src_row = inner_id_to_row.get(from_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (channel_x_right, id_to_y_center.get(from_id, _py + 40)), (channel_x_right, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
                        else:
                            above_y = _align40(_py - GRID)
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (or_col_x + OR_GATE_W, above_y), (or_col_x + OR_GATE_W, deb_y)], align=[False, True, True])
                    geo.text = "\n            "
                else:
                    key_hi = (r.name, "hi", gi)
                    if key_hi not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_hi] = aid
                        idx = and_idx_by_rail.get(r.name, 0)
                        and_idx_by_rail[r.name] = idx + 1
                        _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": style_and_gate, "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + and_gate_offset_x), "y": str(_py + idx * AND_GATE_DY),
                            "as": "geometry"
                        })
                        _ay = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                    and_id = and_gate_id[key_hi]
                    and_srcs = [( _source_id(d, inv_list[i], True), d) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], True) is not None]
                    and_srcs = [(fid, d) for (fid, d) in and_srcs if fid is not None]
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)))
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _add_edge_points(geo, [(channel_x_left, lab_y), (channel_x_left, gy)], align=[False, True])
                        else:
                            out_name = inner_id_to_output.get(from_id)
                            if out_name:
                                cell_x, cell_y = positions_out.get(out_name, (0, 0))
                                cell_right_x = cell_x + CELL_INNER_X + CELL_INNER_W
                                cy = cell_y + CELL_GROUP_H // 2
                                and_y = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                turn_y = _align40((cy + and_y) // 2)
                                _add_edge_points(geo, [(cell_right_x, cy), (cell_right_x, turn_y), (and_col_x, turn_y), (and_col_x, and_y)], align=[False, True, True, True])
                        geo.text = "\n            "
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_hi, "edge": "1", "parent": "1", "source": str(and_id), "target": str(to_gid + 4)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    geo.text = "\n            "

        lo_groups = r.get_lo_groups()
        if len(lo_groups) >= 2:
            group_outputs_lo: list[int] = []
            for gi, group in enumerate(lo_groups):
                if not group:
                    continue
                inv_list = [r.depends_on_lo_inv.get(d, False) for d in group]
                if len(group) == 1:
                    d = group[0]
                    if d in valid and d not in CONST_DEPS:
                        from_id = _source_id(d, inv_list[0], False)
                        if from_id is not None:
                            group_outputs_lo.append(from_id)
                else:
                    key_lo = (r.name, "lo", gi)
                    if key_lo not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_lo] = aid
                        idx = and_idx_by_rail.get(r.name, 0)
                        and_idx_by_rail[r.name] = idx + 1
                        _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": style_and_gate, "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + and_gate_offset_x), "y": str(_py + idx * AND_GATE_DY),
                            "as": "geometry"
                        })
                        _ay = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                    and_srcs_lo = []
                    for i, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        from_id = _source_id(d, inv_list[i], False)
                        if from_id is not None:
                            and_srcs_lo.append((from_id, d, inv_list[i]))
                    and_srcs_lo.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv) in enumerate(and_srcs_lo):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo)))
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_lo])})
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _add_edge_points(geo, [(channel_x_left, lab_y), (channel_x_left, gy)], align=[False, True])
                        else:
                            out_name = inner_id_to_output.get(from_id)
                            if out_name:
                                cell_x, cell_y = positions_out.get(out_name, (0, 0))
                                cell_right_x = cell_x + CELL_INNER_X + CELL_INNER_W
                                cy = cell_y + CELL_GROUP_H // 2
                                and_y = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                turn_y = _align40((cy + and_y) // 2)
                                _add_edge_points(geo, [(cell_right_x, cy), (cell_right_x, turn_y), (and_col_x, turn_y), (and_col_x, and_y)], align=[False, True, True, True])
                        geo.text = "\n            "
                    group_outputs_lo.append(and_gate_id[key_lo])
            if group_outputs_lo:
                or_id = cell_id
                cell_id += 1
                _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                _oy = _py + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2
                id_to_y_center[or_id] = _oy
                or_cell = ET.SubElement(root, "mxCell", {
                    "id": str(or_id), "parent": "1", "style": style_or_gate, "value": "", "vertex": "1"
                })
                ET.SubElement(or_cell, "mxGeometry", {
                    "height": str(OR_GATE_H), "width": str(OR_GATE_W),
                    "x": str(_px + or_gate_offset_x), "y": str(_py + OR_GATE_OFFSET_LO_Y),
                    "as": "geometry"
                })
                sorted_lo = sorted(group_outputs_lo, key=lambda sid: id_to_y_center.get(sid, 0))
                and_ids_lo = {and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "lo"}
                for idx, src_id in enumerate(sorted_lo):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_lo)))
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _oy = _py + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2
                    if src_id in and_ids_lo:
                        # AND→OR：依 golden 原則，同列無 waypoints
                        pass
                    elif src_id in id_to_row:
                        # 輸入→OR：依 golden 原則，無 waypoints，由 Draw.io 自動路由
                        pass
                    else:
                        src_row = inner_id_to_row.get(src_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (channel_x_right, id_to_y_center[src_id]), (channel_x_right, _oy)], align=[False, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, _oy)], align=[False, True, True])
                        else:
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, _oy)], align=[False, True])
                    geo.text = "\n            "
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_lo, "edge": "1", "parent": "1", "source": str(or_id), "target": str(to_gid + 5)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                geo.text = "\n            "
        else:
            for gi, group in enumerate(lo_groups):
                if not group:
                    continue
                inv_list = [r.depends_on_lo_inv.get(d, False) for d in group]
                if len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    from_id = _source_id(d, inv_list[0], False)
                    if from_id is None:
                        continue
                    _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                    if name_to_rail[d].seq_type == "input":
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_edge_l_to_label, "edge": "1", "parent": "1", "source": str(to_inner), "target": str(from_id)})
                    else:
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_lo_to_cell, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_gid + 5)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if name_to_rail[d].seq_type == "input":
                        label_pos = positions_in.get(d)
                        if label_pos:
                            _add_edge_waypoint(geo, positions_out[r.name], label_pos, waypoint_x=channel_x_left, gate_right_x=or_col_x + OR_GATE_W, row_py=_py)
                    else:
                        deb_y = _py + CELL_L_DEB_Y + CELL_L_DEB_H // 2
                        src_row = inner_id_to_row.get(from_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (channel_x_right, id_to_y_center.get(from_id, _py + 40)), (channel_x_right, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
                        else:
                            above_y = _align40(_py - GRID)
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (or_col_x + OR_GATE_W, above_y), (or_col_x + OR_GATE_W, deb_y)], align=[False, True, True])
                    geo.text = "\n            "
                else:
                    key_lo = (r.name, "lo", gi)
                    if key_lo not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_lo] = aid
                        idx = and_idx_by_rail.get(r.name, 0)
                        and_idx_by_rail[r.name] = idx + 1
                        _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": style_and_gate, "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + and_gate_offset_x), "y": str(_py + idx * AND_GATE_DY),
                            "as": "geometry"
                        })
                        _ay = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                    and_id = and_gate_id[key_lo]
                    and_srcs_lo2 = [( _source_id(d, inv_list[i], False), d) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], False) is not None]
                    and_srcs_lo2 = [(fid, d) for (fid, d) in and_srcs_lo2 if fid is not None]
                    and_srcs_lo2.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d) in enumerate(and_srcs_lo2):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo2)))
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _add_edge_points(geo, [(channel_x_left, lab_y), (channel_x_left, gy)], align=[False, True])
                        else:
                            out_name = inner_id_to_output.get(from_id)
                            if out_name:
                                cell_x, cell_y = positions_out.get(out_name, (0, 0))
                                cell_right_x = cell_x + CELL_INNER_X + CELL_INNER_W
                                cy = cell_y + CELL_GROUP_H // 2
                                and_y = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                turn_y = _align40((cy + and_y) // 2)
                                _add_edge_points(geo, [(cell_right_x, cy), (cell_right_x, turn_y), (and_col_x, turn_y), (and_col_x, and_y)], align=[False, True, True, True])
                        geo.text = "\n            "
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_lo, "edge": "1", "parent": "1", "source": str(and_id), "target": str(to_gid + 5)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    geo.text = "\n            "

    rough = ET.tostring(mxfile, encoding="unicode", default_namespace="")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
