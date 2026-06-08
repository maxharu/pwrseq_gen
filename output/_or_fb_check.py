import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import STROKE_FEEDBACK, generate_drawio

cfg = PowerSeqConfig.from_dict(
    json.load(open("src/reference/drawio_fb_matrix.json", encoding="utf-8"))
)
outputs = [r for r in cfg.rails if r.seq_type != "input"]
output_to_row = {r.name: i for i, r in enumerate(outputs)}
root = ET.fromstring(generate_drawio(cfg))
cells = {c.get("id"): c for c in root.iter("mxCell")}

logic_ids = {
    c.get("id")
    for c in root.iter("mxCell")
    if c.get("vertex") == "1" and "operation=or" in (c.get("style") or "")
}


def nearest_rail(y: float) -> tuple[str, int | None]:
    best = None
    for c in root.iter("mxCell"):
        v = (c.get("value") or "").strip()
        if not (v.startswith("RAIL_") or v == "FB_HUB"):
            continue
        gy = float(c.find("mxGeometry").get("y", 0))
        if best is None or abs(gy - y) < abs(best[0] - y):
            best = (gy, v)
    if best is None:
        return "?", None
    return best[1], output_to_row.get(best[1])


print("OR/NOR -> OR/NOR edges:")
for c in root.iter("mxCell"):
    if c.get("edge") != "1":
        continue
    s, t = c.get("source"), c.get("target")
    if s not in logic_ids or t not in logic_ids:
        continue
    sy = float(cells[s].find("mxGeometry").get("y", 0))
    ty = float(cells[t].find("mxGeometry").get("y", 0))
    sr, sri = nearest_rail(sy)
    tr, tri = nearest_rail(ty)
    fb = STROKE_FEEDBACK in (c.get("style") or "")
    neg_s = "negating=1" in (cells[s].get("style") or "")
    neg_t = "negating=1" in (cells[t].get("style") or "")
    row_fb = sri is not None and tri is not None and sri > tri
    print(
        f"  e{c.get('id')} {'NOR' if neg_s else 'OR'}@{sr}({sri}) y{sy:.0f}"
        f" -> {'NOR' if neg_t else 'OR'}@{tr}({tri}) y{ty:.0f}"
        f" row_fb={row_fb} geom_up={sy>ty} blue={fb}"
    )
