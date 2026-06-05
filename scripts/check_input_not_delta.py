"""Report label_x - NOT_x for each input label -> input NOT edge."""
import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import (
    generate_drawio,
    INPUT_NOT_LEFT,
    INPUT_LABEL_W,
    NOT_GATE_W,
    _input_label_bottom_y,
    _input_not_bottom_y,
)

with open("src/reference/golden.json", encoding="utf-8") as f:
    cfg = PowerSeqConfig.from_dict(json.load(f))

root = ET.fromstring(generate_drawio(cfg))
cells = {c.get("id"): c for c in root.iter("mxCell") if c.get("id")}

deltas = []
for e in root.iter("mxCell"):
    if e.get("edge") != "1":
        continue
    src, tgt = e.get("source"), e.get("target")
    sc, tc = cells.get(src), cells.get(tgt)
    if sc is None or tc is None:
        continue
    ss, ts = sc.get("style") or "", tc.get("style") or ""
    if not (
        "rotation=90" in ss
        and "align=right" in ss
        and "inverter_2" in ts
        and "rotation=90" in ts
    ):
        continue
    lg, ng = sc.find("mxGeometry"), tc.find("mxGeometry")
    lx, nx = float(lg.get("x")), float(ng.get("x"))
    ly, ny = float(lg.get("y")), float(ng.get("y"))
    lb, nb = _input_label_bottom_y(int(ly)), _input_not_bottom_y(int(ny))
    deltas.append((sc.get("value"), lx - nx, lb - nb, lx, nx, ly, ny, lb, nb))

print(f"INPUT_NOT_LEFT = {INPUT_NOT_LEFT}")
print(f"edges label->NOT: {len(deltas)}")
for row in sorted(deltas, key=lambda r: -r[3]):
    name, dx, d_bottom, lx, nx, ly, ny, lb, nb = row
    print(
        f"  {name}: dx={dx:.0f} bottom_delta={d_bottom:.0f}  "
        f"label=({lx:.0f},{ly:.0f}) lb={lb:.0f} NOT=({nx:.0f},{ny:.0f}) nb={nb:.0f}"
    )
print("unique dx:", sorted({round(r[1]) for r in deltas}))
print("unique bottom_delta (label_bottom - NOT_bottom, expect -80):", sorted({round(r[2]) for r in deltas}))
bad_lb = [r for r in deltas if r[7] % 40 != 0]
bad_nb = [r for r in deltas if r[8] % 40 != 0]
if bad_lb or bad_nb:
    print("FAIL: bottom not on 40pt grid", bad_lb, bad_nb)
else:
    print("OK: all label/NOT bottoms on 40pt grid")
