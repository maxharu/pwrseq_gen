"""Check input NOT bottom vs first cell top."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config_models import PowerSeqConfig
from drawio_export import (
    _align40,
    _input_not_visual_bottom_y,
    _input_not_y,
    generate_drawio,
)

with open(ROOT / "output" / "power.json", encoding="utf-8") as f:
    cfg = PowerSeqConfig.from_dict(json.load(f))

xml = generate_drawio(cfg)
cells = [int(m.group(1)) for m in re.finditer(r"rounded=0;whiteSpace=wrap.*?y=\"(\d+)\"", xml, re.S)]
nots = [int(m.group(1)) for m in re.finditer(r"inverter_2;rotation=90.*?y=\"(-?\d+)\"", xml, re.S)]

cell_top = min(cells)
expected_bottom = _align40(cell_top - 40)
print("cell_top:", cell_top)
print("expected NOT visual bottom:", expected_bottom)
for ny in nots[:3]:
    nb = _input_not_visual_bottom_y(ny)
    print(f"  NOT y={ny} visual_bottom={nb} gap={cell_top - nb}")
print("_input_not_y:", _input_not_y(cell_top))

# INPUT_NOT.xml reference
ref_not_y = 290
ref_bottom = _input_not_visual_bottom_y(ref_not_y)
print("INPUT_NOT.xml: not_y=290 -> bottom", ref_bottom, "implied cell_top", ref_bottom + 40)
