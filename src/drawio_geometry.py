"""Shared Draw.io geometry: grid, PSEQCELL layout, gate styles."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from config_models import PowerRail
from group_logic import normalize_intra_op

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"
CONST_DEPS = {DEP_HIGH, DEP_LOW}

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
CELL_O_W = 20
CELL_O_H = 20
CELL_O_X = 60
CELL_O_Y = 30

GRID = 40
GAP = 40

STROKE_HI = "#ff0000"
STROKE_LO = "#008000"
STROKE_DEFAULT = "#000000"

INPUT_LABEL_H = 20

AND_GATE_W = 80
AND_GATE_H = 40
OR_GATE_W = 80
OR_GATE_H = 40

_PSEQCELL_STYLE_INNER = "rounded=0;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_H_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_L_DEB = "rounded=1;whiteSpace=wrap;html=1;"
_PSEQCELL_STYLE_O = "rounded=1;whiteSpace=wrap;html=1;"


def _reference_dir() -> Path:
    """PyInstaller onefile 時資源在 sys._MEIPASS/reference。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "reference"
    return Path(__file__).resolve().parent / "reference"


_REFERENCE_DIR = _reference_dir()


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
    """自 reference/PSEQCELL.xml 載入 Cell 幾何與 style。"""
    global CELL_GROUP_W, CELL_GROUP_H, CELL_INNER_X, CELL_INNER_W, CELL_INNER_H
    global CELL_H_DEB_W, CELL_H_DEB_H, CELL_L_DEB_W, CELL_L_DEB_H
    global CELL_H_DEB_Y, CELL_L_DEB_Y
    global CELL_O_W, CELL_O_H, CELL_O_X, CELL_O_Y
    global _PSEQCELL_STYLE_INNER, _PSEQCELL_STYLE_H_DEB, _PSEQCELL_STYLE_L_DEB
    global _PSEQCELL_STYLE_O

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
        elif not val and "rounded=0" in style:
            parts["inner"] = (x, y, w, h)
            styles["inner"] = style

    required = ("inner", "h_deb", "l_deb", "o")
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
    ox, oy, ow, oh = parts["o"]
    CELL_O_X, CELL_O_Y, CELL_O_W, CELL_O_H = ox, oy, ow, oh
    _PSEQCELL_STYLE_O = styles["o"]
    CELL_GROUP_W = group_w or iw
    CELL_GROUP_H = group_h or ih
    _PSEQCELL_STYLE_INNER = styles["inner"]
    _PSEQCELL_STYLE_H_DEB = _style_align_left(styles["h_deb"])
    _PSEQCELL_STYLE_L_DEB = _style_align_left(styles["l_deb"])


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


_GATE_STYLE_XOR = _load_logic_gate_style("XOR1.xml")
_GATE_STYLE_XNOR = _load_logic_gate_style("XNOR1.xml")

_INTRA_POS = {
    "and": _GATE_STYLE_AND,
    "or": _GATE_STYLE_OR,
    "xor": _GATE_STYLE_XOR,
}
_INTRA_NEG = {
    "and": _GATE_STYLE_NAND,
    "or": _GATE_STYLE_NOR,
    "xor": _GATE_STYLE_XNOR,
}


def _get_intra_op(r: PowerRail, hl: str, gi: int) -> str:
    if hl == "hi":
        return r.get_hi_intra_op(gi)
    return r.get_lo_intra_op(gi)


def _group_output_not(r: PowerRail, hl: str, gi: int) -> bool:
    """整組結果反相（group_inv）→ 繪製 negating 閘。"""
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


def _intra_child_gate_style(r: PowerRail, hl: str, gi: int) -> str:
    """2-level tree 左側 child 閘（不反相）。"""
    op = normalize_intra_op(_get_intra_op(r, hl, gi))
    return _INTRA_POS[op]


def _intra_merge_gate_style(r: PowerRail, hl: str, gi: int) -> str:
    """Group 內 merge 閘；group_inv 時用 negating 閘。"""
    op = normalize_intra_op(_get_intra_op(r, hl, gi))
    if _group_output_not(r, hl, gi):
        return _INTRA_NEG[op]
    return _INTRA_POS[op]


def _and_gate_style(r: PowerRail, hl: str, gi: int) -> str:
    """相容別名：intra merge 閘 style。"""
    return _intra_merge_gate_style(r, hl, gi)


def _or_gate_style(r: PowerRail, hl: str) -> str:
    """OR 或 NOR；2-level tree 時僅 merge 層用此 style，child 恆為 OR。"""
    if _or_output_not(r, hl):
        return _GATE_STYLE_NOR
    return _GATE_STYLE_OR


def _escape_xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_load_pseqcell_layout()
