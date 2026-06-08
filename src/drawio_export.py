"""
Export Power Sequence dependency as Draw.io XML.

版面與樣式依專案內 DRAWIO_RULES.md 實作，摘要如下：
- 規則一（輸入）：label 與 input NOT 皆 **rotation=90**；依 config 由**右→左**每欄 40pt，若**前一個** input 有 NOT 則下一個再左 40pt；垂直錨點見 `INPUT_NOT.xml`（NOT 底邊在**最上 Cell 上緣之上 40pt**、40pt 對齊；label 在 NOT 上方）；NOT **左 20pt**；走線**先下後右**。
- 規則二（邏輯閘）：X 三層 ①AND/NAND→②OR/NOR（若有）→③Cell；② 在 ① 後、③ 前，不同欄；AND/NAND、OR/NOR 垂直＝global catalog 鍊＋Y slack（去重）；Cell 列距＋回授 slack；`group_inv`→NAND/NOR；閘 output 先右走 **40×n**。
- 規則三（PSEQCELL）：5 個獨立 cells（inner + H_Deb + L_Deb + Q + ~Q），無 group；對應 PSEQCELL.v 之 iHi/iLo/iForce/o；連到 H_Deb 實心綠、連到 L_Deb 實心紅。
- 規則四（輸出）：直接從 O 矩形右側拉一條水平邊到輸出名稱文字框，無小圓圈、無轉角。
- 規則五（連接線）：線寬 2pt、交叉處弧線跳接（jumpStyle=arc）、一律實線；預設黑、Hi 綠、Lo 紅；正交、少交叉；不穿越元件；**相同 source 允許水平重疊、垂直不重疊**，不同 source 則水平/垂直皆錯開；**source/destination 一律水平連接，水平段至少 40pt**；waypoint 處與輸入同高可不對齊 40pt。
- 規則六：不同 source 走線不重疊、箭頭與分岔清楚；常數見 DRAWIO_RULES.md。
"""
import random
import re
import string
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from xml.dom import minidom

from config_models import PowerSeqConfig, PowerRail
from drawio_export_options import DrawioExportOptions
from drawio_edge_freeze import (
    _style_to_frozen_none,
    freeze_edge_routing,
    restore_orthogonal_auto_routing,
)

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"
CONST_DEPS = {DEP_HIGH, DEP_LOW}

# Power Sequence Cell 尺寸（RTL：PSEQCELL.v；Draw.io 幾何：PSEQCELL.xml）
CELL_GROUP_W = 80
CELL_GROUP_H = 80
CELL_INNER_X = 0
CELL_INNER_W = 80
CELL_INNER_H = 80
CELL_H_DEB_W = 50
CELL_H_DEB_H = 20
CELL_L_DEB_W = 50
CELL_L_DEB_H = 20
CELL_H_DEB_Y = 10
CELL_L_DEB_Y = 50
CELL_Q_W = 20
CELL_Q_H = 20
CELL_Q_X = 60
CELL_Q_Y = CELL_H_DEB_Y
CELL_NQ_W = 20
CELL_NQ_H = 20
CELL_NQ_X = 60
CELL_NQ_Y = CELL_L_DEB_Y
# 版面規則：欄位水平間距 GAP（40pt）；列距／NOT 等仍用 ROW_GAP（80pt）
GRID = 40
FB_Q_RIGHT = GRID
FB_Q_UP = GRID + 20
FB_NQ_RIGHT = 2 * GRID   # ~Q 回授：先右 2×40pt
FB_NQ_UP = 3 * GRID + 20  # 再向上 3×40pt + 20pt（140pt，避開 Q 的 60pt 上拐）
GAP = 40
ROW_GAP = 80

def _align40(v: int | float) -> int:
    """將座標對齊到 40 的倍數。"""
    return round(float(v) / GRID) * GRID


def _align10(v: int | float) -> int:
    """將座標對齊到 10 的倍數（文字框垂直位置用）。"""
    return round(float(v) / 10) * 10

# 欄位式版面（左→右）：輸入欄 | AND 欄 | OR 欄(GAP) | Cell 欄 | 輸出名稱欄
# AND/OR 分層：愈前一級愈左，輸入→AND→OR→Cell，相鄰欄水平間隔 GAP（40pt）
MARGIN = GRID
INPUT_COL_X = _align40(GAP * 2)  # 預設列參考；實際 x 由右→左動態分配
INPUT_LABEL_W = _align40(80)
INPUT_LABEL_H = 20
INPUT_SLOT_W = GRID              # 每個 input 佔 40pt 欄寬
INPUT_VERTICAL_DY = ROW_GAP      # 每個 input 垂直間距（用於反相 output 等）
GATE_COL_X = _align40(GAP * 5)   # 200：OR 與 AND 同一欄（參考）
CELL_START_X = _align40(GAP * 8)  # 320（參考）
OUTPUT_NAME_GAP = _align40(120)       # Cell 右緣 → 輸出名稱欄淨空（pt）
OUTPUT_NAME_NOT_EXTRA = ROW_GAP       # 任一 output 用 O 側 NOT 時，全列再 +80pt
OUTPUT_NAME_OFFSET_X = CELL_GROUP_W + OUTPUT_NAME_GAP  # 預設參考（無 output NOT）
# 輸出名稱 y 與 Q 垂直置中對齊，使 Q→名稱為水平直線
OUTPUT_NAME_OFFSET_Y = CELL_Q_Y + CELL_Q_H // 2 - INPUT_LABEL_H // 2
# 連接線顏色：Hi 實心紅、Lo 實心綠、Feedback 實心藍、預設實心黑（一律實線）
STROKE_HI = "#ff0000"
STROKE_LO = "#008000"
STROKE_DEFAULT = "#000000"
STROKE_FEEDBACK = "#0000ff"
# 走線：線寬 2pt、交叉處留白跳接（Draw.io jumpStyle=gap）
EDGE_STROKE_WIDTH = 2
EDGE_JUMP_STYLE = "gap"
EDGE_JUMP_SIZE = 6
AND_GATE_W = 80
AND_GATE_H = 40
# logic_gate numInputs=1（AND1.xml 等）：唯一輸入錨點在左側中央
_GATE_ENTRY_AY = 0.5
OR_GATE_W = 80
OR_GATE_H = 40
NOT_GATE_W = 40
NOT_GATE_H = 20
# output NOT：O 矩形右 80pt、下 40pt（未旋轉）
NOT_OFFSET_X = ROW_GAP  # 右 80pt
NOT_OFFSET_Y = GRID     # 下 40pt
NOT_TURN_X = GRID    # input 走線：label 錨點 + 40pt 垂直 bus（先下後右）
# input NOT（皆 rotation=90，見 reference/INPUT_NOT.xml）：左 20pt；底邊在最上 Cell 上緣之上 40pt
INPUT_NOT_LEFT = GRID - 20
INPUT_NOT_ABOVE_CELL = GRID
INPUT_NOT_LABEL_TO_NOT_GAP = INPUT_LABEL_H  # label 底邊至 NOT 頂 20pt（INPUT_NOT.xml）
NOT_STACK_GAP = INPUT_LABEL_H  # 下一列放在 NOT 下方時的間距
# AND/OR 整組反相：內建 negating bubble（reference/NAND1.xml、NOR1.xml），不再外掛 inverter_2
_REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


_PSEQCELL_STYLE_INNER = "rounded=0;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_H_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_L_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_Q = "rounded=1;whiteSpace=wrap;html=1;"


def _load_pseqcell_layout() -> None:
    """自 reference/PSEQCELL.xml 載入 Cell 幾何與 style（含連接點 points；RTL 見 PSEQCELL.v）。"""
    global CELL_GROUP_W, CELL_GROUP_H, CELL_INNER_X, CELL_INNER_W, CELL_INNER_H
    global CELL_H_DEB_W, CELL_H_DEB_H, CELL_L_DEB_W, CELL_L_DEB_H
    global CELL_H_DEB_Y, CELL_L_DEB_Y
    global CELL_Q_W, CELL_Q_H, CELL_Q_X, CELL_Q_Y
    global CELL_NQ_W, CELL_NQ_H, CELL_NQ_X, CELL_NQ_Y
    global _PSEQCELL_STYLE_INNER, _PSEQCELL_STYLE_H_DEB, _PSEQCELL_STYLE_L_DEB, _PSEQCELL_STYLE_Q

    path = _REFERENCE_DIR / "PSEQCELL.xml"
    parts: dict[str, tuple[int, int, int, int]] = {}
    styles: dict[str, str] = {}
    group_w = group_h = 0
    for cell in ET.parse(path).getroot().iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        style = cell.get("style") or ""
        if style.startswith("group"):
            geo = cell.find("mxGeometry")
            if geo is not None:
                group_w = int(float(geo.get("width", 0)))
                group_h = int(float(geo.get("height", 0)))
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        w = int(float(geo.get("width", 0)))
        h = int(float(geo.get("height", 0)))
        x = int(float(geo.get("x", 0) or 0))
        y = int(float(geo.get("y", 0) or 0))
        val = (cell.get("value") or "").strip()
        if val == "H_Deb":
            parts["h_deb"] = (x, y, w, h)
            styles["h_deb"] = style
        elif val == "L_Deb":
            parts["l_deb"] = (x, y, w, h)
            styles["l_deb"] = style
        elif val == "Q":
            parts["q"] = (x, y, w, h)
            styles["q"] = style
        elif val == "~Q":
            parts["nq"] = (x, y, w, h)
            styles["nq"] = style
        elif not val and "rounded=0" in style:
            parts["inner"] = (x, y, w, h)
            styles["inner"] = style

    required = ("inner", "h_deb", "l_deb", "q", "nq")
    missing = [k for k in required if k not in parts]
    if missing:
        raise ValueError(f"PSEQCELL.xml missing parts: {missing}")

    ix, _iy, iw, ih = parts["inner"]
    CELL_INNER_X = ix
    CELL_INNER_W, CELL_INNER_H = iw, ih
    _, hy, hw, hh = parts["h_deb"]
    CELL_H_DEB_W, CELL_H_DEB_H, CELL_H_DEB_Y = hw, hh, hy
    _, ly, lw, lh = parts["l_deb"]
    CELL_L_DEB_W, CELL_L_DEB_H, CELL_L_DEB_Y = lw, lh, ly
    qx, qy, qw, qh = parts["q"]
    CELL_Q_X, CELL_Q_Y, CELL_Q_W, CELL_Q_H = qx, qy, qw, qh
    nx, ny, nw, nh = parts["nq"]
    CELL_NQ_X, CELL_NQ_Y, CELL_NQ_W, CELL_NQ_H = nx, ny, nw, nh
    CELL_GROUP_W = group_w or iw
    CELL_GROUP_H = group_h or ih
    _PSEQCELL_STYLE_INNER = styles["inner"]
    _PSEQCELL_STYLE_H_DEB = styles["h_deb"]
    _PSEQCELL_STYLE_L_DEB = styles["l_deb"]
    _PSEQCELL_STYLE_Q = styles["q"]


def _load_logic_gate_style(xml_name: str) -> str:
    """自 reference/*1.xml 讀取 logic_gate 的 mxCell style（AND1／NAND1／OR1／NOR1）。"""
    path = _REFERENCE_DIR / xml_name
    for cell in ET.parse(path).getroot().iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        style = cell.get("style") or ""
        if "logic_gates.logic_gate" in style:
            return style
    raise ValueError(f"no logic_gate vertex in {path}")


_GATE_STYLE_AND = _load_logic_gate_style("AND1.xml")
_GATE_STYLE_NAND = _load_logic_gate_style("NAND1.xml")
_GATE_STYLE_OR = _load_logic_gate_style("OR1.xml")
_GATE_STYLE_NOR = _load_logic_gate_style("NOR1.xml")
_load_pseqcell_layout()
# 由欄位推算的相對偏移（AND 在左、OR 在右，generate_drawio 內動態計算 and_col_x / or_col_x）
AND_GATE_DY = ROW_GAP           # 多個 AND 垂直間距 80pt
# OR 閘與該行 Cell 同高，放在左側（不放到 Cell 下方）
OR_GATE_OFFSET_HI_Y = 0
OR_GATE_OFFSET_LO_Y = GRID  # 40，若同時有 Hi/Lo 兩個 OR 則垂直錯開 40pt


def _input_label_center_y(ly: int) -> int:
    """rotation=90 時 label 連接點沿頁面 y 的中心（幾何 width 沿 y 展開）。"""
    return ly + INPUT_LABEL_W // 2


def _input_label_bottom_y(ly: int) -> int:
    """rotation=90 時 label 底邊 y（幾何 width 沿頁面向下展開）。"""
    return ly + INPUT_LABEL_W


def _input_not_visual_bottom_y(not_y: int) -> int:
    """rotation=90 時 mxGraph 繞中心旋轉後的底邊 y（INPUT_NOT.xml：y=290 → bottom=320）。"""
    return not_y + NOT_GATE_W - NOT_GATE_H // 2


def _input_not_bottom_y(not_y: int) -> int:
    """rotation=90 時 NOT 底邊 y（同 _input_not_visual_bottom_y）。"""
    return _input_not_visual_bottom_y(not_y)


def _input_not_y(cell_top_y: int) -> int:
    """input NOT 左上角 y：旋轉後底邊在 Cell 上緣之上 40pt（40pt 對齊，見 INPUT_NOT.xml）。"""
    cell_top = _align40(cell_top_y)
    visual_bottom = cell_top - INPUT_NOT_ABOVE_CELL
    return visual_bottom - NOT_GATE_W + NOT_GATE_H // 2


def _input_row_y(cell_top_y: int) -> int:
    """input label 左上角 y：NOT 頂之上 INPUT_LABEL_H（20pt），見 INPUT_NOT.xml。"""
    not_y = _input_not_y(cell_top_y)
    return not_y - INPUT_NOT_LABEL_TO_NOT_GAP - INPUT_LABEL_W


def _input_bus_x(lx: int) -> int:
    """input／NOT 走線垂直 bus（先下後右：錨點 x + 40pt）。"""
    return _align40(lx + NOT_TURN_X)


def _input_not_position(label_xy: tuple[int, int], cell_top_y: int) -> tuple[int, int]:
    """input NOT 左上角：x 在 label 左 20pt；y 由最上 Cell 上緣錨定（見 INPUT_NOT.xml）。"""
    lx, _ly = label_xy
    return (lx - INPUT_NOT_LEFT, _input_not_y(cell_top_y))


def _input_band_width(used_inputs_list: list[str], inputs_with_not: set[str]) -> int:
    """input 帶總寬：每個 40pt；若「前一個」（宣告序、圖上較右）有 NOT，下一個再左留 40pt。"""
    if not used_inputs_list:
        return 0
    w = INPUT_SLOT_W * len(used_inputs_list)
    for i in range(len(used_inputs_list) - 1):
        if used_inputs_list[i] in inputs_with_not:
            w += GRID
    return w


def _min_and_gate_top_y(outputs: list[PowerRail], row_y_base: list[int]) -> int:
    """全域最上方 AND 閘上緣 y（無 AND 時用第一列 output 上緣）。"""
    best: int | None = None
    for j, r in enumerate(outputs):
        has_and = any(len(g) >= 2 for g in r.get_hi_groups()) or any(
            len(g) >= 2 for g in r.get_lo_groups()
        )
        if has_and:
            top = row_y_base[j]
            if best is None or top < best:
                best = top
    return best if best is not None else row_y_base[0]


def _build_and_catalog(
    outputs: list[PowerRail],
) -> tuple[list[tuple[str, str, int]], dict[tuple[str, str, int], int]]:
    """依 output 宣告序（上→下）編號 AND／NAND：#1, #2, …（group_inv 不另編號）。"""
    catalog: list[tuple[str, str, int]] = []
    idx_map: dict[tuple[str, str, int], int] = {}
    n = 0
    for r in outputs:
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) >= 2:
                    n += 1
                    catalog.append((r.name, hl, gi))
                    idx_map[(r.name, hl, gi)] = n
    return catalog, idx_map


def _departing_and_index(
    src_output: str,
    use: str,
    *,
    idx_map: dict[tuple[str, str, int], int],
    name_to_rail: dict[str, PowerRail],
) -> int | None:
    """跨列回授時，從來源 output 哪一顆 AND 的 output 出發（無 AND 則 None）。"""
    r = name_to_rail[src_output]
    if use == "lo":
        keys = [(src_output, "lo", gi) for gi, g in enumerate(r.get_lo_groups()) if len(g) >= 2]
    elif use == "hi":
        keys = [(src_output, "hi", gi) for gi, g in enumerate(r.get_hi_groups()) if len(g) >= 2]
    else:
        keys = []
        for hl in ("hi", "lo"):
            groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
            for gi, g in enumerate(groups):
                if len(g) >= 2:
                    keys.append((src_output, hl, gi))
    for key in keys:
        if key in idx_map:
            return idx_map[key]
    return None


def _count_feedback_trunks(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> tuple[int, set[int], bool]:
    """
    回授幹線數（每條 40pt）：
    - 每個「跨列、進 AND、由來源列 AND output 出發」的來源 AND 編號各 1 條；
    - RSMRST_N 扇出到下游 AND 只算 1 條（不論幾個目標）。
    """
    _, idx_map = _build_and_catalog(outputs)
    trunk_and: set[int] = set()
    has_rsmrst = False
    for tgt in outputs:
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) < 2:
                    continue
                for ii, d in enumerate(group):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        continue
                    src_row = output_to_row.get(d)
                    tgt_row = output_to_row.get(tgt.name)
                    if src_row is None or tgt_row is None or src_row == tgt_row:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if d == "RSMRST_N":
                        has_rsmrst = True
                        continue
                    src_idx = _departing_and_index(
                        d, use, idx_map=idx_map, name_to_rail=name_to_rail
                    )
                    if src_idx is not None:
                        trunk_and.add(src_idx)
    n = len(trunk_and) + (1 if has_rsmrst else 0)
    return n, trunk_and, has_rsmrst


LayoutFeedbackDepKey = tuple[str, str, int, int, str]


def _is_cross_row_feedback(src_row: int, tgt_row: int) -> bool:
    """回授：來源列在圖上較下方（列號較大）→ 往上游列走（src_row > tgt_row）。"""
    return src_row > tgt_row


