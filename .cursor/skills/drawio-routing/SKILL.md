---
name: drawio-routing
description: >-
  pwrseq_gen Draw.io edge routing for cell-centric export: all edges use
  orthogonal auto (no frozen waypoints). Covers label→gate→Deb paths, multi-group
  vertical stack to OR, AND tree child→merge lane, Hi/Lo stroke colors, use=hi/lo
  cond labels, export net names, O→output name. Legacy layer-column FB routing
  removed. Use when modifying drawio_cell_export.py wire logic.
---

# Draw.io Edge Routing (pwrseq_gen)

**Single routing mode:** Draw.io **`orthogonalEdgeStyle`** on every edge. No `edgeStyle=none`, no frozen waypoints, no feedback (FB) pass.

| Source | Role |
|--------|------|
| `src/drawio_cell_export.py` | Emit all edges via `_Builder.edge` / `_STYLE_O_OUT` |
| `src/drawio_geometry.py` | Stroke colors, gate entry defaults |

Placement (block grid, gate columns, export wire reserve): [drawio-placement](../drawio-placement/SKILL.md).

Program map: [reference.md](reference.md).

> **Removed (archived):** Old Input→AND→OR→Cell **layer-column** layout with Rule 1/2/3 (input auto / gate frozen stub / FB five-segment). That pipeline and `tests/test_gate_exit_lanes.py` are gone. Do not reintroduce FB constants or `_apply_feedback_routing` unless restoring the legacy exporter.

---

## Orthogonal auto only ★

Every edge:

| Property | Value |
|----------|--------|
| **edgeStyle** | `orthogonalEdgeStyle` |
| **Waypoints** | None (`mxGeometry relative=1` only) |
| **Routing** | Draw.io editor auto-routes at open time |

```python
_STYLE_EDGE = (
    "edgeStyle=orthogonalEdgeStyle;..."
    "exitX=1;exitY=0.5;entryX=0;entryY=0.5;..."
    "strokeColor=%s;..."
)
```

Output port edge (`O` → output name) uses `_STYLE_O_OUT` (`exitX=1;exitY=0.5`, default stroke).

**Test:** `test_edges_use_orthogonal_auto_only` — no `edgeStyle=none` in any edge.

---

## Edge types within one block

### 1. Input / cond label → gate

- **Source:** text label vertex (`_STYLE_LABEL`)
- **Target:** intra-group merge gate or OR-tree child gate
- **Stroke:** `STROKE_DEFAULT` (`#000000`)
- **Anchor:** label right (`exitX=1`) → gate left (`entryX=0`)

Single-input group with no gate: label connects **directly to H_Deb or L_Deb** (see §4).

### 2. Intra-group gate → gate (AND tree)

When `len(terms) ≥ AND_TREE_THRESHOLD` (8):

- **child gate** (left) → **merge gate** (right); stroke `STROKE_DEFAULT`
- left labels → child (`left_label_x = child_gx − GAP − LABEL_W`)
- **right labels → merge** in lane between gates; width `merge_lane_w = _merge_lane_label_w(right_terms)`
- child right → merge left gap = **`_child_merge_channel(right_terms)`** (≥ `GAP + LABEL_W + GAP`, 40pt grid)
- merge input index 0 reserved for child output; right-side label stack uses index **`ii+1`**

Inter-group **OR tree** (≥8 branches): child OR → merge OR at fixed **`2×GAP`** (no label lane).

### 3. Multi-group branch → OR merge → Deb

When `len(parsed_groups) ≥ 2`:

- each group placed at **shared `branch_attach` X**, **stacked vertically** (Hi up / Lo down from group 0 Deb anchor)
- single-input group: label at `branch_attach − LABEL_W` → OR (or via branch gate output)
- multi-input group: branch output (merge AND or single gate) → OR
- OR right edge at `gate_right`; **OR left − branch merge right = `GAP` (40pt)**
- OR output → **H_Deb** / **L_Deb** at group 0 `deb_anchor_y`

