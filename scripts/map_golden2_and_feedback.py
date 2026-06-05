#!/usr/bin/env python3
"""Map golden2 AND gates (top-to-bottom) to GATE->GATE feedback edges."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = ET.parse(Path("src/reference/golden2.xml")).getroot()
root_el = root.find(".//root")

verts: dict[str, dict] = {}
for c in root_el:
    if c.get("vertex") != "1":
        continue
    geo = c.find("mxGeometry")
    if geo is None:
        continue
    sty = c.get("style") or ""
    op = re.search(r"operation=([^;]+)", sty)
    verts[c.get("id")] = {
        "val": c.get("value") or "",
        "x": float(geo.get("x", 0)),
        "y": float(geo.get("y", 0)),
        "op": op.group(1) if op else "",
        "is_and": "logic_gate" in sty and (op and op.group(1) == "and"),
    }

ands = [
    (v["y"], v["x"], vid, v["val"])
    for vid, v in verts.items()
    if v["is_and"]
]
ands.sort(key=lambda t: (t[0], t[1]))
print("golden2 AND 由上而下 (y,x):")
for i, (y, x, vid, val) in enumerate(ands, 1):
    print(f"  #{i:2d} id={vid} y={y:.0f} x={x:.0f}")

print("\nGATE -> GATE (4-waypoint) 回授邊:")
for c in root_el:
    if c.get("edge") != "1":
        continue
    src, tgt = c.get("source"), c.get("target")
    sv, tv = verts.get(src), verts.get(tgt)
    if not sv or not tv or not sv["is_and"]:
        continue
    if "logic_gate" not in (verts.get(tgt) or {}).get("op", "") and not verts.get(tgt, {}).get("is_and"):
        if not (verts.get(tgt) or {}).get("is_and"):
            pass
    tgt_is_gate = "logic_gate" in (verts.get(tgt) or {}).get("op", "") or verts.get(tgt, {}).get("is_and")
    if not tgt_is_gate:
        continue
    geo = c.find("mxGeometry")
    arr = geo.find("Array[@as='points']") if geo is not None else None
    n = len(list(arr)) if arr is not None else 0
    if n < 4:
        continue
    src_idx = next((i for i, (_, _, vid, _) in enumerate(ands, 1) if vid == src), None)
    tgt_idx = next((i for i, (_, _, vid, _) in enumerate(ands, 1) if vid == tgt), None)
    print(f"  AND #{src_idx} -> AND/OR #{tgt_idx}  (src_y={sv['y']:.0f} -> tgt_y={tv['y']:.0f})")

# RSMRST_N: cell_box with O->name
print("\n含 RSMRST 的 cell_box / 大 AND 回授 (cell->GATE 4pt):")
for c in root_el:
    if c.get("edge") != "1":
        continue
    src, tgt = c.get("source"), c.get("target")
    sv, tv = verts.get(src), verts.get(tgt)
    if not sv or not tv:
        continue
    geo = c.find("mxGeometry")
    arr = geo.find("Array[@as='points']") if geo is not None else None
    if arr is None or len(list(arr)) < 4:
        continue
    # cell inner 80x80 at ~3440
    if sv.get("w") == 80 or (sv["val"] == "" and sv["x"] > 3000):
        tgt_idx = next((i for i, (_, _, vid, _) in enumerate(ands, 1) if vid == tgt), None)
        if tgt_idx:
            oname = ""
            for oid, ov in verts.items():
                if ov.get("val") and "align=left" in (verts.get(oid) or {}).get("op", ""):
                    pass
            print(f"  cell id={src} y={sv['y']:.0f} -> AND #{tgt_idx}")
