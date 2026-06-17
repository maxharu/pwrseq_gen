---
name: drawio-placement
description: >-
  Documents pwrseq_gen Draw.io placement: (1) cell-centric grid in
  drawio_cell_export.py (default generate_drawio) — per-output blocks,
  Cell 40pt snap, ROW/COL gap, label stack, AND tree, PSEQCELL O port,
  export net-name wire reserve; (2) legacy layer-based
  pipeline in drawio_export.py (archived). Use when modifying cell block
  spacing, BLOCK_PAD, grid columns, gate placement in cell export, or legacy
  row/gate columns / Y slack / fb slack.
---

# Draw.io Placement (pwrseq_gen)

Placement is **deterministic**; there is no separate auto-layout engine.

| Mode | Entry | Source |
|------|-------|--------|
| **Default (active)** | `generate_drawio()` | `src/drawio_cell_export.py` |
| Legacy (archived body) | same name, old impl retained in file | `src/drawio_export.py` (~3500 lines) |

`drawio_export.py` → `generate_drawio()` is a thin wrapper delegating to `drawio_cell_export.generate_drawio`.

Cell export uses **orthogonal auto edges** only (no FB five-segment freeze). Legacy FB／channel rules: [drawio-routing](../drawio-routing/SKILL.md).

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

Loaded at import via `_load_pseqcell_layout()` in `drawio_export.py`.

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
| `CELL_GROUP_W/H` | 80×80 PSEQCELL group (`drawio_export.py`) |
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

**`GRID`** is defined in `src/drawio_export.py` (`GRID = 40`). Cell export imports it; change `BLOCK_PAD` locally rather than global `GRID` unless whole project grid should change.

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

## Legacy layer-based export (archived)

The following documents the **old** columnar layout still present in `drawio_export.py` (not used by default `generate_drawio`). Authoritative rules: `doc/DRAWIO_RULES.md` (§8 X gaps, §10 Y slack).

### Pipeline overview

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
| AND chain Y | `_chain_and_top_y` | `and_top_y[g]`；**新列**錨定 nominal（H/L_Deb）；同列可 chain |
| OR chain Y | `_chain_or_top_y` | `or_top_y[g]`（新列錨定 `row_py+off` 對齊 H/L_Deb；同列 Hi→Lo 同 AND） |

**Cell row spacing formula (normal row):**

```
next_y = y + h + ROW_GAP(40) + cell_row_slack[j]
```

- `h` = `_row_height_for_output(r)`（≥ 80pt；**僅**當同 hl 多顆 AND 堆疊超出 Cell 下緣時才 > 80）。
- Hi／Lo 各一顆 AND（offset 0／40，對齊 H_Deb／L_Deb）落在 80pt Cell 框內 → **不**加列高。
- If row has **output NOT**: next row starts at NOT bottom + `NOT_STACK_GAP`(20), not `ROW_GAP`.
- **Default Cell–Cell visual gap**（h=80、無 slack）：**40pt**。

**列高 `_row_height_for_output`：** 取各 AND／OR 下緣最大值；OR 單顆（`len(groups)≥2`）亦落在 Deb 對齊高度內。

**AND 鍊 `_chain_and_top_y`：** **新列**（`row_j ≠ prev_row`）一律錨定 `row_py + nominal offset`（H/L_Deb 對齊），**不受**前列 global chain 下推。同列多顆 AND 仍依 `nominal` vs `chain` 鍊式下移。

**Y slack（§10）：** AND／OR 層：相鄰同層 gap +40pt、**去重**（`_mark_y_gap`）。**Input→AND 不計。**

**Cell row slack（FB ③ 段）：** 跨列 Cell **Q／~Q** 回授（`use=self`、來源 output）— 僅在**來源 Cell 與上一列 Cell 之間**（gap `src_row−1`）預留 +40pt。**同 Cell 的 Q 與 ~Q 各一條走廊**（profile 不同、同 gap 可累加 +40）；同 profile 多目標扇出去重。**不**再往上一格（`src_row−2`）加寬。

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

**Cell-centric (`drawio_cell_export.py`):**

- [ ] Spacing: `BLOCK_PAD`, `ROW_GAP`, `COL_GAP`, `LABEL_STACK_STEP`, `BLOCK_MIN_H`
- [ ] `block_h` / `row_heights`: `_block_vertical_layout` + per-row `max`
- [ ] `cell_x`/`cell_y`: `_cell_y_in_block`, `_snap_grid` after position calc
- [ ] Block width: `_estimate_block_size`, `_export_wire_extra_for_name`, AND depth; direct-label path skips extra `GAP`
- [ ] PSEQCELL: `_load_pseqcell_layout` / `CELL_O_*`; output edge from O right
- [ ] Run `pytest tests/test_drawio_cell.py`

**Legacy (`drawio_export.py`):**

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
| Hi+Lo 各一 AND 仍把列高算成 160 | 對齊 Deb 時 `_row_height_for_output` 維持 80pt |
| 跨列 AND 被 global chain 下推偏離 Deb | 新列 `_chain_and_top_y` 用 nominal，不用 `max(nominal, chain)` |
| `ROW_GAP` 與 `AND_GATE_DY` 綁死 | `ROW_GAP=40`（列距）；`AND_GATE_DY=80`（同 hl 堆疊） |
| ~Q slack 預留 `src_row−2` | 僅 gap `src_row−1`（來源列正上方一格） |
| Fixed 40pt AND↔Cell gap | Dynamic `n+2+fb-exempt` (§8) |
| Direct label→Deb uses 80pt (GAP+GATE_CELL_GAP) | Single-term branch: `label_right = attach_right` (40pt only) |
| Export `extra` not on 40pt grid | `_snap_grid_up` on `_export_wire_extra_for_name` result |
| `use=hi/lo` 一律 `exitX=0` | 僅 Deb 佔位符左出；logic_out 已存在須 `exitX=1`（AND 右側） |

## Verification

```bash
python -m pytest tests/test_drawio_cell.py -q
# Legacy only:
python -m pytest tests/test_drawio_y_slack.py tests/test_drawio_matrix.py -q
```

Export sample: `run.bat` → inspect `output/*.xml` in Draw.io.

## See also

- [reference.md](reference.md) — constants, function index, slack triggers
- `doc/DRAWIO_RULES.md` — full layout & wire rules
- `.cursor/skills/drawio-routing/` — **edge routing**（Rule 1 input／Rule 2 gate／Rule 3 FB）
