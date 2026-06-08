"""Automated verification of output/test_draw_io.xml against matrix spec."""
import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import (
    STROKE_FEEDBACK,
    _build_or_catalog,
    _count_and_or_middle_slots,
    _count_or_cell_middle_slots,
    generate_drawio,
)

MATRIX = "src/reference/drawio_fb_matrix.json"
OUT = "output/test_draw_io.xml"

cfg = PowerSeqConfig.from_dict(json.load(open(MATRIX, encoding="utf-8")))
outputs = [r for r in cfg.rails if r.seq_type != "input"]
name_to_rail = {r.name: r for r in cfg.rails}
valid = {r.name for r in cfg.rails}
output_to_row = {r.name: i for i, r in enumerate(outputs)}
_, or_idx = _build_or_catalog(outputs)

xml = generate_drawio(cfg)
open(OUT, "w", encoding="utf-8").write(xml)
root = ET.fromstring(xml)
cells = {c.get("id"): c for c in root.iter("mxCell")}

errors: list[str] = []

# --- gap widths ---
and_col = min(
    int(float(c.find("mxGeometry").get("x", 0)))
    for c in root.iter("mxCell")
    if c.get("vertex") == "1"
    and "operation=and" in (c.get("style") or "")
    and "negating=1" not in (c.get("style") or "")
)
or_col = min(
    int(float(c.find("mxGeometry").get("x", 0)))
    for c in root.iter("mxCell")
    if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
)
cell_col = min(
    int(float(c.find("mxGeometry").get("x", 0)))
    for c in root.iter("mxCell")
    if c.get("vertex") == "1" and c.get("value") == "H_Deb"
)
gap_ao = (or_col - and_col - 80) // 40
gap_oc = (cell_col - or_col - 80) // 40
mid_ao = _count_and_or_middle_slots(outputs, output_to_row, name_to_rail, valid)
mid_oc = _count_or_cell_middle_slots(outputs, output_to_row, name_to_rail, valid)

if gap_ao != 7:
    errors.append(f"AND-OR gap: expected 7 cells, got {gap_ao}")
if gap_oc != 8:
    errors.append(f"OR-Cell gap: expected 8 cells, got {gap_oc}")
if mid_ao != 5:
    errors.append(f"AND-OR middle slots: expected 5, got {mid_ao}")
if mid_oc != 6:
    errors.append(f"OR-Cell middle slots: expected 6, got {mid_oc}")

# --- gate id sets ---
and_ids = {
    c.get("id")
    for c in root.iter("mxCell")
    if c.get("vertex") == "1"
    and "operation=and" in (c.get("style") or "")
    and "negating=1" not in (c.get("style") or "")
}
or_ids = {
    c.get("id")
    for c in root.iter("mxCell")
    if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
}
q_ids = {
    c.get("id")
    for c in root.iter("mxCell")
    if c.get("vertex") == "1" and c.get("value") == "Q"
}

or_sorted = sorted(
    (
        float(cells[oid].find("mxGeometry").get("y", 0)),
        oid,
    )
    for oid in or_ids
)
# global OR catalog #1..#8 (hi/lo per row)
nor_hi = (or_sorted[4][1], or_sorted[4][0])  # #5 RAIL_NOR_TRY hi
nor_lo = (or_sorted[5][1], or_sorted[5][0])  # #6 RAIL_NOR_TRY lo
mix_hi = (or_sorted[2][1], or_sorted[2][0])  # #3 RAIL_MIX hi
mix_lo = (or_sorted[3][1], or_sorted[3][0])  # #4 RAIL_MIX lo

for label, pair in (
    ("NOR_TRY lo -> MIX hi (OR#6->OR#3)", (nor_lo, mix_hi)),
    ("NOR_TRY hi -> MIX lo (OR#5->OR#4)", (nor_hi, mix_lo)),
):
    if not pair[0] or not pair[1]:
        errors.append(f"missing OR vertex for {label}")
        continue
    src_id, tgt_id = pair[0][0], pair[1][0]
    edge = next(
        (
            c
            for c in root.iter("mxCell")
            if c.get("edge") == "1"
            and c.get("source") == src_id
            and c.get("target") == tgt_id
        ),
        None,
    )
    if edge is None:
        errors.append(f"missing edge {label}")
    elif STROKE_FEEDBACK not in (edge.get("style") or ""):
        errors.append(f"{label} edge {edge.get('id')} not blue FB")
    else:
        pts = edge.find("mxGeometry").find("Array")
        if pts is None or len(pts.findall("mxPoint")) < 5:
            errors.append(f"{label} edge {edge.get('id')} missing 5 FB waypoints")

# All AND -> OR: must NOT be FB (incl. FB_HUB AND -> RAIL_ORFB OR)
for c in root.iter("mxCell"):
    if c.get("edge") != "1":
        continue
    if c.get("source") not in and_ids or c.get("target") not in or_ids:
        continue
    if STROKE_FEEDBACK in (c.get("style") or ""):
        errors.append(f"AND->OR edge {c.get('id')} must not be blue FB")

# Q -> OR cross-row FB (FB_HUB)
q_fb_or = [
    c
    for c in root.iter("mxCell")
    if c.get("edge") == "1"
    and c.get("source") in q_ids
    and c.get("target") in or_ids
    and STROKE_FEEDBACK in (c.get("style") or "")
]
if not q_fb_or:
    errors.append("missing Cell Q cross-row FB to OR")

# OR->OR FB must use 5-segment routing with p3x left of OR column
for c in root.iter("mxCell"):
    if c.get("edge") != "1" or c.get("source") not in or_ids or c.get("target") not in or_ids:
        continue
    if STROKE_FEEDBACK not in (c.get("style") or ""):
        continue
    sty = c.get("style") or ""
    if "edgeStyle=none" not in sty:
        errors.append(f"OR->OR FB edge {c.get('id')} must use edgeStyle=none")
    pts = c.find("mxGeometry").find("Array")
    if pts is None or len(pts.findall("mxPoint")) < 5:
        errors.append(f"OR->OR FB edge {c.get('id')} missing 5 waypoints")
    else:
        p3x = float(pts.findall("mxPoint")[2].get("x"))
        if p3x >= or_col:
            errors.append(
                f"OR->OR FB edge {c.get('id')} p3x={p3x} must be left of OR col {or_col}"
            )

# --- report ---
print("=== test_draw_io.xml verification ===")
print(f"AND col={and_col} OR col={or_col} Cell col={cell_col}")
print(f"AND-OR gap={gap_ao} cells (middle={mid_ao}+2)")
print(f"OR-Cell gap={gap_oc} cells (middle={mid_oc}+2)")
print(f"Q->OR FB edges: {len(q_fb_or)}")
print(f"OR->OR FB edges: {sum(1 for c in root.iter('mxCell') if c.get('edge')=='1' and c.get('source') in or_ids and c.get('target') in or_ids and STROKE_FEEDBACK in (c.get('style') or ''))}")

if errors:
    print("\nFAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
