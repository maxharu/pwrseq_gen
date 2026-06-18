---
name: excel-template
description: >-
  Builds and maintains pwrseq_gen Excel node import template (v5 long-table
  Output/Input conditions, Lists dropdowns, VBA sync button). Use when modifying
  generate_excel_template.py, excel_import.py, excel_export.py,
  excel_template_layout.py, templates/powerseq_nodes_template.xlsm, VBA in
  templates/vba/, embed_excel_vba.py, inject_vba_zip.py, Output/Input Conditions
  layout, SignalList, or PowerSeqConfig Excel round-trip.
---

# Excel Template (pwrseq_gen)

Node import workbook for non-expert users. **openpyxl** builds sheet structure;
**VBA** provides manual sync via button (no auto-sync on edit).

**Import / export:** `src/excel_import.py` → `PowerSeqConfig`; `src/excel_export.py` ← config.
GUI **Open** / **Save As** use `.xlsx` / `.xlsm`.

Target output: `templates/powerseq_nodes_template.xlsm` (fallback: `powerseq_nodes_template.xlsx`)

## Pipeline

```
scripts/generate_excel_template.py
  → openpyxl: Instructions / Config / Nodes / Output Conditions / Input Conditions / Lists / Field Reference
  → save TMP xlsx
  → inject_vba_zip (templates/vba/vbaProject.bin) OR embed_excel_vba (COM)
  → add_sync_button_inplace (Nodes top-right, caption "Sync Conditions")
  → powerseq_nodes_template.xlsm
```

Regenerate:

```bash
python scripts/generate_excel_template.py
```

Full detail: [reference.md](reference.md)

## Workbook layout

Sheets are detected by **row-1 column-A key** (same in Python `_find_sheet` and VBA `SetSheetRefs`) — not by localized sheet tab title.

| Sheet tab | A1 key | Role |
|-----------|--------|------|
| Instructions | — | User instructions |
| Config | `key` | `module_name`, `pulses`, defaults, `wavedrom_steps`, `wavedrom_hscale` |
| **Nodes** | `name` | Main: one row per node; row order = system order |
| **Output Conditions** | `output_name` | Long table: one row = one AND/OR/XOR group (Verilog + Draw.io) |
| **Input Conditions** | `input_name` | WaveDrom Input Hi/Lo only (not Verilog) |
| Lists | — | Hidden; `SignalList`, `PulseList` defined names |
| Field Reference | — | key / label / hint reference |

Data rows start at **row 4** (`DATA_START_ROW` in `excel_import.py`).

### Nodes (10 columns)

`name`, `type`, `cycle_hi`, `cycle_lo`, `cycle_force`, `init`, `force_val`, `pulse_hi`, `pulse_lo`, `pulse_timing`

- Dropdowns: `type` (Input/Output), `init`/`force_val` (0/1), pulses from `=PulseList`
- Input: `cycle_*` → debounce; `init` → DEB INIT; `pulse_timing` → Pulse_Deb
- Output: `cycle_*` → CYCLE; `force_val`; `pulse_timing` → Pulse_Force
- Header rows 1–3 shared via `src/excel_template_layout.py` (`node_sheet_headers`, `apply_nodes_sheet_header_rows`)

### Output Conditions (long table)

| Col | Field | Dropdown |
|-----|-------|----------|
| A | `output_name` | — (merged per Output block) |
| B | `cond_type` | Hi, Lo, Force |
| C | `operation` | AND, OR, XOR (intra-group) |
| D | `group_inv` | Y, N (blank → N) |
| E+ | `signal*` | `=SignalList` |

Rules:

- **Same row, multiple signals** → combined by `operation` (AND/OR/XOR)
- **Same output + same cond_type, multiple rows** → OR between groups
- **`!` prefix** on signal → per-item invert
- **`NAME`** only → GUI `use=self` (Node)
- **`NAME|Hi Cond`**, **`|Lo Cond`**, **`|Force Cond`** → GUI use dropdown (Output only in Lists)
- Signal columns: 8 initial, validation to col 52; user may insert columns and copy validation
- Legacy: col C = `group_inv` only (no Operation) still parses as AND + group inv

Maps to `PowerRail.depends_on_*_groups`, `*_intra_op`, `*_group_inv` via `load_powerseq_from_excel`.

### Input Conditions (WaveDrom only)

| Col | Field | Dropdown |
|-----|-------|----------|
| A | `input_name` | — (merged per Input block) |
| B | `cond_side` | Hi, Lo |
| C | `mode` | Low (0), High (1), Custom wave, Signal cond. |
| D | `wave` | Custom wave pattern (see wavedrom skill) |
| E | `operation` | AND, OR, XOR |
| F | `group_inv` | Y, N |
| G+ | `signal*` | `=SignalList` (Signal cond. mode) |

- Hi default after sync: Signal cond.; Lo default: Low (0)
- `load_wavedrom_scenario_from_excel()` reads this sheet + Config `wavedrom_*`
- Import embeds specs on input rails via `apply_input_wave_dict`

### Lists / SignalList

Built by `build_signal_dropdown_entries()` (Python template + VBA sync):

