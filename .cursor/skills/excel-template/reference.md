# Excel Template — Reference

## File map

| Path | Purpose |
|------|---------|
| `scripts/generate_excel_template.py` | Main builder: sheets, validations, sample rows, orchestration |
| `src/excel_import.py` | Load `PowerSeqConfig` / `WaveDromScenario`; shared constants & signal parsing |
| `src/excel_export.py` | Export config back to workbook; preserves VBA via golden xlsm or zip inject |
| `src/excel_template_layout.py` | Shared Nodes sheet header rows 1–3 |
| `src/group_logic.py` | AND/OR/XOR labels ↔ internal ops; legacy group_inv detection |
| `scripts/embed_excel_vba.py` | COM: import VBA modules, add sync button, `refresh_vba_inplace` |
| `scripts/inject_vba_zip.py` | Merge `vbaProject.bin` into xlsx → xlsm without Excel |
| `scripts/rebuild_vba_project.py` | Helper to refresh bin after VBA edits (wraps generate + COM) |
| `templates/powerseq_nodes_template.xlsm` | Shipped template (macros) |
| `templates/powerseq_nodes_template.xlsx` | Fallback when VBA embed fails (import/export still work) |
| `templates/vba/PwrSeqSync.bas` | Sync logic module |
| `templates/vba/ThisWorkbook.cls` | Empty (no auto events) |
| `templates/vba/SheetNodes.cls` | Empty (no sheet events) |
| `templates/vba/vbaProject.bin` | Precompiled VBA for zip inject |

## Key constants

Shared between `generate_excel_template.py` and `excel_import.py`:

```python
DATA_START_ROW = 4
COND_META_COLS = 4          # output_name, cond_type, operation, group_inv
INPUT_META_COLS = 6         # input_name, cond_side, mode, wave, operation, group_inv
COND_SIGNAL_MAX_COLS = 49   # validation width
INPUT_COND_SIGNAL_MAX_COLS = 49
NODES_MAX_COL = 10
```

Sheet tabs (English) and A1 detection keys:

| Tab | A1 key |
|-----|--------|
| Config | `key` |
| Nodes | `name` |
| Output Conditions | `output_name` |
| Input Conditions | `input_name` |

```python
SIGNAL_PRESETS = ("High", "Low")   # import also accepts 固定為高/低 aliases
OUTPUT_USE_SUFFIXES = ("|Hi Cond", "|Lo Cond", "|Force Cond")
```

Sample data arrays: `NODE_ROWS`, `COND_ROWS`, `INPUT_COND_ROWS`, `CONFIG_ROWS`.

## Defined names

| Name | Refers to |
|------|-----------|
| `SignalList` | `Lists!$A$2:$A$n` (rebuilt by VBA sync + export) |
| `PulseList` | `Lists!$B$2:$B$n` (from Config `pulses`) |

## VBA public API

| Sub/Function | Role |
|--------------|------|
| `RequestSyncFromNodes` | Entry point (button + Alt+F8) |
| `SyncPulseListFromConfig` | Rebuild PulseList from Config |
| `SyncOutputConditions` | Rebuild Output Conditions rows |
| `SyncInputConditions` | Rebuild Input Conditions rows |
| `SyncListsNodeNames` | Rebuild Lists column A + update `SignalList` |
| `SetSheetRefs` | Resolve sheets by row-1 key `name` / `output_name` / `input_name` |
| `IsSyncInProgress` | Reentrancy guard |

Button: `btnSyncOutput`, caption **`Sync Conditions`** (`embed_excel_vba.py`).

### SyncOutputConditions algorithm

1. Scan existing Output Conditions; group rows by resolved `output_name` (inherit blank col A)
2. Collect Outputs from Nodes col A where col B = `Output`
3. Clear data area; for each Output in node order:
   - Load saved row groups; ensure at least one Hi, Lo, Force template row
   - Sort rows: all Hi, then Lo, then Force
   - Write block; merge column A

### SyncInputConditions algorithm

1. Same pattern for Inputs; ensure Hi + Lo rows per input
2. Hi default mode: Signal cond.; Lo default: Low (0)
3. Sort rows: Hi then Lo; merge column A

