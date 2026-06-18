---
name: drawio-placement
description: >-
  Documents pwrseq_gen Draw.io placement in drawio_cell_export.py (default
  generate_drawio) — per-output blocks, Cell 40pt snap, ROW/COL gap, label
  stack, intra-group AND/OR/XOR trees, PSEQCELL O port, export net-name wire
  reserve. Shared geometry in drawio_geometry.py. Use when modifying cell block
  spacing, BLOCK_PAD, grid columns, or gate placement.
---

# Draw.io Placement (pwrseq_gen)

Placement is **deterministic**; there is no separate auto-layout engine.

| Entry | Source |
|-------|--------|
| `generate_drawio()` | `src/drawio_cell_export.py` (thin wrapper in `src/drawio_export.py`) |
| Options | `src/drawio_export_options.py` (`grid_columns`, `margin`) |
| Shared geometry | `src/drawio_geometry.py` (`GRID`, PSEQCELL, gate styles, intra-op) |

`drawio_export.generate_drawio()` delegates to `drawio_cell_export.generate_drawio`.

**Wire rules:** all edges are Draw.io **orthogonal auto** — no frozen waypoints. See [drawio-routing](../drawio-routing/SKILL.md).

Function map & constants: [reference.md](reference.md).

---

## Cell-centric export (only layout) ★

One **block** per output rail; blocks arranged in a multi-column **grid**. Output order = **declaration order** in config (`_declaration_order_outputs`), not topo sort.

**Not drawn:** Force conditions (`use=force` terms skipped). **No Q／~Q** ports — only H_Deb, L_Deb, O inside each PSEQCELL group.

**Cross-block deps:** `use=hi` / `use=lo` appear as **purple cond labels** (`{internal_sig}_{hi|lo}`) inside the consumer block; they are **not** wired to other cells on the page.

### Pipeline

```
config.rails (outputs)
  → _exported_hilo_keys (who needs purple export label on Deb edge)
  → _estimate_block_size per rail (w, h)
  → n_cols = options.grid_columns or ceil(sqrt(n)) clamped 2…6
  → col_widths[c] = max(w); row_heights[r] = max(h)
  → col_x[], row_y[] with _snap_grid(margin); +COL_GAP / +ROW_GAP between blocks
  → foreach output: _build_cell_block(ox, oy, col_widths[col], row_heights[row])
```

Left→right inside block: **input/cond labels → AND/OR/XOR (local) → PSEQCELL (H/L_Deb + O) → output name**.

### PSEQCELL (`src/reference/PSEQCELL.xml`)

Loaded at import via `_load_pseqcell_layout()` in `drawio_geometry.py`.

| Part | Geometry | Notes |
|------|----------|--------|
| inner | 80×80 | Group bbox |
| H_Deb / L_Deb | y=10 / y=50 | Debounce labels (`_deb_port_label`) |
| **O** | x=60, y=30, 20×20 | **Output port**; `points=[[1,0.5]]` right exit |

Emit: **inner + H_Deb + L_Deb + O** only.

### Block geometry

| Piece | Role |
|-------|------|
| `BLOCK_PAD` | Top/bottom/left/right inset inside block bbox (`= GRID` import; override here without changing global `GRID`) |
| `CELL_GROUP_W/H` | 80×80 PSEQCELL group |
| `top_extent` / `bottom_extent` | Hi labels stack **up**, Lo labels stack **down** from Deb anchors (`LABEL_STACK_STEP` per extra label) |
| `block_h` | `max(BLOCK_MIN_H, BLOCK_PAD×2 + top_extent + CELL_GROUP_H + bottom_extent)` |

**Cell position inside block:**

- `cell_x = snap(ox + bw − BLOCK_PAD − OUT_LABEL_W − GAP − CELL_GROUP_W)` — right-aligned
- `cell_y = snap(_cell_y_in_block(oy, hi_count))` — first Hi label aligns with Hi_Deb; `hi_count=0` → `oy + BLOCK_PAD`

**Cell top-left** must land on **40pt grid** (`_snap_grid`, step `GRID`).

### Cell–Cell spacing

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

**Horizontal Cell gap** (same row): `col_width + COL_GAP − CELL_GROUP_W` — dominated by **column width** (gates + `wire_extra` + labels).

**Row/column max:** tallest block in a row sets `row_heights` for **all** cells in that row; widest block in a column sets `col_widths`.

### Horizontal gaps (label / gate → Cell Deb)

| Path | Right edge → Cell left |
|------|------------------------|
| Label → gate input | `GAP` (40pt) between label right and gate left |
| Gate output → Cell Deb | `GATE_CELL_GAP` (40pt) |
| **Label direct → Deb** (single input, no gate) | **`GATE_CELL_GAP` only** (40pt) |
| Above + **export net name** | `GATE_CELL_GAP + extra` (extra on 40pt grid) |

Block width (`_estimate_block_size`): `LABEL_W + (GAP + gate_w if depth>0 else 0) + GATE_CELL_GAP + wire_extra + …`

### Export net name (purple cond on Hi/Lo → Deb edge)

