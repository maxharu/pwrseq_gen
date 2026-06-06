# Draw.io Placement Reference

Source of truth: `src/drawio_export.py`, `doc/DRAWIO_RULES.md`.

## Key constants

| Constant | Value | Role |
|----------|-------|------|
| `GRID` / `GAP` | 40 | Grid unit; horizontal stub, slack increment |
| `ROW_GAP` | 80 | Default row spacing; AND vertical step; NOT offset X |
| `AND_GATE_W/H` | 80/40 | Gate size（`AND1.xml` 等） |
| `AND_GATE_DY` | 80 | Same-row AND–AND spacing |
| `MARGIN` | 40 | Top/left margin |
| `CELL_GROUP_H/W` | 80 | Cell inner |
| `CELL_Q_X/Y`, `CELL_NQ_X/Y` | 60/10, 60/50 | Q／~Q 錨（PWRCELL.xml） |
| `FB_Q_RIGHT/UP` | 40, 60 | Q 回授 ①②（routing） |
| `FB_NQ_RIGHT/UP` | 80, 140 | ~Q 回授 ①②（routing） |
| `OUTPUT_NAME_GAP` | 120 | Cell right → name label |
| `NOT_STACK_GAP` | 20 | Row after output NOT (`INPUT_LABEL_H`) |

## Function index (placement-related)

| Function | Layer | Purpose |
|----------|-------|---------|
| `_feedback_y_slack_between_cell_rows` | Cell Y | Cross-row `use=self` → Deb; gap j = between row j and j+1 (0-based) |
| `_feedback_y_slack_after_and` | AND Y | Cross-row output→AND; Input direct to OR/NOR/Cell (not AND) |
| `_feedback_y_slack_after_or` | OR Y | Cross-row Cell→OR input; Input/AND direct to Cell |
| `_mark_y_gap` | AND/OR | Dedup +40pt per gap (gap ≥ 1) |
| `_build_and_catalog` | AND | Global AND/NAND order |
| `_build_or_catalog` | OR | Global OR/NOR order (Hi then Lo per row) |
| `_chain_and_top_y` | AND | Chain Y with slack |
| `_chain_or_top_y` | OR | Chain Y; same-row Hi→Lo +40; cross-row +80 + slack |
| `_nearest_and_and_gap` | AND | Map feedback edge → AND–AND gap below |
| `_nearest_or_or_gap` | OR | Map feedback edge → OR–OR gap below |
| `_row_height_for_output` | Cell Y | Min row height from local AND/OR stack |
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

## Output row ordering

- `_topological_order_outputs` then `_barycenter_order_outputs` only reorder **Cell rows** (vertical).
- Does **not** assign AND/OR column X or wire channels; see placement phases above.

## Y slack triggers (§10)

**Dedup:** each gap gets at most one +40pt.

| Layer | Triggers |
|-------|----------|
| **AND/NAND** | Cross-row output → AND input; Input direct to OR/NOR/Cell (`len(group)==1`) |
| **OR/NOR** | Cross-row output → OR input (OR row, `len(group)==1`); Input direct to Cell; AND direct to Cell (no OR on row) |
| **Cell rows** | Cross-row Cell output `use=self` → downstream Deb; all row gaps on path |

**Excluded:** Input → AND (feeds via label x+40 bus).

## X gap formula (§8)

```
segment_pt = max(0, base + 2 + fb - exempt) × 40
```

| Segment | base | fb |
|---------|------|-----|
| AND→Cell | n (AND count) | fb_cell |
| AND→OR | n | fb_or |
| OR→Cell | m (OR count) | fb_cell |

`+2` = GAP on each side of channel (same as Input→AND trunk padding).

## Data structures in generate_drawio

| Name | Content |
|------|---------|
| `output_to_row` | rail name → row index |
| `and_index_per_key` | `(rail, hl, gi)` → `(row_j, and_idx_on_row)` |
| `or_index_per_key` | `(rail, hl)` → `(row_j, nominal_offset_y)` |
| `idx_map` / `or_idx_map` | catalog key → global gate number |
| `row_py` | copy of `row_y_base` (Cell anchor Y) |
| `and_top_y` / `or_top_y` | global gate number → top Y |
| `row_gate_layout` | per rail: `cell_start_x`, `or_col_x`, `has_or` |
| `positions_out` / `positions_in` | final vertex origins |

## Draw order (Phase 4)

1. Input labels (+ input NOT vertices)
2. For each output: inner, H_Deb, L_Deb, O, name label, O→name edge
3. Per output, Hi then Lo: AND gates → OR (if ≥2 groups) → wires to Deb
4. `_GateExitLanes` — stub lane **n** skips gates with only one horizontal direct output
5. `use=hi/lo` passthrough — emit: logic_out already → `exitX=1`; Deb placeholder → `exitX=0` then Pass 1 swap (see drawio-routing skill)

## Files

| Layer | Gaps | Total extra Y |
|-------|------|---------------|
| AND | 8 | 320pt |
| Cell rows | 9 (0–6, 9, 10) | 360pt |
| OR | 0 | (no OR path) |

## Files

| Path | Role |
|------|------|
| `src/reference/AND1.xml` | AND 元件（`numInputs=1`） |
| `src/reference/NAND1.xml` | NAND（`group_inv`） |
| `src/reference/OR1.xml` | OR 元件 |
| `src/reference/NOR1.xml` | NOR（OR 反相） |
| `src/drawio_export.py` | Main placement + export |
| `src/drawio_export_options.py` | Wire overlap options |
| `src/drawio_edge_freeze.py` | Export finale: `freeze_edge_routing`, `restore_orthogonal_auto_routing` |
| `tests/test_drawio_y_slack.py` | Y slack unit tests |
| `tests/test_drawio_matrix.py` | FB matrix / gate style / routing tests |