def _build_layout_feedback_dep_keys(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> set[LayoutFeedbackDepKey]:
    """
    佈局回授十三類（四類加總）：跨列且
    - RSMRST_N 依賴；或
    - PCH_PWROK lo inv 單一 Deb；或
    - 多輸入 AND 且 _departing_and_index 非空（AND Output，不含 RSMRST_N）。
    """
    _, and_idx_map = _build_and_catalog(outputs)
    keys: set[LayoutFeedbackDepKey] = set()
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                glen = len(group)
                for ii, d in enumerate(group):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    inv = (
                        tgt.get_hi_inv(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_inv(gi, ii, d)
                    )
                    if d == "RSMRST_N":
                        # RSMRST use=self 扇出至下游 AND 亦佔回授幹線（含 src_row < tgt_row）
                        if src_row != tgt_row:
                            keys.add((tgt.name, hl, gi, ii, d))
                        continue
                    if d == "PCH_PWROK" and glen == 1 and inv:
                        if _is_cross_row_feedback(src_row, tgt_row):
                            keys.add((tgt.name, hl, gi, ii, d))
                    elif glen >= 2:
                        # AND 層輸出 → AND 層輸入＝同層回授，不分上下（src_row != tgt_row 即可）。
                        # placement 的回授幹線 _count_feedback_trunks 本就不分方向計入，容量已對齊。
                        if src_row != tgt_row and _departing_and_index(
                            d, use, idx_map=and_idx_map, name_to_rail=name_to_rail
                        ) is not None:
                            keys.add((tgt.name, hl, gi, ii, d))
    return keys


def _pass1_is_layout_feedback(
    upstream_rail: str,
    src_row: int,
    tgt_row: int,
    tgt_id: int,
    hl_pass: str,
    *,
    layout_feedback_dep_keys: set[LayoutFeedbackDepKey],
    and_rev_pass1: dict[int, tuple[str, str, int]],
    deb_tgt_row: dict[int, int],
    output_to_row: dict[str, int],
) -> bool:
    if src_row == tgt_row:
        return False
    for tgt_rail, hl, gi, ii, d in layout_feedback_dep_keys:
        if d != upstream_rail or hl != hl_pass:
            continue
        if output_to_row.get(tgt_rail) != tgt_row:
            continue
        if tgt_id in and_rev_pass1:
            ak = and_rev_pass1[tgt_id]
            if ak == (tgt_rail, hl, gi):
                return True
        elif tgt_id in deb_tgt_row and deb_tgt_row[tgt_id] == tgt_row:
            return True
    return False


def _mark_y_gap(slack: dict[int, int], gap: int) -> None:
    """相鄰同層間隙最多 +GRID（40pt）；同一 gap 去重。"""
    if gap >= 1:
        slack[gap] = GRID


def _build_or_catalog(
    outputs: list[PowerRail],
) -> tuple[list[tuple[str, str]], dict[tuple[str, str], int]]:
    """依 output 宣告序（上→下）編號 OR／NOR：#1, #2, …（Hi 再 Lo）。"""
    catalog: list[tuple[str, str]] = []
    idx_map: dict[tuple[str, str], int] = {}
    n = 0
    for r in outputs:
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            if len(groups) >= 2:
                n += 1
                catalog.append((r.name, hl))
                idx_map[(r.name, hl)] = n
    return catalog, idx_map


def _build_or_index_per_key(
    outputs: list[PowerRail],
) -> dict[tuple[str, str], tuple[int, int]]:
    """(rail, hl) -> (row_j, nominal_offset_y)。"""
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for j, r in enumerate(outputs):
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            if len(groups) >= 2:
                off = OR_GATE_OFFSET_HI_Y if hl == "hi" else OR_GATE_OFFSET_LO_Y
                out[(r.name, hl)] = (j, off)
    return out


def _and_row_by_global(idx_map: dict[tuple[str, str, int], int], and_index_per_key: dict) -> dict[int, int]:
    return {g: and_index_per_key[key][0] for key, g in idx_map.items()}


def _or_row_by_global(or_idx_map: dict[tuple[str, str], int], or_index_per_key: dict) -> dict[int, int]:
    return {g: or_index_per_key[key][0] for key, g in or_idx_map.items()}


def _nearest_and_and_gap(
    src_output: str,
    use: str,
    tgt_global: int,
    *,
    idx_map: dict[tuple[str, str, int], int],
    and_row: dict[int, int],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
) -> int:
    """回授訊號對應的 AND–AND 間隙：slack 加在該 global AND 編號**下方**。"""
    src_g = _departing_and_index(
        src_output, use, idx_map=idx_map, name_to_rail=name_to_rail
    )
    if src_g is not None:
        if src_g < tgt_global:
            return src_g
        return max(1, tgt_global - 1)
    src_row = output_to_row[src_output]
    below_on_src = [g for g, row in and_row.items() if row == src_row and g < tgt_global]
    if below_on_src:
        return max(below_on_src)
    return max(1, tgt_global - 1)


def _departing_or_index(
    src_output: str,
    use: str,
    *,
    or_idx_map: dict[tuple[str, str], int],
    name_to_rail: dict[str, PowerRail],
) -> int | None:
    """跨列回授時，從來源 output 哪一顆 OR 的 output 出發（無 OR 則 None）。"""
    r = name_to_rail[src_output]
    if use == "lo" and len(r.get_lo_groups()) >= 2:
        return or_idx_map.get((src_output, "lo"))
    if use == "hi" and len(r.get_hi_groups()) >= 2:
        return or_idx_map.get((src_output, "hi"))
    return None


def _nearest_or_or_gap(
    src_output: str,
    use: str,
    tgt_global: int,
    *,
    or_idx_map: dict[tuple[str, str], int],
    or_row: dict[int, int],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
) -> int:
    """回授／直連對應的 OR–OR 間隙：slack 加在該 global OR 編號**下方**。"""
    src_g = _departing_or_index(
        src_output, use, or_idx_map=or_idx_map, name_to_rail=name_to_rail
    )
    if src_g is not None:
        if src_g < tgt_global:
            return src_g
        return max(1, tgt_global - 1)
    src_row = output_to_row[src_output]
    below_on_src = [g for g, row in or_row.items() if row == src_row and g < tgt_global]
    if below_on_src:
        return max(below_on_src)
    return max(1, tgt_global - 1)


def _nearest_and_and_gap_for_row(
    tgt_row: int,
    *,
    idx_map: dict[tuple[str, str, int], int],
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]],
) -> int:
    """Input 直連後級時，依目標列找最近 AND–AND 間隙。"""
    on_row = sorted(
        g for key, g in idx_map.items() if and_index_per_key[key][0] == tgt_row
    )
    if on_row:
        return max(1, min(on_row) - 1)
    below = sorted(
        g for key, g in idx_map.items() if and_index_per_key[key][0] > tgt_row
    )
    if below:
        return max(1, min(below) - 1)
    above = sorted(
        (g for key, g in idx_map.items() if and_index_per_key[key][0] < tgt_row),
        reverse=True,
    )
    if above:
        return above[0]
    return 1


def _nearest_or_or_gap_for_row(
    tgt_row: int,
    hl: str,
    *,
    or_idx_map: dict[tuple[str, str], int],
    or_index_per_key: dict[tuple[str, str], tuple[int, int]],
) -> int:
    """Input／AND 直連 Cell 時，依目標列找最近 OR–OR 間隙。"""
    on_row_other: list[int] = []
    for or_key, g in or_idx_map.items():
        if or_index_per_key[or_key][0] != tgt_row:
            continue
        if or_key[1] == hl:
            return max(1, g - 1)
        on_row_other.append(g)
    if on_row_other:
        return max(1, min(on_row_other) - 1)
    below = sorted(
        g for key, g in or_idx_map.items() if or_index_per_key[key][0] > tgt_row
    )
    if below:
        return max(1, min(below) - 1)
    above = sorted(
        (g for key, g in or_idx_map.items() if or_index_per_key[key][0] < tgt_row),
        reverse=True,
    )
    if above:
        return above[0]
    return 1


def _feedback_y_slack_after_and(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]],
) -> dict[int, int]:
    """
    AND／NAND 層：相鄰兩顆間隙 +40pt（去重）。
    觸發：跨列 output→AND input；Input 直連 OR／NOR／Cell（不含 Input→AND）。
    """
    _, idx_map = _build_and_catalog(outputs)
    and_row = _and_row_by_global(idx_map, and_index_per_key)
    slack: dict[int, int] = {}
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) >= 2:
                    tgt_g = idx_map.get((tgt.name, hl, gi))
                    if tgt_g is None:
                        continue
                    for ii, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        if name_to_rail[d].seq_type == "input":
                            continue
                        src_row = output_to_row.get(d)
                        if src_row is None or src_row == tgt_row:
                            continue
                        use = (
                            tgt.get_hi_use(gi, ii, d)
                            if hl == "hi"
                            else tgt.get_lo_use(gi, ii, d)
                        )
                        gap = _nearest_and_and_gap(
                            d,
                            use,
                            tgt_g,
                            idx_map=idx_map,
                            and_row=and_row,
                            output_to_row=output_to_row,
                            name_to_rail=name_to_rail,
                        )
                        _mark_y_gap(slack, gap)
                elif len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type != "input":
                        continue
                    gap = _nearest_and_and_gap_for_row(
                        tgt_row, idx_map=idx_map, and_index_per_key=and_index_per_key
                    )
                    _mark_y_gap(slack, gap)
    return slack


def _feedback_y_slack_after_or(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    or_index_per_key: dict[tuple[str, str], tuple[int, int]],
) -> dict[int, int]:
    """
    OR／NOR 層：相鄰兩顆間隙 +40pt（去重）。
    觸發：跨列 Cell fb→OR input；Input／AND 直連 Cell input。
    """
    _, or_idx_map = _build_or_catalog(outputs)
    if not or_idx_map:
        return {}
    or_row = _or_row_by_global(or_idx_map, or_index_per_key)
    slack: dict[int, int] = {}
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            tgt_or_g = or_idx_map.get((tgt.name, hl))
            if len(groups) >= 2 and tgt_or_g is not None:
                for gi, group in enumerate(groups):
                    if len(group) != 1:
                        continue
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type != "output":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None or src_row == tgt_row:
                        continue
                    use = (
                        tgt.get_hi_use(gi, 0, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, 0, d)
                    )
                    gap = _nearest_or_or_gap(
                        d,
                        use,
                        tgt_or_g,
                        or_idx_map=or_idx_map,
                        or_row=or_row,
                        output_to_row=output_to_row,
                        name_to_rail=name_to_rail,
                    )
                    _mark_y_gap(slack, gap)
            if len(groups) < 2:
                for gi, group in enumerate(groups):
                    if len(group) < 2:
                        continue
                    gap = _nearest_or_or_gap_for_row(
                        tgt_row,
                        hl,
                        or_idx_map=or_idx_map,
                        or_index_per_key=or_index_per_key,
                    )
                    _mark_y_gap(slack, gap)
            for gi, group in enumerate(groups):
                if len(group) != 1:
                    continue
                d = group[0]
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type != "input":
                    continue
                gap = _nearest_or_or_gap_for_row(
                    tgt_row,
                    hl,
                    or_idx_map=or_idx_map,
                    or_index_per_key=or_index_per_key,
                )
                _mark_y_gap(slack, gap)
    return slack


def _cell_fb_segment3_y_gaps(src_row: int, profile: str) -> list[int]:
    """FB ③ 段 p2y 水平走廊所需 Y 通道 gap（0-based：row j 與 j+1 之間）。

    僅在來源列上方 1～2 格預留；④ 段垂直幹線走 X 通道，不沿 src→tgt 整段加寬。
    profile: ``q``（FB_Q_UP=60）或 ``nq``（FB_NQ_UP=140，可能需第二格）。
    """
    gaps: list[int] = []
    if src_row >= 1:
        gaps.append(src_row - 1)
    if profile == "nq" and src_row >= 2:
        gaps.append(src_row - 2)
    return gaps


def _feedback_y_slack_between_cell_rows(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> dict[int, int]:
    """
    Cell 層：相鄰兩列間隙 +40pt（同一 gap 可累加）。
    觸發：跨列 Cell Q／~Q 回授（use=self、來源為 output）— 含 ~Q→Deb 與 Q→AND。
    僅在 FB ③ 段 p2y 水平走廊（來源列上方 1～2 gap）預留 Y 通道。
    同一來源 Q 與 ~Q 各佔一條走廊（p2y 不同，不共用）；同 profile 多目標扇出去重。
    gap j 表示 row j 與 row j+1 之間（0-based）。
    """
    src_profiles: dict[str, set[str]] = {}
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                for ii, d in enumerate(group):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type != "output":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None or src_row == tgt_row:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use != "self":
                        continue
                    inv = (
                        tgt.get_hi_inv(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_inv(gi, ii, d)
                    )
                    profile = "nq" if inv else "q"
                    src_profiles.setdefault(d, set()).add(profile)

    slack: dict[int, int] = {}
    for d, profiles in src_profiles.items():
        src_row = output_to_row[d]
        for profile in sorted(profiles):
            for gap in _cell_fb_segment3_y_gaps(src_row, profile):
                if gap >= 0:
                    slack[gap] = slack.get(gap, 0) + GRID
    return slack


def _chain_and_top_y(
    row_py: list[int],
    catalog: list[tuple[str, str, int]],
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]],
    feedback_y_slack: dict[int, int],
    name_to_rail: dict[str, PowerRail] | None = None,
) -> dict[int, int]:
    """依 global 序鍊式定位 AND／NAND；slack 只加在相鄰兩顆之間的對應 gap。

    and_index_per_key 第二欄為列內 nominal Y offset（pt）：hi 自 OR_GATE_OFFSET_HI_Y、
    lo 自 OR_GATE_OFFSET_LO_Y，同 hl 多顆再 +idx*AND_GATE_DY。
    """
    tops: dict[int, int] = {}
    for g, key in enumerate(catalog, start=1):
        row_j, ai = and_index_per_key[key]
        py = row_py[row_j]
        nominal = py + ai
        if g == 1:
            tops[g] = nominal
            continue
        prev_row, _ = and_index_per_key[catalog[g - 2]]
        extra = feedback_y_slack.get(g - 1, 0)
        chain = tops[g - 1] + AND_GATE_DY + extra
        if row_j == prev_row and nominal >= tops[g - 1] + AND_GATE_H:
            tops[g] = nominal
        else:
            tops[g] = max(nominal, chain)
    return tops


def _chain_or_top_y(
    row_py: list[int],
    catalog: list[tuple[str, str]],
    or_index_per_key: dict[tuple[str, str], tuple[int, int]],
    feedback_y_slack: dict[int, int],
) -> dict[int, int]:
    """依 global 序鍊式定位 OR／NOR；slack 只加在相鄰兩顆之間的對應 gap。

    與 ``_chain_and_top_y`` 對齊：新列首顆錨定 ``row_py+off``（H_Deb／L_Deb）；
    同列 Hi→Lo 在 nominal 放得下時亦錨定 nominal，否則鍊式下移。
    """
    tops: dict[int, int] = {}
    for g, key in enumerate(catalog, start=1):
        row_j, off = or_index_per_key[key]
        py = row_py[row_j]
        nominal = py + off
        if g == 1:
            tops[g] = nominal
            continue
        prev_row, prev_off = or_index_per_key[catalog[g - 2]]
        extra = feedback_y_slack.get(g - 1, 0)
        if row_j == prev_row:
            if nominal >= tops[g - 1] + OR_GATE_H:
                tops[g] = nominal
            else:
                tops[g] = max(
                    nominal,
                    tops[g - 1] + (off - prev_off) + extra,
                )
        else:
            tops[g] = nominal
    return tops


def _group_output_not(r: PowerRail, hl: str, gi: int) -> bool:
    """整組 AND 結果反相（group_inv）→ 繪製 NAND（negating=1）。"""
    groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
    if gi >= len(groups) or len(groups[gi]) < 2:
        return False
    return r.get_hi_group_inv(gi) if hl == "hi" else r.get_lo_group_inv(gi)


def _or_output_not(r: PowerRail, hl: str) -> bool:
    """OR 路徑（≥2 group）且每組皆單一依賴、全部 group_inv → 繪製 NOR（negating=1）。"""
    groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
    if len(groups) < 2:
        return False
    if any(len(g) >= 2 for g in groups):
        return False
    get_inv = r.get_hi_group_inv if hl == "hi" else r.get_lo_group_inv
    return all(get_inv(gi) for gi in range(len(groups)))


def _and_gate_style(r: PowerRail, hl: str, gi: int) -> str:
    """AND 或 NAND（group_inv）；style 取自 reference/AND1.xml、NAND1.xml。"""
    if _group_output_not(r, hl, gi):
        return _GATE_STYLE_NAND
    return _GATE_STYLE_AND


def _or_gate_style(r: PowerRail, hl: str) -> str:
    """OR 或 NOR；style 取自 reference/OR1.xml、NOR1.xml。"""
    if _or_output_not(r, hl):
        return _GATE_STYLE_NOR
    return _GATE_STYLE_OR


def _count_and_gates_on_row(r: PowerRail) -> int:
    n = 0
    for groups in (r.get_hi_groups(), r.get_lo_groups()):
        for group in groups:
            if len(group) >= 2:
                n += 1
    return n


def _count_or_gates_on_row(r: PowerRail) -> int:
    n = 0
    if len(r.get_hi_groups()) >= 2:
        n += 1
    if len(r.get_lo_groups()) >= 2:
        n += 1
    return n


def _unique_output_sources_in_hilo(
    outputs: list[PowerRail],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    *,
    or_path_only: bool = False,
) -> set[str]:
    """全圖 hi/lo 路徑上，來源為 output 的不重複 signal 名稱（同一 source 只算 1）。"""
    sources: set[str] = set()
    for r in outputs:
        for groups in (r.get_hi_groups(), r.get_lo_groups()):
            if or_path_only and len(groups) < 2:
                continue
            for group in groups:
                for d in group:
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type == "output":
                        sources.add(d)
    return sources


