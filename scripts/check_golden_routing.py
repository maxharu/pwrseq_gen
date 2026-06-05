"""Check export matches golden2 routing policy (orthogonal only, no A*)."""
import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import generate_drawio

with open("src/reference/golden.json", encoding="utf-8") as f:
    cfg = PowerSeqConfig.from_dict(json.load(f))
root = ET.fromstring(generate_drawio(cfg))
none_style = ortho = ortho_wp = rot_in = rot_not = 0
for c in root.iter("mxCell"):
    if c.get("edge") == "1":
        sty = c.get("style") or ""
        if "edgeStyle=none" in sty:
            none_style += 1
        if "orthogonalEdgeStyle" in sty:
            ortho += 1
            geo = c.find("mxGeometry")
            if geo is not None and geo.find("Array[@as='points']") is not None:
                ortho_wp += 1
    if c.get("vertex") == "1":
        sty = c.get("style") or ""
        if "rotation=90" in sty and "align=right" in sty:
            rot_in += 1
        if "inverter_2" in sty and "rotation=90" in sty:
            rot_not += 1
print(f"edgeStyle=none: {none_style}")
print(f"orthogonalEdgeStyle: {ortho} (with waypoints: {ortho_wp})")
print(f"input labels rotation=90: {rot_in}")
print(f"input NOT rotation=90: {rot_not}")
