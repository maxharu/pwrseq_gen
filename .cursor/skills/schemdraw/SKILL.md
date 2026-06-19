---
name: schemdraw
description: >-
  pwrseq_gen Schemdraw timing export and GUI preview: extended edges from sim
  steps (not single-char node letters), dual lane labels, SVG/PNG/PDF render,
  Preview panel canvas navigation, and Export using Preview node/arrow settings.
  Use when modifying schemdraw_export.py, Schemdraw Preview/Export in gui.py,
  or debugging backward condition arrows on large diagrams.
---

# Schemdraw Timing Export (pwrseq_gen)

Schemdraw renders **WaveJSON-shaped** docs via `schemdraw.logic.TimingDiagram`.
Same simulation + lane building as the shared timing export helpers; **extended edge notation** and Schemdraw render path.

## Design

| Topic | Legacy node-letter export (removed) | Schemdraw export |
|-------|-------------------------------------|------------------|
| Condition arrows | Single-char `node` + `A-~>a` | Extended `[lane:step]-~>[lane:step]` |
| Large diagrams | Node pool exhausts (`z` collisions → wrong arrows) | No node letters; sim step indices |
| Output | `.json` for wavedrom.com | `.svg` / `.png` / `.pdf` |
| Signal names | Left only (Schemdraw default) | Left + right (`_TimingDiagramDualLabels`) |

**Do not** build Schemdraw edges via node-letter remap. Always use
`build_schemdraw_extended_edges()` from `_collect_condition_edge_pending()`.

## Module map

| File | Role |
|------|------|
| `src/schemdraw_export.py` | Doc generation, render, export API |
| `src/wavedrom_export.py` | Shared: `_build_export_lanes`, `_collect_condition_edge_pending`, `TimingExportOptions` |
| `src/wavedrom_sim.py` | `simulate()`, scenario, step indices for edges |
| `src/gui.py` | `PreviewPanel` (Schemdraw mode), `TimingNodeSelectDialog`, export menu |
| `tests/test_schemdraw_export.py` | Extended edges, dual labels, PDF/PNG render |

## Pipeline

```
PowerSeqConfig + WaveDromScenario
  → simulate()
  → _build_export_lanes(include_rails?)
  → _collect_condition_edge_pending(edge_kinds?)
  → build_schemdraw_extended_edges()   # [dsi:dep_step]-~>[osi:out_step]
  → generate_schemdraw_doc()           # WaveJSON dict, no node fields
  → _TimingDiagramDualLabels.from_json()
  → render_schemdraw(path) | render_schemdraw_png_bytes()
```

## Extended edge format

```
[lane_index:period_index]-~>[lane_index:period_index]
```

- `lane_index`: index in exported `signal[]` (after `include_rails` filter)
- `period_index`: **simulation step** where the GPIO transition occurs (same as pending tuple from export)
- Curve style: `-~>` (Schemdraw C-curve); do not use `<->` (renders bidirectional straight line)

Regression: `schemdraw_edges_forward_in_time(doc)` must be `[]` (no backward-in-time edges).

## Render rules

| Extension | Backend | Notes |
|-----------|---------|-------|
| `.svg` | Schemdraw default (SVG) | No matplotlib required |
| `.png`, `.pdf` | `schemdraw.use("matplotlib")` | Requires `matplotlib` in `requirements.txt` |

**Always** use `Drawing(..., show=False)` when saving files from a CustomTkinter app.
Default `show=True` triggers `fig.show()` on context exit → `main thread is not in mainloop`.

Preview PNG: `render_schemdraw_png_bytes()` → background thread in GUI → `PreviewPanel.set_schemdraw_image()`.

## GUI: Preview (Schemdraw)

Language selector: **Schemdraw** in `PreviewPanel`.

| Control | Behavior |
|---------|----------|
| **Steps / hscale** | Simulation length and horizontal scale; saved in `wavedrom_scenario`; shown only in Schemdraw mode |
| **Nodes…** | `TimingNodeSelectDialog` → `_schemdraw_preview_opts` (`TimingExportOptions`); Apply does not close |
| **Refresh** | Debounced render (600 ms); uses preview options |
| **Zoom −/+ / Fit** | Scale displayed PNG; Fit = fit viewport width |
| **Drag** | Canvas pan (`scan_mark` / `scan_dragto`) |
| **Wheel** | Vertical scroll |
| **Shift+Wheel** | Horizontal scroll |
| **Ctrl+Wheel** | Zoom |

Canvas: `tk.Canvas` + scrollbars (not `CTkScrollableFrame`). Background via `_resolve_canvas_bg()`.

Initial preview opts: all exportable rails, `WAVEDROM_EDGE_BOTH`.

## GUI: Export

**Export → Schemdraw** (Ctrl+Shift+E or export menu):

- **No** Select Nodes dialog — uses `_schemdraw_preview_options(cfg)` (Preview settings)
- Save dialog: SVG / PNG / PDF
- Warn if Preview has zero selected lanes

## Node select dialog (Preview)

`TimingNodeSelectDialog` in `gui.py`.

- **Shift+Click**: Explorer-style range (anchor = last normal click, or index 0 if none); anchor unchanged on Shift
- **Normal click**: toggle + set anchor
- **Search filter**: forget all rows → repack visible in original order (avoid pack order bug)
- **CTkCheckBox clicks**: bind `cb._canvas` + `cb._text_label` only; **no** `command=` (prevents double-toggle / shift lag)

Multi-select pattern: see personal skill `explorer-checkbox-multiselect` for portable helper.

## Shared options (`TimingExportOptions`)

```python
TimingExportOptions(
    include_rails=frozenset({"VDD", "RESET", ...}),  # rail.name, not port
    edge_kinds=TIMING_EDGE_BOTH,  # or HI_ONLY / LO_ONLY
)
```

Simulation always uses **full** config; only diagram lanes and arrow kinds are filtered.

## Agent workflow

1. Changing waves/lanes/edges → edit `wavedrom_export` shared helpers or `schemdraw_export.build_schemdraw_extended_edges`; run `tests/test_schemdraw_export.py`.
2. Changing render/labels → `_TimingDiagramDualLabels` in `schemdraw_export.py`.
3. Changing Preview UX → `PreviewPanel` + `PowerSeqGUI._start_schemdraw_preview` in `gui.py`.
4. Backward arrow bug on large design → verify extended edges (not node letters); run `test_generate_schemdraw_doc_edges_never_go_backward_in_time`.
5. WaveJSON wave/head/foot semantics → Schemdraw uses the same WaveJSON lane shape (without `node` fields).

## Validation checklist

- [ ] `doc["edge"]` entries match `^\[\d+:\d+\]-~>\[\d+:\d+\]$`
- [ ] No `node` keys on `signal[]` lanes in Schemdraw doc
- [ ] `schemdraw_edges_forward_in_time(doc) == []`
- [ ] PDF/PNG export uses `show=False`
- [ ] Export respects Preview `include_rails` + `edge_kinds`

## Additional resources

- Extended edges, API signatures: [reference.md](reference.md)
- Code snippets and GUI flows: [examples.md](examples.md)
