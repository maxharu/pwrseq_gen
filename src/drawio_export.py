"""
Export Power Sequence dependency as Draw.io XML (cell-centric grid).

Each output rail is an independent block on a single-page multi-column grid:
input / cond labels → local AND/OR → PSEQCELL → output name.
Cross-cell deps use Verilog-style cond names ({internal_sig}_{hi|lo}). Force is not drawn.
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
CELL_O_W = 20
CELL_O_H = 20
CELL_O_X = 60
CELL_O_Y = 30
# 版面規則：欄位水平間距 GAP（40pt）；Cell 列間基本間距 ROW_GAP（40pt）
GRID = 40
FB_Q_RIGHT = GRID
FB_Q_UP = GRID + 20
FB_NQ_RIGHT = 2 * GRID   # ~Q 回授（同 Cell 亦有 Q 回授）：先右 2×40pt
FB_NQ_UP = 3 * GRID + 20  # ② 上移 140pt（高於 Q 的 60pt，走廊不重疊）
FB_NQ_UP_NO_Q = 100       # ~Q 回授（同 Cell 無 Q 回授）：② 上移 100pt
GAP = 40
ROW_GAP = GRID  # Cell 列間基本 Y 間距（40pt）

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
INPUT_VERTICAL_DY = 80           # 每個 input 垂直間距（用於反相 output 等）
GATE_COL_X = _align40(GAP * 5)   # 200：OR 與 AND 同一欄（參考）
CELL_START_X = _align40(GAP * 8)  # 320（參考）
OUTPUT_NAME_GAP = _align40(120)       # Cell 右緣 → 輸出名稱欄淨空（pt）
OUTPUT_NAME_NOT_EXTRA = 80            # 任一 output 用 O 側 NOT 時，全列再 +80pt
OUTPUT_NAME_OFFSET_X = CELL_GROUP_W + OUTPUT_NAME_GAP  # 預設參考（無 output NOT）
# 輸出名稱 y 與 O 垂直置中對齊，使 O→名稱為水平直線（載入 PSEQCELL.xml 後重算）
OUTPUT_NAME_OFFSET_Y = CELL_O_Y + CELL_O_H // 2 - INPUT_LABEL_H // 2
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
NOT_OFFSET_X = 80  # output NOT 右移 80pt
NOT_OFFSET_Y = GRID     # 下 40pt
NOT_TURN_X = GRID    # input 走線：label 錨點 + 40pt 垂直 bus（先下後右）
# input NOT（皆 rotation=90，見 reference/INPUT_NOT.xml）：左 20pt；底邊在最上 Cell 上緣之上 40pt
INPUT_NOT_LEFT = GRID - 20
INPUT_NOT_ABOVE_CELL = GRID
INPUT_NOT_LABEL_TO_NOT_GAP = INPUT_LABEL_H  # label 底邊至 NOT 頂 20pt（INPUT_NOT.xml）
NOT_STACK_GAP = INPUT_LABEL_H  # 下一列放在 NOT 下方時的間距
# AND/OR 整組反相：內建 negating bubble（reference/NAND1.xml、NOR1.xml），不再外掛 inverter_2
def _reference_dir() -> Path:
    """PyInstaller onefile 時資源在 sys._MEIPASS/reference。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "reference"
    return Path(__file__).resolve().parent / "reference"


_REFERENCE_DIR = _reference_dir()


_PSEQCELL_STYLE_INNER = "rounded=0;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_H_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_L_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_Q = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_O = "rounded=1;whiteSpace=wrap;html=1;"


def _parse_pulse_period(pulse_name: str) -> tuple[int, str] | None:
    """Pulse_1us / iPulse_1us → (1, 'us')；Pulse_2ms → (2, 'ms')。"""
    if not pulse_name or pulse_name in ("default", "High"):
        return None
    s = pulse_name
    if s.startswith("iPulse_"):
        s = s[7:]
    elif s.startswith("Pulse_"):
        s = s[6:]
    if s.endswith("us"):
        try:
            return int(s[:-2]), "us"
        except ValueError:
            return None
    if s.endswith("ms"):
        try:
            return int(s[:-2]), "ms"
        except ValueError:
            return None
    return None


