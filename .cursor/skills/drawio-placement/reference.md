# Draw.io Placement Reference

## Cell-centric export (`drawio_cell_export.py`) — default

`generate_drawio()` delegates here. Shared geometry (`GRID`, `CELL_*`, gate styles) imported from `drawio_export.py`.

### Key constants (cell export)

| Constant | Default | Role |
|----------|---------|------|
| `GRID` | 40 | Import from `drawio_export.py`; `_snap_grid` step; **not** redefined in cell file |
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
| `src/drawio_export.py` | `GRID`, PSEQCELL/gate constants; legacy placement body |
| `src/drawio_export_options.py` | `grid_columns`, `margin` |
| `tests/test_drawio_cell.py` | Cell export tests |

---

## Legacy layer-based export (`drawio_export.py`)

Source of truth for archived pipeline: `doc/DRAWIO_RULES.md`.

### Key constants (legacy)

| Constant | Value | Role |
|----------|-------|------|
| `GRID` / `GAP` | 40 | Grid unit; horizontal stub, slack increment |
| `ROW_GAP` | 40 | **Cell 列間基本 Y 間距**（≠ AND 堆疊步距） |
| `AND_GATE_W/H` | 80/40 | Gate size（`AND1.xml` 等） |
| `AND_GATE_DY` | 80 | 同 hl 多顆 AND 垂直堆疊（對齊 Deb 後 +80pt） |
| `NOT_OFFSET_X` | 80 | output NOT 右移（與 `ROW_GAP` 無關） |
| `OUTPUT_NAME_NOT_EXTRA` | 80 | 有 output NOT 時輸出名稱欄額外寬度 |
| `OR_GATE_OFFSET_HI_Y` | 0 | Hi OR／NOR nominal Y → 對齊 H_Deb |
| `OR_GATE_OFFSET_LO_Y` | 40 | Lo OR／NOR nominal Y → 對齊 L_Deb |
| `OR_GATE_H` | 40 | OR／NOR 高度 |
| `MARGIN` | 40 | Top/left margin |
| `CELL_GROUP_H/W` | 80 | Cell inner |
| `CELL_O_X/Y/W/H` | 60/30/20/20 | O 輸出埠（`PSEQCELL.xml`） |
| `FB_Q_RIGHT/UP` | 40, 60 | Q 回授 ①②（routing） |
| `FB_NQ_RIGHT/UP` | 80, 140 | ~Q 回授 ①②（**同 Cell 亦有 Q 回授**；routing） |
| `FB_NQ_UP_NO_Q` | 100 | ~Q 回授 ②（**同 Cell 無 Q 回授**；routing） |
| `OUTPUT_NAME_GAP` | 120 | Cell right → name label |
| `NOT_STACK_GAP` | 20 | Row after output NOT (`INPUT_LABEL_H`) |

### Function index (legacy placement-related)

| Function | Layer | Purpose |
|----------|-------|---------|
| `_cell_fb_segment3_y_gaps` | Cell Y | FB ③ p2y：僅 gap `src_row−1`（來源列與上一列之間） |
| `_feedback_y_slack_between_cell_rows` | Cell Y | Cross-row Cell Q/~Q (`use=self`, output src); q/nq 同 gap 可累加 |
| `_feedback_y_slack_after_and` | AND Y | Cross-row output→AND; Input direct to OR/NOR/Cell (not AND) |
| `_feedback_y_slack_after_or` | OR Y | Cross-row Cell→OR input; Input/AND direct to Cell |
| `_mark_y_gap` | AND/OR | Dedup +40pt per gap (gap ≥ 1) |
| `_build_and_catalog` | AND | Global AND/NAND order |
| `_build_or_catalog` | OR | Global OR/NOR order (Hi then Lo per row) |
| `_chain_and_top_y` | AND | 新列錨定 nominal；同列 chain + slack |
| `_chain_or_top_y` | OR | Chain Y; new-row anchor `row_py+off` (Deb); same-row Hi→Lo like AND |
| `_nearest_and_and_gap` | AND | Map feedback edge → AND–AND gap below |
| `_nearest_or_or_gap` | OR | Map feedback edge → OR–OR gap below |
| `_row_height_for_output` | Cell Y | max(80, 閘體下緣)；Deb 對齊 Hi/Lo AND 不額外加高 |
| `_input_band_width` | Input X | Input column width |
| `_layout_input_positions` | Input X/Y | Label x (R→L), shared `input_row_y` |
| `_count_feedback_trunks` | Input X | Left trunk count (cross-row→AND) |
| `_count_cell_fb_to_deb` | Cell X | `fb_cell` for gap formula（走線 slot 見 routing：per source per layer） |
| `_gate_gap_width` | Gate X | `(n+2+fb-exempt)×40` |
| `_compute_row_gate_layouts` | Gate X | Per-row `cell_start_x`, `or_col_x` |
| `_count_direct_horizontal_exempts` | Gate X | Same-Y direct −1 slot |
| `_ChannelAllocator` | Wire X | Right-side vertical lanes |
| `_GateExitLanes` | Wire X | Per-gate right stub 40×n |
| `_topological_order_outputs` | Cell Y | Dependency topo sort for row order |
| `_barycenter_order_outputs` | Cell Y | 4-pass barycenter tweak (adjacent deps); **not** full-graph Sugiyama |

