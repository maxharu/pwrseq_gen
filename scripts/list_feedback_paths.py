"""List all cross-row feedback paths in output/power.xml (via generate_drawio)."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawio_export as de
from config_models import PowerSeqConfig
from drawio_export import (
    CONST_DEPS,
    _build_layout_feedback_dep_keys,
    generate_drawio,
)

FEEDBACK_IDS: set[str] = set()
_orig_mark = de._mark_layout_feedback_edge


def _capture_mark(
    edge_ids,
    edge_id,
    *,
    layout_feedback_dep_keys,
    tgt_rail,
    hl,
    gi,
    ii,
    dep_name,
):
    if _orig_mark(
        edge_ids,
        edge_id,
        layout_feedback_dep_keys=layout_feedback_dep_keys,
        tgt_rail=tgt_rail,
        hl=hl,
        gi=gi,
        ii=ii,
        dep_name=dep_name,
    ):
        FEEDBACK_IDS.add(edge_id)
        return True
    return False


def _load_cfg() -> PowerSeqConfig:
    with open(ROOT / "output" / "power.json", encoding="utf-8") as f:
        return PowerSeqConfig.from_dict(json.load(f))


def _logical_feedback_deps(cfg: PowerSeqConfig) -> list[dict]:
    """From power.json: output deps with src_row > tgt_row."""
    outputs = [r for r in cfg.rails if r.seq_type != "input"]
    output_to_row = {r.name: i for i, r in enumerate(outputs)}
    name_to_rail = {r.name: r for r in cfg.rails}
    valid = {r.name for r in cfg.rails}
    rows: list[dict] = []

    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) == 1:
                    d = group[0]
                    if d not in valid or d in CONST_DEPS:
                        continue
                    if name_to_rail[d].seq_type == "input":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None or src_row <= tgt_row:
                        continue
                    inv = tgt.get_hi_inv(gi, 0, d) if hl == "hi" else tgt.get_lo_inv(gi, 0, d)
                    use = tgt.get_hi_use(gi, 0, d) if hl == "hi" else tgt.get_lo_use(gi, 0, d)
                    rows.append({
                        "src_rail": d,
                        "tgt_rail": tgt.name,
                        "hl": hl,
                        "group": gi,
                        "inv": inv,
                        "use": use,
                        "target": "Deb" if len(group) == 1 else "AND",
                        "src_row": src_row,
                        "tgt_row": tgt_row,
                    })
                elif len(group) >= 2:
                    for ii, d in enumerate(group):
                        if d not in valid or d in CONST_DEPS:
                            continue
                        if name_to_rail[d].seq_type == "input":
                            continue
                        src_row = output_to_row.get(d)
                        if src_row is None or src_row <= tgt_row:
                            continue
                        inv = tgt.get_hi_inv(gi, ii, d) if hl == "hi" else tgt.get_lo_inv(gi, ii, d)
                        use = tgt.get_hi_use(gi, ii, d) if hl == "hi" else tgt.get_lo_use(gi, ii, d)
                        rows.append({
                            "src_rail": d,
                            "tgt_rail": tgt.name,
                            "hl": hl,
                            "group": gi,
                            "inv": inv,
                            "use": use,
                            "target": f"AND(gi={gi})",
                            "src_row": src_row,
                            "tgt_row": tgt_row,
                        })
    return rows


def _build_id_maps(root: ET.Element, outputs: list, output_to_row: dict[str, int]):
    id_to_rail: dict[str, str] = {}
    id_kind: dict[str, str] = {}

    # output inner cell: same row band as rail label (x=2200)
    label_y: dict[str, int] = {}
    for cell in root.findall('.//mxCell[@vertex="1"]'):
        val = (cell.get("value") or "").strip()
        if val not in output_to_row:
            continue
        geo = cell.find("mxGeometry")
        if geo is None:
            continue
        label_y[val] = int(float(geo.get("y", 0)))

    for cell in root.findall('.//mxCell[@vertex="1"]'):
        cid = cell.get("id")
        if cid is None:
            continue
        sty = cell.get("style") or ""
        val = (cell.get("value") or "").strip()
        if val in output_to_row:
            id_to_rail[cid] = val
            id_kind[cid] = "rail_label"
            continue
        if "logic_gate" in sty:
            geo = cell.find("mxGeometry")
            y = int(float(geo.get("y", 0))) if geo is not None else 0
            rail = min(outputs, key=lambda r: abs(y - label_y.get(r.name, y)))
            id_to_rail[cid] = rail.name
            op = "AND"
            if "operation=nor" in sty:
                op = "NOR"
            elif "operation=or" in sty:
                op = "OR"
            elif "operation=nand" in sty:
                op = "NAND"
            id_kind[cid] = f"{op}#{cid}"
            continue
        if "rounded=0" in sty:
            geo = cell.find("mxGeometry")
            if geo is None:
                continue
            x = int(float(geo.get("x", 0)))
            if x < 1900:
                continue
            y = int(float(geo.get("y", 0)))
            rail = min(outputs, key=lambda r: abs(y - label_y.get(r.name, y)))
            id_to_rail[cid] = rail.name
            id_kind[cid] = "output_inner"
        elif val in ("H_Deb", "L_Deb"):
            geo = cell.find("mxGeometry")
            y = int(float(geo.get("y", 0))) if geo is not None else 0
            rail = min(outputs, key=lambda r: abs(y - label_y.get(r.name, y)))
            id_to_rail[cid] = rail.name
            id_kind[cid] = val

    return id_to_rail, id_kind


def _describe(cid: str | None, id_to_rail: dict[str, str], id_kind: dict[str, str]) -> str:
    if cid is None:
        return "?"
    if cid in id_kind:
        k = id_kind[cid]
        rail = id_to_rail.get(cid, "?")
        if k == "output_inner":
            return f"{rail} (output cell)"
        if k in ("H_Deb", "L_Deb"):
            return f"{rail}/{k}"
        return f"{rail}/{k}"
    cell = root.find(f".//mxCell[@id='{cid}']")
    if cell is not None:
        v = (cell.get("value") or "").strip()
        if v:
            return v
    return f"id={cid}"


def main() -> None:
    cfg = _load_cfg()
    outputs = [r for r in cfg.rails if r.seq_type != "input"]
    output_to_row = {r.name: i for i, r in enumerate(outputs)}
    name_to_rail = {r.name: r for r in cfg.rails}
    valid = {r.name for r in cfg.rails}

    de._mark_layout_feedback_edge = _capture_mark
    try:
        xml = generate_drawio(cfg)
    finally:
        de._mark_layout_feedback_edge = _orig_mark

    global root
    root = ET.fromstring(xml)
    id_to_rail, id_kind = _build_id_maps(root, outputs, output_to_row)

    logical = _logical_feedback_deps(cfg)
    layout_keys = _build_layout_feedback_dep_keys(
        outputs, output_to_row, name_to_rail, valid
    )
    print(f"=== 佈局回授 dep keys 共 {len(layout_keys)} 條 ===\n")
    print(f"=== 邏輯回授依賴（src_row != tgt_row 向上子集）共 {len(logical)} 條 ===\n")
    for i, row in enumerate(logical, 1):
        inv_s = " inv" if row["inv"] else ""
        print(
            f"{i:2}. {row['src_rail']} (row {row['src_row']}) "
            f"→ {row['tgt_rail']}/{row['hl']}{inv_s} "
            f"[{row['target']}, use={row['use']}, gi={row['group']}] "
            f"(row {row['tgt_row']})"
        )

    print(f"\n=== Draw.io 回授邊（feedback_auto_edge_ids）共 {len(FEEDBACK_IDS)} 條 ===\n")
    for eid in sorted(FEEDBACK_IDS, key=int):
        cell = root.find(f".//mxCell[@id='{eid}']")
        if cell is None:
            continue
        src = _describe(cell.get("source"), id_to_rail, id_kind)
        tgt = _describe(cell.get("target"), id_to_rail, id_kind)
        sty = cell.get("style") or ""
        geo = cell.find("mxGeometry")
        has_pts = geo is not None and geo.find("Array") is not None
        print(
            f"edge {eid}: {src} → {tgt} | "
            f"{'orthogonal' if 'orthogonalEdgeStyle' in sty else sty.split(';')[0]} | "
            f"waypoints={'有' if has_pts else '無'}"
        )


if __name__ == "__main__":
    main()
