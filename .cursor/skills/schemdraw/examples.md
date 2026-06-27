# Schemdraw Examples (pwrseq_gen)

## CLI-style export (Python)

```python
from config_models import PowerSeqConfig
from timing_export import TimingExportOptions, TIMING_EDGE_HI_ONLY
from schemdraw_export import export_schemdraw_from_options
from timing_sim import load_scenario_json

cfg = PowerSeqConfig.from_dict(...)
scenario = load_scenario_json("templates/x15dot-f-timing_scenario.json")

opts = TimingExportOptions(
    include_rails=frozenset({"VDD", "RESET", "SLPS4"}),
    edge_kinds=TIMING_EDGE_HI_ONLY,
)

export_schemdraw_from_options(cfg, scenario, opts, "output/timing.pdf")
```

## Generate doc only (inspect edges)

```python
from schemdraw_export import generate_schemdraw_doc, schemdraw_edges_forward_in_time
import json

doc = generate_schemdraw_doc(cfg, scenario, include_rails=opts.include_rails)
assert schemdraw_edges_forward_in_time(doc) == []
print(json.dumps(doc["edge"][:5], indent=2))
# ["[3:12]-~>[7:14]", ...]
```

## GUI user flow

1. Open project JSON; enable Preview pane.
2. Preview language → **Schemdraw**.
3. **Nodes…** → select lanes, Hi/Lo arrows → **Apply**.
4. **Refresh** → pan/zoom preview.
5. **Export → Schemdraw** → pick `.svg` / `.png` / `.pdf` (same nodes/arrows as Preview).

## Preview wheel bindings (reference)

| Input | Schemdraw Preview | Verilog/C Preview |
|-------|-------------------|-------------------|
| Wheel | Vertical scroll | Vertical scroll |
| Shift+Wheel | Horizontal scroll | Horizontal scroll |
| Ctrl+Wheel | Zoom | Font size step |
| Drag | Pan | — |

Constants: `SCHEMDRAW_ZOOM_MIN=0.1`, `MAX=5.0`, `STEP=1.2`, debounce 40 ms for resize.

## Minimal extended-edge doc (hand-written)

```json
{
  "signal": [
    {"name": "iDEP", "wave": "01"},
    {"name": "oOUT", "wave": "01"}
  ],
  "config": {"hscale": 1, "skin": "narrow"},
  "edge": ["[0:0]-~>[1:1]"]
}
```

Render:

```python
from schemdraw_export import render_schemdraw
render_schemdraw(doc, "timing.svg")
```

## Template artifacts

| File | Notes |
|------|-------|
| `templates/x15dot-f-wavedrom.json` | WaveDrom export (has node letters) |
| `templates/x15dot-f-timing_scenario.json` | Simulation inputs (shared) |
| `templates/x15dot-f-Schemdraw_*.png` | Local render samples (not in git) |

Schemdraw does not commit a separate JSON; doc is generated on the fly like WaveDrom but with extended edges only.
