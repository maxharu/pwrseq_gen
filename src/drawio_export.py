"""
Export Power Sequence dependency as Draw.io XML.

版面與樣式依專案內 DRAWIO_RULES.md 實作，摘要如下：
- 規則一（輸入）：最左側正向命名；反相一律用共用 NOT 閘呈現；每條輸入線垂直對齊其第一個連接的閘輸入端。
- 規則二（邏輯閘）：AND 在左、OR 在右、NOT 共用（input NOT 緊鄰 input label 下方；output NOT 在 logic_not_col_x）。
- 規則三（PSEQCELL）：4 個獨立 cells（inner + H_Deb + L_Deb + O 矩形），無 group；連到 H_Deb 實心綠、連到 L_Deb 虛線紅。
- 規則四（輸出）：直接從 O 矩形右側拉一條水平邊到輸出名稱文字框，無小圓圈、無轉角。
- 規則五（連接線）：預設黑、Hi 綠、Lo 虛線紅；正交、少交叉；不穿越元件、繞開元件；走線不重疊；waypoint 處與輸入同高可不對齊 40pt。
- 規則六：走線間不重疊、箭頭與分岔清楚；常數見 DRAWIO_RULES.md。
"""
import random
import string
import xml.etree.ElementTree as ET
from xml.dom import minidom

from config_models import PowerSeqConfig, PowerRail
from layout_engine import minimize_crossings

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"
CONST_DEPS = {DEP_HIGH, DEP_LOW}

# Power Sequence Cell 尺寸（依 PSEQCELL.xml 範本：無 group，4 個獨立 cells，O 矩形內嵌 inner 右側）
CELL_GROUP_W = 80   # cell 整體視覺寬度（= inner 寬，無額外右側空間）
CELL_GROUP_H = 80
CELL_INNER_X = 0    # inner 相對 cell 原點的 x（過去用 group 時為 40）
CELL_INNER_W = 80
CELL_INNER_H = 80
CELL_H_DEB_W = 50
CELL_H_DEB_H = 20
CELL_L_DEB_W = 50
CELL_L_DEB_H = 20
CELL_H_DEB_Y = 10
CELL_L_DEB_Y = 50
CELL_O_W = 20
CELL_O_H = 20
CELL_O_X = 60       # O 矩形貼 inner 右側內部
CELL_O_Y = 30
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
# 輸出名稱 y 與 cell 垂直置中對齊，使 O 矩形→名稱為水平直線、無轉角
OUTPUT_NAME_OFFSET_Y = (CELL_GROUP_H - INPUT_LABEL_H) // 2
# 連接線顏色：Hi 實心綠、Lo 虛線紅、預設實心黑
STROKE_HI = "#059669"
STROKE_LO = "#dc2626"
STROKE_DEFAULT = "#000000"
AND_GATE_W = 80
AND_GATE_H = 40
OR_GATE_W = 80
OR_GATE_H = 40
NOT_GATE_W = 40
NOT_GATE_H = 20
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


def _barycenter_order_outputs(
    outputs: list[PowerRail],
    name_to_rail: dict,
    valid: set[str],
) -> list[PowerRail]:
    """拓撲排序 + 重心法微調：依賴關係緊密的 output 盡量相鄰，減少跨行走線交叉。

    1. 先做拓撲排序，確保被依賴者在前。
    2. 對每個 output 計算「重心」= 其所有 output 類型依賴在拓撲序中的平均位置。
    3. 在不違反拓撲約束的前提下，按重心由小到大排序。
    4. 迭代多次收斂（經典 Sugiyama 重心啟發式）。
    """
    topo = _topological_order_outputs(outputs, name_to_rail)
    if len(topo) <= 2:
        return topo

    out_names = {r.name for r in topo}
    name_to_idx: dict[str, int] = {r.name: i for i, r in enumerate(topo)}

    def _deps_of(r: PowerRail) -> list[str]:
        return [
            d for d in r.get_depends_on_hi_flat() + r.get_depends_on_lo_flat()
            if d not in CONST_DEPS and d in valid and d in out_names
        ]

    order = list(topo)
    for _ in range(4):
        pos = {r.name: i for i, r in enumerate(order)}
        bary: dict[str, float] = {}
        for r in order:
            deps = _deps_of(r)
            if deps:
                bary[r.name] = sum(pos[d] for d in deps) / len(deps)
            else:
                bary[r.name] = float(pos[r.name])

        new_order = sorted(order, key=lambda r: bary[r.name])

        topo_pos = {r.name: i for i, r in enumerate(new_order)}
        violated = False
        for r in new_order:
            for d in _deps_of(r):
                if topo_pos[d] > topo_pos[r.name]:
                    violated = True
                    break
            if violated:
                break
        if violated:
            break
        if [r.name for r in new_order] == [r.name for r in order]:
            break
        order = new_order

    return order


# 走線通道 x（規則五／六：線經通道轉向、繞開元件、避免交叉與線段重疊；generate_drawio 內依 and_col_x 重算 channel_x_left）
CHANNEL_X_LEFT = (INPUT_COL_X + INPUT_LABEL_W + GATE_COL_X) // 2
CHANNEL_X_RIGHT = (GATE_COL_X + AND_GATE_W + CELL_START_X) // 2


