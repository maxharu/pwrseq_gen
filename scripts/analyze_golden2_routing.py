"""Analyze routing patterns in src/reference/golden2.xml."""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

root = ET.parse("src/reference/golden2.xml").getroot()
root_el = root.find(".//root")

verts: dict[str, dict] = {}
edges: list[dict] = []

for c in root_el:
    if c.get("vertex") == "1":
        geo = c.find("mxGeometry")
        if geo is not None:
            verts[c.get("id")] = {
                "x": float(geo.get("x", 0)),
                "y": float(geo.get("y", 0)),
                "w": float(geo.get("width", 0)),
                "h": float(geo.get("height", 0)),
                "val": (c.get("value") or "")[:50],
                "style": c.get("style") or "",
            }
    if c.get("edge") == "1":
        sty = c.get("style") or ""
        geo = c.find("mxGeometry")
        pts: list[tuple[float, float]] = []
        if geo is not None:
            arr = geo.find("Array[@as='points']")
            if arr is not None:
                for p in arr:
                    pts.append((float(p.get("x", 0)), float(p.get("y", 0))))

        def gf(k: str, d: str = "?") -> str:
            m = re.search(rf"{k}=([^;]+)", sty)
            return m.group(1) if m else d

        edges.append({
            "id": c.get("id"),
            "source": c.get("source"),
            "target": c.get("target"),
            "edgeStyle": gf("edgeStyle"),
            "exitX": gf("exitX"), "exitY": gf("exitY"),
            "entryX": gf("entryX"), "entryY": gf("entryY"),
            "stroke": gf("strokeColor", "#000000"),
            "n_pts": len(pts),
            "pts": pts,
        })


def vname(vid: str | None) -> str:
    if vid is None:
        return "?"
    v = verts.get(vid, {})
    val = v.get("val", "")
    if val:
        return val
    if "inverter_2" in v.get("style", ""):
        return "NOT"
    if "logic_gate" in v.get("style", ""):
        return "GATE"
    return vid


def vtype(vid: str | None) -> str:
    if vid is None:
        return "?"
    v = verts.get(vid, {})
    sty = v.get("style", "")
    val = v.get("val", "")
    if "rotation=90" in sty and val:
        return "input_label"
    if "inverter_2" in sty:
        return "NOT"
    if "logic_gate" in sty:
        return "logic_gate"
    if val == "O":
        return "O"
    if val in ("H_Deb", "L_Deb"):
        return val
    if val and "align=left" in sty:
        return "output_name"
    if not val and v.get("w") == 80:
        return "cell_box"
    return "other"


not_ids = {vid for vid, v in verts.items() if "inverter_2" in v.get("style", "")}
gate_ids = {vid for vid, v in verts.items() if "logic_gate" in v.get("style", "")}

print("=== SUMMARY ===")
print(f"vertices: {len(verts)}, edges: {len(edges)}")
print(f"NOT gates: {len(not_ids)}, logic gates: {len(gate_ids)}")
print("\nedgeStyle:", dict(Counter(e["edgeStyle"] for e in edges)))
print("waypoint count:", dict(Counter(e["n_pts"] for e in edges)))

# Classify edges by connection type
def classify(e: dict) -> str:
    st, tt = vtype(e["source"]), vtype(e["target"])
    return f"{st} -> {tt}"

print("\nconnection types:", dict(Counter(classify(e) for e in edges)))

# Edges with waypoints - analyze geometry
print("\n=== EDGES WITH WAYPOINTS ===")
for e in sorted([x for x in edges if x["n_pts"] > 0], key=lambda x: (classify(x), x["id"])):
    print(
        f"  id={e['id']} {vname(e['source'])} -> {vname(e['target'])} "
        f"style={e['edgeStyle']} n={e['n_pts']} "
        f"exit=({e['exitX']},{e['exitY']}) entry=({e['entryX']},{e['entryY']}) "
        f"pts={e['pts']}"
    )

print("\n=== ZERO-WAYPOINT EDGES BY TYPE ===")
for cat in sorted(set(classify(e) for e in edges if e["n_pts"] == 0)):
    n = sum(1 for e in edges if e["n_pts"] == 0 and classify(e) == cat)
    sample = next(e for e in edges if e["n_pts"] == 0 and classify(e) == cat)
    print(f"  {cat}: {n}  (e.g. {vname(sample['source'])}->{vname(sample['target'])})")

# NOT edges detail
print("\n=== NOT EDGES ===")
for e in edges:
    if e["source"] in not_ids or e["target"] in not_ids:
        print(
            f"  {vname(e['source'])} -> {vname(e['target'])} "
            f"n_pts={e['n_pts']} style={e['edgeStyle']} pts={e['pts']}"
        )

# Check horizontal stub on input->gate edges with waypoints
print("\n=== INPUT ROUTING (input_label -> logic_gate / NOT) ===")
for e in edges:
    if vtype(e["source"]) == "input_label":
        print(
            f"  {vname(e['source'])} -> {vname(e['target'])} "
            f"n_pts={e['n_pts']} exit=({e['exitX']},{e['exitY']}) pts={e['pts']}"
        )

# edgeStyle=none?
none_style = [e for e in edges if e["edgeStyle"] == "none"]
print(f"\nedgeStyle=none count: {len(none_style)}")

# Unique x columns for vertical busses
print("\n=== VERTICAL CHANNEL X (from waypoints, rounded) ===")
vx: Counter[float] = Counter()
for e in edges:
    for x, y in e["pts"]:
        vx[round(x / 40) * 40] += 1
for x, c in vx.most_common(15):
    print(f"  x={x}: {c} waypoint refs")