When another output references this rail with `use=hi` / `use=lo`, the last edge into Deb gets a purple HTML label `{internal_sig}_{hl}`.

```
text_w = len(name)×EXPORT_CHAR_PT + EXPORT_WIRE_PAD
raw    = max(EXPORT_WIRE_MIN, ⌈text_w − GATE_CELL_GAP⌉)
extra  = _snap_grid_up(raw)
```

`gate_right -= extra` before placing gates/labels (`_wire_path_v2`). Hi/Lo both exported → `max(extra)` for block width.

Functions: `_exported_hilo_keys`, `_export_wire_extra_for_name`, `_max_export_wire_extra`, `_snap_grid_up`.

### Intra-group gates (AND / OR / XOR)

Per group (`depends_on_*_intra_op` from Excel / JSON):

| Op | Normal | `group_inv` (multi-input group) |
|----|--------|----------------------------------|
| AND | AND | NAND |
| OR | OR | NOR |
| XOR | XOR | XNOR |

Styles from `AND1.xml` / `NAND1.xml` / `OR1.xml` / `NOR1.xml` / `XOR1.xml` / `XNOR1.xml` via `drawio_geometry._intra_*_gate_style`.

**Between groups** (same Hi or Lo path): OR merge (`_wire_or_fanin`); all single-input groups with every `group_inv` → NOR at merge.

### AND/OR trees (n ≥ 8)

Per `example (1).xml` / `example (2).xml`: **child gate** (left) → **merge gate** (right). Right label column uses index `ii+1` so index 0 stays free for child output wire.

Applies to intra-group AND (`_wire_and_branch`) and inter-group OR (`_wire_or_fanin`).

Stack height uses `_effective_stack_inputs` (not raw input count) for block sizing.

### Tunable constants (`drawio_cell_export.py`)

| Constant | Default | Adjust for |
|----------|---------|------------|
| `BLOCK_PAD` | `GRID` (40) | Block inset |
| `ROW_GAP` | 0 | Extra space between block rows |
| `COL_GAP` | 0 | Extra space between block columns |
| `BLOCK_MIN_H` | 0 | Minimum block height floor |
| `LABEL_STACK_STEP` | 20 | Vertical spacing per extra input label |
| `LABEL_W` / `OUT_LABEL_W` | 100 | Horizontal block width |
| `GATE_CELL_GAP` | `GAP` (40) | Gate column → Cell |
| `EXPORT_CHAR_PT` / `EXPORT_WIRE_PAD` / `EXPORT_WIRE_MIN` | 8 / 0 / 0 | Purple export-name wire reserve |
| `AND_TREE_THRESHOLD` | 8 | ≥8 inputs/branches → 2-level cascade |

**`GRID`** is in `src/drawio_geometry.py` (`GRID = 40`). Change `BLOCK_PAD` locally unless the whole project grid should change.

All spacing constants live at the top of `drawio_cell_export.py` — not in `DrawioExportOptions`.

### Options (`DrawioExportOptions`)

| Field | Default | Effect |
|-------|---------|--------|
| `grid_columns` | `None` → `ceil(sqrt(n))` clamped 2…6 | Column count |
| `margin` | 40 | Page origin; snapped |

---

## Modification checklist

- [ ] Spacing: `BLOCK_PAD`, `ROW_GAP`, `COL_GAP`, `LABEL_STACK_STEP`, `BLOCK_MIN_H`
- [ ] `block_h` / `row_heights`: `_block_vertical_layout` + per-row `max`
- [ ] `cell_x`/`cell_y`: `_cell_y_in_block`, `_snap_grid` after position calc
- [ ] Block width: `_estimate_block_size`, `_export_wire_extra_for_name`, gate depth; direct-label path skips extra `GAP`
- [ ] PSEQCELL: `_load_pseqcell_layout` / `CELL_O_*`; output edge from O right
- [ ] Intra-op / group_inv: `_intra_merge_gate_style`, `_or_gate_style` in `drawio_geometry.py`
- [ ] Run `pytest tests/test_drawio_cell.py tests/test_integration.py -q`

## Common mistakes

| Mistake | Correct approach |
|---------|------------------|
| Expecting Sugiyama / layer-column layout | Only cell-centric grid in `drawio_cell_export.py` |
| Direct label→Deb uses 80pt (GAP+GATE_CELL_GAP) | Single-term branch: `label_right = attach_right` (40pt only) |
| Wiring Q/~Q feedback between blocks | Not supported; use cond label `{sig}_{hi\|lo}` |
| Export `extra` not on 40pt grid | `_snap_grid_up` on `_export_wire_extra_for_name` result |

## Verification

```bash
python -m pytest tests/test_drawio_cell.py tests/test_integration.py::TestIntegration::test_cell_centric_drawio_from_demo -q
```

Export sample: GUI or `run.bat` → inspect `output/*.xml` in Draw.io.

## See also

- [reference.md](reference.md) — constants, function index
- `.cursor/skills/drawio-routing/` — orthogonal edge rules within a block
