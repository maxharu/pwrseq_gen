---
name: drawio-placement
description: >-
  Documents pwrseq_gen Draw.io placement pipeline in generate_drawio:
  Y/X coordinates for AND/NAND, OR/NOR, Cell rows, input band, gate gaps,
  Y slack (deduped), and wire channel assignment. Use when modifying
  drawio_export.py placement, row spacing, gate columns, fb slack, Cell-Cell
  gap, placement flow, or debugging layout coordinates in power-sequence
  diagrams.
---

# Draw.io Placement (pwrseq_gen)

Placement is **deterministic** and lives in `src/drawio_export.py` → `generate_drawio()`.
All coordinates are computed in export; there is no separate auto-layout engine.

Authoritative rules: `doc/DRAWIO_RULES.md` (§8 X gaps, §10 Y slack).
Routing regimes (**three** rules — input / gate / **FB**): [drawio-routing](../drawio-routing/SKILL.md).
Function map & constants: [reference.md](reference.md).

## Pipeline overview

```
config.rails
  → Phase 0  Pre-scan (inv, output_to_row, and_index_per_key)
  → Phase 1  Y placement (row_y_base, AND/OR chains, input_row_y)
  → Phase 2  X placement (input band, trunks, and_col_x, per-row cell_start_x)
  → Phase 3  Channel alloc (left trunk x)
  → Phase 4  Emit vertices (input → PSEQCELL Q/~Q → AND → OR → edges)
  → Phase 5  Wire routing (_GateExitLanes, waypoints; FB 僅標記)
  → Post-fix NOT (3 passes) + _apply_feedback_routing (Rule 3)
```

Left→right columns: **Input → [trunk] → AND/NAND → OR/NOR (if) → Cell → output name**.

## Phase 0 — Pre-scan

Before any coordinates:

1. Split rails: `input` labels only; `output` → one Power Sequence Cell per rail (config order = top→bottom).
2. Scan `inv` → `inputs_with_not`, `outputs_with_not`.
3. Build `output_to_row`, `and_index_per_key`（列內 nominal Y offset：hi 自 `OR_GATE_OFFSET_HI_Y`、lo 自 `OR_GATE_OFFSET_LO_Y`，同 hl 多顆再 +`AND_GATE_DY`；**非** hi/lo 共用連續 idx）。
4. Compute **Cell row slack** early: `_feedback_y_slack_between_cell_rows` (needed for `row_y_base`).

## Phase 1 — Y axis

Order matters: **Cell rows fixed first**; AND/OR chains may extend below row box but do not move `row_py`.

| Step | Function | Output |
|------|----------|--------|
| Cell row Y | loop in `generate_drawio` | `row_y_base[j]`, `row_heights[j]` |
| AND catalog | `_build_and_catalog` | global AND #1…n |
| OR catalog | `_build_or_catalog` | global OR #1…m |
| AND slack | `_feedback_y_slack_after_and` | gap → 40pt (dedup) |
| OR slack | `_feedback_y_slack_after_or` | gap → 40pt (dedup) |
| AND chain Y | `_chain_and_top_y` | `and_top_y[g]`（offset 為 pt，非 stack index×DY） |
| OR chain Y | `_chain_or_top_y` | `or_top_y[g]`（新列錨定 `row_py+off` 對齊 H/L_Deb；同列 Hi→Lo 同 AND） |

**Cell row spacing formula (normal row):**

```
next_y = y + h + ROW_GAP(80) + cell_row_slack[j]
```

- `h` = `_row_height_for_output(r)` (≥ 80pt; grows with local AND/OR stack).
- If row has **output NOT**: next row starts at NOT bottom + `NOT_STACK_GAP`(20), not `ROW_GAP`.
- **Default Cell–Cell visual gap** (when h=80, no slack): **80pt**.

**Y slack（§10）：** AND／OR 層：相鄰同層 gap +40pt、**去重**（`_mark_y_gap`）。**Input→AND 不計。**

