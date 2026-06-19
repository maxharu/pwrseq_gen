# Draw.io routing — code map (cell-centric)

## Implementation file

All routing: `src/drawio_cell_export.py`. No separate routing pass.

## Edge styles

| Style var | Used for | Key attrs |
|-----------|----------|-----------|
| `_STYLE_EDGE % stroke` | Label→gate, gate→gate, gate/label→Deb | `orthogonalEdgeStyle`, `exitX=1`, `entryX=0`, `entryY=0.5` |
| `_STYLE_O_OUT` | O → output name | `orthogonalEdgeStyle`, `exitX=1;exitY=0.5` |

Stroke colors (`drawio_geometry.py`):

| Constant | Value | Use |
|----------|-------|-----|
| `STROKE_DEFAULT` | `#000000` | Label→gate, intra-gate, branch→OR |
| `STROKE_HI` | `#ff0000` | Path to H_Deb |
| `STROKE_LO` | `#008000` | Path to L_Deb |

## `_Builder`

| Method | Role |
|--------|------|
| `vertex(...)` | Labels, gates (not PSEQCELL group — that uses manual ET) |
| `edge(src, tgt, stroke=..., value=...)` | Orthogonal auto edge; optional HTML `value` (export label) |

## Wire functions

| Function | Topology |
|----------|----------|
| `_wire_path_v2` | Parse terms → vertical multi-group stack → `_wire_and_branch` each → `_wire_or_fanin`? → Deb |
| `_wire_and_branch` | 1 term: label→Deb/OR; 2–7: one gate; ≥8: child→merge + merge-lane labels |
| `_wire_or_fanin` | 1 branch: direct Deb; 2–7: one OR; ≥8: child OR→merge OR/NOR |
| `_parse_path_group_terms` | Config groups → filtered `list[list[_Term]]` |
| `_resolve_term` | Build label text; `use=hi/lo` → purple cond name |
| `_export_edge_label` | HTML for Deb edge export net name |

## Placement helpers used by routing (same file)

| Function | Routing impact |
|----------|----------------|
| `_group_branch_attach_right` | Shared X for all group branch outputs |
| `_group_vertical_extents` | Per-group anchor Y when stacking |
| `_merge_lane_label_w` | Right-label width in AND tree |
| `_child_merge_channel` | child→merge edge horizontal clearance |
| `_add_term_label(..., w=merge_lane_w)` | Wider label vertex for long merge-side names |

## Cross-block / feedback (not implemented)

The following existed in the **removed** layer-column exporter (`drawio_export.py` legacy). **Do not document as active:**

- `feedback_auto_edge_ids`, `_apply_feedback_routing`
- `FB_Q_RIGHT`, `FB_NQ_UP`, `_first_clear_up_y`
- `_GateExitLanes`, `wire_via_channel`, `freeze_edge_routing`
- Q / ~Q ports, Pass 1–3 NOT rewrite

Scripts `scripts/enumerate_feedback.py` / `scripts/list_feedback_paths.py` (if present) target the old layout only.

## Tests

| Test file | Asserts |
|-----------|---------|
| `tests/test_drawio_cell.py` | Orthogonal only, O exit, label gaps, export wire reserve, AND tree, multi-group stack, child-merge channel, declaration order |
| `tests/test_integration.py` | `test_cell_centric_drawio_from_demo` — all edges orthogonal |

Notable tests:

| Test | Covers |
|------|--------|
| `test_two_level_and_tree_for_many_inputs` | child→merge topology |
| `test_child_merge_channel_on_40pt_grid` | channel snap + label width |
| `test_and_tree_child_merge_gap_fits_long_merge_labels` | long merge-side names |
| `test_multi_group_vertical_stack_same_gate_x` | shared X + OR GAP + vertical stack |

Run:

```bash
python -m pytest tests/test_drawio_cell.py tests/test_integration.py -q
```

## Related placement (not routing)

Export wire **width reserve** and gate column layout are placement (`_export_wire_extra_for_name`, `_path_horizontal_gate_width`, `_child_merge_channel`); routing only emits edges with orthogonal auto.

See [drawio-placement/reference.md](../drawio-placement/reference.md).