class _ChannelAllocator:
    """為垂直走線分配不重疊的 x 通道。

    每條走線以 (y_min, y_max) 表示其垂直佔用範圍。y 範圍重疊的走線
    會被分配到不同的 x 通道（間隔 GRID pt），y 範圍不重疊的可共用同一通道。
    """

    def __init__(self, base_x: int, step: int = GRID):
        self._base_x = base_x
        self._step = step
        self._channels: list[list[tuple[float, float]]] = []

    def allocate(self, y_min: float, y_max: float) -> int:
        """分配一個 x 通道給 y 範圍 [y_min, y_max]，回傳 x 座標。"""
        if y_min > y_max:
            y_min, y_max = y_max, y_min
        for i, spans in enumerate(self._channels):
            if all(y_max <= s[0] or y_min >= s[1] for s in spans):
                spans.append((y_min, y_max))
                return self._base_x + i * self._step
        self._channels.append([(y_min, y_max)])
        return self._base_x + (len(self._channels) - 1) * self._step

    @property
    def width(self) -> int:
        """已使用的通道總寬度。"""
        if not self._channels:
            return 0
        return (len(self._channels) - 1) * self._step


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
    Generate Draw.io XML per PSEQCELL.xml:
    - Only output rails become nodes (Power Sequence Cell: 4 個獨立 cells — inner + H_Deb + L_Deb + O 矩形，無 group）。
    - Input rails are text labels only; 反相一律用共用 NOT 閘呈現（非舊版 ~Name 文字）。

    版面預設啟用拓撲排序 + 重心法列排序與走線交叉最小化，使依賴關係緊密的 output 相鄰、走線交叉最少。
    """
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail.keys())
    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs_raw = [r for r in config.rails if r.seq_type == "output"]
    outputs = _barycenter_order_outputs(outputs_raw, name_to_rail, valid)

    # 偵測是否有 inv=True（任何反相皆用共用 NOT 閘，佔用 AND 欄左側空間）
    _has_not_gate = False
    _has_input_not = False  # 有 input 訊號被反相 → 需要 input NOT 欄
    _has_logic_not = False  # 有 output 訊號被反相 → 需要 logic NOT 欄（在 AND 左側）
    for r in outputs:
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            for gi, g in enumerate(groups):
                for ii, d in enumerate(g):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    inv = r.get_hi_inv(gi, ii, d) if hl == "hi" else r.get_lo_inv(gi, ii, d)
                    if not inv:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        _has_input_not = True
                    else:
                        _has_logic_not = True
    _has_not_gate = _has_input_not or _has_logic_not

    # 規則二：層級間距 80pt（GAP）。閘↔Cell 固定 80pt；input↔gate 與 cell↔name 之
    # 通道寬度由「實際走線」決定（_ChannelAllocator 會將 y 範圍不重疊的走線共用同 x），
    # 因此先 dry-run channel allocation 量出真實寬度，再算各欄位 x。
    gap_gc = _align40(GAP)
    input_right = INPUT_COL_X + INPUT_LABEL_W

    # 動態行高：每行高度依該 output 左側 AND/OR 數量預留，對齊 40pt、行間距 GAP
    row_heights: list[int] = [_align40(_row_height_for_output(r)) for r in outputs]
    row_y_base: list[int] = []
    acc = MARGIN
    for h in row_heights:
        row_y_base.append(_align40(acc))
        acc += h + GAP

    output_to_row: dict[str, int] = {r.name: j for j, r in enumerate(outputs)}

    # 僅建立「有被使用」的 input 標籤（無論是否反相皆為單一正向標籤），並記錄第一個使用者
    used_inputs_set: set[str] = set()
    input_first_output: dict[str, str] = {}  # input name -> 第一個使用它的 output name（依拓撲序）
    for r in outputs:
        for d in r.get_depends_on_hi_flat() + r.get_depends_on_lo_flat():
            if d not in valid or d in CONST_DEPS:
                continue
            if name_to_rail[d].seq_type == "input":
                if d not in input_first_output:
                    input_first_output[d] = r.name
                used_inputs_set.add(d)
    _input_order = lambda n: next(i for i, r in enumerate(config.rails) if r.name == n)
    used_inputs_list = sorted(used_inputs_set, key=_input_order)
    all_input_names = list(used_inputs_list)

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
        """AND 閘左側第 pin_index 個輸入 pin 的 y。
        只有兩個物理 pin (0.25/0.75)：前半輸入接 0.25，後半接 0.75（與 _gate_entry_y 一致）。"""
        if total_pins <= 1:
            entry_rel = 0.5
        else:
            entry_rel = 0.25 if pin_index < (total_pins + 1) // 2 else 0.75
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

    # 去重疊：當多個 input 對齊同一個閘輸入端（例如一個 8-input AND 只有
    # 兩個實體 pin，前/後半各自共用同一 y），標籤會疊在一起。依偏好 y 由上而下
    # 貪婪錯開，確保同欄標籤間至少留 INPUT_LABEL_GAP；邊以 cell id 連接，
    # 標籤略微離開 pin 高度只會讓走線多一個轉角，不影響連線正確性（規則五允許）。
    INPUT_LABEL_GAP = 10
    _step = INPUT_LABEL_H + INPUT_LABEL_GAP
    _ordered = sorted(all_input_names, key=lambda n: (positions_in[n][1], _input_order(n)))
    _prev_bottom: int | None = None
    for name in _ordered:
        x, y = positions_in[name]
        if _prev_bottom is not None and y < _prev_bottom:
            y = _prev_bottom
        positions_in[name] = (x, y)
        _prev_bottom = y + _step

    # --- Channel Assignment (Phase B) ---
    # 為左側通道（input→gate）和右側通道（跨行 output→gate）分配不重疊的 x。
    # _ChannelAllocator 對 y 範圍不重疊的走線共用同 x，實際通道數遠少於走線數，
    # 因此先 dry-run 量出真實寬度，再決定欄位 x；最後再正式以真實 base_x 分配。

    def _walk_wires():
        """yield ("left"|"right", wkey, y_min, y_max) for each wire that needs a channel."""
        for j, r in enumerate(outputs):
            _py = row_y_base[j]
            hi_groups = r.get_hi_groups()
            lo_groups = r.get_lo_groups()
            for hl, groups in [("hi", hi_groups), ("lo", lo_groups)]:
                for gi, group in enumerate(groups):
                    for ii, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if not lab:
                                continue
                            lab_y = lab[1] + INPUT_LABEL_H // 2
                            key_and = and_index_per_key.get((r.name, hl, gi))
                            if key_and and len(group) >= 2:
                                gy = _and_gate_center_y(key_and[0], key_and[1])
                            elif hl == "hi":
                                gy = _py + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2
                            else:
                                gy = _py + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2
                            yield "left", (d, r.name, hl, gi), min(lab_y, gy), max(lab_y, gy)
                        else:
                            src_row = output_to_row.get(d)
                            if src_row is None or src_row == j:
                                continue
                            src_cy = row_y_base[src_row] + CELL_GROUP_H // 2
                            if hl == "hi":
                                tgt_y = _py + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2
                            else:
                                tgt_y = _py + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2
                            yield "right", (d, r.name, hl, gi), min(src_cy, tgt_y), max(src_cy, tgt_y)

    # Dry-run：用 base_x=0 跑一遍，僅為量寬度；分配結果丟棄
    _dry_left = _ChannelAllocator(0, step=GRID)
    _dry_right = _ChannelAllocator(0, step=GRID)
    for side, _wk, y0, y1 in _walk_wires():
        (_dry_left if side == "left" else _dry_right).allocate(y0, y1)

    # 用實際通道寬度算欄位 x。版面從左到右：
    #   input | GAP | [input_NOT | GAP] | [logic_NOT | GAP] | channel_left | GAP | AND | GAP | OR | GAP | cell | channel_right | GAP | name
    # NOT 欄與 channel 區明確分開，避免垂直走線穿越 NOT 閘 vertex。
    left_channel_w = _dry_left.width  # = (n_channels - 1) * GRID
    right_channel_w = _dry_right.width

    _not_cols_right = input_right + GAP
    if _has_input_not:
        _not_cols_right += NOT_GATE_W + GAP
    if _has_logic_not:
        _not_cols_right += NOT_GATE_W + GAP
    channel_x_left = _align40(_not_cols_right)
    and_col_x = _align40(channel_x_left + left_channel_w + GAP)
    or_col_x = and_col_x + AND_GATE_W + GAP
    gate_col_x = or_col_x
    cell_start_x = or_col_x + OR_GATE_W + gap_gc
    gap_ig = gate_col_x - input_right  # 報告用；非實際決策變數

    # cell→name 之間擺 channel_right + GAP 緩衝
    cell_right = cell_start_x + CELL_GROUP_W
    channel_x_right = _align40(cell_right + GAP)
    output_name_offset_x = CELL_GROUP_W + GAP + right_channel_w + GAP
    gap_co = output_name_offset_x - CELL_GROUP_W  # 報告用

    or_gate_offset_x = or_col_x - cell_start_x
    and_gate_offset_x = and_col_x - cell_start_x

    positions_out: dict[str, tuple[int, int]] = {
        r.name: (cell_start_x, _align40(row_y_base[j])) for j, r in enumerate(outputs)
    }

    # 正式 channel allocation（用真實 base_x）
    ch_left = _ChannelAllocator(channel_x_left, step=GRID)
    ch_right = _ChannelAllocator(channel_x_right, step=GRID)
    wire_channel_left: dict[tuple, int] = {}
    wire_channel_right: dict[tuple, int] = {}
    for side, wk, y0, y1 in _walk_wires():
        if side == "left":
            wire_channel_left[wk] = ch_left.allocate(y0, y1)
        else:
            wire_channel_right[wk] = ch_right.allocate(y0, y1)

    def _ch_left_x(dep_name: str, rail_name: str, hl: str, gi: int) -> int:
        return wire_channel_left.get((dep_name, rail_name, hl, gi), channel_x_left)

    def _ch_right_x(dep_name: str, rail_name: str, hl: str, gi: int) -> int:
        return wire_channel_right.get((dep_name, rail_name, hl, gi), channel_x_right)

    # 記錄每個 rail 的 Hi/Lo 邏輯輸出 cell id（AND/OR 閘或直連來源），
    # 供 use_mode="hi"/"lo" 時作為出發點（而非 H_Deb/L_Deb 本身）。
    # 邊生成迴圈依拓撲序處理，確保被依賴者的 ID 在被引用前已記錄。
    hi_logic_out_id: dict[str, int] = {}
    lo_logic_out_id: dict[str, int] = {}

    cell_id = 2
    out_inner_id: dict[str, int] = {}
    h_deb_id_map: dict[str, int] = {}
    l_deb_id_map: dict[str, int] = {}
    o_box_id_map: dict[str, int] = {}
    in_label_id: dict[str, int] = {}
    # (rail_name, "hi"|"lo", group_index) -> AND gate cell id（僅當該 group 有 2+ 訊號時）
    and_gate_id: dict[tuple[str, str, int], int] = {}
    # 共用 NOT 閘：key = (來源 d, use_mode)，value = NOT 閘 cell id
    not_gate_id: dict[tuple[str, str], int] = {}
    # 記錄所有 inv=True 的邊：edge id (str) -> (來源 d, use_mode)；
    # post-fix 會為每個唯一 (d, use_mode) 建立一顆共用 NOT 閘，並把這些邊 source 替換為 NOT 閘 id。
    _inv_edges: dict[str, tuple[str, str]] = {}

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

    style_inner = "rounded=0;whiteSpace=wrap;html=1;"
    style_deb = "rounded=1;whiteSpace=wrap;html=1;"
    style_input_label = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=right;verticalAlign=middle;rounded=0;"
    style_output_name = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;rounded=0;"
    style_edge_o_to_name = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % STROKE_DEFAULT
    # cell→input 反向標示邊：箭頭在 source(cell) 端表示「cell 取訊號」；
    # 強制 entryX=1, entryY=0.5 讓 target 端固定連 input label 右邊中央（避免 Draw.io 自動連到左邊）。
    style_edge_h_to_label = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.25;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_edge_l_to_label = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.75;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;startArrow=classic;startFill=1;endArrow=none;endFill=0;strokeColor=%s;" % STROKE_DEFAULT
    style_and_gate = "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;verticalAlign=top;shape=mxgraph.electrical.logic_gates.logic_gate;operation=and;"
    style_or_gate = "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;verticalAlign=top;shape=mxgraph.electrical.logic_gates.logic_gate;operation=or;"
    # 邏輯閘左側輸入 pin：2 輸入用 0.25/0.75，3+ 輸入均分 (對齊 mxgraph logic_gate)
    # exit_left 應只在 source 是 output cell（取 H_Deb/L_Deb 訊號）時使用；
    # source 是 input label 時 input 沒有 H/L 概念，一律從右邊出（exitX=1）。
    def _style_edge_to_gate_entry(entry_y: float, source_id: int, use_mode: str | None) -> str:
        is_input_src = source_id in set(in_label_id.values())
        exit_left = (use_mode in ("hi", "lo")) and not is_input_src
        ex = 0 if exit_left else 1
        return (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=%d;exitY=0.5;exitDx=0;exitDy=0;"
            "entryX=0;entryY=%.2f;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % (ex, entry_y, STROKE_DEFAULT)
        )
    def _gate_entry_y(index: int, total: int) -> float:
        """AND/OR 閘只畫兩個輸入 pin (0.25/0.75)。多輸入時平均分配到這兩個 pin：
        前半（含中位）接上 pin (0.25)，後半接下 pin (0.75)。"""
        if total <= 1:
            return 0.5
        return 0.25 if index < (total + 1) // 2 else 0.75
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

    # 2) Output 節點：依 PSEQCELL.xml 範本，4 個獨立 cells（無 group、無 H/L edge 標籤）
    #    + 1 個 O 矩形（內嵌 inner 右側）+ name label + 一條 O→name label edge
    style_o_box = "rounded=1;whiteSpace=wrap;html=1;"
    for r in outputs:
        px, py = positions_out.get(r.name, (cell_start_x, MARGIN))
        inner_id = cell_id; cell_id += 1
        h_deb_id = cell_id; cell_id += 1
        l_deb_id = cell_id; cell_id += 1
        o_box_id = cell_id; cell_id += 1
        name_label_id = cell_id; cell_id += 1
        edge_o_to_name_id = cell_id; cell_id += 1
        out_inner_id[r.name] = inner_id
        h_deb_id_map[r.name] = h_deb_id
        l_deb_id_map[r.name] = l_deb_id
        o_box_id_map[r.name] = o_box_id

        # 先放 inner（底層），再放 H_Deb/L_Deb/O（上層），確保 z-order
        inner = ET.SubElement(root, "mxCell", {
            "id": str(inner_id), "parent": "1", "style": style_inner, "value": "", "vertex": "1"
        })
        ET.SubElement(inner, "mxGeometry", {
            "height": str(CELL_INNER_H), "width": str(CELL_INNER_W),
            "x": str(px + CELL_INNER_X), "y": str(py), "as": "geometry"
        })

        h_deb = ET.SubElement(root, "mxCell", {
            "id": str(h_deb_id), "parent": "1", "style": style_deb, "value": "H_Deb", "vertex": "1"
        })
        ET.SubElement(h_deb, "mxGeometry", {
            "height": str(CELL_H_DEB_H), "width": str(CELL_H_DEB_W),
            "x": str(px + CELL_INNER_X), "y": str(py + CELL_H_DEB_Y), "as": "geometry"
        })

        l_deb = ET.SubElement(root, "mxCell", {
            "id": str(l_deb_id), "parent": "1", "style": style_deb, "value": "L_Deb", "vertex": "1"
        })
        ET.SubElement(l_deb, "mxGeometry", {
            "height": str(CELL_L_DEB_H), "width": str(CELL_L_DEB_W),
            "x": str(px + CELL_INNER_X), "y": str(py + CELL_L_DEB_Y), "as": "geometry"
        })

        o_box = ET.SubElement(root, "mxCell", {
            "id": str(o_box_id), "parent": "1", "style": style_o_box, "value": "O", "vertex": "1"
        })
        ET.SubElement(o_box, "mxGeometry", {
            "height": str(CELL_O_H), "width": str(CELL_O_W),
            "x": str(px + CELL_O_X), "y": str(py + CELL_O_Y), "as": "geometry"
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

        # O 矩形 → 輸出名稱（水平、無轉角）
        edge_o_to_name = ET.SubElement(root, "mxCell", {
            "id": str(edge_o_to_name_id), "edge": "1", "parent": "1",
            "source": str(o_box_id), "target": str(name_label_id),
            "style": style_edge_o_to_name, "value": ""
        })
        ET.SubElement(edge_o_to_name, "mxGeometry", {"relative": "1", "as": "geometry"})

    # 每個 cell id 的垂直中心 y（用於 AND/OR 依垂直位置接 input pin，減少走線交叉）
    id_to_y_center: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_y_center[nid] = positions_in[name][1] + INPUT_LABEL_H // 2
    for name, nid in out_inner_id.items():
        id_to_y_center[nid] = positions_out[name][1] + CELL_GROUP_H // 2

    # 每個 label id 所屬的 row（僅在「不同 row」時加 waypoints，與 debug_golden 一致）
    id_to_row: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_row[nid] = output_to_row.get(input_first_output.get(name, ""), 0)
    inner_id_to_row: dict[int, int] = {out_inner_id[name]: output_to_row[name] for name in output_to_row}
    inner_id_to_output: dict[int, str] = {v: k for k, v in out_inner_id.items()}

    and_idx_by_rail: dict[str, int] = {}
    and_gate_y: dict[int, int] = {}  # AND gate id -> y 中心，供排序用

    # 記錄每個 rail 的 Hi/Lo 邏輯輸出 cell id（AND/OR 閘或直連來源），
    # 供 use_mode="hi"/"lo" 時作為出發點（而非 H_Deb/L_Deb 本身）。
    hi_logic_out_id: dict[str, int] = {}  # rail name -> 最後一個閘 id（OR > AND > 直連來源）
    lo_logic_out_id: dict[str, int] = {}

    # 3) 依賴邊：依 group 繪製；單一訊號直連 H/L，兩訊號以上經 AND 閘。規則五：走線經 waypoint 繞開元件、不重疊；Hi 綠、Lo 虛線紅。
    style_hi_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_lo_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;dashed=1;strokeColor=%s;" % STROKE_LO
    style_hi_to_cell_left = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_lo_to_cell_left = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;dashed=1;strokeColor=%s;" % STROKE_LO

    def _source_id(d: str, inv: bool, is_hi: bool, use_mode: str = "self") -> int | None:
        """依賴來源的「邏輯來源」cell id。

        use_mode:
          'self' = Node 自身輸出 (inner)
          'hi'   = 該節點 Hi 依賴邏輯的輸出（AND/OR 閘）
          'lo'   = 該節點 Lo 依賴邏輯的輸出（AND/OR 閘）

        use_mode="hi"/"lo" 時回傳 H_Deb/L_Deb 作為佔位符，
        post-fix pass 會替換為正確的邏輯輸出 ID。
        inv=True 不再走 ~Name 文字標籤，而是由 post-fix 統一插入「共用 NOT 閘」
        並將 source 替換為 NOT 閘 id；本函式忽略 inv 參數。
        """
        if name_to_rail[d].seq_type == "input":
            return in_label_id.get(d)
        if use_mode == "hi":
            return h_deb_id_map.get(d) or out_inner_id.get(d)  # H_Deb placeholder, post-fix 替換為 hi_logic_out_id
        if use_mode == "lo":
            return l_deb_id_map.get(d) or out_inner_id.get(d)  # L_Deb placeholder, post-fix 替換為 lo_logic_out_id
        return out_inner_id.get(d)

    for r in outputs:
        to_inner = out_inner_id.get(r.name)
        to_h_deb = h_deb_id_map.get(r.name)
        to_l_deb = l_deb_id_map.get(r.name)
        if to_inner is None or to_h_deb is None or to_l_deb is None:
            continue

        hi_groups = r.get_hi_groups()
        if len(hi_groups) >= 2:
            # 每筆 = (from_id, dep_name_if_direct_inv 或 None, use_mode)；後者用於 OR 邊建立時記 _inv_edges
            group_outputs_hi: list[tuple[int, str | None, str]] = []
            for gi, group in enumerate(hi_groups):
                if not group:
                    continue
                inv_list = [r.get_hi_inv(gi, ii, d) for ii, d in enumerate(group)]
                use_list = [r.get_hi_use(gi, ii, d) for ii, d in enumerate(group)]
                if len(group) == 1:
                    d = group[0]
                    if d in valid and d not in CONST_DEPS:
                        from_id = _source_id(d, inv_list[0], True, use_list[0])
                        if from_id is not None:
                            group_outputs_hi.append((from_id, d if inv_list[0] else None, use_list[0]))
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
                    and_srcs = []
                    for i, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        from_id = _source_id(d, inv_list[i], True, use_list[i])
                        if from_id is not None:
                            and_srcs.append((from_id, d, inv_list[i], use_list[i]))
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv, _um) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)), from_id, _um)
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_hi])})
                        if inv:
                            _inv_edges[str(cell_id)] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _cx = _ch_left_x(d, r.name, "hi", gi)
                                _add_edge_points(geo, [(_cx, lab_y), (_cx, gy)], align=[False, True])
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
                    group_outputs_hi.append((and_gate_id[key_hi], None, "self"))
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
                sorted_hi = sorted(group_outputs_hi, key=lambda t: id_to_y_center.get(t[0], 0))
                and_ids_hi = {and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "hi"}
                for idx, (src_id, dep_inv, dep_um) in enumerate(sorted_hi):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_hi)), src_id, dep_um)
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    if dep_inv is not None:
                        _inv_edges[str(cell_id)] = (dep_inv, dep_um)
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
                        _src_out = inner_id_to_output.get(src_id, "")
                        if src_row is not None and src_row != tgt_row:
                            _crx = _ch_right_x(_src_out, r.name, "hi", 0)
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (_crx, id_to_y_center[src_id]), (_crx, _oy)], align=[False, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, _oy)], align=[False, True, True])
                        else:
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, _oy)], align=[False, True])
                    geo.text = "\n            "
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_hi, "edge": "1", "parent": "1", "source": str(or_id), "target": str(to_h_deb)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                geo.text = "\n            "
                hi_logic_out_id[r.name] = or_id
        else:
            for gi, group in enumerate(hi_groups):
                if not group:
                    continue
                inv_list = [r.get_hi_inv(gi, ii, d) for ii, d in enumerate(group)]
                use_list = [r.get_hi_use(gi, ii, d) for ii, d in enumerate(group)]
                if len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    _iv = inv_list[0]
                    _use = use_list[0]
                    from_id = _source_id(d, _iv, True, _use)
                    if from_id is None:
                        continue
                    # hi_logic_out 應記錄「真實邏輯來源」而非 H_Deb 佔位符。
                    # 單一 dep 且 use=hi/lo 時，本 rail 沒有獨立閘，需透傳上游 hi/lo_logic_out，
                    # 否則下游引用 hi_logic_out_id[本 rail] 會拿到佔位符（被 Pass 1 替換錯誤）。
                    if name_to_rail[d].seq_type != "input" and _use == "hi":
                        _real_src = hi_logic_out_id.get(d, from_id)
                    elif name_to_rail[d].seq_type != "input" and _use == "lo":
                        _real_src = lo_logic_out_id.get(d, from_id)
                    else:
                        _real_src = from_id
                    hi_logic_out_id.setdefault(r.name, _real_src)
                    _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                    is_input_dep = name_to_rail[d].seq_type == "input"
                    # inv=True 時統一走「正向邊」(source=來源, target=H_Deb)，方便 post-fix 插入共用 NOT。
                    if is_input_dep and not _iv:
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_edge_h_to_label, "edge": "1", "parent": "1", "source": str(to_inner), "target": str(from_id)})
                    else:
                        _sty = style_hi_to_cell_left if _use in ("hi", "lo") else style_hi_to_cell
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": _sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_h_deb)})
                    if _iv:
                        _inv_edges[str(cell_id)] = (d, _use)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if is_input_dep and not _iv:
                        label_pos = positions_in.get(d)
                        if label_pos:
                            _add_edge_waypoint(geo, positions_out[r.name], label_pos, waypoint_x=_ch_left_x(d, r.name, "hi", gi), gate_right_x=or_col_x + OR_GATE_W, row_py=_py)
                    elif not is_input_dep:
                        deb_y = _py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
                        src_row = inner_id_to_row.get(from_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            _crx = _ch_right_x(d, r.name, "hi", gi)
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (_crx, id_to_y_center.get(from_id, _py + 40)), (_crx, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
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
                    and_srcs = [(_source_id(d, inv_list[i], True, use_list[i]), d, use_list[i], inv_list[i]) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], True, use_list[i]) is not None]
                    and_srcs = [(fid, d, um, iv) for (fid, d, um, iv) in and_srcs if fid is not None]
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, _um, _iv) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)), from_id, _um)
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        if _iv:
                            _inv_edges[str(cell_id)] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _cx = _ch_left_x(d, r.name, "hi", gi)
                                _add_edge_points(geo, [(_cx, lab_y), (_cx, gy)], align=[False, True])
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
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_hi, "edge": "1", "parent": "1", "source": str(and_id), "target": str(to_h_deb)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    geo.text = "\n            "
                    hi_logic_out_id.setdefault(r.name, and_id)

        lo_groups = r.get_lo_groups()
        if len(lo_groups) >= 2:
            group_outputs_lo: list[tuple[int, str | None, str]] = []
            for gi, group in enumerate(lo_groups):
                if not group:
                    continue
                inv_list = [r.get_lo_inv(gi, ii, d) for ii, d in enumerate(group)]
                use_list = [r.get_lo_use(gi, ii, d) for ii, d in enumerate(group)]
                if len(group) == 1:
                    d = group[0]
                    if d in valid and d not in CONST_DEPS:
                        from_id = _source_id(d, inv_list[0], False, use_list[0])
                        if from_id is not None:
                            group_outputs_lo.append((from_id, d if inv_list[0] else None, use_list[0]))
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
                        from_id = _source_id(d, inv_list[i], False, use_list[i])
                        if from_id is not None:
                            and_srcs_lo.append((from_id, d, inv_list[i], use_list[i]))
                    and_srcs_lo.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv, _um) in enumerate(and_srcs_lo):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo)), from_id, _um)
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_lo])})
                        if inv:
                            _inv_edges[str(cell_id)] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _cx = _ch_left_x(d, r.name, "lo", gi)
                                _add_edge_points(geo, [(_cx, lab_y), (_cx, gy)], align=[False, True])
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
                    group_outputs_lo.append((and_gate_id[key_lo], None, "self"))
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
                sorted_lo = sorted(group_outputs_lo, key=lambda t: id_to_y_center.get(t[0], 0))
                and_ids_lo = {and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "lo"}
                for idx, (src_id, dep_inv, dep_um) in enumerate(sorted_lo):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_lo)), src_id, dep_um)
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    if dep_inv is not None:
                        _inv_edges[str(cell_id)] = (dep_inv, dep_um)
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
                        _src_out = inner_id_to_output.get(src_id, "")
                        if src_row is not None and src_row != tgt_row:
                            _crx = _ch_right_x(_src_out, r.name, "lo", 0)
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (_crx, id_to_y_center[src_id]), (_crx, _oy)], align=[False, True, True])
                            else:
                                bypass_y = _align40(row_y_base[src_row] + row_heights[src_row] + GRID)
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, bypass_y), (or_col_x + OR_GATE_W, _oy)], align=[False, True, True])
                        else:
                            _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center[src_id]), (or_col_x + OR_GATE_W, _oy)], align=[False, True])
                    geo.text = "\n            "
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_lo, "edge": "1", "parent": "1", "source": str(or_id), "target": str(to_l_deb)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                geo.text = "\n            "
                lo_logic_out_id[r.name] = or_id
        else:
            for gi, group in enumerate(lo_groups):
                if not group:
                    continue
                inv_list = [r.get_lo_inv(gi, ii, d) for ii, d in enumerate(group)]
                use_list = [r.get_lo_use(gi, ii, d) for ii, d in enumerate(group)]
                if len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    _iv = inv_list[0]
                    _use = use_list[0]
                    from_id = _source_id(d, _iv, False, _use)
                    if from_id is None:
                        continue
                    # lo_logic_out 應記錄「真實邏輯來源」而非 L_Deb 佔位符（同 hi 分支說明）。
                    if name_to_rail[d].seq_type != "input" and _use == "hi":
                        _real_src = hi_logic_out_id.get(d, from_id)
                    elif name_to_rail[d].seq_type != "input" and _use == "lo":
                        _real_src = lo_logic_out_id.get(d, from_id)
                    else:
                        _real_src = from_id
                    lo_logic_out_id.setdefault(r.name, _real_src)
                    _px, _py = positions_out.get(r.name, (cell_start_x, MARGIN))
                    is_input_dep = name_to_rail[d].seq_type == "input"
                    if is_input_dep and not _iv:
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_edge_l_to_label, "edge": "1", "parent": "1", "source": str(to_inner), "target": str(from_id)})
                    else:
                        _sty = style_lo_to_cell_left if _use in ("hi", "lo") else style_lo_to_cell
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": _sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_l_deb)})
                    if _iv:
                        _inv_edges[str(cell_id)] = (d, _use)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if is_input_dep and not _iv:
                        label_pos = positions_in.get(d)
                        if label_pos:
                            _add_edge_waypoint(geo, positions_out[r.name], label_pos, waypoint_x=_ch_left_x(d, r.name, "lo", gi), gate_right_x=or_col_x + OR_GATE_W, row_py=_py)
                    elif not is_input_dep:
                        deb_y = _py + CELL_L_DEB_Y + CELL_L_DEB_H // 2
                        src_row = inner_id_to_row.get(from_id)
                        tgt_row = output_to_row[r.name]
                        if src_row is not None and src_row != tgt_row:
                            _crx = _ch_right_x(d, r.name, "lo", gi)
                            if src_row < tgt_row:
                                _add_edge_points(geo, [(or_col_x + OR_GATE_W, id_to_y_center.get(from_id, _py + 40)), (_crx, id_to_y_center.get(from_id, _py + 40)), (_crx, deb_y), (cell_start_x + CELL_INNER_X, deb_y)], align=[False, True, True, True])
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
                    and_srcs_lo2 = [(_source_id(d, inv_list[i], False, use_list[i]), d, use_list[i], inv_list[i]) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], False, use_list[i]) is not None]
                    and_srcs_lo2 = [(fid, d, um, iv) for (fid, d, um, iv) in and_srcs_lo2 if fid is not None]
                    and_srcs_lo2.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, _um, _iv) in enumerate(and_srcs_lo2):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo2)), from_id, _um)
                        cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        if _iv:
                            _inv_edges[str(cell_id)] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _py + (and_idx_by_rail[r.name] - 1) * AND_GATE_DY + AND_GATE_H // 2
                                lab_y = lab[1] + INPUT_LABEL_H // 2
                                _cx = _ch_left_x(d, r.name, "lo", gi)
                                _add_edge_points(geo, [(_cx, lab_y), (_cx, gy)], align=[False, True])
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
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_lo, "edge": "1", "parent": "1", "source": str(and_id), "target": str(to_l_deb)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    geo.text = "\n            "
                    lo_logic_out_id.setdefault(r.name, and_id)

    # --- Post-fix ---
    # 三個 pass：
    # Pass 1: 將「use_mode=hi/lo 但非 inv」的邊 source 從 H_Deb/L_Deb 佔位符替換為邏輯輸出 cell；
    #         同時修正 style：exitX=0（H_Deb 左側）→ exitX=1（AND/OR 閘右側）。
    # Pass 2: 為每個唯一 (來源 d, use_mode) 建立一顆「共用 NOT 閘」。
    #         input 反相的 NOT 放在「Input NOT 欄」（緊鄰 input label），
    #         output 反相的 NOT 放在「Logic NOT 欄」（AND 欄左側）。
    # Pass 3: 將所有 inv=True 的邊 source 替換為對應 NOT 閘 id；修正 style 與走線。
    input_not_col_x = _align40(input_right + GAP)
    logic_not_col_x = _align40(input_not_col_x + NOT_GATE_W + GAP) if _has_input_not else input_not_col_x
    style_not_gate = "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;verticalAlign=top;shape=mxgraph.electrical.logic_gates.inverter_2"
    style_logic_to_not = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;"

    h_deb_ids: dict[int, str] = {nid: rname for rname, nid in h_deb_id_map.items()}
    l_deb_ids: dict[int, str] = {nid: rname for rname, nid in l_deb_id_map.items()}

    # 收集所有已放置元件 bbox，用於避免 NOT 閘重疊
    _placed_boxes: list[tuple[int, int, int, int]] = []
    for v_cell in root.iter("mxCell"):
        if v_cell.get("vertex") != "1":
            continue
        geo = v_cell.find("mxGeometry")
        if geo is None:
            continue
        vx, vy, vw, vh = geo.get("x"), geo.get("y"), geo.get("width"), geo.get("height")
        if vx is None or vy is None:
            continue
        try:
            bx, by = int(float(vx)), int(float(vy))
            bw = int(float(vw)) if vw else 0
            bh = int(float(vh)) if vh else 0
            pid = v_cell.get("parent", "1")
            if pid != "1":
                pg = root.find(f".//mxCell[@id='{pid}']")
                if pg is not None:
                    pgeo = pg.find("mxGeometry")
                    if pgeo is not None:
                        bx += int(float(pgeo.get("x", "0")))
                        by += int(float(pgeo.get("y", "0")))
            _placed_boxes.append((bx, by, bx + bw, by + bh))
        except (ValueError, TypeError):
            pass

    def _find_non_overlapping_y(nx: int, ny_preferred: int, nw: int, nh: int) -> int:
        ny = _align40(ny_preferred)
        for _ in range(60):
            box = (nx, ny, nx + nw, ny + nh)
            if all(box[2] <= b[0] or b[2] <= box[0] or box[3] <= b[1] or b[3] <= box[1] for b in _placed_boxes):
                return ny
            ny += GRID
        return ny

    # ---- Pass 1: use=hi/lo 非 inv 的邊 source 替換 ----
    inv_edge_ids = set(_inv_edges.keys())
    for edge_cell in list(root.iter("mxCell")):
        if edge_cell.get("edge") != "1":
            continue
        if edge_cell.get("id") in inv_edge_ids:
            continue  # inv 邊由 Pass 3 處理
        src_str = edge_cell.get("source")
        if src_str is None:
            continue
        try:
            src_id = int(src_str)
        except ValueError:
            continue
        sty = edge_cell.get("style", "")
        if "exitX=0" not in sty:
            continue
        real_id = None
        if src_id in h_deb_ids:
            real_id = hi_logic_out_id.get(h_deb_ids[src_id])
        elif src_id in l_deb_ids:
            real_id = lo_logic_out_id.get(l_deb_ids[src_id])
        if real_id is None or real_id == src_id:
            continue
        edge_cell.set("source", str(real_id))
        sty = sty.replace("exitX=0", "exitX=1")
        sty = sty.replace("exitY=0.25", "exitY=0.5").replace("exitY=0.75", "exitY=0.5")
        edge_cell.set("style", sty)

    # ---- Pass 2: 為每個唯一 (d, use_mode) 建立共用 NOT 閘 ----
    def _logic_source_id(d: str, use_mode: str) -> int | None:
        """根據 (d, use_mode) 取得真正的邏輯來源 cell id。"""
        if name_to_rail[d].seq_type == "input":
            return in_label_id.get(d)
        if use_mode == "hi":
            return hi_logic_out_id.get(d) or out_inner_id.get(d)
        if use_mode == "lo":
            return lo_logic_out_id.get(d) or out_inner_id.get(d)
        return out_inner_id.get(d)

    def _logic_source_y(src_id: int) -> int:
        return id_to_y_center.get(src_id, MARGIN)

    unique_inv_keys: list[tuple[str, str]] = []
    seen = set()
    for k in _inv_edges.values():
        if k not in seen:
            seen.add(k)
            unique_inv_keys.append(k)

    for d, use_mode in unique_inv_keys:
        src_id = _logic_source_id(d, use_mode)
        if src_id is None:
            continue
        is_input_src = name_to_rail[d].seq_type == "input"
        not_x = input_not_col_x if is_input_src else logic_not_col_x
        if is_input_src:
            # input NOT 放在 label 正下方（NOT 上邊貼 label 下邊），讓非反相 input 的水平
            # 走線可從 NOT 上方水平通過、不會穿越 NOT 閘 vertex。
            label_center_y = _logic_source_y(src_id)
            not_y_preferred = label_center_y + INPUT_LABEL_H // 2
        else:
            not_y_preferred = _logic_source_y(src_id) - NOT_GATE_H // 2
        not_y = _find_non_overlapping_y(not_x, not_y_preferred, NOT_GATE_W, NOT_GATE_H)
        nid = cell_id
        cell_id += 1
        not_gate_id[(d, use_mode)] = nid
        not_cell = ET.SubElement(root, "mxCell", {
            "id": str(nid), "parent": "1", "style": style_not_gate, "value": "", "vertex": "1"
        })
        ET.SubElement(not_cell, "mxGeometry", {
            "height": str(NOT_GATE_H), "width": str(NOT_GATE_W),
            "x": str(not_x), "y": str(not_y), "as": "geometry"
        })
        _placed_boxes.append((not_x, not_y, not_x + NOT_GATE_W, not_y + NOT_GATE_H))
        id_to_y_center[nid] = not_y + NOT_GATE_H // 2

        e_src_to_not = ET.SubElement(root, "mxCell", {
            "id": str(cell_id), "style": style_logic_to_not % STROKE_DEFAULT,
            "edge": "1", "parent": "1", "source": str(src_id), "target": str(nid),
        })
        cell_id += 1
        ET.SubElement(e_src_to_not, "mxGeometry", {"relative": "1", "as": "geometry"})

    # ---- Pass 3: 把所有 inv 邊 source 替換為 NOT 閘 id ----
    for edge_cell in list(root.iter("mxCell")):
        edge_id_str = edge_cell.get("id")
        if edge_id_str not in _inv_edges:
            continue
        d, use_mode = _inv_edges[edge_id_str]
        nid = not_gate_id.get((d, use_mode))
        if nid is None:
            continue
        sty = edge_cell.get("style", "")
        sty = sty.replace("exitX=0", "exitX=1")
        sty = sty.replace("exitY=0.25", "exitY=0.5").replace("exitY=0.75", "exitY=0.5")
        edge_cell.set("style", sty)
        edge_cell.set("source", str(nid))
        # 清掉原本 source 為佔位符時的 waypoints（座標已失效）
        geo = edge_cell.find("mxGeometry")
        if geo is not None:
            for arr in list(geo):
                if arr.tag == "Array" and arr.get("as") == "points":
                    geo.remove(arr)

    minimize_crossings(root, grid=GRID)

    rough = ET.tostring(mxfile, encoding="unicode", default_namespace="")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