def _deb_time_text(cycle: int, pulse: str) -> str:
    """PSEQCELL debounce 總時間：cycle × pulse 週期；cycle≤0 或 High/default → 0s。"""
    if cycle <= 0:
        return "0s"
    parsed = _parse_pulse_period(pulse)
    if parsed is None:
        return "0s"
    period, unit = parsed
    return f"{cycle * period}{unit}"


def _deb_port_label(kind: str, cycle: int, pulse: str) -> str:
    """H_Deb / L_Deb 顯示為「H: 時間」「L: 時間」。"""
    return f"{kind}:{_deb_time_text(cycle, pulse)}"


def _style_align_left(style: str) -> str:
    """mxGraph html label 靠左對齊（不重複附加 align）。"""
    if re.search(r"(?:^|;)align=", style):
        return style
    sep = "" if style.endswith(";") or not style else ";"
    return f"{style}{sep}align=left;"


def _load_pseqcell_layout() -> None:
    """自 reference/PSEQCELL.xml 載入 Cell 幾何與 style（含連接點 points；RTL 見 PSEQCELL.v）。"""
    global CELL_GROUP_W, CELL_GROUP_H, CELL_INNER_X, CELL_INNER_W, CELL_INNER_H
    global CELL_H_DEB_W, CELL_H_DEB_H, CELL_L_DEB_W, CELL_L_DEB_H
    global CELL_H_DEB_Y, CELL_L_DEB_Y
    global CELL_O_W, CELL_O_H, CELL_O_X, CELL_O_Y
    global CELL_Q_W, CELL_Q_H, CELL_Q_X, CELL_Q_Y
    global CELL_NQ_W, CELL_NQ_H, CELL_NQ_X, CELL_NQ_Y
    global OUTPUT_NAME_OFFSET_Y
    global _PSEQCELL_STYLE_INNER, _PSEQCELL_STYLE_H_DEB, _PSEQCELL_STYLE_L_DEB
    global _PSEQCELL_STYLE_Q, _PSEQCELL_STYLE_O

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
        elif val == "O":
            parts["o"] = (x, y, w, h)
            styles["o"] = style
        elif val == "Q":
            parts["q"] = (x, y, w, h)
            styles["q"] = style
        elif val == "~Q":
            parts["nq"] = (x, y, w, h)
            styles["nq"] = style
        elif not val and "rounded=0" in style:
            parts["inner"] = (x, y, w, h)
            styles["inner"] = style

    if "o" in parts:
        required = ("inner", "h_deb", "l_deb", "o")
    else:
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
    if "o" in parts:
        ox, oy, ow, oh = parts["o"]
        CELL_O_X, CELL_O_Y, CELL_O_W, CELL_O_H = ox, oy, ow, oh
        CELL_Q_X, CELL_Q_Y, CELL_Q_W, CELL_Q_H = ox, oy, ow, oh
        _PSEQCELL_STYLE_O = styles["o"]
        _PSEQCELL_STYLE_Q = styles["o"]
    else:
        qx, qy, qw, qh = parts["q"]
        CELL_Q_X, CELL_Q_Y, CELL_Q_W, CELL_Q_H = qx, qy, qw, qh
        CELL_O_X, CELL_O_Y, CELL_O_W, CELL_O_H = qx, qy, qw, qh
        _PSEQCELL_STYLE_Q = styles["q"]
        _PSEQCELL_STYLE_O = styles["q"]
    if "nq" in parts:
        nx, ny, nw, nh = parts["nq"]
        CELL_NQ_X, CELL_NQ_Y, CELL_NQ_W, CELL_NQ_H = nx, ny, nw, nh
    CELL_GROUP_W = group_w or iw
    CELL_GROUP_H = group_h or ih
    _PSEQCELL_STYLE_INNER = styles["inner"]
    _PSEQCELL_STYLE_H_DEB = _style_align_left(styles["h_deb"])
    _PSEQCELL_STYLE_L_DEB = _style_align_left(styles["l_deb"])
    OUTPUT_NAME_OFFSET_Y = CELL_O_Y + CELL_O_H // 2 - INPUT_LABEL_H // 2


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
AND_GATE_DY = 80                # 同 hl 多顆 AND 垂直堆疊（對齊 H/L_Deb 後再 +80pt）
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


