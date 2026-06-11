---
name: excel-template
description: >-
  Builds and maintains pwrseq_gen Excel node import template (v5 long-table
  Output conditions, Lists dropdowns, VBA sync button). Use when modifying
  generate_excel_template.py, templates/powerseq_nodes_template.xlsm, VBA
  in templates/vba/, embed_excel_vba.py, inject_vba_zip.py, Output條件 sheet
  layout, SignalList, or excel2json import spec.
---

# Excel Template (pwrseq_gen)

Node import workbook for non-expert users. **openpyxl** builds sheet structure;
**VBA** provides manual sync via button (no auto-sync on edit).

Target output: `templates/powerseq_nodes_template.xlsm`

## Pipeline

```
scripts/generate_excel_template.py
  → openpyxl: 說明 / Config / 節點清單 / Output條件 / Lists / 欄位說明
  → save TMP xlsx
  → inject_vba_zip (templates/vba/vbaProject.bin) OR embed_excel_vba (COM)
  → add_sync_button_inplace (節點清單右上角)
  → powerseq_nodes_template.xlsm
```

Regenerate:

```bash
python scripts/generate_excel_template.py
```

Full detail: [reference.md](reference.md)

## Workbook layout (v5)

| Sheet | Role |
|-------|------|
| 說明 | User instructions |
| Config | `module_name`, `pulses`, `default_*` |
| **節點清單** | Main: one row per node; row order = system order |
| **Output條件** | Long table: one row = one AND group |
| Lists | Hidden; `SignalList` defined name for dropdowns |
| 欄位說明 | key / label / hint reference |

Data rows start at **row 4** (`DATA_START_ROW`).

### 節點清單 (10 columns)

`name`, `type`, `cycle_hi`, `cycle_lo`, `cycle_force`, `init`, `force_val`, `pulse_hi`, `pulse_lo`, `pulse_timing`

- Dropdowns: `type` (Input/Output), `init`/`force_val` (0/1), pulses from Config
- Output vs Input semantics documented in row 3 hints

### Output條件 (long table)

| Col | Field | Dropdown |
|-----|-------|----------|
| A | `output_name` | — (merged per Output block) |
| B | `cond_type` | Hi, Lo, Force |
| C | `group_inv` | Y, N (blank → N) |
| D+ | `signal*` | `=SignalList` |

Rules:

- **Same row, multiple signals** → AND
- **Same output + same cond_type, multiple rows** → OR
- **`!` prefix** on signal → per-item invert
- **`NAME`** only → GUI `use=self` (Node)
- **`NAME|Hi Cond`**, **`|Lo Cond`**, **`|Force Cond`** → GUI use dropdown (Output only in Lists)
- Signal columns: 8 initial, validation to col 52; user may insert columns and copy validation

Maps to `PowerRail.depends_on_*_groups` in `src/config_models.py` (excel2json not yet implemented).

## VBA sync (manual only)

- **Button**: `節點清單` sheet, `btnSyncOutput`, caption `Sync Output Conditions`
- **Macro**: `RequestSyncFromNodes` → `SyncOutputConditions` + `SyncListsNodeNames`
- **No** `Workbook_Open` / `Worksheet_Change` auto-sync

On button press:

1. **Output條件**: For each Output in 節點清單 (in order), ensure ≥1 Hi + 1 Lo + 1 Force row; preserve extra rows and signal data by name; merge col A per block
2. **Lists**: Rebuild from presets + all node names + Output `|Hi/Lo/Force Cond` variants + signals still referenced in Output條件

VBA sources: `templates/vba/PwrSeqSync.bas`, `ThisWorkbook.cls`, `SheetNodes.cls` (empty events)

**VBA sheet detection**: Use English header keys (`name`, `output_name`) in row 1 — **never** Chinese sheet-name constants in VBA (encoding breaks on import).

## When changing the template

### Python-only (structure, styles, sample data, validations)

1. Edit `scripts/generate_excel_template.py` (`NODE_ROWS`, `COND_ROWS`, `CONFIG_ROWS`, `_cond_headers`, `_add_validations`, `INSTRUCTIONS`)
2. Run `python scripts/generate_excel_template.py`
3. If only openpyxl changed and VBA unchanged, zip inject + button COM step is enough

### VBA logic changes

1. Edit `templates/vba/*.bas` / `*.cls`
2. Rebuild `vbaProject.bin` via Excel COM (required once per VBA change):

```bash
# Excel must be installed; Trust Center → Trust access to VBA project object model
python scripts/embed_excel_vba.py templates/_powerseq_nodes_template_build.xlsx templates/powerseq_nodes_template.xlsm
# Or run full generate after building xlsx; then extract bin from xlsm xl/vbaProject.bin
```

3. Commit updated `templates/vba/vbaProject.bin` so CI/headless runs can zip-inject without Excel

### Refresh VBA on user's existing xlsm (keep their data)

```bash
python -c "from scripts.embed_excel_vba import refresh_vba_inplace; refresh_vba_inplace('templates/powerseq_nodes_template.xlsm')"
```

## Verification checklist

After rebuild:

- [ ] `templates/powerseq_nodes_template.xlsm` opens; **Enable Content** enables macros
- [ ] `節點清單` has **Sync Output Conditions** button (top-right)
- [ ] Alt+F8 lists `RequestSyncFromNodes`
- [ ] Press button: each Output gets 3 cond rows; Lists has presets + nodes + `NAME|Hi Cond` etc.
- [ ] Removed node disappears from Lists after sync; cond-only orphan refs may remain if still in signal cells

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
| Chinese sheet names in VBA | Use `SetSheetRefs()` row-1 key lookup, not `Worksheets("節點清單")` |

## Related code (not in template yet)

- Import target: `PowerSeqConfig` / `PowerRail` in `src/config_models.py`
- GUI use labels: `USE_LABELS` in `src/gui.py` (`Node`, `Hi Cond`, `Lo Cond`, `Force Cond`)