| Path | Stroke | Deb target |
|------|--------|------------|
| Hi | `STROKE_HI` (`#ff0000`) | `h_deb_id` |
| Lo | `STROKE_LO` (`#008000`) | `l_deb_id` |

Single-input group in multi-group path: label → OR directly (still at shared branch column X).

Single group total: branch output → Deb directly (same colors).

### 4. Label direct → Deb (no gate)

One term in group → `_wire_and_branch` places label with `label_right = attach_right` (only `GATE_CELL_GAP` before Cell).

Edge: label → Deb, Hi/Lo stroke.

### 5. O → output name

- **Source:** PSEQCELL **O** port inside group
- **Target:** output name text label (right of Cell)
- **Style:** `_STYLE_O_OUT`, orthogonal auto
- **Geometry check:** output label at `cell_x + CELL_O_X + CELL_O_W + GAP`, vertically centered on O

---

## Term resolution (`_resolve_term`)

| Config | Label text | Wired? |
|--------|------------|--------|
| Input GPIO, `use=self` | `NAME` or `~NAME` if inv | Yes, inside block |
| Output GPIO, `use=self` | `NAME` or `~NAME` | Yes |
| `use=hi` / `use=lo` | **`{internal_sig}_{hi\|lo}`** (purple cond HTML) | Yes, but text only — **not** a cross-page wire |
| `use=force` | — | **Skipped** (not drawn) |
| `__HIGH__` / `__LOW__` | — | Skipped |

Purple cond styling: `_cond_html` / `COND_COLOR`.

Consumers reference upstream Hi/Lo **by name on the label**; the upstream cell’s Deb edge may carry the matching purple **export label** (see below).

---

## Export net name (Deb edge label)

When rail `(R, hl)` is in `_exported_hilo_keys` (some other output uses `R` with `use=hl`):

1. Placement reserves `extra` width before Cell (`_export_wire_extra_for_name`)
2. Last edge into Deb gets `value=_export_edge_label("{internal_sig}_{hl}")`

This documents the Verilog-style net name on the wire segment; routing is still orthogonal auto.

---

## What is NOT routed

| Feature | Cell-centric behavior |
|---------|----------------------|
| Q / ~Q feedback | No Q/~Q ports emitted |
| Cross-cell wires | No edges between blocks |
| Force conditions | Terms omitted |
| Frozen stub lanes | Not used |
| FB X channels / slot allocation | Not used |
| Pass 1–3 (NOT rewrite) | Not used |

---

## Emit flow (routing-relevant)

```
_build_cell_block
  → _add_pseqcell_group (H_Deb, L_Deb, O)
  → O → output name edge
  → _wire_path_v2 (hi)
       → _parse_path_group_terms
       → foreach group: anchor_y (vertical stack) + _wire_and_branch(branch_attach)
       → _wire_or_fanin (if multi-group) → H_Deb
  → _wire_path_v2 (lo)  # same pattern → L_Deb
```

No post-pass routing rewrite — XML is final. Placement details: [drawio-placement](../drawio-placement/SKILL.md) § multi-group, § child↔merge channel.

---

## Modification checklist

- [ ] New edge uses `_Builder.edge` or `_STYLE_O_OUT` (orthogonal only)?
- [ ] Hi/Lo paths use `STROKE_HI` / `STROKE_LO` on Deb-bound edges?
- [ ] Single-term path: direct label→Deb without extra `GAP`?
- [ ] `use=hi/lo` stays label text (`is_cond=True`), not a cross-block wire?
- [ ] Export label only when key in `_exported_hilo_keys`?
- [ ] AND tree: right labels use dynamic `w=merge_lane_w`; channel via `_child_merge_channel`?
- [ ] Multi-group: branches wire to OR at `deb_anchor_y`, not per-group Y?
- [ ] `pytest tests/test_drawio_cell.py tests/test_integration.py -q`

## See also

- [reference.md](reference.md) — function index, stroke table
- [drawio-placement](../drawio-placement/SKILL.md) — gate columns, export `extra`, block sizing