def _and_fb_source_key_for_dep(
    d: str,
    *,
    inv: bool,
    use: str,
    name_to_rail: dict[str, PowerRail],
    idx_map: dict[tuple[str, str, int], int],
) -> tuple:
    """對應 Pass 3 後實際 FB 來源（Q／~Q／AND output），供 placement 幹線寬度估算。"""
    if inv and name_to_rail[d].seq_type != "input":
        return ("nq", d)
    if use == "self" and name_to_rail[d].seq_type != "input":
        return ("q", d)
    src_idx = _departing_and_index(d, use, idx_map=idx_map, name_to_rail=name_to_rail)
    if src_idx is not None:
        return ("and_idx", src_idx)
    if use in ("hi", "lo") and name_to_rail[d].seq_type != "input":
        return ("or", d, use)
    return ("q", d)


def _estimate_and_lane_count(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> int:
    """預估 AND 層唯一 FB source 數（Q／~Q／departing AND／OR／RSMRST），供 placement 左幹線寬度。"""
    n_trunk, trunk_and, has_rsmrst = _count_feedback_trunks(
        outputs, output_to_row, name_to_rail, valid
    )
    keys: set[tuple] = set()
    for idx in trunk_and:
        keys.add(("and_idx", idx))
    if has_rsmrst:
        keys.add(("rsmrst",))
    _, idx_map = _build_and_catalog(outputs)
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
                    if src_row is None or tgt_row is None:
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
                        continue
                    if src_row == tgt_row:
                        if not inv and use == "self":
                            keys.add(("q", d))
                        continue
                    keys.add(
                        _and_fb_source_key_for_dep(
                            d,
                            inv=inv,
                            use=use,
                            name_to_rail=name_to_rail,
                            idx_map=idx_map,
                        )
                    )
    return max(n_trunk, len(keys), 1)


_FB_FAMILY_PRIO = {"gate": 0, "q": 1, "nq": 2}


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

    僅在來源 Cell 與上一列 Cell 之間（gap src_row-1）預留；④ 段垂直幹線走 X 通道。
    profile（``q``／``nq``）區分 Q／~Q 走廊，同 gap 可累加。
    """
    _ = profile
    if src_row >= 1:
        return [src_row - 1]
    return []


def _feedback_y_slack_between_cell_rows(
    outputs: list[PowerRail],
    output_to_row: dict[str, int],
    name_to_rail: dict[str, PowerRail],
    valid: set[str],
) -> dict[int, int]:
    """
    Cell 層：來源 Cell 與上一列 Cell 之間的 gap +40pt（同一 gap 可累加）。
    觸發：跨列 Cell Q／~Q 回授（use=self、來源為 output）— 含 ~Q→Deb 與 Q→AND。
    僅在 FB ③ 段 p2y 水平走廊、來源列正上方一格預留 Y 通道。
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
        if row_j != prev_row:
            # 新列：錨定 H_Deb/L_Deb 對齊 offset，不受前列 global chain 下推
            tops[g] = nominal
        elif nominal >= tops[g - 1] + AND_GATE_H:
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


def _feedback_source_rail(
    src_id: int,
    *,
    q_rev: dict[int, str],
    nq_rev: dict[int, str],
    and_rev: dict[int, tuple[str, str, int]],
    or_rev: dict[int, tuple[str, str]],
) -> str:
    if src_id in nq_rev:
        return nq_rev[src_id]
    if src_id in q_rev:
        return q_rev[src_id]
    if src_id in and_rev:
        return and_rev[src_id][0]
    if src_id in or_rev:
        return or_rev[src_id][0]
    return f"__src_{src_id}"


@dataclass
class _FbRouteSpec:
    edge_cell: ET.Element
    eid: str
    src_id: int
    profile: str
    rail_name: str
    ey: float
    ty: float
    p1x: float
    tgt_layer: str
    tgt_rail: str
    entry_x: float
    up_delta: float
    p3x: float
    sty: str


def _plan_global_feedback_y_rows(
    specs: list[_FbRouteSpec],
    *,
    obstacle_boxes: list[tuple[float, float, float, float]],
    and_rev: dict[int, tuple[str, str, int]],
    or_rev: dict[int, tuple[str, str]],
) -> dict[str, float]:
    """C.1：依目標層／來源列／profile 全局排序後分配 ② 橫列 Y。"""
    used_fb_rows: list[tuple[float, float, float]] = []
    rail_rows: dict[str, list[float]] = {}
    source_layer_row: dict[tuple[int, str], float] = {}
    p2y_by_eid: dict[str, float] = {}

    ordered = sorted(
        specs,
        key=lambda s: (
            s.tgt_layer,
            -s.ey,
            _FB_FAMILY_PRIO.get(s.profile, 9),
            s.rail_name,
            s.src_id,
        ),
    )
    for spec in ordered:
        key = (spec.src_id, spec.tgt_layer)
        if key in source_layer_row:
            p2y_by_eid[spec.eid] = source_layer_row[key]
            continue

        nominal = spec.ey - spec.up_delta
        use_dynamic = spec.profile in ("q", "nq") or (
            spec.profile == "gate"
            and (
                (spec.tgt_layer == "and" and spec.src_id in and_rev)
                or (spec.tgt_layer == "or" and spec.src_id in or_rev)
            )
        )
        if use_dynamic:
            p2y = _first_clear_up_y(
                nominal,
                spec.p1x,
                spec.p3x,
                obstacle_boxes,
                avoid=used_fb_rows,
                extra_avoid_y=rail_rows.get(spec.rail_name, []),
            )
        else:
            p2y = nominal

        source_layer_row[key] = p2y
        p2y_by_eid[spec.eid] = p2y
        used_fb_rows.append((p2y, min(spec.p1x, spec.p3x), max(spec.p1x, spec.p3x)))
        rail_rows.setdefault(spec.rail_name, []).append(p2y)

    return p2y_by_eid


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


def _collect_cell_inner_boxes(
    root: ET.Element,
) -> list[tuple[float, float, float, float]]:
    """Power Cell inner 80×80 的 (x0, x1, y0, y1) 佔位框（含上下緣）。"""
    boxes: list[tuple[float, float, float, float]] = []
    for cell in root.iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        if cell.get("style") != _PSEQCELL_STYLE_INNER:
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


def _merge_obstacle_boxes(
    *box_lists: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    merged: list[tuple[float, float, float, float]] = []
    for boxes in box_lists:
        merged.extend(boxes)
    return merged


def _first_clear_up_y(
    start_y: float,
    xa: float,
    xb: float,
    gate_boxes: list[tuple[float, float, float, float]],
    *,
    avoid: list[tuple[float, float, float]] | None = None,
    extra_avoid_y: list[float] | None = None,
    max_steps: int = 60,
) -> float:
    """自 start_y 起一律向上（y 遞減）逐格(GRID)搜尋，回傳第一條同時滿足：
    (1) 與 [xa, xb] 內任何閘體／閘邊不重疊；
    (2) 不與其他 source 已佔用且 x 區間重疊的回授橫列同列；
    (3) 不與 extra_avoid_y 同列（同 rail 協調）；
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
    if extra_avoid_y:
        avoid_rows.extend(extra_avoid_y)
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
    cell_boxes = _collect_cell_inner_boxes(root)
    obstacle_boxes = _merge_obstacle_boxes(gate_boxes, cell_boxes)

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
        occupied_vx.add(int(_align40(gate_exit_lanes.stub_x(_sid, _sr))))
    assigned_cell_vx: set[int] = set()
    source_cell_x: dict[int, float] = {}

    q_rev = {v: k for k, v in q_box_id_map.items()}
    nq_rev = {v: k for k, v in nq_box_id_map.items()}
    q_ids_with_feedback: set[int] = set()
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
        if _sid in q_rev:
            q_ids_with_feedback.add(_sid)

    # 同 Cell 欄（相同 exit X）的 Q／~Q 回授：② 垂直段錯開 stub
    cell_col_stub_rank: dict[int, int] = {}
    cell_col_pending: dict[int, list[tuple[float, int]]] = {}
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid is None or eid not in feedback_auto_edge_ids:
            continue
        try:
            src_id = int(cell.get("source") or "")
        except ValueError:
            continue
        profile = _feedback_profile(
            src_id, q_box_id_map=q_box_id_map, nq_box_id_map=nq_box_id_map
        )
        if profile not in ("q", "nq"):
            continue
        s_box = _vertex_geom(root, cell.get("source") or "")
        if s_box is None:
            continue
        sty = cell.get("style") or ""
        ex, ey = _anchor_xy(
            s_box, _style_float(sty, "exitX", 1.0), _style_float(sty, "exitY", 0.5)
        )
        col_key = int(_align40(ex))
        cell_col_pending.setdefault(col_key, []).append((ey, src_id))
    for _items in cell_col_pending.values():
        for rank, (_, sid) in enumerate(sorted(_items, key=lambda t: (-t[0], t[1]))):
            cell_col_stub_rank[sid] = rank
    cell_col_used_p1x: set[int] = set()

    fb_specs: list[_FbRouteSpec] = []
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
            tgt_id = int(tgt_s)
        except ValueError:
            continue
        sty = cell.get("style") or ""
        exit_ax = _style_float(sty, "exitX", 1.0)
        exit_ay = _style_float(sty, "exitY", 0.5)
        entry_ax = _style_float(sty, "entryX", 0.0)
        entry_ay = _style_float(sty, "entryY", 0.5)
        ex, ey = _anchor_xy(s_box, exit_ax, exit_ay)
        ty = _anchor_xy(t_box, entry_ax, entry_ay)[1]

        profile = _feedback_profile(
            src_id, q_box_id_map=q_box_id_map, nq_box_id_map=nq_box_id_map
        )
        if profile == "nq":
            _rail = nq_rev.get(src_id)
            _q_id = q_box_id_map.get(_rail) if _rail else None
            if _q_id is not None and _q_id in q_ids_with_feedback:
                right_delta = FB_NQ_RIGHT
                up_delta = FB_NQ_UP
            else:
                right_delta = FB_Q_RIGHT
                up_delta = FB_NQ_UP_NO_Q
        elif profile == "q":
            right_delta = FB_Q_RIGHT
            up_delta = FB_Q_UP
        else:
            right_delta = 0
            up_delta = FB_Q_UP

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
            stub_right = gate_right_x.get(src_id, and_col_x + AND_GATE_W)
            p1x = float(gate_exit_lanes.stub_x(src_id, stub_right))
        else:
            stub_rank = cell_col_stub_rank.get(src_id, 0)
            candidate = int(_align40(ex + right_delta + stub_rank * GRID))
            while candidate in cell_col_used_p1x:
                candidate += GRID
            cell_col_used_p1x.add(candidate)
            p1x = float(candidate)

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
        if tgt_layer == "and":
            p3x = min(p3x, float(and_col_x - GAP))
        elif tgt_layer == "or":
            p3x = min(p3x, float(or_col_x_fn(tgt_rail) - GAP))
        if tgt_layer == "cell":
            if src_id in source_cell_x:
                p3x = source_cell_x[src_id]
            else:
                _floor_x = and_col_x + AND_GATE_W + GAP
                _cx = int(_align40(p3x))
                while (_cx in occupied_vx or _cx in assigned_cell_vx) and _cx - GRID >= _floor_x:
                    _cx -= GRID
                p3x = float(_cx)
                assigned_cell_vx.add(_cx)
                source_cell_x[src_id] = p3x

        fb_specs.append(
            _FbRouteSpec(
                edge_cell=cell,
                eid=eid,
                src_id=src_id,
                profile=profile,
                rail_name=_feedback_source_rail(
                    src_id,
                    q_rev=q_rev,
                    nq_rev=nq_rev,
                    and_rev=and_rev,
                    or_rev=or_rev,
                ),
                ey=ey,
                ty=ty,
                p1x=p1x,
                tgt_layer=tgt_layer,
                tgt_rail=tgt_rail,
                entry_x=entry_x,
                up_delta=up_delta,
                p3x=p3x,
                sty=sty,
            )
        )

    p2y_plan = _plan_global_feedback_y_rows(
        fb_specs,
        obstacle_boxes=obstacle_boxes,
        and_rev=and_rev,
        or_rev=or_rev,
    )

    for spec in fb_specs:
        p1x = spec.p1x
        p1y = spec.ey
        p2y = p2y_plan[spec.eid]
        p2x = p1x
        p3x = spec.p3x
        p3y = p2y
        p4x = p3x
        p4y = spec.ty
        entry_x = spec.entry_x
        ty = spec.ty

        geo = spec.edge_cell.find("mxGeometry")
        if geo is None:
            geo = ET.SubElement(
                spec.edge_cell, "mxGeometry", {"relative": "1", "as": "geometry"}
            )
        _clear_edge_waypoints(geo)
        fb_pts = [(p1x, p1y), (p2x, p2y), (p3x, p3y), (p4x, p4y), (entry_x, ty)]
        fb_align = [(True, False), (True, True), (True, True), (True, False), (True, False)]
        arr = ET.SubElement(geo, "Array", {"as": "points"})
        for (px, py), (do_ax, do_ay) in zip(fb_pts, fb_align):
            x = _align40(px) if do_ax else round(float(px))
            y = _align40(py) if do_ay else round(float(py))
            ET.SubElement(arr, "mxPoint", {"x": str(x), "y": str(y)})
        spec.edge_cell.set("style", _style_to_frozen_none(spec.sty))


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
    """單一 output 列高：AND/OR 輸出與 H_Deb/L_Deb 同水平時落在 Cell 框內，不另加 Y。"""
    hi_groups = r.get_hi_groups()
    lo_groups = r.get_lo_groups()
    max_bottom = CELL_GROUP_H

    for hl, groups in [("hi", hi_groups), ("lo", lo_groups)]:
        base = OR_GATE_OFFSET_HI_Y if hl == "hi" else OR_GATE_OFFSET_LO_Y
        idx = 0
        for g in groups:
            if len(g) >= 2:
                top = base + idx * AND_GATE_DY
                max_bottom = max(max_bottom, top + AND_GATE_H)
                idx += 1
        if len(groups) >= 2:
            max_bottom = max(max_bottom, base + OR_GATE_H)

    return _align40(max_bottom)



def generate_drawio(
    config: PowerSeqConfig,
    *,
    options: DrawioExportOptions | None = None,
) -> str:
    """Generate cell-centric Draw.io XML (single-page grid)."""
    from drawio_cell_export import generate_drawio as _generate

    return _generate(config, options=options)