1. `High`, `Low`
2. Each node name + `!{name}` (invert shorthand for dropdown)
3. For each Output: `{name}|Hi Cond`, `|Lo Cond`, `|Force Cond`
4. Extras still referenced in condition sheets (e.g. `RSMRST_N`)

## VBA sync (manual only)

- **Button**: Nodes sheet, `btnSyncOutput`, caption **`Sync Conditions`**
- **Macro**: `RequestSyncFromNodes`
- **No** `Workbook_Open` / `Worksheet_Change` auto-sync

On button press (order in `PwrSeqSync.bas`):

1. **SyncPulseListFromConfig** — rebuild `PulseList` from Config `pulses`
2. **SyncOutputConditions** — per Output: ≥1 Hi + Lo + Force row; preserve extra rows/signals; merge col A
3. **SyncInputConditions** — per Input: ≥1 Hi + Lo row; defaults above; merge col A
4. **SyncListsNodeNames** — rebuild `SignalList` (presets, nodes, `!name`, output use suffixes, orphan refs from both cond sheets)

VBA sources: `templates/vba/PwrSeqSync.bas`, `ThisWorkbook.cls`, `SheetNodes.cls` (empty events)

**VBA sheet detection**: Use English header keys in row 1 (`name`, `output_name`, `input_name`) — **never** hard-code Chinese sheet tab names in VBA.

## Python import / export

| Module | Entry | Role |
|--------|-------|------|
| `excel_import.py` | `load_powerseq_from_excel(path)` | Full `PowerSeqConfig` |
| `excel_import.py` | `load_wavedrom_scenario_from_excel(path)` | `WaveDromScenario` from Input Conditions |
| `excel_import.py` | `parse_signal_cell`, `build_signal_dropdown_entries` | Shared signal parsing / Lists |
| `excel_export.py` | `export_powerseq_to_excel(config, path)` | Write config into template workbook |
| `group_logic.py` | `parse_intra_op_cell`, `intra_op_label` | AND/OR/XOR ↔ labels |

Tests: `tests/test_excel_import.py`, `tests/test_excel_export.py`

## When changing the template

### Python-only (structure, styles, sample data, validations)

1. Edit `scripts/generate_excel_template.py` (`NODE_ROWS`, `COND_ROWS`, `INPUT_COND_ROWS`, `CONFIG_ROWS`, headers, `_add_validations`, `INSTRUCTIONS`)
2. If Nodes header changes, update `src/excel_template_layout.py`
3. Keep `excel_import.py` constants in sync (`COND_META_COLS`, `INPUT_META_COLS`, etc.)
4. Run `python scripts/generate_excel_template.py`
5. If only openpyxl changed and VBA unchanged, zip inject + button COM step is enough

### VBA logic changes

1. Edit `templates/vba/*.bas` / `*.cls`
2. Rebuild `vbaProject.bin` via Excel COM (required once per VBA change):

```bash
# Excel must be installed; Trust Center → Trust access to VBA project object model
python scripts/embed_excel_vba.py templates/_powerseq_nodes_template_build.xlsx templates/powerseq_nodes_template.xlsm
```

3. Commit updated `templates/vba/vbaProject.bin` so CI/headless runs can zip-inject without Excel

### Refresh VBA on user's existing xlsm (keep their data)

```bash
python -c "from scripts.embed_excel_vba import refresh_vba_inplace; refresh_vba_inplace('templates/powerseq_nodes_template.xlsm')"
```

## Verification checklist

After rebuild:

- [ ] `templates/powerseq_nodes_template.xlsm` opens; **Enable Content** enables macros
- [ ] Nodes has **Sync Conditions** button (top-right)
- [ ] Alt+F8 lists `RequestSyncFromNodes`
- [ ] Press button: each Output gets Hi/Lo/Force rows; each Input gets Hi/Lo rows; Lists updated
- [ ] `python -m pytest tests/test_excel_import.py tests/test_excel_export.py -q` passes

Quick COM smoke test (Windows + Excel):

```python
import win32com.client, os
p = os.path.abspath("templates/powerseq_nodes_template.xlsm")
xl = win32com.client.DispatchEx("Excel.Application")
wb = xl.Workbooks.Open(p)
xl.Run("RequestSyncFromNodes")
wb.Close(SaveChanges=False)
xl.Quit()
```

## Common failures

| Symptom | Fix |
|---------|-----|
| PermissionError on save | Close Excel holding the xlsm |
| VBA embed fails, only `.xlsx` | Install `pywin32`, enable AccessVBOM, rerun generate |
| Button missing | `add_sync_button_inplace` failed; rerun generate with Excel closed |
| Sync does nothing | Macros disabled; Enable Content |
| Sheet not found on import | Row-1 key missing/wrong; match `name` / `output_name` / `input_name` |
| Chinese sheet names in VBA | Use `SetSheetRefs()` row-1 key lookup, not `Worksheets("…")` |

## Related code

- Data model: `PowerRail` / `PowerSeqConfig` in `src/config_models.py`
- GUI use labels: `USE_LABELS` in `src/gui.py` (`Node`, `Hi Cond`, `Lo Cond`, `Force Cond`)
- WaveDrom scenario from Excel: `.cursor/skills/wavedrom/SKILL.md`