### Output row ordering (legacy)

- `_topological_order_outputs` then `_barycenter_order_outputs` only reorder **Cell rows** (vertical).
- Does **not** assign AND/OR column X or wire channels; see placement phases above.

### Y slack triggers (§10)

**AND／OR 層：** 相鄰同層 gap 最多 +40pt（**去重**，`_mark_y_gap`）。

**Cell row 層：** ③ 段 p2y 走廊；**僅** gap `src_row−1`；**q 與 nq 不共用** profile 但同 gap 可 **累加** +40。

| Layer | Triggers | Dedup |
|-------|----------|-------|
| **AND/NAND** | Cross-row output → AND input; Input direct to OR/NOR/Cell (`len(group)==1`) | per gap |
| **OR/NOR** | Cross-row output → OR input (OR row, `len(group)==1`); Input direct to Cell; AND direct to Cell (no OR on row) | per gap |
| **Cell rows** | Cross-row Cell Q/~Q `use=self` (→ Deb or AND)；gap = **來源列正上方一格** | per profile; q+nq stack |

**Excluded:** Input → AND (feeds via label x+40 bus).

**demo／power.json 範例（Cell row）：** `{6: 80, 10: 40}`（RSMRST row7：q+nq 同 gap6；PCH_PWROK row11：gap10）。

### X gap formula (§8)

```
segment_pt = max(0, base + 2 + fb - exempt) × 40
```

| Segment | base | fb |
|---------|------|-----|
| AND→Cell | n (AND count) | fb_cell |
| AND→OR | n | fb_or |
| OR→Cell | m (OR count) | fb_cell |

`+2` = GAP on each side of channel (same as Input→AND trunk padding).

### Data structures in generate_drawio (legacy)

| Name | Content |
|------|---------|
| `output_to_row` | rail name → row index |
| `and_index_per_key` | `(rail, hl, gi)` → `(row_j, nominal_y_off_pt)` — hi: `OR_GATE_OFFSET_HI_Y`+idx×`AND_GATE_DY`；lo: `OR_GATE_OFFSET_LO_Y`+idx×`AND_GATE_DY` |
| `or_index_per_key` | `(rail, hl)` → `(row_j, nominal_offset_y)` |
| `idx_map` / `or_idx_map` | catalog key → global gate number |
| `row_py` | copy of `row_y_base` (Cell anchor Y) |
| `and_top_y` / `or_top_y` | global gate number → top Y |
| `row_gate_layout` | per rail: `cell_start_x`, `or_col_x`, `has_or` |
| `positions_out` / `positions_in` | final vertex origins |

### Draw order (Phase 4, legacy)

1. Input labels (+ input NOT vertices)
2. For each output: inner, H_Deb, L_Deb, Q, ~Q, name label, Q→name edge
3. Per output, Hi then Lo: AND gates → OR (if ≥2 groups) → wires to Deb
4. `_GateExitLanes` — stub lane **n** skips gates with only one horizontal direct output
5. `use=hi/lo` passthrough — emit: logic_out already → `exitX=1`; Deb placeholder → `exitX=0` then Pass 1 swap (see drawio-routing skill)

### Files (legacy + shared)

| Path | Role |
|------|------|
| `src/reference/PSEQCELL.v` | Power Sequence Cell RTL（`iHi`／`iLo`／`iForce`／`o`） |
| `src/reference/PSEQCELL.xml` | Cell Draw.io 幾何（inner／H_Deb／L_Deb／**O**） |
| `src/reference/AND1.xml` | AND 元件（`numInputs=1`） |
| `src/reference/NAND1.xml` | NAND（`group_inv`） |
| `src/reference/OR1.xml` | OR 元件 |
| `src/reference/NOR1.xml` | NOR（OR 反相） |
| `src/drawio_export.py` | Shared constants + legacy placement body; `generate_drawio` wrapper |
| `src/drawio_export_options.py` | Wire overlap options |
| `src/drawio_edge_freeze.py` | Export finale: `freeze_edge_routing`, `restore_orthogonal_auto_routing` |
| `tests/test_drawio_y_slack.py` | Y slack unit tests |
| `tests/test_drawio_matrix.py` | FB matrix / gate style / routing；`TestOrDebAlignment`（OR↔Deb） |
| `src/reference/drawio_fb_matrix.json` | OR／NOR 回授矩陣範例 config |
