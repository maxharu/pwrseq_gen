import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")
from config_models import PowerSeqConfig
from drawio_export import generate_drawio

cfg = PowerSeqConfig.from_dict(json.load(open("doc/demo_json.json", encoding="utf-8")))
xml = generate_drawio(cfg)
root = ET.fromstring(xml)
groups = [c for c in root.iter("mxCell") if c.get("connectable") == "0"]
print("groups", len(groups))
print("outputs", sum(1 for c in root.iter("mxCell") if (c.get("value") or "").strip() and "PRIM" in (c.get("value") or "")))
edges = [c for c in root.iter("mxCell") if c.get("edge") == "1"]
print("edges", len(edges))
gates = [c for c in root.iter("mxCell") if "logic_gate" in (c.get("style") or "")]
print("gates", len(gates))
