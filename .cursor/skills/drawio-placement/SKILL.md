---
name: drawio-placement
description: >-
  Documents pwrseq_gen Draw.io placement in drawio_cell_export.py (default
  generate_drawio) — per-output blocks, Cell 40pt snap, ROW/COL gap, label
  stack, AND tree, PSEQCELL O port, export net-name wire reserve. Shared
  geometry in drawio_geometry.py. Use when modifying cell block spacing,
  BLOCK_PAD, grid columns, or gate placement.
---

# Draw.io Placement (pwrseq_gen)

Placement is **deterministic**; there is no separate auto-layout engine.

| Entry | Source |
|-------|--------|
| `generate_drawio()` | `src/drawio_cell_export.py` (wrapper in `src/drawio_export.py`) |
| Shared geometry | `src/drawio_geometry.py` (`GRID`, PSEQCELL, gate styles) |

`drawio_export.generate_drawio()` delegates to `drawio_cell_export.generate_drawio`.

Cell export uses **orthogonal auto edges** only. Wire rules: [drawio-routing](../drawio-routing/SKILL.md)（cell-centric 章節）.

Function map & constants: [reference.md](reference.md).

---

## Cell-centric export (default) ★

One **block** per output rail; blocks arranged in a multi-column **grid**. Output order = **declaration order** in config (`_declaration_order_outputs`), not topo sort.

### Pipeline

```
config.rails (outputs)
  → _estimate_block_size per rail (w, h)
  → n_cols = options.grid_columns or ceil(sqrt(n)) clamped 2…6
  → col_widths[c] = max(w); row_heights[r] = max(h)  # per column/row
  → col_x[], row_y[] with _snap_grid(margin); +COL_GAP / +ROW_GAP between blocks
  → foreach output: _build_cell_block(ox, oy, col_widths[col], row_heights[row])
```

Left→right inside block: **input labels → AND/OR (local) → PSEQCELL (H/L_Deb + O) → output name**.

### PSEQCELL (`src/reference/PSEQCELL.xml`)

Loaded at import via `_load_pseqcell_layout()` in `drawio_geometry.py`.

| Part | Geometry | Notes |
|------|----------|--------|
| inner | 80×80 | Group bbox |
| H_Deb / L_Deb | y=10 / y=50 | Debounce labels (`_deb_port_label`) |
| **O** | x=60, y=30, 20×20 | **Output port**; `points=[[1,0.5]]` right exit |

Cell-centric emit: **inner + H_Deb + L_Deb + O** only (no Q／~Q).  
Output name edge: `source=O`, `exitX=1;exitY=0.5`; label left = `cell_x + CELL_O_X + CELL_O_W + GAP`.

Legacy archived export may still reference Q／~Q constants when old `PSEQCELL.xml` had them.

### Block geometry

| Piece | Role |
|-------|------|
| `BLOCK_PAD` | Top/bottom/left/right inset inside block bbox (`= GRID` import; override here without changing global `GRID`) |
| `CELL_GROUP_W/H` | 80×80 PSEQCELL group (`drawio_geometry.py`) |
| `top_extent` / `bottom_extent` | Hi labels stack **up**, Lo labels stack **down** from Deb anchors (`LABEL_STACK_STEP` per extra label) |
| `block_h` | `max(BLOCK_MIN_H, BLOCK_PAD×2 + top_extent + CELL_GROUP_H + bottom_extent)` |

**Cell position inside block:**

- `cell_x = snap(ox + bw − BLOCK_PAD − OUT_LABEL_W − GAP − CELL_GROUP_W)` — right-aligned
- `cell_y = snap(_cell_y_in_block(oy, hi_count))` — first Hi label aligns with Hi_Deb; `hi_count=0` → `oy + BLOCK_PAD`

**Cell top-left** must land on **40pt grid** (`_snap_grid`, step `GRID`).

### Cell–Cell spacing (what actually controls it)

```
next row_y = prev row_y + row_heights[r] + ROW_GAP
next col_x = prev col_x + col_widths[c] + COL_GAP
```

**Visual vertical gap** between two Cells (same column, similar `hi_count`):

```
≈ row_heights − CELL_GROUP_H(80) + ROW_GAP
  = block_h − 80 + ROW_GAP
```

With `ROW_GAP=COL_GAP=BLOCK_MIN_H=0`, floor is still:

| Case | `block_h` | Cell–Cell gap |
|------|-----------|---------------|
| No Hi/Lo labels | `BLOCK_PAD×2 + 80` = **160** | **80** |
| 1 Hi + 1 Lo | ~200 | ~120 |
| 2 Hi + 2 Lo | ~240 | ~160 |

`ROW_GAP`/`BLOCK_MIN_H` being 0 does **not** remove `BLOCK_PAD` or label `top_extent`/`bottom_extent`.

**Horizontal Cell gap** (same row, equal column width): `col_width + COL_GAP − CELL_GROUP_W` — dominated by **column width** (gates + `wire_extra` + labels), not `COL_GAP` alone.

**Row/column max:** tallest block in a row sets `row_heights` for **all** cells in that row; widest block in a column sets `col_widths`. One complex output stretches neighbors.

### Horizontal gaps (label / gate → Cell Deb)

