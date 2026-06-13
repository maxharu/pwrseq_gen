# Draw.io Placement Reference

Source of truth: `src/drawio_export.py`, `doc/DRAWIO_RULES.md`.

## Key constants

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
| `CELL_Q_X/Y`, `CELL_NQ_X/Y` | 60/10, 60/50 | Q／~Q 錨（`PSEQCELL.xml`；RTL `PSEQCELL.v`） |
| `FB_Q_RIGHT/UP` | 40, 60 | Q 回授 ①②（routing） |
| `FB_NQ_RIGHT/UP` | 80, 140 | ~Q 回授 ①②（**同 Cell 亦有 Q 回授**；routing） |
| `FB_NQ_UP_NO_Q` | 100 | ~Q 回授 ②（**同 Cell 無 Q 回授**；routing） |
| `OUTPUT_NAME_GAP` | 120 | Cell right → name label |
| `NOT_STACK_GAP` | 20 | Row after output NOT (`INPUT_LABEL_H`) |

## Function index (placement-related)

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

## Output row ordering

- `_topological_order_outputs` then `_barycenter_order_outputs` only reorder **Cell rows** (vertical).
- Does **not** assign AND/OR column X or wire channels; see placement phases above.

## Y slack triggers (§10)

**AND／OR 層：** 相鄰同層 gap 最多 +40pt（**去重**，`_mark_y_gap`）。

**Cell row 層：** ③ 段 p2y 走廊；**僅** gap `src_row−1`；**q 與 nq 不共用** profile 但同 gap 可 **累加** +40。

| Layer | Triggers | Dedup |
|-------|----------|-------|
| **AND/NAND** | Cross-row output → AND input; Input direct to OR/NOR/Cell (`len(group)==1`) | per gap |
| **OR/NOR** | Cross-row output → OR input (OR row, `len(group)==1`); Input direct to Cell; AND direct to Cell (no OR on row) | per gap |
| **Cell rows** | Cross-row Cell Q/~Q `use=self` (→ Deb or AND)；gap = **來源列正上方一格** | per profile; q+nq stack |

**Excluded:** Input → AND (feeds via label x+40 bus).

**demo／power.json 範例（Cell row）：** `{6: 80, 10: 40}`（RSMRST row7：q+nq 同 gap6；PCH_PWROK row11：gap10）。

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
| `and_index_per_key` | `(rail, hl, gi)` → `(row_j, nominal_y_off_pt)` — hi: `OR_GATE_OFFSET_HI_Y`+idx×`AND_GATE_DY`；lo: `OR_GATE_OFFSET_LO_Y`+idx×`AND_GATE_DY` |
| `or_index_per_key` | `(rail, hl)` → `(row_j, nominal_offset_y)` |
| `idx_map` / `or_idx_map` | catalog key → global gate number |
| `row_py` | copy of `row_y_base` (Cell anchor Y) |
| `and_top_y` / `or_top_y` | global gate number → top Y |
| `row_gate_layout` | per rail: `cell_start_x`, `or_col_x`, `has_or` |
| `positions_out` / `positions_in` | final vertex origins |

## Draw order (Phase 4)

1. Input labels (+ input NOT vertices)
2. For each output: inner, H_Deb, L_Deb, Q, ~Q, name label, Q→name edge
3. Per output, Hi then Lo: AND gates → OR (if ≥2 groups) → wires to Deb
4. `_GateExitLanes` — stub lane **n** skips gates with only one horizontal direct output
5. `use=hi/lo` passthrough — emit: logic_out already → `exitX=1`; Deb placeholder → `exitX=0` then Pass 1 swap (see drawio-routing skill)

## Files

| Path | Role |
|------|------|
| `src/reference/PSEQCELL.v` | Power Sequence Cell RTL（`iHi`／`iLo`／`iForce`／`o`） |
| `src/reference/PSEQCELL.xml` | Cell Draw.io 幾何（inner／H_Deb／L_Deb／Q／~Q） |
| `src/reference/AND1.xml` | AND 元件（`numInputs=1`） |
| `src/reference/NAND1.xml` | NAND（`group_inv`） |
| `src/reference/OR1.xml` | OR 元件 |
| `src/reference/NOR1.xml` | NOR（OR 反相） |
| `src/drawio_export.py` | Main placement + export |
| `src/drawio_export_options.py` | Wire overlap options |
| `src/drawio_edge_freeze.py` | Export finale: `freeze_edge_routing`, `restore_orthogonal_auto_routing` |
| `tests/test_drawio_y_slack.py` | Y slack unit tests |
| `tests/test_drawio_matrix.py` | FB matrix / gate style / routing；`TestOrDebAlignment`（OR↔Deb） |
| `src/reference/drawio_fb_matrix.json` | OR／NOR 回授矩陣範例 config |