### SyncListsNodeNames algorithm

1. Save presets `High`/`Low` from `Lists!A2:A3` before clear
2. Clear `Lists!A2:A*`
3. Write presets → all node names → `!{name}` for each → Output `NAME|Hi/Lo/Force Cond`
4. Append signals still in Output Conditions or Input Conditions
5. `UpdateSignalList` → refresh defined name `RefersTo`

## Build paths

### A. Normal (bin exists)

```
openpyxl → TMP xlsx
inject_vba_zip(TMP, OUT, vbaProject.bin)
add_sync_button_inplace(OUT)   # needs Excel COM
```

### B. No bin / VBA changed

```
openpyxl → TMP xlsx
embed_vba(TMP, OUT)            # COM: import .bas/.cls + button + SaveAs xlsm
extract xl/vbaProject.bin → templates/vba/
```

### C. Fallback

VBA step fails → copy TMP to `powerseq_nodes_template.xlsx` only.

## Excel Trust Center (developer machine)

For COM embed / button:

1. File → Options → Trust Center → Trust Center Settings
2. Macro Settings → **Trust access to the VBA project object model** (AccessVBOM)
3. User files: **Disable all macros with notification** → click **Enable Content** when opening xlsm

Registry (optional dev): `HKCU\Software\Microsoft\Office\16.0\Excel\Security\AccessVBOM` = 1

## Import mapping (`excel_import.py`)

### Nodes → `PowerRail`

Row order = rail order. Input vs Output from col B.

### Output Conditions → `depends_on_*`

```text
cond_type=Hi    → depends_on_hi_groups[]
cond_type=Lo    → depends_on_lo_groups[]
cond_type=Force → depends_on_force_groups[]
```

Per row: signals in cols E+ → one group; col C → `*_intra_op`; col D Y → `*_group_inv[i]`.

Multiple rows same output + cond_type → OR groups.

### Input Conditions → WaveDrom

Per input: Hi/Lo rows → `InputWaveSpec` fields on rail (`hi_mode`, `lo_mode`, `hi_wave`, groups, etc.).

Config `wavedrom_steps` / `wavedrom_hscale` → `PowerSeqConfig.wavedrom_scenario` stub on full import.

### Signal cell parsing (`parse_signal_cell`)

| Cell value | dep name | inv | use |
|------------|----------|-----|-----|
| `SIG` | SIG | false | self |
| `!SIG` | SIG | true | self |
| `OUT\|Hi Cond` | OUT | false | hi |
| `!OUT\|Lo Cond` | OUT | true | lo |
| `High` / `Low` | `__HIGH__` / `__LOW__` | false | self |

### Lists builder (`build_signal_dropdown_entries`)

```python
["High", "Low", name, f"!{name}", ...]
# + for each output: f"{name}|Hi Cond", ...
# + sorted extras from condition sheets
```

## Export mapping (`excel_export.py`)

`export_powerseq_to_excel(config, path)`:

1. Clone template (xlsx or golden xlsm for VBA preservation)
2. Write Config, Nodes, Output Conditions, Input Conditions, Lists
3. Reapply validations / defined names
4. For xlsm output: zip-inject `vbaProject.bin` and copy sync button drawing from golden if needed

Round-trip covered by `tests/test_excel_export.py`.

## Sample COND_ROWS (template demo)

```python
COND_ROWS = [
    ("PCH_P0V85A_EN", "Hi", "AND", "N", "EKEY", "PRIM_VR_EN", "!RSMRST_N"),
    ("", "Lo", "AND", "N", "Low"),
    ("", "Force", "AND", "N"),
]
```

First row of each block carries `output_name`; follow-up rows leave A blank (merged in file).

## Sample INPUT_COND_ROWS

```python
INPUT_COND_ROWS = [
    ("EKEY", "Hi", "Custom wave", "01", "AND", "N"),
    ("", "Lo", "Low (0)", None, "AND", "N"),
    ("PRIM_VR_EN", "Hi", "Signal cond.", None, "AND", "N", "EKEY"),
    ("", "Lo", "Low (0)", None, "AND", "N"),
]
```