| Path | Right edge → Cell left |
|------|------------------------|
| Label → gate input | `GAP` (40pt) between label right and gate left |
| Gate output → Cell Deb | `GATE_CELL_GAP` (40pt) |
| **Label direct → Deb** (single input, no gate) | **`GATE_CELL_GAP` only** (40pt) — same as gate→Cell |
| Above + **export net name** | `GATE_CELL_GAP + extra` (both 40pt-grid aligned) |

Block width (`_estimate_block_size`): `LABEL_W + (GAP + gate_w if depth>0 else 0) + GATE_CELL_GAP + wire_extra + …`

### Export net name (purple cond on Hi/Lo edge)

Triggered when another output references this rail with `use=hi`/`use=lo`. Name: `{_internal_sig(rail)}_{hl}`.

```
text_w = len(name)×EXPORT_CHAR_PT + EXPORT_WIRE_PAD
raw    = max(EXPORT_WIRE_MIN, ⌈text_w − GATE_CELL_GAP⌉)
extra  = _snap_grid_up(raw)          # ceil to 40pt multiple
```

`gate_right -= extra` before placing gates/labels (`_wire_path_v2`). Last edge to Deb gets purple HTML label. Hi/Lo both exported → `max(extra)` for block width.

Functions: `_exported_hilo_keys`, `_export_wire_extra_for_name`, `_max_export_wire_extra`, `_snap_grid_up`.

### Tunable constants (`drawio_cell_export.py`)

| Constant | Default | Adjust for |
|----------|---------|------------|
| `BLOCK_PAD` | `GRID` (40) | Block inset; main lever after `ROW_GAP`/`COL_GAP` |
| `ROW_GAP` | 0 (tunable; design 80) | Extra space between block rows |
| `COL_GAP` | 0 (tunable; design 120) | Extra space between block columns |
| `BLOCK_MIN_H` | 0 (tunable; design 120) | Minimum block height floor |
| `LABEL_STACK_STEP` | 20 | Vertical spacing per extra input label |
| `LABEL_W` / `OUT_LABEL_W` | 100 | Horizontal block width |
| `GATE_CELL_GAP` | `GAP` (40) | Gate column → Cell |
| `EXPORT_CHAR_PT` / `EXPORT_WIRE_PAD` / `EXPORT_WIRE_MIN` | 8 / 32 / 40 | Purple export-name wire segment → block width |
| `AND_TREE_THRESHOLD` | 8 | ≥8 inputs → 2-level AND cascade |

**`GRID`** is defined in `src/drawio_geometry.py` (`GRID = 40`). Cell export imports it; change `BLOCK_PAD` locally rather than global `GRID` unless whole project grid should change.

All spacing constants (`ROW_GAP`, `COL_GAP`, `BLOCK_MIN_H`, `BLOCK_PAD`) live at the top of `drawio_cell_export.py` — not in `DrawioExportOptions`.

### AND tree (n ≥ 8)

Per `example (1).xml` / `example (2).xml`: **child AND** (left) → **merge AND** (right). Right label column uses index `ii+1` so index 0 stays free for child output wire.

Stack height uses `_effective_stack_inputs` (not raw input count) for block sizing.

### Options (`DrawioExportOptions`)

| Field | Default | Effect |
|-------|---------|--------|
| `grid_columns` | `None` → `ceil(sqrt(n))` clamped 2…6 | Column count |
| `margin` | 40 | Page origin; snapped |

### Verification

```bash
python -m pytest tests/test_drawio_cell.py -q
```

Includes: PSEQCELL **O** geometry, label stack, export wire 40pt grid, label→Deb 40pt, AND tree, declaration order, **Cell on 40pt grid**.

---

## Modification checklist

- [ ] Spacing: `BLOCK_PAD`, `ROW_GAP`, `COL_GAP`, `LABEL_STACK_STEP`, `BLOCK_MIN_H`
- [ ] `block_h` / `row_heights`: `_block_vertical_layout` + per-row `max`
- [ ] `cell_x`/`cell_y`: `_cell_y_in_block`, `_snap_grid` after position calc
- [ ] Block width: `_estimate_block_size`, `_export_wire_extra_for_name`, AND depth; direct-label path skips extra `GAP`
- [ ] PSEQCELL: `_load_pseqcell_layout` / `CELL_O_*`; output edge from O right
- [ ] 閘 style 變更：對齊 `AND1`／`NAND1`／`OR1`／`NOR1.xml`
- [ ] Run `pytest tests/test_drawio_cell.py`

## Common mistakes

| Mistake | Correct approach |
|---------|------------------|
| Expecting Sugiyama / generic graph layout for export | Only `generate_drawio` defines coords |
| Direct label→Deb uses 80pt (GAP+GATE_CELL_GAP) | Single-term branch: `label_right = attach_right` (40pt only) |
| Export `extra` not on 40pt grid | `_snap_grid_up` on `_export_wire_extra_for_name` result |

## Verification

```bash
python -m pytest tests/test_drawio_cell.py -q
```

Export sample: `run.bat` → inspect `output/*.xml` in Draw.io.

## See also

- [reference.md](reference.md) — constants, function index
- `.cursor/skills/drawio-routing/` — cell-centric wire rules
