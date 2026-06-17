# Draw.io Placement Reference

## Cell-centric export (`drawio_cell_export.py`) — default

`generate_drawio()` delegates here. Shared geometry (`GRID`, `CELL_*`, gate styles) from `drawio_geometry.py`.

### Key constants (cell export)

| Constant | Default | Role |
|----------|---------|------|
| `GRID` | 40 | Import from `drawio_geometry.py`; `_snap_grid` step |
| `BLOCK_PAD` | `GRID` | Block inset (override here to tune spacing without changing global `GRID`) |
| `ROW_GAP` | 0* | Extra Y between block rows (*tunable in source; was 80) |
| `COL_GAP` | 0* | Extra X between block columns (*tunable; was 120) |
| `BLOCK_MIN_H` | 0* | Minimum block height floor (*tunable; was 120) |
| `LABEL_W` | 100 | Input / cond label width |
| `OUT_LABEL_W` | 100 | Output name label width |
| `LABEL_STACK_STEP` | 20 | Extra Hi↑ / Lo↓ per stacked input label |
| `GATE_CELL_GAP` | `GAP` (40) | Rightmost gate → Cell |
| `AND_TREE_THRESHOLD` | 8 | Single AND if n&lt;8; else 2-level child→merge |
| `EXPORT_CHAR_PT` | 8 | Export label width estimate |
| `EXPORT_WIRE_PAD` | 32 | Added to export wire segment |
| `EXPORT_WIRE_MIN` | 40 | Minimum `extra` before grid snap |
| *(export extra)* | — | `extra=_snap_grid_up(max(40,⌈len×8+32−40⌉))`; segment=`GAP+extra` (40pt grid) |

Shared (import): `CELL_GROUP_H/W` 80, `CELL_H_DEB_Y` 10, `CELL_L_DEB_Y` 50, `CELL_O_X/Y` 60/30, `CELL_O_W/H` 20, `AND_GATE_W/H` 80/40, `GAP` 40, `INPUT_LABEL_H` 20.

### Horizontal spacing (cell export)

| Segment | Gap |
|---------|-----|
| Label right → gate left | `GAP` (40) |
| Gate right → Cell left (Deb path) | `GATE_CELL_GAP` (40) |
| Label right → Cell left (direct, no gate) | `GATE_CELL_GAP` (40) only |
| + export net name | `+ extra` (`_export_wire_extra_for_name`) |

`_estimate_block_size`: `LABEL_W + (GAP+gate_w if depth>0 else 0) + GATE_CELL_GAP + wire_extra + CELL…`

### Function index (cell export)

| Function | Purpose |
|----------|---------|
| `generate_drawio` | Grid layout, page size, emit all blocks |
| `_estimate_block_size` | Per-rail `(width, height)` before grid merge |
| `_block_vertical_layout` | `(top_extent, bottom_extent, block_h)` |
| `_cell_y_in_block` | Cell top Y inside block from `hi_count` |
| `_snap_grid` | Round coordinate to `GRID` multiple |
| `_snap_grid_up` | Ceil to `GRID` (export `extra`; never shrink below formula) |
| `_add_pseqcell_group` | inner + H/L_Deb + **O**; returns `o_id` |
| `_build_cell_block` | Cell, labels, gates; O→output name edge |
| `_exported_hilo_keys` | `(rail, hi\|lo)` pairs needing purple net label |
| `_wire_path_v2` | Hi or Lo path: labels → AND/OR → Deb |
| `_wire_and_branch` | One AND group; 2-level tree if n≥8 |
| `_effective_stack_inputs` | Stack height for sizing (tree uses half-columns) |
| `_declaration_order_outputs` | Output row order (= config declaration) |
| `_grid_columns` | `options.grid_columns` or sqrt heuristic |
| `_export_wire_extra_for_name` | Horizontal space for purple export edge label |

### Grid merge

```python
col_widths[col] = max(w per column)
row_heights[row] = max(h per row)
row_y[r+1] = row_y[r] + row_heights[r] + ROW_GAP
col_x[c+1] = col_x[c] + col_widths[c] + COL_GAP
```

### Cell–Cell gap (vertical, same hi_count)

`≈ block_h − CELL_GROUP_H + ROW_GAP`. With gaps zeroed, floor `block_h = BLOCK_PAD×2 + 80` → visual gap `2×BLOCK_PAD` when no label extents (80pt if `BLOCK_PAD=40`).

### Files

| Path | Role |
|------|------|
| `src/drawio_cell_export.py` | Cell-centric placement + emit |
| `src/drawio_geometry.py` | `GRID`, PSEQCELL/gate constants |
| `src/drawio_export.py` | `generate_drawio` entry wrapper |
| `src/drawio_export_options.py` | `grid_columns`, `margin` |
| `tests/test_drawio_cell.py` | Cell export tests |

### Reference XML

| Path | Role |
|------|------|
| `src/reference/PSEQCELL.xml` | Cell Draw.io 幾何（inner／H_Deb／L_Deb／**O**） |
| `src/reference/AND1.xml` | AND 元件（`numInputs=1`） |
| `src/reference/NAND1.xml` | NAND（`group_inv`） |
| `src/reference/OR1.xml` | OR 元件 |
| `src/reference/NOR1.xml` | NOR（OR 反相） |