def _count_output_deps_to_hilo(
    r: PowerRail,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """該列 hi/lo 上不重複 output 來源數（同一 source 只算 1）。"""
    sources: set[str] = set()
    for groups in (r.get_hi_groups(), r.get_lo_groups()):
        for group in groups:
            for d in group:
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "output":
                    sources.add(d)
    return len(sources)


def _count_output_deps_to_or_path(
    r: PowerRail,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """有 OR 時：該列 OR 路徑上不重複 output 來源數。"""
    sources: set[str] = set()
    for groups in (r.get_hi_groups(), r.get_lo_groups()):
        if len(groups) < 2:
            continue
        for group in groups:
            for d in group:
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "output":
                    sources.add(d)
    return len(sources)


def _unique_cell_fb_to_deb_sources(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> set[str]:
    """
    Cell fb（DRAWIO_RULES §八）：跨列、use=self 的 output → 下游 H_Deb/L_Deb。
    不含 use=hi/lo 進 Deb、不含進 AND/OR。
    """
    sources: set[str] = set()
    for r in outputs:
        tgt_row = output_to_row[r.name]
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) != 1:
                    continue
                d = group[0]
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type != "output":
                    continue
                src_row = output_to_row.get(d)
                if src_row is None or not _is_cross_row_feedback(src_row, tgt_row):
                    continue
                use = (
                    r.get_hi_use(gi, 0, d)
                    if hl == "hi"
                    else r.get_lo_use(gi, 0, d)
                )
                if use != "self":
                    continue
                sources.add(d)
    return sources


def _count_cell_fb_to_deb(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    return len(_unique_cell_fb_to_deb_sources(outputs, output_to_row, name_to_rail, valid))


def _count_total_output_deps_to_hilo(
    outputs: list[PowerRail],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    return len(_unique_output_sources_in_hilo(outputs, name_to_rail, valid))


def _count_total_output_deps_to_or_path(
    outputs: list[PowerRail],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    return len(_unique_output_sources_in_hilo(outputs, name_to_rail, valid, or_path_only=True))


def _row_has_or_path(r: PowerRail) -> bool:
    return len(r.get_hi_groups()) >= 2 or len(r.get_lo_groups()) >= 2


def _source_row_has_or(
    rail: str,
    hl: str,
    *,
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
) -> bool:
    """來源列在指定 band 是否有 OR 合併（logic_out 為 OR 輸出）。"""
    row = output_to_row.get(rail)
    if row is None:
        return False
    for r in outputs:
        if output_to_row.get(r.name) != row:
            continue
        groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
        if len(groups) >= 2:
            return True
    return False


def _count_and_or_middle_slots(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """
    AND→OR 段中間走線格（不含公式 +2 兩側 GAP）：
    AND 轉角至後級、OR 回授至 OR 輸入（同源去重）、Cell 回授至 OR 輸入（同源去重）。
    """
    _, and_idx_map = _build_and_catalog(outputs)
    and_corners: set[str] = set()
    or_fb_or: set[tuple[str, str]] = set()
    cell_fb_or: set[str] = set()

    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        if not _row_has_or_path(tgt):
            continue
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            if len(groups) < 2:
                continue
            for gi, group in enumerate(groups):
                if len(group) != 1:
                    continue
                d = group[0]
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "input":
                    continue
                src_row = output_to_row.get(d)
                if src_row is None or src_row == tgt_row:
                    continue
                use = (
                    tgt.get_hi_use(gi, 0, d)
                    if hl == "hi"
                    else tgt.get_lo_use(gi, 0, d)
                )
                if use not in ("hi", "lo", "self"):
                    continue
                if _is_cross_row_feedback(src_row, tgt_row):
                    if use == "self" and name_to_rail[d].seq_type == "output":
                        cell_fb_or.add(d)
                    elif use in ("hi", "lo") and _source_row_has_or(
                        d, use, outputs=outputs, output_to_row=output_to_row
                    ):
                        or_fb_or.add((d, use))
                    elif use in ("hi", "lo"):
                        and_corners.add(f"pas:{d}:{use}")
                elif use in ("hi", "lo"):
                    dep_idx = _departing_and_index(
                        d, use, idx_map=and_idx_map, name_to_rail=name_to_rail
                    )
                    if dep_idx is not None:
                        and_corners.add(f"and:{dep_idx}")
    return len(and_corners) + len(or_fb_or) + len(cell_fb_or)


def _count_or_cell_middle_slots(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """
    OR→Cell 段中間走線格（不含公式 +2 兩側 GAP）：
    OR 轉角至後級、OR 回授至 OR／AND 輸入（同源去重）、Cell 回授至 Cell 輸入（同源去重）。
    """
    or_corners: set[tuple[str, str]] = set()
    or_fb_or: set[tuple[str, str]] = set()
    or_fb_and: set[tuple[str, str]] = set()
    cell_fb_cell: set[str] = set()

    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                for ii, d in enumerate(group):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None or src_row == tgt_row:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use not in ("hi", "lo"):
                        continue
                    if not _source_row_has_or(
                        d, use, outputs=outputs, output_to_row=output_to_row
                    ):
                        continue
                    if _is_cross_row_feedback(src_row, tgt_row):
                        if len(group) >= 2:
                            or_fb_and.add((d, use))
                        elif _row_has_or_path(tgt):
                            or_fb_or.add((d, use))
                    elif src_row < tgt_row:
                        if _row_has_or_path(tgt):
                            or_fb_or.add((d, use))
                            or_corners.add((d, use))
                        else:
                            or_corners.add((d, use))
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            if len(groups) != 1:
                continue
            d = groups[0][0]
            if d not in valid or d in CONST_DEPS:
                continue
            if name_to_rail[d].seq_type != "output":
                continue
            src_row = output_to_row.get(d)
            if src_row is None or not _is_cross_row_feedback(src_row, tgt_row):
                continue
            use = (
                tgt.get_hi_use(0, 0, d)
                if hl == "hi"
                else tgt.get_lo_use(0, 0, d)
            )
            if use == "self":
                cell_fb_cell.add(d)

    return len(or_corners) + len(or_fb_or) + len(or_fb_and) + len(cell_fb_cell)


def _count_or_fb_routing_slots(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """OR 目標層 FB X 通道容量（同源去重）。"""
    or_fb_or: set[tuple[str, str]] = set()
    cell_fb_or: set[str] = set()
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        if not _row_has_or_path(tgt):
            continue
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            if len(groups) < 2:
                continue
            for gi, group in enumerate(groups):
                if len(group) != 1:
                    continue
                d = group[0]
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "input":
                    continue
                src_row = output_to_row.get(d)
                if src_row is None or not _is_cross_row_feedback(src_row, tgt_row):
                    continue
                use = (
                    tgt.get_hi_use(gi, 0, d)
                    if hl == "hi"
                    else tgt.get_lo_use(gi, 0, d)
                )
                if use == "self" and name_to_rail[d].seq_type == "output":
                    cell_fb_or.add(d)
                elif use in ("hi", "lo") and _source_row_has_or(
                    d, use, outputs=outputs, output_to_row=output_to_row
                ):
                    or_fb_or.add((d, use))
    return max(1, len(or_fb_or) + len(cell_fb_or))


def _count_total_and_gates(outputs: list[PowerRail]) -> int:
    catalog, _ = _build_and_catalog(outputs)
    return len(catalog)


def _count_total_or_gates(outputs: list[PowerRail]) -> int:
    return sum(_count_or_gates_on_row(r) for r in outputs)


def _output_name_channel_gap(any_output_not: bool) -> int:
    """Cell 右緣至輸出名稱欄：120pt；任一 Cell 有 output NOT 則全圖 200pt。"""
    return OUTPUT_NAME_GAP + (OUTPUT_NAME_NOT_EXTRA if any_output_not else 0)


def _gate_gap_width(
    n_gates: int,
    feedback_signals: int,
    direct_exempt: int = 0,
) -> int:
    """欄間淨空：(n+2+fb-直接水平)*40；NAND/NOR 與 AND/OR 同尺寸，不另加寬。"""
    slots = max(0, n_gates + 2 + feedback_signals - direct_exempt)
    return slots * GRID


def _same_connection_y(a: int, b: int) -> bool:
    return abs(a - b) <= 2


def _deb_center_y(row_py: int, hl: str) -> int:
    if hl == "hi":
        return row_py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
    return row_py + CELL_L_DEB_Y + CELL_L_DEB_H // 2


def _or_center_y(row_py: int, hl: str) -> int:
    if hl == "hi":
        return row_py + OR_GATE_OFFSET_HI_Y + OR_GATE_H // 2
    return row_py + OR_GATE_OFFSET_LO_Y + OR_GATE_H // 2


def _or_chained_center_y(
    rail: str,
    hl: str,
    *,
    output_to_row: dict[str, int],
    or_idx_map: dict[tuple[str, str], int],
    or_top_y: dict[int, int],
    row_py: list[int],
) -> int:
    g = or_idx_map.get((rail, hl))
    if g is not None:
        return or_top_y[g] + OR_GATE_H // 2
    row_j = output_to_row[rail]
    return _or_center_y(row_py[row_j], hl)


def _output_has_cross_row_and_feedback(
    src_rail: str,
    *,
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> bool:
    """上游 output 是否跨列回授到其他列 AND input（必走垂直，不可 exempt）。"""
    src_row = output_to_row[src_rail]
    for tgt in outputs:
        if output_to_row[tgt.name] == src_row:
            continue
        for tgt_hl in ("hi", "lo"):
            groups = tgt.get_hi_groups() if tgt_hl == "hi" else tgt.get_lo_groups()
            for gi, group in enumerate(groups):
                if len(group) < 2:
                    continue
                for ii, d in enumerate(group):
                    if d != src_rail or d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type != "output":
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if tgt_hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use in ("hi", "lo", "self"):
                        return True
    return False


def _count_hi_lo_fanout_from_rail(
    source_rail: str,
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """下游以 use=hi/lo 引用 source_rail 邏輯輸出的邊數（Pass 1 扇出）。"""
    n = 0
    for tgt in outputs:
        if tgt.name == source_rail:
            continue
        for hl in ("hi", "lo"):
            groups = tgt.get_hi_groups() if hl == "hi" else tgt.get_lo_groups()
            for gi, group in enumerate(groups):
                for ii, d in enumerate(group):
                    if d != source_rail or d not in valid or d in CONST_DEPS:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use in ("hi", "lo"):
                        n += 1
    return n


def _and_primary_output_horizontal(
    key: tuple[str, str, int],
    *,
    name_to_rail: dict[str, PowerRail],
    output_to_row: dict[str, int],
    and_top_y: dict[int, int],
    idx_map: dict[tuple[str, str, int], int],
    row_py: list[int],
    or_idx_map: dict[tuple[str, str], int] | None,
    or_top_y: dict[int, int] | None,
) -> bool:
    rail, hl, _gi = key
    r = name_to_rail[rail]
    g = idx_map[key]
    and_cy = and_top_y[g] + AND_GATE_H // 2
    row_j = output_to_row[rail]
    all_hl = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
    if len(all_hl) >= 2:
        if or_idx_map is not None and or_top_y is not None:
            tgt_cy = _or_chained_center_y(
                rail, hl,
                output_to_row=output_to_row,
                or_idx_map=or_idx_map,
                or_top_y=or_top_y,
                row_py=row_py,
            )
        else:
            tgt_cy = _or_center_y(row_py[row_j], hl)
    else:
        tgt_cy = _deb_center_y(row_py[row_j], hl)
    return _same_connection_y(and_cy, tgt_cy)


def _gate_needs_stub_lane_and(
    key: tuple[str, str, int],
    *,
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    and_top_y: dict[int, int],
    idx_map: dict[tuple[str, str, int], int],
    row_py: list[int],
    or_idx_map: dict[tuple[str, str], int] | None,
    or_top_y: dict[int, int] | None,
) -> bool:
    """False = 僅一條水平直連 output，不佔 stub lane 序 n。"""
    rail, hl, _gi = key
    fanout = _count_hi_lo_fanout_from_rail(
        rail, outputs, output_to_row, name_to_rail, valid
    )
    total = 1 + fanout
    if total != 1:
        return True
    return not _and_primary_output_horizontal(
        key,
        name_to_rail=name_to_rail,
        output_to_row=output_to_row,
        and_top_y=and_top_y,
        idx_map=idx_map,
        row_py=row_py,
        or_idx_map=or_idx_map,
        or_top_y=or_top_y,
    )


def _gate_needs_stub_lane_or(
    key: tuple[str, str],
    *,
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    or_top_y: dict[int, int],
    or_idx_map: dict[tuple[str, str], int],
    row_py: list[int],
) -> bool:
    rail, hl = key
    fanout = _count_hi_lo_fanout_from_rail(
        rail, outputs, output_to_row, name_to_rail, valid
    )
    total = 1 + fanout
    if total != 1:
        return True
    g = or_idx_map[key]
    or_cy = or_top_y[g] + OR_GATE_H // 2
    deb_cy = _deb_center_y(row_py[output_to_row[rail]], hl)
    return not _same_connection_y(or_cy, deb_cy)


def _build_gate_lane_indices(
    outputs: list[PowerRail],
    catalog: list[tuple[str, str, int]],
    idx_map: dict[tuple[str, str, int], int],
    or_catalog: list[tuple[str, str]],
    or_idx_map: dict[tuple[str, str], int],
    *,
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    and_top_y: dict[int, int],
    or_top_y: dict[int, int],
    row_py: list[int],
) -> tuple[dict[tuple[str, str, int], int | None], dict[tuple[str, str], int | None]]:
    """AND/OR catalog key → stub lane 序 n（None=不佔 lane；非 None 時 stub=(1+n)×40）。"""
    and_lane: dict[tuple[str, str, int], int | None] = {}
    lane = 0
    for key in catalog:
        if _gate_needs_stub_lane_and(
            key,
            outputs=outputs,
            output_to_row=output_to_row,
            name_to_rail=name_to_rail,
            valid=valid,
            and_top_y=and_top_y,
            idx_map=idx_map,
            row_py=row_py,
            or_idx_map=or_idx_map,
            or_top_y=or_top_y,
        ):
            lane += 1
            and_lane[key] = lane
        else:
            and_lane[key] = None
    # OR 層 stub lane 在「OR→Cell gap」獨立計數（與 AND→OR gap 不同物理通道區），
    # 故歸零重數；不可沿用 AND 的全域序，否則 OR 出口通道整批右移、擠到 Cell 欄邊界。
    or_lane: dict[tuple[str, str], int | None] = {}
    lane = 0
    for key in or_catalog:
        if _gate_needs_stub_lane_or(
            key,
            outputs=outputs,
            output_to_row=output_to_row,
            name_to_rail=name_to_rail,
            valid=valid,
            or_top_y=or_top_y,
            or_idx_map=or_idx_map,
            row_py=row_py,
        ):
            lane += 1
            or_lane[key] = lane
        else:
            or_lane[key] = None
    return and_lane, or_lane


def _find_dep_group_index(
    tgt_rail: str,
    dep_name: str,
    hl: str,
    name_to_rail: dict[str, PowerRail],
) -> int:
    r = name_to_rail[tgt_rail]
    groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
    for gi, group in enumerate(groups):
        if dep_name in group:
            return gi
    return 0


def _count_direct_horizontal_exempts(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]],
    idx_map: dict[tuple[str, str, int], int],
    and_top_y: dict[int, int],
    row_py: list[int],
    or_idx_map: dict[tuple[str, str], int] | None = None,
    or_top_y: dict[int, int] | None = None,
) -> tuple[int, int, int]:
    """
    同列、同 Y、且無跨列回授到其他 AND → 可少留 1 格（40pt）。
    回授到前一級 AND 必走垂直，不得 exempt。
    回傳 (and→or 豁免數, and→cell 豁免數, or→cell 豁免數)。
    """
    exempt_ao = 0
    exempt_ac = 0
    exempt_oc = 0

    for key, g in idx_map.items():
        rail, hl, gi = key
        r = name_to_rail[rail]
        groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
        if len(groups[gi]) < 2:
            continue
        if _output_has_cross_row_and_feedback(
            rail, outputs=outputs, output_to_row=output_to_row,
            name_to_rail=name_to_rail, valid=valid,
        ):
            continue
        row_j = output_to_row[rail]
        and_cy = and_top_y[g] + AND_GATE_H // 2
        all_hl_groups = r.get_hi_groups() if hl == "hi" else r.get_lo_groups()
        if len(all_hl_groups) >= 2:
            if or_idx_map is not None and or_top_y is not None:
                tgt_cy = _or_chained_center_y(
                    rail, hl,
                    output_to_row=output_to_row,
                    or_idx_map=or_idx_map,
                    or_top_y=or_top_y,
                    row_py=row_py,
                )
            else:
                tgt_cy = _or_center_y(row_py[row_j], hl)
            if _same_connection_y(and_cy, tgt_cy):
                exempt_ao += 1
        else:
            tgt_cy = _deb_center_y(row_py[row_j], hl)
            if _same_connection_y(and_cy, tgt_cy):
                exempt_ac += 1

    for r in outputs:
        row_j = output_to_row[r.name]
        py = row_py[row_j]
        hi_groups = r.get_hi_groups()
        lo_groups = r.get_lo_groups()
        if len(hi_groups) >= 2:
            hi_cy = (
                _or_chained_center_y(
                    r.name, "hi",
                    output_to_row=output_to_row,
                    or_idx_map=or_idx_map,
                    or_top_y=or_top_y,
                    row_py=row_py,
                )
                if or_idx_map is not None and or_top_y is not None
                else _or_center_y(py, "hi")
            )
            if _same_connection_y(hi_cy, _deb_center_y(py, "hi")):
                exempt_oc += 1
        if len(lo_groups) >= 2:
            lo_cy = (
                _or_chained_center_y(
                    r.name, "lo",
                    output_to_row=output_to_row,
                    or_idx_map=or_idx_map,
                    or_top_y=or_top_y,
                    row_py=row_py,
                )
                if or_idx_map is not None and or_top_y is not None
                else _or_center_y(py, "lo")
            )
            if _same_connection_y(lo_cy, _deb_center_y(py, "lo")):
                exempt_oc += 1

    return exempt_ao, exempt_ac, exempt_oc


@dataclass
class _RowGateLayout:
    has_or: bool
    cell_start_x: int
    or_col_x: int | None
    gap_after_and: int


def _compute_row_gate_layouts(
    outputs: list[PowerRail],
    and_col_x: int,
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
    *,
    output_to_row: dict[str, int],
    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]],
    idx_map: dict[tuple[str, str, int], int],
    and_top_y: dict[int, int],
    row_py: list[int],
    or_idx_map: dict[tuple[str, str], int] | None = None,
    or_top_y: dict[int, int] | None = None,
) -> dict[str, _RowGateLayout]:
    """n / m / fb 皆為全圖總數；同 Y 直連可各減 1 格。"""
    n_and_total = _count_total_and_gates(outputs)
    m_or_total = _count_total_or_gates(outputs)
    fb_cell_total = _count_cell_fb_to_deb(outputs, output_to_row, name_to_rail, valid)
    and_or_middle = _count_and_or_middle_slots(
        outputs, output_to_row, name_to_rail, valid
    )
    or_cell_middle = _count_or_cell_middle_slots(
        outputs, output_to_row, name_to_rail, valid
    )
    exempt_ao, exempt_ac, exempt_oc = _count_direct_horizontal_exempts(
        outputs,
        output_to_row,
        name_to_rail,
        valid,
        and_index_per_key,
        idx_map,
        and_top_y,
        row_py,
        or_idx_map=or_idx_map,
        or_top_y=or_top_y,
    )
    gap_and_cell = _gate_gap_width(n_and_total, fb_cell_total, exempt_ac)
    # 走線格模型：中間格數已含轉角／回授去重，不再扣 exempt（§八 base=n 模型才扣）
    gap_and_or = _gate_gap_width(0, and_or_middle, 0)
    gap_or_cell = _gate_gap_width(0, or_cell_middle, 0)
    # 全圖任一列有 OR/NOR → 所有 Cell 對齊結構 B（保留 OR 欄位），非僅有 OR 的列後移。
    diagram_has_or = m_or_total > 0
    or_col_x_global: int | None = None
    cell_x_structure_b: int | None = None
    if diagram_has_or:
        or_col_x_global = _align40(and_col_x + AND_GATE_W + gap_and_or)
        cell_x_structure_b = _align40(or_col_x_global + OR_GATE_W + gap_or_cell)
    layouts: dict[str, _RowGateLayout] = {}
    for r in outputs:
        m_or_row = _count_or_gates_on_row(r)
        if diagram_has_or:
            assert or_col_x_global is not None and cell_x_structure_b is not None
            layouts[r.name] = _RowGateLayout(
                has_or=m_or_row > 0,
                cell_start_x=cell_x_structure_b,
                or_col_x=or_col_x_global,
                gap_after_and=gap_and_or,
            )
        else:
            cell_x = _align40(and_col_x + AND_GATE_W + gap_and_cell)
            layouts[r.name] = _RowGateLayout(
                has_or=False,
                cell_start_x=cell_x,
                or_col_x=None,
                gap_after_and=gap_and_cell,
            )
    return layouts


def _layout_input_positions(
    used_inputs_list: list[str],
    inputs_with_not: set[str],
    band_right_x: int,
    input_row_y: int,
) -> dict[str, tuple[int, int]]:
    """依 ``config.rails`` 宣告順序由右→左：第 1 個最右；每欄 40pt；前一個有 NOT 則下一個再左 40pt。"""
    positions: dict[str, tuple[int, int]] = {}
    x = band_right_x
    for i, name in enumerate(used_inputs_list):
        if i > 0 and used_inputs_list[i - 1] in inputs_with_not:
            x -= GRID
        x -= INPUT_SLOT_W
        positions[name] = (_align40(x), input_row_y)
    return positions


def _q_right_x(cell_xy: tuple[int, int]) -> int:
    cx, cy = cell_xy
    return cx + CELL_Q_X + CELL_Q_W


def _nq_right_x(cell_xy: tuple[int, int]) -> int:
    cx, cy = cell_xy
    return cx + CELL_NQ_X + CELL_NQ_W


def _coerce_cell_out_id(
    dep_rail: str,
    fid: int,
    *,
    inv: bool,
    out_inner_id: dict[str, int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
) -> int:
    """inner 佔位改綁 Q／~Q（~Q 右緣 = 原 output NOT 輸出）。"""
    if fid == out_inner_id.get(dep_rail):
        return nq_box_id_map[dep_rail] if inv else q_box_id_map[dep_rail]
    if inv and fid == q_box_id_map.get(dep_rail):
        return nq_box_id_map[dep_rail]
    return fid


def _input_to_not_waypoints(
    label_xy: tuple[int, int],
    not_xy: tuple[int, int],
) -> list[tuple[int, int]]:
    """label→NOT（皆 rotation=90）：先下後右。"""
    lx, ly = label_xy
    nx, ny = not_xy
    bus = _input_bus_x(lx)
    ay = _input_label_center_y(ly)
    ncy = ny + NOT_GATE_H // 2
    pts: list[tuple[int, int]] = [(bus, ay), (bus, ncy)]
    if nx != bus:
        pts.append((nx, ncy))
    return pts


def _logic_source_right_x(
    src_id: int,
    *,
    inner_id_to_output: dict[int, str],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    positions_out: dict[str, tuple[int, int]],
    gate_right_x: dict[int, int],
    and_col_x: int,
) -> int:
    """邏輯邊起點右緣：Q／~Q 或閘右緣。"""
    for rail, qid in q_box_id_map.items():
        if src_id == qid:
            return _q_right_x(positions_out[rail])
    for rail, nqid in nq_box_id_map.items():
        if src_id == nqid:
            return _nq_right_x(positions_out[rail])
    out_name = inner_id_to_output.get(src_id)
    if out_name:
        cell_x, _ = positions_out[out_name]
        return cell_x + CELL_INNER_X + CELL_INNER_W
    return gate_right_x.get(src_id, and_col_x + AND_GATE_W)


def _not_source_to_not_waypoints(
    *,
    anchor_cy: int,
    turn_x: int,
    not_left: int,
    not_cy: int,
) -> list[tuple[int, int]]:
    """O→NOT（未旋轉）：右側水平 → 下折 → 水平進 NOT。"""
    pts: list[tuple[int, int]] = [(turn_x, anchor_cy), (turn_x, not_cy)]
    if not_left != turn_x:
        pts.append((not_left, not_cy))
    return pts


class _GateExitLanes:
    """每顆 AND/OR/NOR 的 output：先向右 (1+n)×40pt，再轉向。

    n＝該閘在**所屬層的 stub lane gap 內**的本地序（AND→OR gap 與 OR→Cell gap
    各自從頭數，見 `_build_gate_lane_indices`）；**不可**沿用跨層的全域序，否則
    OR 出口通道會被 AND 佔掉的格數整批右推、擠到 Cell 欄邊界。同一閘的正向與回授
    共用這條 lane。"""

    def __init__(self) -> None:
        self._catalog_n: dict[int, int] = {}
        self._edge_n: dict[int, int] = {}

    def set_catalog_n(self, entity_id: int, catalog_n: int) -> None:
        self._catalog_n[entity_id] = catalog_n

    def catalog_stub_items(self) -> dict[int, int]:
        """entity_id → 出發水平段長度 (1+n)×GRID。"""
        return {eid: (1 + n) * GRID for eid, n in self._catalog_n.items()}

    def stub_x(self, entity_id: int, entity_right: int) -> int:
        if entity_id in self._catalog_n:
            n = self._catalog_n[entity_id]
            return _align40(entity_right + (1 + n) * GRID)
        k = self._edge_n.get(entity_id, 0) + 1
        self._edge_n[entity_id] = k
        return _align40(entity_right + k * GRID)

    def wire_vertical(
        self,
        geo: ET.Element,
        entity_id: int,
        entity_right: int,
        src_y: int,
        tgt_y: int,
    ) -> None:
        if abs(src_y - tgt_y) < 2:
            return
        lx = self.stub_x(entity_id, entity_right)
        _add_edge_points(geo, [(lx, src_y), (lx, tgt_y)], align=[False, True])

    def wire_vertical_chain(
        self,
        geo: ET.Element,
        entity_id: int,
        entity_right: int,
        ys: list[int],
    ) -> None:
        """同一 stub x 上多段垂直折線（跨列 bypass 等）。"""
        if len(ys) < 2:
            return
        lx = self.stub_x(entity_id, entity_right)
        _add_edge_points(geo, [(lx, y) for y in ys], align=[False] + [True] * (len(ys) - 1))

    def wire_hv_to(
        self,
        geo: ET.Element,
        entity_id: int,
        entity_right: int,
        src_y: int,
        mid_y: int,
        end_x: int,
        end_y: int,
    ) -> None:
        lx = self.stub_x(entity_id, entity_right)
        _add_edge_points(
            geo,
            [(lx, src_y), (lx, mid_y), (end_x, mid_y), (end_x, end_y)],
            align=[False, True, True, True],
        )

    def wire_via_channel(
        self,
        geo: ET.Element,
        entity_id: int,
        entity_right: int,
        src_y: int,
        entry_x: int,
        entry_y: int,
        *,
        max_lx: int | None = None,
    ) -> None:
        """跨列：先 (1+n)×40 stub lane → 垂直到 entry Y → 水平進 entry（若 lx≠entry_x）。
        max_lx：限制 stub 不可超過此 x（保證最後一段為水平向右進入 entry）。"""
        lx = self.stub_x(entity_id, entity_right)
        if max_lx is not None and lx > max_lx:
            lx = _align40(max_lx)
        pts: list[tuple[int, int]] = [(lx, src_y), (lx, entry_y)]
        if entry_x != lx:
            pts.append((entry_x, entry_y))
        _add_edge_points(geo, pts, align=False)


def _register_gate_catalog(lanes: _GateExitLanes, gate_id: int, catalog_n: int | None) -> None:
    if catalog_n is not None:
        lanes.set_catalog_n(gate_id, catalog_n)


def _mark_layout_feedback_edge(
    edge_ids: set[str],
    edge_id: str,
    *,
    layout_feedback_dep_keys: set[LayoutFeedbackDepKey],
    tgt_rail: str,
    hl: str,
    gi: int,
    ii: int,
    dep_name: str,
) -> bool:
    """佈局回授邊：匯出後改 orthogonalEdgeStyle 並清 waypoints。"""
    if (tgt_rail, hl, gi, ii, dep_name) not in layout_feedback_dep_keys:
        return False
    edge_ids.add(edge_id)
    return True


def _resolved_logic_pin(
    from_id: int,
    dep_name: str,
    use_mode: str,
    *,
    hi_logic_out_id: dict[str, int],
    lo_logic_out_id: dict[str, int],
) -> int:
    """use=hi/lo 時取已回溯的 logic_out 輸出腳。"""
    if use_mode == "hi" and dep_name in hi_logic_out_id:
        return hi_logic_out_id[dep_name]
    if use_mode == "lo" and dep_name in lo_logic_out_id:
        return lo_logic_out_id[dep_name]
    return from_id


def _logic_pin_row(
    pin_id: int,
    *,
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    output_to_row: dict[str, int],
) -> tuple[str | None, int | None]:
    """邏輯輸出腳 (Q/~Q/AND/OR) 所屬 rail 與列。"""
    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}
    if pin_id in q_rev:
        r = q_rev[pin_id]
        return r, output_to_row.get(r)
    if pin_id in nq_rev:
        r = nq_rev[pin_id]
        return r, output_to_row.get(r)
    and_rev = {v: k for k, v in and_gate_id.items()}
    if pin_id in and_rev:
        r = and_rev[pin_id][0]
        return r, output_to_row.get(r)
    or_rev = {v: k for k, v in or_gate_id.items()}
    if pin_id in or_rev:
        r = or_rev[pin_id][0]
        return r, output_to_row.get(r)
    if pin_id in inner_id_to_row:
        r = inner_id_to_output.get(pin_id)
        return r, inner_id_to_row.get(pin_id)
    rail = inner_id_to_output.get(pin_id)
    if rail is not None:
        return rail, output_to_row.get(rail)
    return None, None


def _mark_traced_layout_feedback_edge(
    edge_ids: set[str],
    edge_id: str,
    from_id: int,
    dep_name: str,
    use_mode: str,
    tgt_rail: str,
    hl: str,
    gi: int,
    ii: int,
    *,
    layout_feedback_dep_keys: set[LayoutFeedbackDepKey],
    output_to_row: dict[str, int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    hi_logic_out_id: dict[str, int],
    lo_logic_out_id: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    and_idx_map: dict[tuple[str, str, int], int],
    name_to_rail: dict[str, PowerRail],
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    tgt_layer: str = "and",
) -> bool:
    """佈局回授鍵或回溯後跨列輸出腳（Q use=self、~Q inv、AND Output）。"""
    if _mark_layout_feedback_edge(
        edge_ids,
        edge_id,
        layout_feedback_dep_keys=layout_feedback_dep_keys,
        tgt_rail=tgt_rail,
        hl=hl,
        gi=gi,
        ii=ii,
        dep_name=dep_name,
    ):
        return True
    pin_id = _resolved_logic_pin(
        from_id,
        dep_name,
        use_mode,
        hi_logic_out_id=hi_logic_out_id,
        lo_logic_out_id=lo_logic_out_id,
    )
    pin_rail, src_row = _logic_pin_row(
        pin_id,
        q_box_id_map=q_box_id_map,
        nq_box_id_map=nq_box_id_map,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
        inner_id_to_row=inner_id_to_row,
        inner_id_to_output=inner_id_to_output,
        output_to_row=output_to_row,
    )
    tgt_row = output_to_row.get(tgt_rail)
    if src_row is None or tgt_row is None:
        return False
    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}
    # Cell Q：use=self 跨列皆走 Q FB profile（② 先上 60pt；含 RSMRST → 下游 hi AND）
    if pin_id in q_rev and use_mode == "self" and src_row != tgt_row:
        edge_ids.add(edge_id)
        return True
    # Cell ~Q：inv 跨列回授（src_row > tgt_row）
    if pin_id in nq_rev and _is_cross_row_feedback(src_row, tgt_row):
        edge_ids.add(edge_id)
        return True
    or_rev = {v: k for k, v in or_gate_id.items()}
    # OR/NOR → OR/NOR：跨列 hi/lo 路徑（含下游列 OR 合併）皆走 FB
    if tgt_layer == "or" and pin_id in or_rev and src_row != tgt_row:
        edge_ids.add(edge_id)
        return True
    if not _is_cross_row_feedback(src_row, tgt_row):
        return False
    and_rev = {v: k for k, v in and_gate_id.items()}
    if tgt_layer == "and" and pin_id in and_rev:
        src_rail, src_hl, _ = and_rev[pin_id]
        if _departing_and_index(
            src_rail, src_hl, idx_map=and_idx_map, name_to_rail=name_to_rail
        ) is not None:
            edge_ids.add(edge_id)
            return True
    if use_mode in ("hi", "lo") and pin_rail and pin_rail != dep_name:
        if pin_rail == "RSMRST_N":
            edge_ids.add(edge_id)
            return True
        if _departing_and_index(
            pin_rail, use_mode, idx_map=and_idx_map, name_to_rail=name_to_rail
        ) is not None:
            edge_ids.add(edge_id)
            return True
    return False


def _supplement_traced_feedback_edges(
    root: ET.Element,
    feedback_auto_edge_ids: set[str],
    *,
    output_to_row: dict[str, int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    and_idx_map: dict[tuple[str, str, int], int],
    name_to_rail: dict[str, PowerRail],
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    deb_tgt_row: dict[int, int],
) -> None:
    """Pass 1 後補標：Cell Q（任意跨列）、~Q／AND／OR 回授邊。"""
    and_rev = {v: k for k, v in and_gate_id.items()}
    or_rev = {v: k for k, v in or_gate_id.items()}
    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}

    def _tgt_row(tgt_id: int) -> int | None:
        if tgt_id in and_rev:
            return output_to_row.get(and_rev[tgt_id][0])
        if tgt_id in or_rev:
            return output_to_row.get(or_rev[tgt_id][0])
        if tgt_id in deb_tgt_row:
            return deb_tgt_row[tgt_id]
        return None

    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid is None or eid in feedback_auto_edge_ids:
            continue
        try:
            src_id = int(cell.get("source") or "")
            tgt_id = int(cell.get("target") or "")
        except ValueError:
            continue
        if tgt_id not in and_rev and tgt_id not in or_rev:
            continue
        tgt_row = _tgt_row(tgt_id)
        if tgt_row is None:
            continue
        _, src_row = _logic_pin_row(
            src_id,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
            and_gate_id=and_gate_id,
            or_gate_id=or_gate_id,
            inner_id_to_row=inner_id_to_row,
            inner_id_to_output=inner_id_to_output,
            output_to_row=output_to_row,
        )
        if src_row is None or tgt_row is None or src_row == tgt_row:
            continue
        if src_id in and_rev and tgt_id in or_rev:
            continue
        if src_id in q_rev:
            feedback_auto_edge_ids.add(eid)
            continue
        if src_id in nq_rev:
            if not _is_cross_row_feedback(src_row, tgt_row):
                continue
            feedback_auto_edge_ids.add(eid)
            continue
        if src_id in or_rev and tgt_id in or_rev:
            feedback_auto_edge_ids.add(eid)
            continue
        if not _is_cross_row_feedback(src_row, tgt_row):
            continue
        if src_id in and_rev:
            src_rail, src_hl, _ = and_rev[src_id]
            if _departing_and_index(
                src_rail, src_hl, idx_map=and_idx_map, name_to_rail=name_to_rail
            ) is not None:
                feedback_auto_edge_ids.add(eid)
                continue
        if src_id in or_rev:
            feedback_auto_edge_ids.add(eid)


def _dep_source_row(
    from_id: int,
    dep_name: str,
    *,
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    output_to_row: dict[str, int],
) -> int | None:
    """依赖边来源所在 Cell 列（含 logic 闸：依 dep output rail 或 inner cell）。"""
    row = inner_id_to_row.get(from_id)
    if row is not None:
        return row
    rail = inner_id_to_output.get(from_id)
    if rail is not None:
        return output_to_row.get(rail)
    return output_to_row.get(dep_name)


def _logic_gate_source_row(
    gate_id: int,
    dep_name: str,
    *,
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int] | None = None,
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    output_to_row: dict[str, int],
) -> int | None:
    """邏輯閘或 cell 所在列（AND／OR 閘依其 rail key）。"""
    and_rev = {v: k for k, v in and_gate_id.items()}
    if gate_id in and_rev:
        return output_to_row.get(and_rev[gate_id][0])
    if or_gate_id is not None:
        or_rev = {v: k for k, v in or_gate_id.items()}
        if gate_id in or_rev:
            return output_to_row.get(or_rev[gate_id][0])
    return _dep_source_row(
        gate_id,
        dep_name,
        inner_id_to_row=inner_id_to_row,
        inner_id_to_output=inner_id_to_output,
        output_to_row=output_to_row,
    )


def _and_dep_effective_source_row(
    from_id: int,
    dep_name: str,
    use_mode: str,
    *,
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    output_to_row: dict[str, int],
    hi_logic_out_id: dict[str, int],
    lo_logic_out_id: dict[str, int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int] | None = None,
    or_gate_id: dict[tuple[str, str], int] | None = None,
) -> int | None:
    """use=hi/lo 時依透傳後的邏輯來源列（如 RSMRST_N 扇出至上游 AND／OR）。"""
    if use_mode == "hi" and dep_name in hi_logic_out_id:
        eff_id = hi_logic_out_id[dep_name]
    elif use_mode == "lo" and dep_name in lo_logic_out_id:
        eff_id = lo_logic_out_id[dep_name]
    else:
        eff_id = from_id
    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}
    if eff_id in q_rev:
        return output_to_row.get(q_rev[eff_id])
    if eff_id in nq_rev:
        return output_to_row.get(nq_rev[eff_id])
    if and_gate_id is not None:
        and_rev = {v: k for k, v in and_gate_id.items()}
        if eff_id in and_rev:
            return output_to_row.get(and_rev[eff_id][0])
    if or_gate_id is not None:
        or_rev = {v: k for k, v in or_gate_id.items()}
        if eff_id in or_rev:
            return output_to_row.get(or_rev[eff_id][0])
    if eff_id in inner_id_to_row:
        return inner_id_to_row[eff_id]
    rail = inner_id_to_output.get(eff_id)
    if rail is not None:
        return output_to_row.get(rail)
    return output_to_row.get(dep_name)


def _wire_and_dep_non_input(
    geo: ET.Element,
    eid: str,
    from_id: int,
    dep_name: str,
    and_y: int,
    rail_name: str,
    hl: str,
    gi: int,
    ii: int,
    *,
    use_mode: str,
    layout_feedback_dep_keys: set[LayoutFeedbackDepKey],
    feedback_auto_edge_ids: set[str],
    inner_id_to_row: dict[int, int],
    inner_id_to_output: dict[int, str],
    output_to_row: dict[str, int],
    hi_logic_out_id: dict[str, int],
    lo_logic_out_id: dict[str, int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    and_idx_map: dict[tuple[str, str, int], int],
    name_to_rail: dict[str, PowerRail],
    positions_out: dict[str, tuple[int, int]],
    id_to_y_center: dict[int, int],
    gate_exit_lanes: _GateExitLanes,
    gate_right_x: dict[int, int],
    and_col_x: int,
) -> None:
    """非 input 依賴 → AND 入邊：佈局／回溯回授僅標記；其餘正向跨列 wire_via_channel。"""
    if _mark_traced_layout_feedback_edge(
        feedback_auto_edge_ids,
        eid,
        from_id,
        dep_name,
        use_mode,
        rail_name,
        hl,
        gi,
        ii,
        layout_feedback_dep_keys=layout_feedback_dep_keys,
        output_to_row=output_to_row,
        q_box_id_map=q_box_id_map,
        nq_box_id_map=nq_box_id_map,
        hi_logic_out_id=hi_logic_out_id,
        lo_logic_out_id=lo_logic_out_id,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
        and_idx_map=and_idx_map,
        name_to_rail=name_to_rail,
        inner_id_to_row=inner_id_to_row,
        inner_id_to_output=inner_id_to_output,
    ):
        return
    pin_id = _resolved_logic_pin(
        from_id,
        dep_name,
        use_mode,
        hi_logic_out_id=hi_logic_out_id,
        lo_logic_out_id=lo_logic_out_id,
    )
    tgt_row = output_to_row[rail_name]
    src_row = _and_dep_effective_source_row(
        pin_id,
        dep_name,
        use_mode,
        inner_id_to_row=inner_id_to_row,
        inner_id_to_output=inner_id_to_output,
        output_to_row=output_to_row,
        hi_logic_out_id=hi_logic_out_id,
        lo_logic_out_id=lo_logic_out_id,
        q_box_id_map=q_box_id_map,
        nq_box_id_map=nq_box_id_map,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
    )
    if src_row is None:
        _, src_row = _logic_pin_row(
            pin_id,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
            and_gate_id=and_gate_id,
            or_gate_id=or_gate_id,
            inner_id_to_row=inner_id_to_row,
            inner_id_to_output=inner_id_to_output,
            output_to_row=output_to_row,
        )
    if src_row is not None and src_row < tgt_row:
        _sy = id_to_y_center.get(pin_id, and_y)
        _right = _logic_source_right_x(
            pin_id,
            inner_id_to_output=inner_id_to_output,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
            positions_out=positions_out,
            gate_right_x=gate_right_x,
            and_col_x=and_col_x,
        )
        gate_exit_lanes.wire_via_channel(geo, pin_id, _right, _sy, and_col_x, and_y)
        return
    out_name = inner_id_to_output.get(pin_id)
    if out_name:
        cell_x, cell_y = positions_out.get(out_name, (0, 0))
        cell_right_x = _q_right_x((cell_x, cell_y))
        cy = cell_y + CELL_Q_Y + CELL_Q_H // 2
        turn_y = _align40((cy + and_y) // 2)
        gate_exit_lanes.wire_hv_to(
            geo, pin_id, cell_right_x, cy, turn_y, and_col_x, and_y
        )
    else:
        _sy = id_to_y_center.get(pin_id, and_y)
        _right = _logic_source_right_x(
            pin_id,
            inner_id_to_output=inner_id_to_output,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
            positions_out=positions_out,
            gate_right_x=gate_right_x,
            and_col_x=and_col_x,
        )
        gate_exit_lanes.wire_vertical(geo, pin_id, _right, _sy, and_y)


def _wire_and_or_output(
    lanes: _GateExitLanes,
    geo: ET.Element,
    src_id: int,
    src_y: int,
    tgt_y: int,
    gate_right: int,
) -> None:
    """AND/NOR output → 下一級 input：同 Y 水平直連；否則先 (1+n)×40pt 再轉。"""
    if abs(src_y - tgt_y) < 2:
        return
    lanes.wire_vertical(geo, src_id, gate_right, src_y, tgt_y)


def _clear_edge_waypoints(geo: ET.Element | None) -> None:
    if geo is None:
        return
    for arr in list(geo):
        if arr.tag == "Array" and arr.get("as") == "points":
            geo.remove(arr)


def _pass1_real_source_row(
    real_id: int,
    upstream_rail: str,
    *,
    inner_id_to_row: dict[int, int],
    hi_logic_out_id: dict[str, int],
    lo_logic_out_id: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    output_to_row: dict[str, int],
) -> int | None:
    """Pass 1 替換後真實來源列（use=hi/lo 透傳時可能與佔位 rail 不同列）。"""
    logic_out_row: dict[int, int] = {}
    for rname, gid in {**hi_logic_out_id, **lo_logic_out_id}.items():
        logic_out_row[gid] = output_to_row[rname]
    and_rev = {v: k for k, v in and_gate_id.items()}
    or_rev = {v: k for k, v in or_gate_id.items()}
    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}
    if real_id in q_rev:
        return output_to_row.get(q_rev[real_id])
    if real_id in nq_rev:
        return output_to_row.get(nq_rev[real_id])
    if real_id in logic_out_row:
        return logic_out_row[real_id]
    if real_id in and_rev:
        return output_to_row.get(and_rev[real_id][0])
    if real_id in or_rev:
        return output_to_row.get(or_rev[real_id][0])
    if real_id in inner_id_to_row:
        return inner_id_to_row[real_id]
    return output_to_row.get(upstream_rail)


def _rewire_pass1_logic_edge(
    geo: ET.Element | None,
    src_id: int,
    tgt_id: int,
    *,
    upstream_rail: str,
    hl: str,
    gate_exit_lanes: _GateExitLanes,
    gate_right_x: dict[int, int],
    id_to_y_center: dict[int, int],
    output_to_row: dict[str, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    h_deb_id_map: dict[str, int],
    l_deb_id_map: dict[str, int],
    and_col_x: int,
    or_col_x_fn,
    row_py: list[int],
    deb_entry_x_fn,
    row_bottom_fn,
    name_to_rail: dict[str, PowerRail],
    entry_ay: float = 0.5,
) -> None:
    """Pass 1 將 source 換成邏輯閘後，依 stub lane 重繞（修正 placeholder 時的 cell stub）。"""
    if geo is None:
        return
    _clear_edge_waypoints(geo)
    _sy = id_to_y_center.get(src_id)
    if _sy is None:
        return
    _right = gate_right_x.get(src_id, and_col_x + AND_GATE_W)
    and_rev = {v: k for k, v in and_gate_id.items()}
    or_rev = {v: k for k, v in or_gate_id.items()}
    src_row = output_to_row.get(upstream_rail)

    if tgt_id in or_rev:
        tgt_rail, _tgt_hl = or_rev[tgt_id]
        _ty = id_to_y_center.get(tgt_id)
        if _ty is None:
            return
        # 進 OR 的入口錨點依 edge entryY（numInputs=1 時為 0.5＝閘中心）；用真正入口 Y 收尾。
        _entry_y = int(round(_ty + (entry_ay - 0.5) * OR_GATE_H))
        or_entry_x = or_col_x_fn(tgt_rail)
        if src_row is not None and src_row != output_to_row[tgt_rail]:
            gate_exit_lanes.wire_via_channel(
                geo, src_id, _right, _sy, or_entry_x, _entry_y
            )
        else:
            gate_exit_lanes.wire_vertical(geo, src_id, _right, _sy, _entry_y)
        return

    if tgt_id in and_rev:
        tgt_key = and_rev[tgt_id]
        tgt_rail = tgt_key[0]
        tgt_row = output_to_row[tgt_rail]
        _ty = id_to_y_center.get(tgt_id)
        if _ty is None:
            return
        _entry_y = int(round(_ty + (entry_ay - 0.5) * AND_GATE_H))
        if src_row is not None and src_row != tgt_row:
            gate_exit_lanes.wire_via_channel(
                geo, src_id, _right, _sy, and_col_x, _entry_y
            )
        else:
            gate_exit_lanes.wire_via_channel(
                geo, src_id, _right, _sy, and_col_x, _entry_y
            )
        return

    deb_rail_by_id: dict[int, tuple[str, str]] = {}
    for rname, nid in h_deb_id_map.items():
        deb_rail_by_id[nid] = (rname, "hi")
    for rname, nid in l_deb_id_map.items():
        deb_rail_by_id[nid] = (rname, "lo")
    if tgt_id not in deb_rail_by_id:
        return
    tgt_rail, tgt_hl = deb_rail_by_id[tgt_id]
    tgt_row = output_to_row[tgt_rail]
    deb_y = id_to_y_center.get(tgt_id)
    if deb_y is None:
        return
    gi = _find_dep_group_index(tgt_rail, upstream_rail, hl, name_to_rail)
    if src_row is not None and src_row != tgt_row:
        if src_row < tgt_row:
            gate_exit_lanes.wire_via_channel(
                geo, src_id, _right, _sy, deb_entry_x_fn(tgt_rail), deb_y
            )
        else:
            bypass_y = _align40(row_bottom_fn(src_row) + GRID)
            lx = gate_exit_lanes.stub_x(src_id, _right)
            _add_edge_points(
                geo,
                [(lx, _sy), (lx, bypass_y), (lx, deb_y), (deb_entry_x_fn(tgt_rail), deb_y)],
                align=[False, True, True, True],
            )
    else:
        _py = row_py[tgt_row]
        above_y = _align40(_py - GRID)
        lx = gate_exit_lanes.stub_x(src_id, _right)
        _add_edge_points(
            geo,
            [(lx, _sy), (lx, above_y), (lx, deb_y), (deb_entry_x_fn(tgt_rail), deb_y)],
            align=[False, True, True, True],
        )


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _ensure_style_kv(style: str, key: str, value: str) -> str:
    """在 mxCell style 字串中設定 key=value（已有則覆寫）。"""
    if re.search(rf"(?:^|;){re.escape(key)}=", style):
        return re.sub(rf"{re.escape(key)}=[^;]*", f"{key}={value}", style)
    sep = "" if not style or style.endswith(";") else ";"
    return f"{style}{sep}{key}={value};"


def _vertex_geom(
    root: ET.Element, vid: str
) -> tuple[float, float, float, float] | None:
    for cell in root.iter("mxCell"):
        if cell.get("id") != vid or cell.get("vertex") != "1":
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            return None
        try:
            x = float(geo.get("x", 0))
            y = float(geo.get("y", 0))
            w = float(geo.get("width", 0))
            h = float(geo.get("height", 0))
        except (TypeError, ValueError):
            return None
        return x, y, w, h
    return None


def _style_float(sty: str, key: str, default: float) -> float:
    for part in (sty or "").split(";"):
        if part.startswith(key + "="):
            try:
                return float(part.split("=", 1)[1])
            except ValueError:
                break
    return default


def _anchor_xy(
    box: tuple[float, float, float, float], ax: float, ay: float
) -> tuple[float, float]:
    x, y, w, h = box
    return x + ax * w, y + ay * h


def _feedback_profile(
    src_id: int,
    *,
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
) -> str:
    if src_id in nq_box_id_map.values():
        return "nq"
    if src_id in q_box_id_map.values():
        return "q"
    return "gate"


def _cell_fb_channel_base_x(
    rail: str,
    *,
    and_col_x: int,
    n_and: int,
    exempt_ac: int,
    m_or: int,
    exempt_oc: int,
    row_gate_layout: dict[str, _RowGateLayout],
) -> int:
    """Cell 左側 fb 區起點（AND→Cell 或 OR→Cell gap 內、stub 之後）。"""
    lay = row_gate_layout[rail]
    if lay.or_col_x is not None:
        return lay.or_col_x + OR_GATE_W + GAP + max(0, m_or - exempt_oc) * GRID
    return and_col_x + AND_GATE_W + GAP + max(0, n_and - exempt_ac) * GRID


def _or_fb_channel_base_x(
    *,
    and_col_x: int,
    n_and: int,
    exempt_ao: int,
) -> int:
    """OR 左側 fb 區起點（AND→OR gap 內、stub 之後）。"""
    return and_col_x + AND_GATE_W + GAP + max(0, n_and - exempt_ao) * GRID


def _feedback_channel_x(
    layer: str,
    slot: int,
    *,
    channel_x_left: int,
    and_col_x: int,
    n_and: int,
    exempt_ac: int,
    exempt_ao: int,
    m_or: int,
    exempt_oc: int,
    tgt_rail: str,
    row_gate_layout: dict[str, _RowGateLayout],
) -> float:
    """依目標層選 FB 垂直幹線 x：AND 左幹線／OR 同 AND（AND→OR gap 內固定回授幹線專區）／Cell 左 fb。"""
    if layer == "and":
        return float(channel_x_left + slot * GRID)
    if layer == "or":
        # 比照 AND：OR 回授幹線位於 AND→OR gap 左端（AND 右緣 + GAP 起算）的固定專區，
        # 隨 slot 向右遞增（同 source 同 slot），停在 OR 欄之前。
        return float(and_col_x + AND_GATE_W + GAP + slot * GRID)
    if layer == "cell":
        return float(_cell_fb_channel_base_x(
            tgt_rail,
            and_col_x=and_col_x,
            n_and=n_and,
            exempt_ac=exempt_ac,
            m_or=m_or,
            exempt_oc=exempt_oc,
            row_gate_layout=row_gate_layout,
        ) + slot * GRID)
    raise ValueError(f"unknown feedback layer: {layer}")


def _feedback_edge_tgt_layer(
    tgt_id: int,
    *,
    and_rev: dict[int, tuple[str, str, int]],
    or_rev: dict[int, tuple[str, str]],
    deb_tgt_row: dict[int, int],
) -> str | None:
    if tgt_id in and_rev:
        return "and"
    if tgt_id in or_rev:
        return "or"
    if tgt_id in deb_tgt_row:
        return "cell"
    return None


def _build_feedback_source_layer_slots(
    root: ET.Element,
    feedback_auto_edge_ids: set[str],
    *,
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    deb_tgt_row: dict[int, int],
    feedback_n: int,
    fb_cell: int,
    fb_or: int,
    and_cap: int | None = None,
) -> dict[tuple[int, str], int]:
    """同一 source 在每個目標層（and／or／cell）只佔 1 條 FB X 通道 → (src_id, layer) → slot。"""
    and_rev = {v: k for k, v in and_gate_id.items()}
    or_rev = {v: k for k, v in or_gate_id.items()}
    sources_by_layer: dict[str, set[int]] = {"and": set(), "or": set(), "cell": set()}
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid is None or eid not in feedback_auto_edge_ids:
            continue
        try:
            src_id = int(cell.get("source") or "")
            tgt_id = int(cell.get("target") or "")
        except ValueError:
            continue
        layer = _feedback_edge_tgt_layer(
            tgt_id,
            and_rev=and_rev,
            or_rev=or_rev,
            deb_tgt_row=deb_tgt_row,
        )
        if layer is None:
            continue
        sources_by_layer[layer].add(src_id)
    caps = {
        # AND 回授幹線：不同 source 各佔一條 lane，cap 取 channel_x_left→AND 之間
        # 實際可容納的 lane 數（避免不同 source 被壓到同一條 x 通道）。
        "and": max(1, and_cap if and_cap is not None else feedback_n),
        "or": max(1, fb_or),
        "cell": max(1, fb_cell),
    }
    slots: dict[tuple[int, str], int] = {}
    for layer, src_ids in sources_by_layer.items():
        cap = caps[layer]
        for i, src_id in enumerate(sorted(src_ids)):
            slots[(src_id, layer)] = min(i, cap - 1)
    return slots


def _collect_logic_gate_boxes(
    root: ET.Element,
) -> list[tuple[float, float, float, float]]:
    """所有 AND/OR/NAND/NOR 邏輯閘的 (x0, x1, y0, y1) 佔位框。"""
    boxes: list[tuple[float, float, float, float]] = []
    for cell in root.iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        sty = cell.get("style") or ""
        if "logic_gates.logic_gate" not in sty:
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        x = float(geo.get("x", 0))
        y = float(geo.get("y", 0))
        w = float(geo.get("width", 0))
        h = float(geo.get("height", 0))
        boxes.append((x, x + w, y, y + h))
    return boxes


def _first_clear_up_y(
    start_y: float,
    xa: float,
    xb: float,
    gate_boxes: list[tuple[float, float, float, float]],
    *,
    avoid: list[tuple[float, float, float]] | None = None,
    max_steps: int = 60,
) -> float:
    """自 start_y 起一律向上（y 遞減）逐格(GRID)搜尋，回傳第一條同時滿足：
    (1) 與 [xa, xb] 內任何閘體／閘邊不重疊；
    (2) 不與其他 source 已佔用且 x 區間重疊的回授橫列同列；
    的 40 對齊水平列；找不到則回傳原值。avoid 為 (y, x0, x1) 清單。"""
    lo_x, hi_x = (xa, xb) if xa <= xb else (xb, xa)
    crossed = [
        (gy0, gy1)
        for (gx0, gx1, gy0, gy1) in gate_boxes
        if gx1 >= lo_x and gx0 <= hi_x
    ]
    avoid_rows = [
        ay
        for (ay, ax0, ax1) in (avoid or [])
        if ax1 >= lo_x and ax0 <= hi_x
    ]
    y = _align40(start_y)
    for _ in range(max_steps):
        gate_ok = all(not (gy0 <= y <= gy1) for gy0, gy1 in crossed)
        row_ok = all(abs(y - ar) > 1 for ar in avoid_rows)
        if gate_ok and row_ok:
            return float(y)
        y -= GRID
    return float(_align40(start_y))


def _apply_feedback_routing(
    root: ET.Element,
    feedback_auto_edge_ids: set[str],
    *,
    channel_x_left: int,
    feedback_n: int,
    fb_cell: int,
    fb_or: int,
    and_col_x: int,
    n_and: int,
    exempt_ac: int,
    exempt_ao: int,
    m_or: int,
    exempt_oc: int,
    row_gate_layout: dict[str, _RowGateLayout],
    q_box_id_map: dict[str, int],
    nq_box_id_map: dict[str, int],
    gate_exit_lanes: _GateExitLanes,
    gate_right_x: dict[int, int],
    and_gate_id: dict[tuple[str, str, int], int],
    or_gate_id: dict[tuple[str, str], int],
    deb_tgt_row: dict[int, int],
    h_deb_id_map: dict[str, int],
    l_deb_id_map: dict[str, int],
    output_to_row: dict[str, int],
    or_col_x_fn,
    deb_entry_x_fn,
) -> None:
    """回授五段凍結走線（Rule 2）；依目標層選對應 FB X 通道。"""
    and_rev = {v: k for k, v in and_gate_id.items()}
    or_rev = {v: k for k, v in or_gate_id.items()}
    deb_rail_by_id: dict[int, str] = {}
    for rname, nid in h_deb_id_map.items():
        deb_rail_by_id[nid] = rname
    for rname, nid in l_deb_id_map.items():
        deb_rail_by_id[nid] = rname
    # AND 回授幹線專區（channel_x_left → AND 欄，需保留 ≥GAP 進閘水平段）實際可容納的 lane 數。
    and_fb_lane_cap = max(1, (and_col_x - GAP - channel_x_left) // GRID + 1)
    source_layer_slots = _build_feedback_source_layer_slots(
        root,
        feedback_auto_edge_ids,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
        deb_tgt_row=deb_tgt_row,
        feedback_n=feedback_n,
        fb_cell=fb_cell,
        fb_or=fb_or,
        and_cap=and_fb_lane_cap,
    )
    gate_boxes = _collect_logic_gate_boxes(root)
    # 同一 source 共用一條回授橫列；不同 source 之間（含跨層）橫列須錯開。
    source_and_row: dict[int, float] = {}
    source_or_row: dict[int, float] = {}
    used_fb_rows: list[tuple[float, float, float]] = []

    # issue 3：cell 回授垂直幹線需避開「實際被佔用」的垂直車道（既有正向邊垂直段
    # ＋ gate-profile 回授的 ① stub 車道），尤其 OR 閘 gate-exit stub。
    occupied_vx: set[int] = set()
    for _c in root.iter("mxCell"):
        if _c.get("edge") != "1":
            continue
        _g = _c.find("mxGeometry")
        _arr = _g.find("Array") if _g is not None else None
        if _arr is None:
            continue
        _p = [(float(m.get("x")), float(m.get("y"))) for m in _arr.findall("mxPoint")]
        for _a, _b in zip(_p, _p[1:]):
            if abs(_a[0] - _b[0]) < 1 and abs(_a[1] - _b[1]) > 1:
                occupied_vx.add(int(round(_a[0])))
    for _c in root.iter("mxCell"):
        if _c.get("edge") != "1":
            continue
        _eid = _c.get("id")
        if _eid is None or _eid not in feedback_auto_edge_ids:
            continue
        try:
            _sid = int(_c.get("source") or "")
        except ValueError:
            continue
        if _feedback_profile(_sid, q_box_id_map=q_box_id_map, nq_box_id_map=nq_box_id_map) != "gate":
            continue
        _sr = gate_right_x.get(_sid)
        if _sr is None:
            continue
        # gate-profile 回授 ① 一律走 catalog (1+n)×40 預留通道（每顆閘各自一條）。
        occupied_vx.add(int(_align40(gate_exit_lanes.stub_x(_sid, _sr))))
    assigned_cell_vx: set[int] = set()
    source_cell_x: dict[int, float] = {}

    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid is None or eid not in feedback_auto_edge_ids:
            continue
        src_s = cell.get("source")
        tgt_s = cell.get("target")
        if src_s is None or tgt_s is None:
            continue
        s_box = _vertex_geom(root, src_s)
        t_box = _vertex_geom(root, tgt_s)
        if s_box is None or t_box is None:
            continue
        try:
            src_id = int(src_s)
        except ValueError:
            continue
        sty = cell.get("style") or ""
        exit_ax = _style_float(sty, "exitX", 1.0)
        exit_ay = _style_float(sty, "exitY", 0.5)
        entry_ax = _style_float(sty, "entryX", 0.0)
        entry_ay = _style_float(sty, "entryY", 0.5)
        ex, ey = _anchor_xy(s_box, exit_ax, exit_ay)
        tx, ty = _anchor_xy(t_box, entry_ax, entry_ay)

        profile = _feedback_profile(
            src_id, q_box_id_map=q_box_id_map, nq_box_id_map=nq_box_id_map
        )
        if profile == "nq":
            right_delta = FB_NQ_RIGHT
            up_delta = FB_NQ_UP
        elif profile == "q":
            right_delta = FB_Q_RIGHT
            up_delta = FB_Q_UP
        else:
            right_delta = 0
            up_delta = FB_Q_UP

        try:
            tgt_id = int(tgt_s)
        except ValueError:
            continue
        tgt_layer: str | None = None
        tgt_rail = ""
        if tgt_id in and_rev:
            tgt_layer = "and"
            tgt_rail = and_rev[tgt_id][0]
            entry_x = float(and_col_x)
        elif tgt_id in or_rev:
            tgt_layer = "or"
            tgt_rail = or_rev[tgt_id][0]
            entry_x = float(or_col_x_fn(tgt_rail))
        elif tgt_id in deb_tgt_row:
            tgt_layer = "cell"
            tgt_rail = deb_rail_by_id.get(tgt_id, "")
            entry_x = float(deb_entry_x_fn(tgt_rail))
        else:
            continue

        if profile == "gate":
            # ① 一律走到該閘「轉角輸出」的預留 stub 通道（catalog (1+n)×40，每顆閘各自一條）；
            # 不同 source 不共用同一 X 通道（含 OR→OR）。placement 已預留此通道。
            stub_right = gate_right_x.get(src_id, and_col_x + AND_GATE_W)
            p1x = float(gate_exit_lanes.stub_x(src_id, stub_right))
        else:
            p1x = ex + right_delta
        p1y = ey
        # Q／~Q／閘：第二段一律先向上（40+20pt）；第四段再依目標 Y 上／下
        p2y = ey - up_delta
        p2x = p1x

        slot = source_layer_slots.get((src_id, tgt_layer), 0)
        p3x = _feedback_channel_x(
            tgt_layer,
            slot,
            channel_x_left=channel_x_left,
            and_col_x=and_col_x,
            n_and=n_and,
            exempt_ac=exempt_ac,
            exempt_ao=exempt_ao,
            m_or=m_or,
            exempt_oc=exempt_oc,
            tgt_rail=tgt_rail,
            row_gate_layout=row_gate_layout,
        )
        # issue 3：cell 回授垂直幹線若落在被佔用的車道（OR 閘 gate-exit stub 等），
        # 往左（朝 OR 欄）逐格挪到無垂直線的空車道，避免與 OR 回授路線重疊。
        if tgt_layer == "cell":
            if src_id in source_cell_x:
                # 同一 source 同層共用一條 X 通道（不可因避讓被拆成多條）。
                p3x = source_cell_x[src_id]
            else:
                _floor_x = and_col_x + AND_GATE_W + GAP
                _cx = int(_align40(p3x))
                while (_cx in occupied_vx or _cx in assigned_cell_vx) and _cx - GRID >= _floor_x:
                    _cx -= GRID
                p3x = float(_cx)
                assigned_cell_vx.add(_cx)
                source_cell_x[src_id] = p3x

        # AND→AND／OR→OR（gate profile）：② 上移量感知上下相鄰閘佔位，停到真正乾淨的列，
        # 避免橫線壓在相鄰閘邊（密集 80pt 堆疊時 40 對齊會落在閘邊）。
        if profile == "gate" and tgt_layer == "and" and src_id in and_rev:
            if src_id in source_and_row:
                p2y = source_and_row[src_id]
            else:
                p2y = _first_clear_up_y(
                    p2y, p1x, p3x, gate_boxes, avoid=used_fb_rows
                )
                source_and_row[src_id] = p2y
            p2x = p1x
        elif profile == "gate" and tgt_layer == "or" and src_id in or_rev:
            if src_id in source_or_row:
                p2y = source_or_row[src_id]
            else:
                p2y = _first_clear_up_y(
                    p2y, p1x, p3x, gate_boxes, avoid=used_fb_rows
                )
                source_or_row[src_id] = p2y
            p2x = p1x
        p3y = p2y
        p4x = p3x
        p4y = ty
        # 記錄本邊橫列（y 與 x 區間），供後續其他 source 的 OR 回授避開同列重疊。
        used_fb_rows.append((p2y, min(p1x, p3x), max(p1x, p3x)))

        geo = cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        _clear_edge_waypoints(geo)
        fb_pts = [(p1x, p1y), (p2x, p2y), (p3x, p3y), (p4x, p4y), (entry_x, ty)]
        fb_align = [(True, False), (True, True), (True, True), (True, False), (True, False)]
        arr = ET.SubElement(geo, "Array", {"as": "points"})
        for (px, py), (do_ax, do_ay) in zip(fb_pts, fb_align):
            x = _align40(px) if do_ax else round(float(px))
            y = _align40(py) if do_ay else round(float(py))
            ET.SubElement(arr, "mxPoint", {"x": str(x), "y": str(y)})
        cell.set("style", _style_to_frozen_none(sty))


def _apply_feedback_edge_color(
    root: ET.Element,
    feedback_auto_edge_ids: set[str],
) -> None:
    """回授邊改藍色；已是 Hi 綠／Lo 紅者保留。"""
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid is None or eid not in feedback_auto_edge_ids:
            continue
        sty = cell.get("style") or ""
        if STROKE_HI in sty or STROKE_LO in sty:
            continue
        cell.set("style", _ensure_style_kv(sty, "strokeColor", STROKE_FEEDBACK))


def _apply_edge_wire_style(root: ET.Element) -> None:
    """所有 edge 一律 strokeWidth=2、jumpStyle=arc。"""
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        sty = cell.get("style") or ""
        sty = _ensure_style_kv(sty, "strokeWidth", str(EDGE_STROKE_WIDTH))
        sty = _ensure_style_kv(sty, "jumpStyle", EDGE_JUMP_STYLE)
        sty = _ensure_style_kv(sty, "jumpSize", str(EDGE_JUMP_SIZE))
        sty = _ensure_style_kv(sty, "dashed", "0")
        cell.set("style", sty)


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
    """為垂直走線分配 x 通道。

    y 範圍重疊時是否可共用 x 由 ``DrawioExportOptions`` 的 same_source_vert /
    same_dest_vert 決定；不重疊時可共用（水平段可重疊）。
    """

    def __init__(self, base_x: int, step: int = GRID, options: DrawioExportOptions | None = None):
        self._base_x = base_x
        self._step = step
        self._options = options or DrawioExportOptions.defaults()
        # (y_min, y_max, source_key, dest_key)
        self._channels: list[list[tuple[float, float, str | None, str | None]]] = []

    def _span_y_overlap(self, y_min: float, y_max: float, span: tuple) -> bool:
        sy0, sy1 = span[0], span[1]
        return not (y_max <= sy0 or y_min >= sy1)

    def _overlap_allowed(self, span: tuple, source_key: str | None, dest_key: str | None) -> bool:
        ss = span[2] if len(span) > 2 else None
        sd = span[3] if len(span) > 3 else None
        if self._options.same_source_vert and source_key and ss == source_key:
            return True
        if self._options.same_dest_vert and dest_key and sd == dest_key:
            return True
        return False

    def allocate(
        self,
        y_min: float,
        y_max: float,
        source_key: str | None = None,
        dest_key: str | None = None,
    ) -> int:
        """分配 x 通道。"""
        if y_min > y_max:
            y_min, y_max = y_max, y_min
        if self._options.same_source_vert and source_key is not None:
            for i, spans in enumerate(self._channels):
                if any(s[2] == source_key for s in spans):
                    spans.append((y_min, y_max, source_key, dest_key))
                    return self._base_x + i * self._step
        if self._options.same_dest_vert and dest_key is not None:
            for i, spans in enumerate(self._channels):
                if any(len(s) > 3 and s[3] == dest_key for s in spans):
                    spans.append((y_min, y_max, source_key, dest_key))
                    return self._base_x + i * self._step
        for i, spans in enumerate(self._channels):
            compatible = True
            for span in spans:
                if not self._span_y_overlap(y_min, y_max, span):
                    continue
                if not self._overlap_allowed(span, source_key, dest_key):
                    compatible = False
                    break
            if compatible:
                spans.append((y_min, y_max, source_key, dest_key))
                return self._base_x + i * self._step
        self._channels.append([(y_min, y_max, source_key, dest_key)])
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


def _wire_input_to_gate(geo: ET.Element, label_xy: tuple[int, int], gate_y: int) -> None:
    """input→AND/OR：先下後右（垂直 bus 在 label x+40pt）。"""
    lab_y = _input_label_center_y(label_xy[1])
    if abs(lab_y - gate_y) < 2:
        return
    bus = _input_bus_x(label_xy[0])
    _add_edge_points(geo, [(bus, lab_y), (bus, gate_y)], align=[False, True])




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


def generate_drawio(
    config: PowerSeqConfig,
    *,
    options: DrawioExportOptions | None = None,
) -> str:
    """
    Generate Draw.io XML per PSEQCELL.xml（RTL：PSEQCELL.v）:
    - Only output rails become nodes (Power Sequence Cell: inner + H_Deb + L_Deb + Q + ~Q，無 group）。
    - Input rails are text labels only; 反相一律用共用 NOT 閘呈現（非舊版 ~Name 文字）。

    版面：output power cell 依 config.rails 宣告順序由上而下排列；
    走線重疊規則由 ``options`` 控制（預設：同 source 水平可重疊、其餘不重疊）。
    """
    _ = options or DrawioExportOptions.defaults()
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail.keys())
    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs_raw = [r for r in config.rails if r.seq_type == "output"]
    outputs = outputs_raw  # 依 config 宣告順序由上而下

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

    # 需共用 NOT 閘的 input / output（inv 用法）
    out_names = {r.name for r in outputs_raw}
    inputs_with_not: set[str] = set()
    outputs_with_not: set[str] = set()
    for r in outputs_raw:
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            for gi, g in enumerate(groups):
                for ii, d in enumerate(g):
                    if d not in valid or d in CONST_DEPS:
                        continue
                    inv = r.get_hi_inv(gi, ii, d) if hl == "hi" else r.get_lo_inv(gi, ii, d)
                    if not inv:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        inputs_with_not.add(d)
                    elif d in out_names:
                        outputs_with_not.add(d)

    # 規則二：欄間距 GAP（40pt）、列距 ROW_GAP（80pt）。Cell→輸出名稱固定 120pt（有 output NOT 則 200pt）。

    output_to_row: dict[str, int] = {r.name: j for j, r in enumerate(outputs)}

    and_index_per_key: dict[tuple[str, str, int], tuple[int, int]] = {}
    for j, r in enumerate(outputs):
        hi_groups = r.get_hi_groups()
        lo_groups = r.get_lo_groups()
        for hl, groups in [("hi", hi_groups), ("lo", lo_groups)]:
            base = OR_GATE_OFFSET_HI_Y if hl == "hi" else OR_GATE_OFFSET_LO_Y
            idx = 0
            for gi, g in enumerate(groups):
                if len(g) >= 2:
                    and_index_per_key[(r.name, hl, gi)] = (j, base + idx * AND_GATE_DY)
                    idx += 1

    or_index_per_key = _build_or_index_per_key(outputs)
    cell_row_slack = _feedback_y_slack_between_cell_rows(
        outputs, output_to_row, name_to_rail, valid
    )

    # 動態行高：依 AND/OR 數量；有 output NOT 者下一列從 NOT 下方開始
    row_heights: list[int] = []
    row_y_base: list[int] = []
    acc = MARGIN
    for j, r in enumerate(outputs):
        y = _align40(acc)
        row_y_base.append(y)
        h = _align40(_row_height_for_output(r))
        row_heights.append(h)
        row_gap_extra = cell_row_slack.get(j, 0)
        acc = y + h + ROW_GAP + row_gap_extra

    # 僅建立「有被使用」的 input 標籤（無論是否反相皆為單一正向標籤），並記錄第一個使用者
    used_inputs_set: set[str] = set()
    input_first_output: dict[str, str] = {}  # input name -> 第一個使用它的 output name（依 config 序）
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
    total_input_w = _input_band_width(used_inputs_list, inputs_with_not)

    # Input 標籤：rotation=90，依 config 由右→左排列（見 _layout_input_positions）
    # 依「第一個使用該 input 的 output 所在列」分組，同列內依 config 序；每列第一個 input 對齊該列 OR 高
    row_to_inputs: dict[int, list[str]] = {}
    for name in all_input_names:
        row = output_to_row.get(input_first_output.get(name, ""), 0)
        row_to_inputs.setdefault(row, []).append(name)
    for row in row_to_inputs:
        row_to_inputs[row].sort(key=_input_order)

    catalog, idx_map = _build_and_catalog(outputs)
    or_catalog, or_idx_map = _build_or_catalog(outputs)
    layout_feedback_dep_keys = _build_layout_feedback_dep_keys(
        outputs, output_to_row, name_to_rail, valid
    )
    feedback_y_slack = _feedback_y_slack_after_and(
        outputs, output_to_row, name_to_rail, valid, and_index_per_key
    )
    feedback_or_y_slack = _feedback_y_slack_after_or(
        outputs, output_to_row, name_to_rail, valid, or_index_per_key
    )
    row_py = list(row_y_base)
    and_top_y = _chain_and_top_y(
        row_py, catalog, and_index_per_key, feedback_y_slack, name_to_rail
    )
    or_top_y = _chain_or_top_y(
        row_py, or_catalog, or_index_per_key, feedback_or_y_slack
    )
    and_lane_idx, or_lane_idx = _build_gate_lane_indices(
        outputs,
        catalog,
        idx_map,
        or_catalog,
        or_idx_map,
        output_to_row=output_to_row,
        name_to_rail=name_to_rail,
        valid=valid,
        and_top_y=and_top_y,
        or_top_y=or_top_y,
        row_py=row_py,
    )

    def _and_y_top(rail: str, hl: str, gi: int) -> int:
        return and_top_y[idx_map[(rail, hl, gi)]]

    def _and_y_center(rail: str, hl: str, gi: int) -> int:
        return and_top_y[idx_map[(rail, hl, gi)]] + AND_GATE_H // 2

    def _or_y_top(rail: str, hl: str) -> int:
        g = or_idx_map.get((rail, hl))
        if g is None:
            j = output_to_row[rail]
            off = OR_GATE_OFFSET_HI_Y if hl == "hi" else OR_GATE_OFFSET_LO_Y
            return row_py[j] + off
        return or_top_y[g]

    def _or_y_center(rail: str, hl: str) -> int:
        return _or_y_top(rail, hl) + OR_GATE_H // 2

    def _row_bottom(j: int) -> int:
        gs = [g for key, g in idx_map.items() if and_index_per_key[key][0] == j]
        og = [g for key, g in or_idx_map.items() if or_index_per_key[key][0] == j]
        extents: list[int] = []
        if gs:
            extents.extend(and_top_y[g] + AND_GATE_H for g in gs)
        if og:
            extents.extend(or_top_y[g] + OR_GATE_H for g in og)
        if extents:
            return max(extents)
        return row_py[j] + row_heights[j]

    min_cell_top_y = _align40(min(row_py))
    input_row_y = _input_row_y(min_cell_top_y)

    positions_in = _layout_input_positions(
        used_inputs_list, inputs_with_not,
        _align40(MARGIN + total_input_w),
        input_row_y,
    )

    # --- Channel Assignment (Phase B) ---
    # input→gate 不佔寬；input 與 AND 之間僅留「回授幹線」：每條 40pt（見 _count_feedback_trunks）。
    # Cell→輸出名稱：固定 120pt（任一 output NOT 則全圖 200pt）；跨列走 stub lane（(1+n)×40）。

    feedback_n, _feedback_and, _feedback_rsmrst = _count_feedback_trunks(
        outputs, output_to_row, name_to_rail, valid
    )
    left_channel_w = feedback_n * GRID

    post_input_x = _align40(MARGIN + total_input_w + GAP)
    channel_x_left = post_input_x
    and_col_x = _align40(post_input_x + left_channel_w + GAP)
    row_gate_layout = _compute_row_gate_layouts(
        outputs,
        and_col_x,
        name_to_rail,
        valid,
        output_to_row=output_to_row,
        and_index_per_key=and_index_per_key,
        idx_map=idx_map,
        and_top_y=and_top_y,
        row_py=row_py,
        or_idx_map=or_idx_map,
        or_top_y=or_top_y,
    )
    max_cell_start_x = max(lay.cell_start_x for lay in row_gate_layout.values())
    input_band_right = channel_x_left - GAP
    positions_in = _layout_input_positions(
        used_inputs_list, inputs_with_not, input_band_right, input_row_y
    )
    input_right = input_band_right

    any_output_not = bool(outputs_with_not)
    output_name_offset_x = CELL_GROUP_W + _output_name_channel_gap(any_output_not)

    def _cell_x(rail_name: str) -> int:
        return row_gate_layout[rail_name].cell_start_x

    def _or_col_x(rail_name: str) -> int:
        lay = row_gate_layout[rail_name]
        assert lay.or_col_x is not None
        return lay.or_col_x

    def _and_gate_offset_x(rail_name: str) -> int:
        return and_col_x - _cell_x(rail_name)

    def _or_gate_offset_x(rail_name: str) -> int:
        return _or_col_x(rail_name) - _cell_x(rail_name)

    def _deb_entry_x(rail_name: str) -> int:
        return _cell_x(rail_name) + CELL_INNER_X

    positions_out: dict[str, tuple[int, int]] = {
        r.name: (row_gate_layout[r.name].cell_start_x, _align40(row_py[j]))
        for j, r in enumerate(outputs)
    }
    min_cell_top_y = min(y for _, y in positions_out.values())

    # 記錄每個 rail 的 Hi/Lo 邏輯輸出 cell id（AND/OR 閘或直連來源），
    # 供 use_mode="hi"/"lo" 時作為出發點（而非 H_Deb/L_Deb 本身）。
    # 邊生成迴圈依拓撲序處理，確保被依賴者的 ID 在被引用前已記錄。
    hi_logic_out_id: dict[str, int] = {}
    lo_logic_out_id: dict[str, int] = {}

    cell_id = 2
    out_inner_id: dict[str, int] = {}
    h_deb_id_map: dict[str, int] = {}
    l_deb_id_map: dict[str, int] = {}
    q_box_id_map: dict[str, int] = {}
    nq_box_id_map: dict[str, int] = {}
    in_label_id: dict[str, int] = {}
    # (rail_name, "hi"|"lo", group_index) -> AND gate cell id（僅當該 group 有 2+ 訊號時）
    and_gate_id: dict[tuple[str, str, int], int] = {}
    or_gate_id: dict[tuple[str, str], int] = {}
    # 共用 NOT 閘：key = (來源 d, use_mode)，value = NOT 閘 cell id
    not_gate_id: dict[tuple[str, str], int] = {}
    input_not_src_ids: set[str] = set()
    # 記錄所有 inv=True 的邊：edge id (str) -> (來源 d, use_mode)；
    # post-fix 會為每個唯一 (d, use_mode) 建立一顆共用 NOT 閘，並把這些邊 source 替換為 NOT 閘 id。
    _inv_edges: dict[str, tuple[str, str]] = {}
    _fixed_not_edge_ids: set[str] = set()

    mxfile = ET.Element(
        "mxfile",
        {"host": "app.diagrams.net", "agent": "PowerSeqGen", "version": "29.6.0"},
    )
    diagram = ET.SubElement(mxfile, "diagram", {"name": "PowerSeq", "id": _random_diagram_id()})
    model = ET.SubElement(diagram, "mxGraphModel", {
        "dx": "1579", "dy": "459", "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1", "pageWidth": "827", "pageHeight": "1169",
        "math": "0", "shadow": "0",
        "jumpStyle": EDGE_JUMP_STYLE, "jumpSize": str(EDGE_JUMP_SIZE),
    })
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    style_input_label = (
        "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
        "align=right;verticalAlign=middle;rounded=0;direction=east;rotation=90;"
    )
    style_input_not_gate = (
        "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;"
        "verticalAlign=top;shape=mxgraph.electrical.logic_gates.inverter_2;rotation=90;"
    )
    gate_exit_lanes = _GateExitLanes()
    feedback_auto_edge_ids: set[str] = set()
    style_output_name = "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;rounded=0;"
    style_edge_o_to_name = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % STROKE_DEFAULT
    # 邏輯閘左側輸入 pin：numInputs=1（AND1.xml 等）唯一錨點 entryY=0.5；多扇入共用此點
    # exit_left 應只在 source 是 output cell（取 H_Deb/L_Deb 訊號）時使用；
    # source 是 input label 時 input 沒有 H/L 概念，一律從右邊出（exitX=1）。
    def _is_deb_placeholder(from_id: int) -> bool:
        return from_id in h_deb_id_map.values() or from_id in l_deb_id_map.values()

    def _use_hi_lo_deb_placeholder_exit(from_id: int, use_mode: str) -> bool:
        """use=hi/lo 且來源仍為上游 H/L_Deb 佔位符時，才從左側出（Pass 1 再換成 logic out）。"""
        return use_mode in ("hi", "lo") and _is_deb_placeholder(from_id)

    def _style_edge_to_gate_entry(entry_y: float, source_id: int, use_mode: str | None) -> str:
        is_input_src = source_id in set(in_label_id.values())
        # 僅 Deb 佔位符從左側出；logic_out（Q/~Q/AND/OR）一律 exitX=1。
        exit_left = (
            use_mode in ("hi", "lo")
            and not is_input_src
            and _is_deb_placeholder(source_id)
        )
        ex = 0 if exit_left else 1
        return (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=%d;exitY=0.5;exitDx=0;exitDy=0;"
            "entryX=0;entryY=%.2f;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;" % (ex, entry_y, STROKE_DEFAULT)
        )
    def _gate_entry_y(index: int, total: int) -> float:
        """AND/OR/NAND/NOR（numInputs=1）唯一輸入錨點；多條入邊共用 entryY=0.5。"""
        del index, total  # 保留簽名供呼叫端；單一輸入點與扇入數無關
        return _GATE_ENTRY_AY
    # 規則三：連到 H_Deb 實心綠、連到 L_Deb 實心紅
    style_and_to_cell_hi = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_and_to_cell_lo = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_LO
    style_or_to_cell_hi = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_or_to_cell_lo = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_LO

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

    # 2) Output 節點：依 PSEQCELL.xml — inner + H/L_Deb + Q + ~Q + name + Q→name
    for r in outputs:
        px, py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
        inner_id = cell_id; cell_id += 1
        h_deb_id = cell_id; cell_id += 1
        l_deb_id = cell_id; cell_id += 1
        q_box_id = cell_id; cell_id += 1
        nq_box_id = cell_id; cell_id += 1
        name_label_id = cell_id; cell_id += 1
        edge_q_to_name_id = cell_id; cell_id += 1
        out_inner_id[r.name] = inner_id
        h_deb_id_map[r.name] = h_deb_id
        l_deb_id_map[r.name] = l_deb_id
        q_box_id_map[r.name] = q_box_id
        nq_box_id_map[r.name] = nq_box_id

        # 先放 inner（底層），再放 H_Deb/L_Deb/Q/~Q（上層），確保 z-order
        inner = ET.SubElement(root, "mxCell", {
            "id": str(inner_id), "parent": "1", "style": _PSEQCELL_STYLE_INNER, "value": "", "vertex": "1"
        })
        ET.SubElement(inner, "mxGeometry", {
            "height": str(CELL_INNER_H), "width": str(CELL_INNER_W),
            "x": str(px + CELL_INNER_X), "y": str(py), "as": "geometry"
        })

        h_deb = ET.SubElement(root, "mxCell", {
            "id": str(h_deb_id), "parent": "1", "style": _PSEQCELL_STYLE_H_DEB, "value": "H_Deb", "vertex": "1"
        })
        ET.SubElement(h_deb, "mxGeometry", {
            "height": str(CELL_H_DEB_H), "width": str(CELL_H_DEB_W),
            "x": str(px + CELL_INNER_X), "y": str(py + CELL_H_DEB_Y), "as": "geometry"
        })

        l_deb = ET.SubElement(root, "mxCell", {
            "id": str(l_deb_id), "parent": "1", "style": _PSEQCELL_STYLE_L_DEB, "value": "L_Deb", "vertex": "1"
        })
        ET.SubElement(l_deb, "mxGeometry", {
            "height": str(CELL_L_DEB_H), "width": str(CELL_L_DEB_W),
            "x": str(px + CELL_INNER_X), "y": str(py + CELL_L_DEB_Y), "as": "geometry"
        })

        q_box = ET.SubElement(root, "mxCell", {
            "id": str(q_box_id), "parent": "1", "style": _PSEQCELL_STYLE_Q, "value": "Q", "vertex": "1"
        })
        ET.SubElement(q_box, "mxGeometry", {
            "height": str(CELL_Q_H), "width": str(CELL_Q_W),
            "x": str(px + CELL_Q_X), "y": str(py + CELL_Q_Y), "as": "geometry"
        })
        nq_box = ET.SubElement(root, "mxCell", {
            "id": str(nq_box_id), "parent": "1", "style": _PSEQCELL_STYLE_Q, "value": "~Q", "vertex": "1"
        })
        ET.SubElement(nq_box, "mxGeometry", {
            "height": str(CELL_NQ_H), "width": str(CELL_NQ_W),
            "x": str(px + CELL_NQ_X), "y": str(py + CELL_NQ_Y), "as": "geometry"
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

        # Q → 輸出名稱（水平、無轉角）
        edge_q_to_name = ET.SubElement(root, "mxCell", {
            "id": str(edge_q_to_name_id), "edge": "1", "parent": "1",
            "source": str(q_box_id), "target": str(name_label_id),
            "style": style_edge_o_to_name, "value": ""
        })
        ET.SubElement(edge_q_to_name, "mxGeometry", {"relative": "1", "as": "geometry"})

    # 每個 cell id 的垂直中心 y（用於 AND/OR 依垂直位置接 input pin，減少走線交叉）
    id_to_y_center: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_y_center[nid] = _input_label_center_y(positions_in[name][1])
    for name, nid in out_inner_id.items():
        id_to_y_center[nid] = positions_out[name][1] + CELL_GROUP_H // 2
    for name, qid in q_box_id_map.items():
        py = positions_out[name][1]
        id_to_y_center[qid] = py + CELL_Q_Y + CELL_Q_H // 2
    for name, nqid in nq_box_id_map.items():
        py = positions_out[name][1]
        id_to_y_center[nqid] = py + CELL_NQ_Y + CELL_NQ_H // 2
    for name, hid in h_deb_id_map.items():
        py = positions_out[name][1]
        id_to_y_center[hid] = py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
    for name, lid in l_deb_id_map.items():
        py = positions_out[name][1]
        id_to_y_center[lid] = py + CELL_L_DEB_Y + CELL_L_DEB_H // 2

    # 每個 label id 所屬的 row（僅在「不同 row」時加 waypoints，與 debug_golden 一致）
    id_to_row: dict[int, int] = {}
    for name, nid in in_label_id.items():
        id_to_row[nid] = output_to_row.get(input_first_output.get(name, ""), 0)
    inner_id_to_row: dict[int, int] = {out_inner_id[name]: output_to_row[name] for name in output_to_row}
    inner_id_to_output: dict[int, str] = {v: k for k, v in out_inner_id.items()}

    and_gate_y: dict[int, int] = {}  # AND gate id -> y 中心，供排序用
    gate_right_x: dict[int, int] = {}  # 邏輯閘 id -> 右緣 x

    # 3) 依賴邊：依 group 繪製；單一訊號直連 H/L，兩訊號以上經 AND 閘。規則五：走線經 waypoint 繞開元件、不重疊；Hi 綠、Lo 虛線紅。
    style_hi_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_lo_to_cell = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_LO
    style_hi_to_cell_left = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_HI
    style_lo_to_cell_left = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;endArrow=blockThin;endFill=1;strokeColor=%s;" % STROKE_LO

    def _source_id(d: str, inv: bool, is_hi: bool, use_mode: str = "self") -> int | None:
        """依賴來源的「邏輯來源」cell id。

        use_mode:
          'self' = Node 自身輸出 (inner)
          'hi'   = 該節點 Hi 依賴邏輯的輸出（AND/OR 閘）
          'lo'   = 該節點 Lo 依賴邏輯的輸出（AND/OR 閘）

        use_mode="hi"/"lo" 時優先回傳上游已登記的 logic_out（Q/~Q/AND/OR 輸出腳）；
        尚未建立時才回傳 H_Deb/L_Deb 佔位（Pass 1 替換，相容處理順序）。
        inv=True 不再走 ~Name 文字標籤，而是由 post-fix 統一插入「共用 NOT 閘」
        並將 source 替換為 NOT 閘 id；本函式忽略 inv 參數。
        """
        if name_to_rail[d].seq_type == "input":
            return in_label_id.get(d)
        if use_mode == "hi":
            if d in hi_logic_out_id:
                return hi_logic_out_id[d]
            return h_deb_id_map.get(d) or out_inner_id.get(d)
        if use_mode == "lo":
            if d in lo_logic_out_id:
                return lo_logic_out_id[d]
            return l_deb_id_map.get(d) or out_inner_id.get(d)
        return q_box_id_map.get(d)

    def _logic_output_pin(dep_rail: str, inv: bool, use_mode: str, from_id: int) -> int:
        """列內 hi/lo 邏輯完成後，對外扇出的輸出腳（Cell Q/~Q 或 AND/OR 右側，非 Deb）。"""
        if name_to_rail[dep_rail].seq_type == "input":
            return from_id
        if use_mode == "hi" and dep_rail in hi_logic_out_id:
            pin = hi_logic_out_id[dep_rail]
        elif use_mode == "lo" and dep_rail in lo_logic_out_id:
            pin = lo_logic_out_id[dep_rail]
        else:
            pin = from_id
        return _coerce_cell_out_id(
            dep_rail,
            pin,
            inv=inv,
            out_inner_id=out_inner_id,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
        )

    for r in outputs:
        to_inner = out_inner_id.get(r.name)
        to_h_deb = h_deb_id_map.get(r.name)
        to_l_deb = l_deb_id_map.get(r.name)
        if to_inner is None or to_h_deb is None or to_l_deb is None:
            continue

        hi_groups = r.get_hi_groups()
        if len(hi_groups) >= 2:
            # 每筆 = (from_id, dep_name_if_direct_inv 或 None, use_mode)；後者用於 OR 邊建立時記 _inv_edges
            group_outputs_hi: list[tuple[int, str, str | None, str, int]] = []
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
                            group_outputs_hi.append(
                                (from_id, d, d if inv_list[0] else None, use_list[0], gi)
                            )
                else:
                    key_hi = (r.name, "hi", gi)
                    if key_hi not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_hi] = aid
                        _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": _and_gate_style(r, "hi", gi), "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + _and_gate_offset_x(r.name)), "y": str(_and_y_top(r.name, "hi", gi)),
                            "as": "geometry"
                        })
                        _ay = _and_y_center(r.name, "hi", gi)
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                        gate_right_x[aid] = and_col_x + AND_GATE_W
                        _register_gate_catalog(gate_exit_lanes, aid, and_lane_idx.get(key_hi))
                    and_srcs = []
                    for i, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        from_id = _source_id(d, inv_list[i], True, use_list[i])
                        if from_id is not None:
                            and_srcs.append((from_id, d, inv_list[i], use_list[i], i))
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv, _um, ii) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)), from_id, _um)
                        eid = str(cell_id)
                        cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_hi])})
                        if inv:
                            _inv_edges[eid] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _and_y_center(r.name, "hi", gi)
                                _wire_input_to_gate(geo, lab, gy)
                        else:
                            _wire_and_dep_non_input(
                                geo, eid, from_id, d,
                                _and_y_center(r.name, "hi", gi), r.name,
                                "hi", gi, ii,
                                use_mode=_um,
                                layout_feedback_dep_keys=layout_feedback_dep_keys,
                                feedback_auto_edge_ids=feedback_auto_edge_ids,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                                hi_logic_out_id=hi_logic_out_id,
                                lo_logic_out_id=lo_logic_out_id,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                and_idx_map=idx_map,
                                name_to_rail=name_to_rail,
                                positions_out=positions_out,
                                id_to_y_center=id_to_y_center,
                                gate_exit_lanes=gate_exit_lanes,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                        geo.text = "\n            "
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    logic_hi = and_gate_id[key_hi]
                    group_outputs_hi.append((logic_hi, r.name, None, "self", gi))
            if group_outputs_hi:
                or_id = cell_id
                cell_id += 1
                or_gate_id[(r.name, "hi")] = or_id
                _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                _or_top = _or_y_top(r.name, "hi")
                _oy = _or_top + OR_GATE_H // 2
                id_to_y_center[or_id] = _oy
                gate_right_x[or_id] = _or_col_x(r.name) + OR_GATE_W
                or_cell = ET.SubElement(root, "mxCell", {
                    "id": str(or_id), "parent": "1", "style": _or_gate_style(r, "hi"), "value": "", "vertex": "1"
                })
                ET.SubElement(or_cell, "mxGeometry", {
                    "height": str(OR_GATE_H), "width": str(OR_GATE_W),
                    "x": str(_px + _or_gate_offset_x(r.name)), "y": str(_or_top),
                    "as": "geometry"
                })
                _register_gate_catalog(
                    gate_exit_lanes, or_id, or_lane_idx.get((r.name, "hi"))
                )
                sorted_hi = sorted(group_outputs_hi, key=lambda t: id_to_y_center.get(t[0], 0))
                hi_gate_out_ids = {
                    and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "hi"
                }
                for idx, (src_id, dep_name, dep_inv, dep_um, dep_gi) in enumerate(sorted_hi):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_hi)), src_id, dep_um)
                    eid = str(cell_id)
                    cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    if dep_inv is not None:
                        _inv_edges[eid] = (dep_inv, dep_um)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _oy = _or_y_center(r.name, "hi")
                    if src_id in hi_gate_out_ids:
                        _wire_and_or_output(
                            gate_exit_lanes, geo, src_id,
                            id_to_y_center[src_id], _oy, gate_right_x[src_id],
                        )
                    elif src_id in id_to_row:
                        # 輸入→OR：freeze_edge_routing 會補 stub waypoints
                        pass
                    else:
                        is_fb = _mark_traced_layout_feedback_edge(
                            feedback_auto_edge_ids,
                            eid,
                            src_id,
                            dep_name,
                            dep_um,
                            r.name,
                            "hi",
                            dep_gi,
                            0,
                            layout_feedback_dep_keys=layout_feedback_dep_keys,
                            output_to_row=output_to_row,
                            q_box_id_map=q_box_id_map,
                            nq_box_id_map=nq_box_id_map,
                            hi_logic_out_id=hi_logic_out_id,
                            lo_logic_out_id=lo_logic_out_id,
                            and_gate_id=and_gate_id,
                            or_gate_id=or_gate_id,
                            and_idx_map=idx_map,
                            name_to_rail=name_to_rail,
                            inner_id_to_row=inner_id_to_row,
                            inner_id_to_output=inner_id_to_output,
                            tgt_layer="or",
                        )
                        if not is_fb:
                            src_row = _logic_gate_source_row(
                                src_id,
                                dep_name,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                            )
                            tgt_row = output_to_row[r.name]
                            or_entry_x = _or_col_x(r.name)
                            _sy = id_to_y_center.get(src_id)
                            if _sy is not None:
                                _right = _logic_source_right_x(
                                    src_id,
                                    inner_id_to_output=inner_id_to_output,
                                    q_box_id_map=q_box_id_map,
                                    nq_box_id_map=nq_box_id_map,
                                    positions_out=positions_out,
                                    gate_right_x=gate_right_x,
                                    and_col_x=and_col_x,
                                )
                                if src_row is not None and src_row < tgt_row:
                                    gate_exit_lanes.wire_via_channel(
                                        geo, src_id, _right, _sy, or_entry_x, _oy
                                    )
                                else:
                                    gate_exit_lanes.wire_vertical(
                                        geo, src_id, _right, _sy, _oy
                                    )
                    geo.text = "\n            "
                or_out_hi = or_id
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_hi, "edge": "1", "parent": "1", "source": str(or_out_hi), "target": str(to_h_deb)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                _deb_y = _py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
                gate_exit_lanes.wire_via_channel(
                    geo, or_out_hi, gate_right_x[or_out_hi], id_to_y_center[or_out_hi],
                    _deb_entry_x(r.name), _deb_y,
                    max_lx=_deb_entry_x(r.name) - GRID,
                )
                geo.text = "\n            "
                hi_logic_out_id[r.name] = or_out_hi
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
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    is_input_dep = name_to_rail[d].seq_type == "input"
                    # input→Cell 與 inv=True 一律走「正向邊」(source=來源, target=H_Deb)：
                    # source 為 input label 者自動歸 Rule 1 正交自動（不畫反向標示邊）。
                    _sty = (
                        style_hi_to_cell_left
                        if _use_hi_lo_deb_placeholder_exit(from_id, _use)
                        else style_hi_to_cell
                    )
                    eid = str(cell_id)
                    cell = ET.SubElement(root, "mxCell", {"id": eid, "style": _sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_h_deb)})
                    if _iv:
                        _inv_edges[str(cell_id)] = (d, _use)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if not is_input_dep:
                        deb_y = _py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
                        src_row = _dep_source_row(
                            from_id,
                            d,
                            inner_id_to_row=inner_id_to_row,
                            inner_id_to_output=inner_id_to_output,
                            output_to_row=output_to_row,
                        )
                        tgt_row = output_to_row[r.name]
                        if _mark_layout_feedback_edge(
                            feedback_auto_edge_ids,
                            eid,
                            layout_feedback_dep_keys=layout_feedback_dep_keys,
                            tgt_rail=r.name,
                            hl="hi",
                            gi=gi,
                            ii=0,
                            dep_name=d,
                        ):
                            pass
                        elif src_row is not None and src_row < tgt_row:
                            _sy = id_to_y_center.get(from_id, _py + 40)
                            _right = _logic_source_right_x(
                                from_id,
                                inner_id_to_output=inner_id_to_output,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                positions_out=positions_out,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                            gate_exit_lanes.wire_via_channel(
                                geo, from_id, _right, _sy, _deb_entry_x(r.name), deb_y
                            )
                        elif src_row is not None and src_row > tgt_row:
                            # 上行回授（含 Q／~Q）→ 交由五段凍結回授走線（依 profile）。
                            feedback_auto_edge_ids.add(eid)
                        else:
                            _sy = id_to_y_center.get(from_id, _py + 40)
                            _right = _logic_source_right_x(
                                from_id,
                                inner_id_to_output=inner_id_to_output,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                positions_out=positions_out,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                            above_y = _align40(_py - GRID)
                            lx = gate_exit_lanes.stub_x(from_id, _right)
                            _add_edge_points(
                                geo,
                                [(lx, _sy), (lx, above_y), (lx, deb_y), (_deb_entry_x(r.name), deb_y)],
                                align=[False, True, True, True],
                            )
                    geo.text = "\n            "
                    hi_logic_out_id.setdefault(
                        r.name, _logic_output_pin(d, _iv, _use, from_id)
                    )
                else:
                    key_hi = (r.name, "hi", gi)
                    if key_hi not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_hi] = aid
                        _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": _and_gate_style(r, "hi", gi), "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + _and_gate_offset_x(r.name)), "y": str(_and_y_top(r.name, "hi", gi)),
                            "as": "geometry"
                        })
                        _ay = _and_y_center(r.name, "hi", gi)
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                        gate_right_x[aid] = and_col_x + AND_GATE_W
                        _register_gate_catalog(gate_exit_lanes, aid, and_lane_idx.get(key_hi))
                    and_id = and_gate_id[key_hi]
                    and_srcs = [(_source_id(d, inv_list[i], True, use_list[i]), d, use_list[i], inv_list[i], i) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], True, use_list[i]) is not None]
                    and_srcs = [(fid, d, um, iv, ii) for (fid, d, um, iv, ii) in and_srcs if fid is not None]
                    and_srcs.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, _um, _iv, ii) in enumerate(and_srcs):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs)), from_id, _um)
                        eid = str(cell_id)
                        cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        if _iv:
                            _inv_edges[eid] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _and_y_center(r.name, "hi", gi)
                                _wire_input_to_gate(geo, lab, gy)
                        else:
                            _wire_and_dep_non_input(
                                geo, eid, from_id, d,
                                _and_y_center(r.name, "hi", gi), r.name,
                                "hi", gi, ii,
                                use_mode=_um,
                                layout_feedback_dep_keys=layout_feedback_dep_keys,
                                feedback_auto_edge_ids=feedback_auto_edge_ids,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                                hi_logic_out_id=hi_logic_out_id,
                                lo_logic_out_id=lo_logic_out_id,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                and_idx_map=idx_map,
                                name_to_rail=name_to_rail,
                                positions_out=positions_out,
                                id_to_y_center=id_to_y_center,
                                gate_exit_lanes=gate_exit_lanes,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                        geo.text = "\n            "
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    and_id = and_gate_id[key_hi]
                    logic_hi = and_id
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_hi, "edge": "1", "parent": "1", "source": str(logic_hi), "target": str(to_h_deb)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _hy = _py + CELL_H_DEB_Y + CELL_H_DEB_H // 2
                    gate_exit_lanes.wire_via_channel(
                        geo, logic_hi, gate_right_x[logic_hi], id_to_y_center[logic_hi],
                        _deb_entry_x(r.name), _hy,
                    )
                    geo.text = "\n            "
                    hi_logic_out_id[r.name] = logic_hi

        lo_groups = r.get_lo_groups()
        if len(lo_groups) >= 2:
            group_outputs_lo: list[tuple[int, str, str | None, str, int]] = []
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
                            group_outputs_lo.append(
                                (from_id, d, d if inv_list[0] else None, use_list[0], gi)
                            )
                else:
                    key_lo = (r.name, "lo", gi)
                    if key_lo not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_lo] = aid
                        _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": _and_gate_style(r, "lo", gi), "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + _and_gate_offset_x(r.name)), "y": str(_and_y_top(r.name, "lo", gi)),
                            "as": "geometry"
                        })
                        _ay = _and_y_center(r.name, "lo", gi)
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                        gate_right_x[aid] = and_col_x + AND_GATE_W
                        _register_gate_catalog(gate_exit_lanes, aid, and_lane_idx.get(key_lo))
                    and_srcs_lo = []
                    for i, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        from_id = _source_id(d, inv_list[i], False, use_list[i])
                        if from_id is not None:
                            and_srcs_lo.append((from_id, d, inv_list[i], use_list[i], i))
                    and_srcs_lo.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, inv, _um, ii) in enumerate(and_srcs_lo):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo)), from_id, _um)
                        eid = str(cell_id)
                        cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_gate_id[key_lo])})
                        if inv:
                            _inv_edges[eid] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _and_y_center(r.name, "lo", gi)
                                _wire_input_to_gate(geo, lab, gy)
                        else:
                            _wire_and_dep_non_input(
                                geo, eid, from_id, d,
                                _and_y_center(r.name, "lo", gi), r.name,
                                "lo", gi, ii,
                                use_mode=_um,
                                layout_feedback_dep_keys=layout_feedback_dep_keys,
                                feedback_auto_edge_ids=feedback_auto_edge_ids,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                                hi_logic_out_id=hi_logic_out_id,
                                lo_logic_out_id=lo_logic_out_id,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                and_idx_map=idx_map,
                                name_to_rail=name_to_rail,
                                positions_out=positions_out,
                                id_to_y_center=id_to_y_center,
                                gate_exit_lanes=gate_exit_lanes,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                        geo.text = "\n            "
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    logic_lo = and_gate_id[key_lo]
                    group_outputs_lo.append((logic_lo, r.name, None, "self", gi))
            if group_outputs_lo:
                or_id = cell_id
                cell_id += 1
                or_gate_id[(r.name, "lo")] = or_id
                _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                _or_top = _or_y_top(r.name, "lo")
                _oy = _or_top + OR_GATE_H // 2
                id_to_y_center[or_id] = _oy
                gate_right_x[or_id] = _or_col_x(r.name) + OR_GATE_W
                or_cell = ET.SubElement(root, "mxCell", {
                    "id": str(or_id), "parent": "1", "style": _or_gate_style(r, "lo"), "value": "", "vertex": "1"
                })
                ET.SubElement(or_cell, "mxGeometry", {
                    "height": str(OR_GATE_H), "width": str(OR_GATE_W),
                    "x": str(_px + _or_gate_offset_x(r.name)), "y": str(_or_top),
                    "as": "geometry"
                })
                _register_gate_catalog(
                    gate_exit_lanes, or_id, or_lane_idx.get((r.name, "lo"))
                )
                sorted_lo = sorted(group_outputs_lo, key=lambda t: id_to_y_center.get(t[0], 0))
                lo_gate_out_ids = {
                    and_gate_id[k] for k in and_gate_id if k[0] == r.name and k[1] == "lo"
                }
                for idx, (src_id, dep_name, dep_inv, dep_um, dep_gi) in enumerate(sorted_lo):
                    sty = _style_edge_to_gate_entry(_gate_entry_y(idx, len(sorted_lo)), src_id, dep_um)
                    eid = str(cell_id)
                    cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(src_id), "target": str(or_id)})
                    if dep_inv is not None:
                        _inv_edges[eid] = (dep_inv, dep_um)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _oy = _or_y_center(r.name, "lo")
                    if src_id in lo_gate_out_ids:
                        _wire_and_or_output(
                            gate_exit_lanes, geo, src_id,
                            id_to_y_center[src_id], _oy, gate_right_x[src_id],
                        )
                    elif src_id in id_to_row:
                        # 輸入→OR：freeze_edge_routing 會補 stub waypoints
                        pass
                    else:
                        is_fb = _mark_traced_layout_feedback_edge(
                            feedback_auto_edge_ids,
                            eid,
                            src_id,
                            dep_name,
                            dep_um,
                            r.name,
                            "lo",
                            dep_gi,
                            0,
                            layout_feedback_dep_keys=layout_feedback_dep_keys,
                            output_to_row=output_to_row,
                            q_box_id_map=q_box_id_map,
                            nq_box_id_map=nq_box_id_map,
                            hi_logic_out_id=hi_logic_out_id,
                            lo_logic_out_id=lo_logic_out_id,
                            and_gate_id=and_gate_id,
                            or_gate_id=or_gate_id,
                            and_idx_map=idx_map,
                            name_to_rail=name_to_rail,
                            inner_id_to_row=inner_id_to_row,
                            inner_id_to_output=inner_id_to_output,
                            tgt_layer="or",
                        )
                        if not is_fb:
                            src_row = _logic_gate_source_row(
                                src_id,
                                dep_name,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                            )
                            tgt_row = output_to_row[r.name]
                            or_entry_x = _or_col_x(r.name)
                            _sy = id_to_y_center.get(src_id)
                            if _sy is not None:
                                _right = _logic_source_right_x(
                                    src_id,
                                    inner_id_to_output=inner_id_to_output,
                                    q_box_id_map=q_box_id_map,
                                    nq_box_id_map=nq_box_id_map,
                                    positions_out=positions_out,
                                    gate_right_x=gate_right_x,
                                    and_col_x=and_col_x,
                                )
                                if src_row is not None and src_row < tgt_row:
                                    gate_exit_lanes.wire_via_channel(
                                        geo, src_id, _right, _sy, or_entry_x, _oy
                                    )
                                else:
                                    gate_exit_lanes.wire_vertical(
                                        geo, src_id, _right, _sy, _oy
                                    )
                    geo.text = "\n            "
                or_out_lo = or_id
                cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_or_to_cell_lo, "edge": "1", "parent": "1", "source": str(or_out_lo), "target": str(to_l_deb)})
                cell_id += 1
                geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                _deb_y = _py + CELL_L_DEB_Y + CELL_L_DEB_H // 2
                gate_exit_lanes.wire_via_channel(
                    geo, or_out_lo, gate_right_x[or_out_lo], id_to_y_center[or_out_lo],
                    _deb_entry_x(r.name), _deb_y,
                    max_lx=_deb_entry_x(r.name) - GRID,
                )
                geo.text = "\n            "
                lo_logic_out_id[r.name] = or_out_lo
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
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    is_input_dep = name_to_rail[d].seq_type == "input"
                    # input→Cell 與 inv=True 一律走「正向邊」(source=來源, target=L_Deb)：
                    # source 為 input label 者自動歸 Rule 1 正交自動（不畫反向標示邊）。
                    _sty = (
                        style_lo_to_cell_left
                        if _use_hi_lo_deb_placeholder_exit(from_id, _use)
                        else style_lo_to_cell
                    )
                    eid = str(cell_id)
                    cell = ET.SubElement(root, "mxCell", {"id": eid, "style": _sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(to_l_deb)})
                    if _iv:
                        _inv_edges[str(cell_id)] = (d, _use)
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    if not is_input_dep:
                        deb_y = _py + CELL_L_DEB_Y + CELL_L_DEB_H // 2
                        src_row = _dep_source_row(
                            from_id,
                            d,
                            inner_id_to_row=inner_id_to_row,
                            inner_id_to_output=inner_id_to_output,
                            output_to_row=output_to_row,
                        )
                        tgt_row = output_to_row[r.name]
                        if _mark_layout_feedback_edge(
                            feedback_auto_edge_ids,
                            eid,
                            layout_feedback_dep_keys=layout_feedback_dep_keys,
                            tgt_rail=r.name,
                            hl="lo",
                            gi=gi,
                            ii=0,
                            dep_name=d,
                        ):
                            pass
                        elif src_row is not None and src_row < tgt_row:
                            _sy = id_to_y_center.get(from_id, _py + 40)
                            _right = _logic_source_right_x(
                                from_id,
                                inner_id_to_output=inner_id_to_output,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                positions_out=positions_out,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                            gate_exit_lanes.wire_via_channel(
                                geo, from_id, _right, _sy, _deb_entry_x(r.name), deb_y
                            )
                        elif src_row is not None and src_row > tgt_row:
                            # 上行回授（含 Q／~Q）→ 交由五段凍結回授走線（依 profile）。
                            feedback_auto_edge_ids.add(eid)
                        else:
                            _sy = id_to_y_center.get(from_id, _py + 40)
                            _right = _logic_source_right_x(
                                from_id,
                                inner_id_to_output=inner_id_to_output,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                positions_out=positions_out,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                            above_y = _align40(_py - GRID)
                            lx = gate_exit_lanes.stub_x(from_id, _right)
                            _add_edge_points(
                                geo,
                                [(lx, _sy), (lx, above_y), (lx, deb_y), (_deb_entry_x(r.name), deb_y)],
                                align=[False, True, True, True],
                            )
                    geo.text = "\n            "
                    lo_logic_out_id.setdefault(
                        r.name, _logic_output_pin(d, _iv, _use, from_id)
                    )
                else:
                    key_lo = (r.name, "lo", gi)
                    if key_lo not in and_gate_id:
                        aid = cell_id
                        cell_id += 1
                        and_gate_id[key_lo] = aid
                        _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                        and_cell = ET.SubElement(root, "mxCell", {
                            "id": str(aid), "parent": "1", "style": _and_gate_style(r, "lo", gi), "value": "", "vertex": "1"
                        })
                        ET.SubElement(and_cell, "mxGeometry", {
                            "height": str(AND_GATE_H), "width": str(AND_GATE_W),
                            "x": str(_px + _and_gate_offset_x(r.name)), "y": str(_and_y_top(r.name, "lo", gi)),
                            "as": "geometry"
                        })
                        _ay = _and_y_center(r.name, "lo", gi)
                        and_gate_y[aid] = _ay
                        id_to_y_center[aid] = _ay
                        gate_right_x[aid] = and_col_x + AND_GATE_W
                        _register_gate_catalog(gate_exit_lanes, aid, and_lane_idx.get(key_lo))
                    and_id = and_gate_id[key_lo]
                    and_srcs_lo2 = [(_source_id(d, inv_list[i], False, use_list[i]), d, use_list[i], inv_list[i], i) for i, d in enumerate(group) if d in valid and d not in CONST_DEPS and _source_id(d, inv_list[i], False, use_list[i]) is not None]
                    and_srcs_lo2 = [(fid, d, um, iv, ii) for (fid, d, um, iv, ii) in and_srcs_lo2 if fid is not None]
                    and_srcs_lo2.sort(key=lambda t: id_to_y_center.get(t[0], 0))
                    for i, (from_id, d, _um, _iv, ii) in enumerate(and_srcs_lo2):
                        sty = _style_edge_to_gate_entry(_gate_entry_y(i, len(and_srcs_lo2)), from_id, _um)
                        eid = str(cell_id)
                        cell = ET.SubElement(root, "mxCell", {"id": eid, "style": sty, "edge": "1", "parent": "1", "source": str(from_id), "target": str(and_id)})
                        if _iv:
                            _inv_edges[eid] = (d, _um)
                        cell_id += 1
                        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                        if name_to_rail[d].seq_type == "input":
                            lab = positions_in.get(d)
                            if lab:
                                gy = _and_y_center(r.name, "lo", gi)
                                _wire_input_to_gate(geo, lab, gy)
                        else:
                            _wire_and_dep_non_input(
                                geo, eid, from_id, d,
                                _and_y_center(r.name, "lo", gi), r.name,
                                "lo", gi, ii,
                                use_mode=_um,
                                layout_feedback_dep_keys=layout_feedback_dep_keys,
                                feedback_auto_edge_ids=feedback_auto_edge_ids,
                                inner_id_to_row=inner_id_to_row,
                                inner_id_to_output=inner_id_to_output,
                                output_to_row=output_to_row,
                                hi_logic_out_id=hi_logic_out_id,
                                lo_logic_out_id=lo_logic_out_id,
                                q_box_id_map=q_box_id_map,
                                nq_box_id_map=nq_box_id_map,
                                and_gate_id=and_gate_id,
                                or_gate_id=or_gate_id,
                                and_idx_map=idx_map,
                                name_to_rail=name_to_rail,
                                positions_out=positions_out,
                                id_to_y_center=id_to_y_center,
                                gate_exit_lanes=gate_exit_lanes,
                                gate_right_x=gate_right_x,
                                and_col_x=and_col_x,
                            )
                        geo.text = "\n            "
                    _px, _py = positions_out.get(r.name, (_cell_x(r.name), MARGIN))
                    and_id = and_gate_id[key_lo]
                    logic_lo = and_id
                    cell = ET.SubElement(root, "mxCell", {"id": str(cell_id), "style": style_and_to_cell_lo, "edge": "1", "parent": "1", "source": str(logic_lo), "target": str(to_l_deb)})
                    cell_id += 1
                    geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
                    _ly = _py + CELL_L_DEB_Y + CELL_L_DEB_H // 2
                    gate_exit_lanes.wire_via_channel(
                        geo, logic_lo, gate_right_x[logic_lo], id_to_y_center[logic_lo],
                        _deb_entry_x(r.name), _ly,
                    )
                    geo.text = "\n            "
                    lo_logic_out_id[r.name] = logic_lo

    # --- Post-fix ---
    # 三個 pass：
    # Pass 1: 將「use_mode=hi/lo 但非 inv」的邊 source 從 H_Deb/L_Deb 佔位符替換為邏輯輸出 cell；
    #         同時修正 style：exitX=0（H_Deb 左側）→ exitX=1（AND/OR 閘右側）。
    # Pass 2: 為每個唯一 (來源 d, use_mode) 建立一顆「共用 NOT 閘」。
    #         input NOT：label 右/下 40pt；output NOT：O 矩形右/下 40pt。
    # Pass 3: 將所有 inv=True 的邊 source 替換為對應 NOT 閘 id；修正 style 與走線。
    style_not_gate_out = (
        "verticalLabelPosition=bottom;shadow=0;dashed=0;align=center;html=1;"
        "verticalAlign=top;shape=mxgraph.electrical.logic_gates.inverter_2"
    )
    style_logic_to_not = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;entryPerimeter=0;strokeColor=%s;endArrow=classic;endFill=1;"
    style_src_to_not = style_logic_to_not % STROKE_DEFAULT

    h_deb_ids: dict[int, str] = {nid: rname for rname, nid in h_deb_id_map.items()}
    l_deb_ids: dict[int, str] = {nid: rname for rname, nid in l_deb_id_map.items()}

    and_rev_pass1 = {v: k for k, v in and_gate_id.items()}
    or_rev_pass1 = {v: k for k, v in or_gate_id.items()}
    deb_tgt_row: dict[int, int] = {}
    for rname, nid in h_deb_id_map.items():
        deb_tgt_row[nid] = output_to_row[rname]
    for rname, nid in l_deb_id_map.items():
        deb_tgt_row[nid] = output_to_row[rname]

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
        upstream_rail = h_deb_ids.get(src_id) or l_deb_ids.get(src_id)
        real_id = _coerce_cell_out_id(
            upstream_rail,
            real_id,
            inv=False,
            out_inner_id=out_inner_id,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
        )
        if upstream_rail is None:
            continue
        hl_pass = "hi" if src_id in h_deb_ids else "lo"
        tgt_str = edge_cell.get("target")
        if tgt_str is None:
            continue
        try:
            tgt_id = int(tgt_str)
        except ValueError:
            continue
        edge_cell.set("source", str(real_id))
        sty = sty.replace("exitX=0", "exitX=1")
        sty = sty.replace("exitY=0.25", "exitY=0.5").replace("exitY=0.75", "exitY=0.5")
        edge_cell.set("style", sty)
        src_row = _pass1_real_source_row(
            real_id,
            upstream_rail,
            inner_id_to_row=inner_id_to_row,
            hi_logic_out_id=hi_logic_out_id,
            lo_logic_out_id=lo_logic_out_id,
            and_gate_id=and_gate_id,
            or_gate_id=or_gate_id,
            q_box_id_map=q_box_id_map,
            nq_box_id_map=nq_box_id_map,
            output_to_row=output_to_row,
        )
        tgt_row: int | None = None
        if tgt_id in and_rev_pass1:
            tgt_row = output_to_row[and_rev_pass1[tgt_id][0]]
        elif tgt_id in or_rev_pass1:
            tgt_row = output_to_row[or_rev_pass1[tgt_id][0]]
        elif tgt_id in deb_tgt_row:
            tgt_row = deb_tgt_row[tgt_id]
        edge_id_str = edge_cell.get("id")
        if edge_id_str is not None and src_row is not None and tgt_row is not None and _pass1_is_layout_feedback(
            upstream_rail,
            src_row,
            tgt_row,
            tgt_id,
            hl_pass,
            layout_feedback_dep_keys=layout_feedback_dep_keys,
            and_rev_pass1=and_rev_pass1,
            deb_tgt_row=deb_tgt_row,
            output_to_row=output_to_row,
        ):
            feedback_auto_edge_ids.add(edge_id_str)
            _clear_edge_waypoints(edge_cell.find("mxGeometry"))
        else:
            _rewire_pass1_logic_edge(
                edge_cell.find("mxGeometry"),
                real_id,
                tgt_id,
                upstream_rail=upstream_rail,
                hl=hl_pass,
                gate_exit_lanes=gate_exit_lanes,
                gate_right_x=gate_right_x,
                id_to_y_center=id_to_y_center,
                output_to_row=output_to_row,
                and_gate_id=and_gate_id,
                or_gate_id=or_gate_id,
                h_deb_id_map=h_deb_id_map,
                l_deb_id_map=l_deb_id_map,
                and_col_x=and_col_x,
                or_col_x_fn=_or_col_x,
                row_py=row_py,
                deb_entry_x_fn=_deb_entry_x,
                row_bottom_fn=_row_bottom,
                name_to_rail=name_to_rail,
                entry_ay=_style_float(sty, "entryY", 0.5),
            )

    # ---- Pass 2: 為每個唯一 (d, use_mode) 建立共用 NOT 閘 ----
    def _logic_source_id(d: str, use_mode: str) -> int | None:
        """根據 (d, use_mode) 取得真正的邏輯來源 cell id。"""
        if name_to_rail[d].seq_type == "input":
            return in_label_id.get(d)
        if use_mode == "hi":
            return hi_logic_out_id.get(d) or q_box_id_map.get(d)
        if use_mode == "lo":
            return lo_logic_out_id.get(d) or q_box_id_map.get(d)
        return q_box_id_map.get(d)

    unique_inv_keys: list[tuple[str, str]] = []
    seen = set()
    for k in _inv_edges.values():
        if k not in seen:
            seen.add(k)
            unique_inv_keys.append(k)

    for d, use_mode in unique_inv_keys:
        is_input_src = name_to_rail[d].seq_type == "input"
        if not is_input_src:
            not_gate_id[(d, use_mode)] = nq_box_id_map[d]
            continue
        label_xy = positions_in[d]
        not_x, not_y = _input_not_position(label_xy, min_cell_top_y)
        src_id = _logic_source_id(d, use_mode)
        if src_id is None:
            continue
        nid = cell_id
        cell_id += 1
        not_gate_id[(d, use_mode)] = nid
        input_not_src_ids.add(str(nid))
        not_cell = ET.SubElement(root, "mxCell", {
            "id": str(nid), "parent": "1", "style": style_input_not_gate, "value": "", "vertex": "1"
        })
        ET.SubElement(not_cell, "mxGeometry", {
            "height": str(NOT_GATE_H), "width": str(NOT_GATE_W),
            "x": str(not_x), "y": str(not_y), "as": "geometry"
        })
        id_to_y_center[nid] = not_y + NOT_GATE_H // 2

        e_src_to_not = ET.SubElement(root, "mxCell", {
            "id": str(cell_id), "style": style_src_to_not,
            "edge": "1", "parent": "1", "source": str(src_id), "target": str(nid),
        })
        _fixed_not_edge_ids.add(str(cell_id))
        cell_id += 1
        geo_not = ET.SubElement(e_src_to_not, "mxGeometry", {"relative": "1", "as": "geometry"})
        lx, ly = positions_in[d]
        _add_edge_points(
            geo_not,
            _input_to_not_waypoints((lx, ly), (not_x, not_y)),
            align=False,
        )

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
        geo = edge_cell.find("mxGeometry")
        if geo is not None:
            for arr in list(geo):
                if arr.tag == "Array" and arr.get("as") == "points":
                    geo.remove(arr)

    input_auto_src_ids = {str(v) for v in in_label_id.values()} | input_not_src_ids
    gate_source_stubs = {
        str(eid): float(stub) for eid, stub in gate_exit_lanes.catalog_stub_items().items()
    }
    n_and_total = _count_total_and_gates(outputs)
    m_or_total = _count_total_or_gates(outputs)
    fb_cell_total = _count_cell_fb_to_deb(outputs, output_to_row, name_to_rail, valid)
    fb_or_total = _count_or_fb_routing_slots(
        outputs, output_to_row, name_to_rail, valid
    )
    exempt_ao, exempt_ac, exempt_oc = _count_direct_horizontal_exempts(
        outputs,
        output_to_row,
        name_to_rail,
        valid,
        and_index_per_key,
        idx_map,
        and_top_y,
        row_py,
        or_idx_map=or_idx_map,
        or_top_y=or_top_y,
    )
    _supplement_traced_feedback_edges(
        root,
        feedback_auto_edge_ids,
        output_to_row=output_to_row,
        q_box_id_map=q_box_id_map,
        nq_box_id_map=nq_box_id_map,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
        and_idx_map=idx_map,
        name_to_rail=name_to_rail,
        inner_id_to_row=inner_id_to_row,
        inner_id_to_output=inner_id_to_output,
        deb_tgt_row=deb_tgt_row,
    )
    _apply_feedback_routing(
        root,
        feedback_auto_edge_ids,
        channel_x_left=channel_x_left,
        feedback_n=feedback_n,
        fb_cell=fb_cell_total,
        fb_or=fb_or_total,
        and_col_x=and_col_x,
        n_and=n_and_total,
        exempt_ac=exempt_ac,
        exempt_ao=exempt_ao,
        m_or=m_or_total,
        exempt_oc=exempt_oc,
        row_gate_layout=row_gate_layout,
        q_box_id_map=q_box_id_map,
        nq_box_id_map=nq_box_id_map,
        gate_exit_lanes=gate_exit_lanes,
        gate_right_x=gate_right_x,
        and_gate_id=and_gate_id,
        or_gate_id=or_gate_id,
        deb_tgt_row=deb_tgt_row,
        h_deb_id_map=h_deb_id_map,
        l_deb_id_map=l_deb_id_map,
        output_to_row=output_to_row,
        or_col_x_fn=_or_col_x,
        deb_entry_x_fn=_deb_entry_x,
    )
    freeze_edge_routing(
        root,
        skip_source_ids=input_auto_src_ids,
        source_min_stub=gate_source_stubs,
    )
    restore_orthogonal_auto_routing(root, input_auto_src_ids)
    _apply_feedback_edge_color(root, feedback_auto_edge_ids)
    _apply_edge_wire_style(root)

    rough = ET.tostring(mxfile, encoding="unicode", default_namespace="")
    dom = minidom.parseString(rough)
    pretty = dom.documentElement.toprettyxml(indent="  ", encoding=None)
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.strip().startswith("<?xml"):
        out = decl + pretty.split("\n", 1)[-1]
    else:
        out = decl + pretty
    return out.replace('"/>', '" />')
