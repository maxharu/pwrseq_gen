import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import generate_drawio
from layout_engine import _edge_uses_orthogonal_style

with open("output/power.json", encoding="utf-8") as f:
    cfg = PowerSeqConfig.from_dict(json.load(f))
root = ET.fromstring(generate_drawio(cfg))
ortho_wp = ortho_no_wp = none_wp = 0
for c in root.iter("mxCell"):
    if c.get("edge") != "1":
        continue
    sty = c.get("style") or ""
    geo = c.find("mxGeometry")
    has_wp = geo is not None and geo.find("Array") is not None
    if _edge_uses_orthogonal_style(sty):
        ortho_wp += has_wp
        ortho_no_wp += not has_wp
    elif "edgeStyle=none" in sty and has_wp:
        none_wp += 1
print(f"orthogonalEdgeStyle with waypoints: {ortho_wp}")
print(f"orthogonalEdgeStyle without waypoints: {ortho_no_wp}")
print(f"edgeStyle=none with waypoints: {none_wp}")
