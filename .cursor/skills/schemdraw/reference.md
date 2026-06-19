# Schemdraw Reference (pwrseq_gen)

## Public API (`schemdraw_export.py`)

```python
generate_schemdraw_doc(
    config, scenario=None, *,
    output_filename=None,
    include_rails: frozenset[str] | None = None,
    edge_kinds: frozenset[str] | None = None,
) -> dict

render_schemdraw(doc: dict, output_path: str) -> None  # .svg | .png | .pdf

render_schemdraw_png_bytes(doc: dict, *, dpi=96) -> bytes

export_schemdraw(config, scenario=None, *, output_filename, include_rails=..., edge_kinds=...)

export_schemdraw_from_options(config, scenario, options: WaveDromExportOptions, output_filename)

build_schemdraw_extended_edges(signals: list[dict], pending: list[ConditionEdgePending]) -> list[str]

schemdraw_edges_forward_in_time(doc: dict) -> list[tuple[str, int, str, int]]
```

## Extended edge construction

`ConditionEdgePending` tuple (from `wavedrom_export`):

```
(dep_step, out_step, dep_lane, out_lane, kind)
```

`build_schemdraw_extended_edges` maps lane dict → index in exported `signals`:

```python
edges.append(f"[{dsi}:{dep_step}]-~>[{osi}:{out_step}]")
```

`dep_step` / `out_step` are **simulation step indices** (int), not wave-string character positions.

## WaveDrom node path (do not use for Schemdraw)

WaveDrom export assigns single-character nodes per `(lane, wave index)` and emits:

```
A-~>a
```

When >52 endpoints collide (e.g. duplicate `z`), `_node_locations()` keeps last mapping → arrows can point backward in time. Schemdraw avoids this entirely.

## Dual labels (`_TimingDiagramDualLabels`)

1. `logic.TimingDiagram.from_json(wavejson_str)` — left names (built-in)
2. Append `SegmentText` at `x = periods * 2 * yheight * hscale` for each flat lane — right names

Right labels use same `fontsize` / `namecolor` as left.

## Render backends

```python
# File export
if ext in {".png", ".pdf"}:
    schemdraw.use("matplotlib")  # ImportError if matplotlib missing

with Drawing(file=path, show=False) as d:
    _TimingDiagramDualLabels.from_json(json.dumps(doc))

# Preview bytes (PNG via matplotlib default canvas)
with Drawing(show=False) as d:
    _TimingDiagramDualLabels.from_json(json.dumps(doc))
    d.draw(show=False)
    return d.get_imagedata("png")
```

## GUI state (`PowerSeqGUI`)

| Attribute | Purpose |
|-----------|---------|
| `_schemdraw_preview_opts` | Last `WaveDromExportOptions` from Nodes dialog |
| `_schemdraw_preview_after_id` | Debounce timer for preview refresh |
| `_schemdraw_render_gen` | Drop stale background render results |

Preview render thread calls `generate_schemdraw_doc` + `render_schemdraw_png_bytes`; main thread applies via `_apply_schemdraw_preview(gen, ...)`.

## Dependencies

```
schemdraw>=0.19
Pillow>=10.0.0      # Preview display
matplotlib>=3.7.0   # PNG/PDF export only
```

## Tests (`tests/test_schemdraw_export.py`)

| Test | Asserts |
|------|---------|
| `test_build_schemdraw_extended_edges_uses_sim_steps` | `[0:0]-~>[1:1]` from pending |
| `test_node_collision_json_has_backward_edges_via_old_mapping` | WaveDrom JSON has backward edges via old node map; documents why Schemdraw differs |
| `test_dual_labels_add_right_side_signal_names` | Right-side `SegmentText` count |
| `test_render_schemdraw_png_bytes` | Non-trivial PNG |
| `test_render_schemdraw_pdf` | Valid `%PDF` header |
| `test_generate_schemdraw_doc_edges_never_go_backward_in_time` | No backward extended edges on demo config |
