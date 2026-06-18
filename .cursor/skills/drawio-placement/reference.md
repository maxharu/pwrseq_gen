# Draw.io Placement Reference

## Cell-centric export (`drawio_cell_export.py`) — default

`generate_drawio()` in `drawio_export.py` delegates here. Shared geometry from `drawio_geometry.py`; options from `drawio_export_options.py`.

### Key constants (cell export)

| Constant | Default | Role |
|----------|---------|------|
| `GRID` | 40 | Import from `drawio_geometry.py`; `_snap_grid` step |
| `BLOCK_PAD` | `GRID` | Block inset |
| `ROW_GAP` | 0 | Extra Y between block rows |
| `COL_GAP` | 0 | Extra X between block columns |
| `BLOCK_MIN_H` | 0 | Minimum block height floor |
| `LABEL_W` | 100 | Input / cond label width |
| `OUT_LABEL_W` | 100 | Output name label width |
| `LABEL_STACK_STEP` | 20 | Extra Hi↑ / Lo↓ per stacked input label |
| `GATE_CELL_GAP` | `GAP` (40) | Rightmost gate → Cell |
| `AND_TREE_THRESHOLD` | 8 | Single gate if n&lt;8; else 2-level child→merge |
| `EXPORT_CHAR_PT` | 8 | Export label width estimate |
| `EXPORT_WIRE_PAD` | 0 | Added to export wire segment |
| `EXPORT_WIRE_MIN` | 0 | Minimum `extra` before grid snap |

Export extra formula: `extra = _snap_grid_up(max(0, ⌈len×8+0 − 40⌉))`; reserved segment = `GATE_CELL_GAP + extra`.

Shared (import): `CELL_GROUP_H/W` 80, `CELL_H_DEB_Y` 10, `CELL_L_DEB_Y` 50, `CELL_O_X/Y` 60/30, `CELL_O_W/H` 20, `AND/OR_GATE_W/H` 80/40, `GAP` 40, `INPUT_LABEL_H` 20.

### Horizontal spacing

| Segment | Gap |
|---------|-----|
| Label right → gate left | `GAP` (40) |
| Gate right → Cell left (Deb path) | `GATE_CELL_GAP` (40) |
| Label right → Cell left (direct, no gate) | `GATE_CELL_GAP` (40) only |
| + export net name | `+ extra` (`_export_wire_extra_for_name`) |

### Intra-op gate styles (`drawio_geometry.py`)

| `intra_op` | Merge (normal) | Merge + `group_inv` |
|------------|----------------|---------------------|
| `and` | AND | NAND |
| `or` | OR | NOR |
| `xor` | XOR | XNOR |

Inter-group OR: `_or_gate_style` → OR or NOR (all single-input groups inverted).

### Function index

| Function | Purpose |
|----------|---------|
| `generate_drawio` | Grid layout, page size, emit all blocks |
| `_estimate_block_size` | Per-rail `(width, height)` before grid merge |
| `_block_vertical_layout` | `(top_extent, bottom_extent, block_h)` |
| `_cell_y_in_block` | Cell top Y inside block from `hi_count` |
| `_snap_grid` / `_snap_grid_up` | Round / ceil to `GRID` |
| `_add_pseqcell_group` | inner + H/L_Deb + **O**; returns port ids |
| `_build_cell_block` | Cell, labels, gates, wire paths, O→name |
| `_exported_hilo_keys` | `(rail, hi\|lo)` needing export Deb label |
| `_wire_path_v2` | Hi or Lo: labels → gates → Deb |
| `_wire_and_branch` | One group; 2-level tree if n≥8 |
| `_wire_or_fanin` | OR merge across groups; 2-level if n≥8 |
| `_resolve_term` | dep/inv/use → `_Term` label text |
| `_effective_stack_inputs` | Stack height for sizing |
| `_declaration_order_outputs` | Output order (= config declaration) |
| `_grid_columns` | `options.grid_columns` or sqrt heuristic |
| `_export_wire_extra_for_name` | Horizontal reserve for purple export label |
| `_gate_depth` / `_and_columns` / `_or_columns` | Block width estimate |

### Grid merge

```python
col_widths[col] = max(w per column)
row_heights[row] = max(h per row)
row_y[r+1] = row_y[r] + row_heights[r] + ROW_GAP
col_x[c+1] = col_x[c] + col_widths[c] + COL_GAP
```

### Files

| Path | Role |
|------|------|
| `src/drawio_cell_export.py` | Cell-centric placement + emit |
| `src/drawio_geometry.py` | `GRID`, PSEQCELL/gate constants, intra-op styles |
| `src/drawio_export.py` | `generate_drawio` wrapper + re-exports |
| `src/drawio_export_options.py` | `DrawioExportOptions` |
| `tests/test_drawio_cell.py` | Cell export tests |
| `tests/test_integration.py` | `test_cell_centric_drawio_from_demo` |

### Reference XML

| Path | Role |
|------|------|
| `src/reference/PSEQCELL.xml` | Cell geometry (inner / H_Deb / L_Deb / **O**) |
| `src/reference/AND1.xml` … `XNOR1.xml` | Logic gate Draw.io styles |