**Cell row slack（FB ③ 段）：** 跨列 Cell **Q／~Q** 回授（`use=self`、來源 output）— 含 **~Q→Deb** 與 **Q→AND** — 僅在 ③ 段 p2y Y 走廊預留（來源列上方 1 格；~Q 可能 2 格）。**同 Cell 的 Q 與 ~Q 各一條走廊（p2y 不同，同 gap 可累加 +40）**；同 profile 多目標扇出去重。**不**沿 src→tgt 整段加寬（④ 走 X 通道）。

**OR／NOR 對齊 H_Deb／L_Deb（與 AND 錨定一致）：**

| hl | `OR_GATE_OFFSET_*_Y` | 對齊 Cell |
|----|----------------------|-----------|
| hi | `OR_GATE_OFFSET_HI_Y` = 0 | H_Deb（`CELL_H_DEB_Y`） |
| lo | `OR_GATE_OFFSET_LO_Y` = 40 | L_Deb（`CELL_L_DEB_Y`） |

`_chain_or_top_y`：**新列**首顆錨定 `row_py + off`；**同列** Hi→Lo 在 `nominal >= tops[g-1] + OR_GATE_H` 時亦用 nominal（否則鍊式下移）。測試：`TestOrDebAlignment`（`drawio_fb_matrix.json`）。

Helpers inside `generate_drawio`: `_and_y_top`, `_or_y_top`, `_row_bottom`.

Input vertical anchor: `_input_row_y(min(row_py))` from topmost Cell (NOT 40pt above per `INPUT_NOT.xml`).

## Phase 2 — X axis

| Region | How x is computed |
|--------|-------------------|
| Input band | `_input_band_width` + `_layout_input_positions` (right→left, 40pt/slot) |
| Trunk zone | `feedback_n × 40` from `_count_feedback_trunks` |
| AND column | `and_col_x` — **fixed** for whole diagram |
| Per-row Cell | `_compute_row_gate_layouts` → `cell_start_x`, optional `or_col_x` |
| Output name | `cell_x + OUTPUT_NAME_GAP` (120pt; 200pt if any output NOT) |

Gate gaps use `_gate_gap_width(n, fb, exempt)` — see DRAWIO_RULES §8.
Structure **A** (no OR): AND→Cell. **B** (has OR): AND→OR→Cell.

Final positions:

```python
positions_out[r] = (row_gate_layout[r].cell_start_x, row_py[j])
positions_in[name] = (ix, input_row_y)
```

## Phase 3 — Channels

- Left: `channel_x_left = post_input_x` (trunk area; input→AND uses label `x+40` bus, not trunk lanes).
- Cross-row: `wire_via_channel` — stub lane `(1+n)×40` → vertical → horizontal to entry (no separate right-side channel x).

## Logic gate components（參考 XML）★

匯出閘元件 style／尺寸以 `src/reference/*1.xml` 為準（**勿**再用 `AND.xml`／`NAND.xml`／`OR.xml`／`NOR.xml`）。

| 閘型 | 參考檔 | style 要點 |
|------|--------|-----------|
| **AND** | `AND1.xml` | `operation=and;numInputs=1;` |
| **NAND** | `NAND1.xml` | `operation=and;negating=1;negSize=0.15;numInputs=1;` |
| **OR** | `OR1.xml` | `operation=or;numInputs=1;` |
| **NOR** | `NOR1.xml` | `operation=or;negating=1;negSize=0.15;numInputs=1;` |

- 幾何：**80×40pt**（`AND_GATE_W`／`AND_GATE_H`）。
- 實作：`_and_gate_style`、`_or_gate_style`（`group_inv`／`_or_output_not` 決定 NAND／NOR）。
- 所有入邊共用唯一輸入錨點 `entryY=0.5`（`_gate_entry_y`／`_GATE_ENTRY_AY`）；多扇入亦接同一點。

## Phase 4–5 — Draw & route

Emit order: input labels (+ input NOT) → PSEQCELL（inner + H/L_Deb + **Q** + **~Q**；RTL `PSEQCELL.v`）+ name → per-row Hi/Lo logic (AND then OR) → edges.

