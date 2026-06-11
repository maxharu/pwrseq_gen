# Excel Template — Reference

## File map

| Path | Purpose |
|------|---------|
| `scripts/generate_excel_template.py` | Main builder: sheets, validations, sample rows, orchestration |
| `scripts/embed_excel_vba.py` | COM: import VBA modules, add sync button, `refresh_vba_inplace` |
| `scripts/inject_vba_zip.py` | Merge `vbaProject.bin` into xlsx → xlsm without Excel |
| `scripts/rebuild_vba_project.py` | Helper to refresh bin after VBA edits (wraps generate + COM) |
| `templates/powerseq_nodes_template.xlsm` | Shipped template |
| `templates/powerseq_nodes_template.xlsx` | Fallback when VBA embed fails |
| `templates/vba/PwrSeqSync.bas` | Sync logic module |
| `templates/vba/ThisWorkbook.cls` | Empty (no auto events) |
| `templates/vba/SheetNodes.cls` | Empty (no sheet events) |
| `templates/vba/vbaProject.bin` | Precompiled VBA for zip inject |

## Key constants (`generate_excel_template.py`)

```python
DATA_START_ROW = 4
SHEET_NODES = "節點清單"
SHEET_COND = "Output條件"
SHEET_LISTS = "Lists"
SIGNAL_PRESETS = ("固定為高", "固定為低")
OUTPUT_USE_SUFFIXES = ("|Hi Cond", "|Lo Cond", "|Force Cond")
COND_META_COLS = 3          # output_name, cond_type, group_inv
COND_SIGNAL_INIT_COLS = 8    # visible signal columns in template
COND_SIGNAL_MAX_COLS = 49     # validation width (cols D..AZ)
```

Sample data arrays: `NODE_ROWS`, `COND_ROWS`, `CONFIG_ROWS` — update when changing demo content.

## Defined names

| Name | Refers to |
|------|-----------|
| `SignalList` | `Lists!$A$2:$A$n` (rebuilt by VBA sync) |
| `NodeNames` | `節點清單!$A$4:$A$200` (legacy; sync uses live scan) |

## VBA public API

| Sub/Function | Role |
|--------------|------|
| `RequestSyncFromNodes` | Entry point (button + Alt+F8) |
| `SyncOutputConditions` | Rebuild Output條件 rows |
| `SyncListsNodeNames` | Rebuild Lists + update `SignalList` |
| `SetSheetRefs` | Resolve sheets by row-1 key `name` / `output_name` |
| `IsSyncInProgress` | Reentrancy guard |

### SyncOutputConditions algorithm

1. Scan existing Output條件; group rows by resolved `output_name` (inherit blank col A from block above)
2. Collect Outputs from 節點清單 col A where col B = `Output`
3. Clear data area; for each Output in node order:
   - Load saved row groups; ensure at least one Hi, Lo, Force template row
   - Sort rows: all Hi, then Lo, then Force
   - Write block; merge column A

### SyncListsNodeNames algorithm

1. Save presets from `Lists!A2:A3` before clear
2. Clear `Lists!A2:A*`
3. Write presets → all node names (dedupe, node sheet order) → for each Output add `NAME|Hi Cond`, `|Lo Cond`, `|Force Cond`
4. Append any signal strings still present in Output條件 (keeps external refs like `RSMRST_N`)
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

## excel2json mapping (planned)

Parse `節點清單` → rails list (order = row order).

Parse `Output條件` long rows per `output_name`:

```text
cond_type=Hi → depends_on_hi_groups[]
cond_type=Lo → depends_on_lo_groups[]
cond_type=Force → depends_on_force_groups[]
```

Per row: signals in cols D+ → one group; `group_inv` Y → `depends_on_*_group_inv[i]`.

Signal cell parsing:

| Cell value | dep name | inv | use |
|------------|----------|-----|-----|
| `SIG` | SIG | false | self |
| `!SIG` | SIG | true | self |
| `OUT\|Hi Cond` | OUT | false | hi |
| `!OUT\|Lo Cond` | OUT | true | lo |

Split on `|` suffix `Hi Cond` / `Lo Cond` / `Force Cond`; strip leading `!`.

## Sample COND_ROWS (template demo)

```python
COND_ROWS = [
    ("PCH_P0V85A_EN", "Hi", "N", "EKEY", "PRIM_VR_EN", "!RSMRST_N"),
    ("", "Lo", "N", "固定為低"),
    ("", "Force", "N"),
]
```

First row of each Output block carries `output_name`; follow-up rows leave A blank (merged in file).