Routing emit: `_GateExitLanes`（非回授）、回授邊只進 `feedback_auto_edge_ids`（waypoints 延後）。**Rule 3** 五段凍結見 [drawio-routing](../drawio-routing/SKILL.md)。

## Post-fix NOT

Three passes after main graph (do not change placement coords):

1. **Pass 1**：`use=hi/lo` 非 inv、且 **source 仍為 H/L_Deb 佔位符**（`exitX=0`）→ 換成上游 logic_out、`exitX=1`、重繞。若 emit 時 logic_out **已存在**（例：下游 Hi 取上游 AND），則 emit 已 `exitX=1`，Pass 1 跳過。
2. **Pass 2**：共用 NOT（output inv 綁 ~Q）。
3. **Pass 3**：inv 邊 source → ~Q。

詳見 [drawio-routing](../drawio-routing/SKILL.md)「`use=hi/lo` 透傳」。

## Modification checklist

When changing placement:

- [ ] Y change affects `row_y_base` **or** chain functions — not both blindly.
- [ ] X change: check `_compute_row_gate_layouts` **and** exempt logic `_count_direct_horizontal_exempts`.
- [ ] New slack rule: add to correct layer function; use `_mark_y_gap` (1-based AND/OR) or direct assign (0-based cell row gap).
- [ ] Run `pytest tests/test_drawio_y_slack.py` + full suite.
- [ ] Update `doc/DRAWIO_RULES.md` if user-visible rules change.
- [ ] 閘 style 變更：對齊 `AND1`／`NAND1`／`OR1`／`NOR1.xml`，勿引用舊 `AND.xml` 等？

## Export finale

See [drawio-routing](../drawio-routing/SKILL.md). Summary:

1. **`_supplement_traced_feedback_edges`** + **`_apply_feedback_routing`** — Rule 3 FB 五段（同 source 同層 1 條 X 通道）
2. **`freeze_edge_routing(root, skip_source_ids=input_auto_src_ids)`** — Rule 2 其餘凍結邊
3. **`restore_orthogonal_auto_routing(root, input_auto_src_ids)`** — Rule 1 input 自動正交
4. **`_apply_feedback_edge_color`** + **`_apply_edge_wire_style`**

佈局 `fb_cell`／`feedback_n` 預留欄寬；走線時 **同一 source 每層只佔 1 slot**（與 `tgt_row` 無關）。

## Common mistakes

| Mistake | Correct approach |
|---------|------------------|
| Expecting Sugiyama / generic graph layout for export | Only `generate_drawio` defines coords |
| Accumulating Y slack per edge on AND/OR | Dedup: one +40pt per gap (`_mark_y_gap`) |
| Treating Cell q/nq as one +40 on same gap | Q／~Q ③ 段各一條走廊；同 gap 可 **stack** +40 |
| OR global chain overrides row_py+off | 新列錨定 nominal；同列 Hi→Lo 同 AND 規則 |
| Counting Input→AND in Y slack | Explicitly excluded |
| Moving Cell rows when AND chain grows | `_chain_and_top_y` pushes AND only; Cell stays at `row_py` |
| Fixed 40pt AND↔Cell gap | Dynamic `n+2+fb-exempt` (§8) |
| `use=hi/lo` 一律 `exitX=0` | 僅 Deb 佔位符左出；logic_out 已存在須 `exitX=1`（AND 右側） |

## Verification

```bash
python -m pytest tests/test_drawio_y_slack.py tests/test_drawio_matrix.py -q
# OR↔Deb：TestOrDebAlignment；Lo AND↔L_Deb：TestLoOnlyAndPlacement
```

Export sample: `run.bat` → inspect `output/*.xml` in Draw.io.

## See also

- [reference.md](reference.md) — constants, function index, slack triggers
- `doc/DRAWIO_RULES.md` — full layout & wire rules
- `.cursor/skills/drawio-routing/` — **edge routing**（Rule 1 input／Rule 2 gate／Rule 3 FB）
