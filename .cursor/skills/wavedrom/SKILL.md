---
name: wavedrom
description: >-
  Author and validate WaveDrom (WaveJSON) digital timing diagrams: wave
  strings, clocks, buses, groups, config, head/foot, and edges. Use when
  editing wavedrom.json, WaveDrom Editor output, wave patterns in
  pwrseq_gen scenario/export, power-sequence timing charts, or questions
  about https://wavedrom.com/tutorial.html.
---

# WaveDrom Timing Diagrams

WaveDrom renders **WaveJSON** in the browser. Official tutorial:
[Hitchhiker's Guide to the WaveDrom](https://wavedrom.com/tutorial.html).
Editor: [wavedrom.com/editor.html](https://wavedrom.com/editor.html).

## Document shape

Top-level object (JSON or JS object literal):

```json
{
  "head": { "text": "Title" },
  "foot": { "text": "Caption" },
  "signal": [ /* WaveLanes and groups */ ],
  "config": { "hscale": 2 },
  "edge": [ "a~b t1" ]
}
```

- **signal** (required): array of lanes. Each lane is either:
  - `{ "name": "sig", "wave": "01..0" }` — one wire
  - `{}` — vertical spacer between lanes
  - `["Group label", laneOrGroup, ...]` — nested named group
- **head / foot** (optional): `{ "text": "...", "tick": 0, "tock": 9, "every": 2 }`
- **config** (optional): `{ "hscale": 1 }` (integer > 0), `{ "skin": "narrow" }` (first diagram on page only)
- **edge** (optional): annotations between **node** markers on lanes (see [reference.md](reference.md))

Every lane needs **name** and **wave**. Optional per lane: **data**, **period**, **phase**, **node**.

## Wave string (one character = one time period)

| Char | Meaning |
|------|---------|
| `0` `1` | Logic low / high |
| `.` | Hold previous level one more period |
| `x` | Unknown |
| `z` | High-Z |
| `=` | Bus/data segment (pair with **data** labels) |
| `2`–`9`, `a`–`f` | Bus value index into **data** |
| `\|` | Gap marker (visual break in timeline) |

**Export encoding (`values_to_wave`):** WaveDrom treats each character as one
period; `2`–`9` are bus/data symbols (not repeat counts). Flat runs bookend the
level with dots between (e.g. 200 highs → `"1" + "."×198 + "1"`, not `"1200"`).
Multiple transitions use `0`/`1` with `.` hold (e.g. `[0,0,1,1,1]` → `"0.1.."`).

When hand-writing patterns for **scenario** `hi_wave` / `lo_wave`, use the full
WaveDrom alphabet; `.` stretches the previous symbol (`0.1.` = low, brief high,
back to low).

**Scenario shorthand (`expand_wave_pattern`, sim-only):** scenario `hi_wave` /
`lo_wave` also accept a regex-style mini-syntax that is expanded to 0/1 before
simulation (it is **not** written into exported WaveJSON, so no impact on
wavedrom.com):

- `0` / `1`：位元；`.` / `|`：延續前一位元一格。
- `{n}`：量詞，把緊接在前的單位（位元或 `(...)` 群組）重複到**剛好 n 次**。
- `(...)`：群組，可巢狀、可被 `{n}` 量化。
- 忽略空白；長度不足補最後電平、超過截斷。
- 範例：`0{29}1` = 29 個 0 後接 1（第 30 step 才成立）、`1{3}0{5}` = `11100000`、`(10){3}` = `101010`。
- 舊版裸數字重複（如 `029`）仍向後相容。

### Clock lanes

Clocks toggle twice per period. Use dedicated symbols (not plain `01`):

| wave | Role |
|------|------|
| `p` `P` | Positive-edge clock (lowercase / uppercase style) |
| `n` `N` | Negative-edge clock |
| `h` `H` `l` `L` | Mixed / gated clock fragments |

Example: `{ "name": "clk", "wave": "P......." }`.

### Buses

```json
{ "name": "bus", "wave": "x.==.=x", "data": ["head", "body", "tail"] }
```

`=` regions consume entries from **data** (string or array). Use `2`–`9` / `a`–`f`
in **wave** for indexed bus transitions.

### Groups and spacers

```json
"signal": [
  ["External inputs", { "name": "ena", "wave": "01" }],
  {},
  ["Outputs", { "name": "vdd", "wave": "0.1.." }]
]
```

`generate_wavedrom()` uses a **flat** `signal` array in **`config.rails` order**
(`i*` / `o*` prefixes), not grouped wrappers.

### period / phase

Per-lane timing stretch (DDR-style diagrams):

```json
{ "name": "CK", "wave": "P.......", "period": 2 },
{ "name": "ADDR", "wave": "x.=x..=x", "data": ["ROW", "COL"], "phase": 0.5 }
```

## pwrseq_gen integration

| Artifact | Role |
|----------|------|
| `*_wavedrom_scenario.json` | `steps` + per-input `hi_*` / `lo_*` (simulation only) |
| `output/wavedrom.json` | Exported WaveJSON for WaveDrom Editor |
| `wavedrom_export.generate_wavedrom()` | Config + scenario → `{ head, foot, signal }` |
| `wavedrom_sim.simulate()` | Input/Output: cond true → switch **next** step (no cycle/pulse) |
| GUI **Export WaveDrom** | Ctrl+Shift+E; see `doc/操作說明.md` §3.10 |

**Export naming:** inputs `i{Name}`, outputs `o{Name}` (`.`/`-`/space → `_`).

**Simulation limits (do not promise full RTL parity):**

- Output / input（**depends** 或 **custom** hi/lo）：wave bit / Cond 為轉態**條件**；**pwrcell permit** + 條件成立後 **下一 sim step** 翻轉（例：`hi_wave: "01"` → 第 2 step 條件成立 → 第 3 step GPIO 拉高）
- 引用 **output GPIO** 的 input（PG、FINAL 等）在每 step **output 評估前**先更新，避免 output Lo 條件晚 1 step 才成立
- Hi∧Lo 同時成立：不給對向 permit（低無法升、高無法降）
- 無 cycle/pulse；`cond_step_delay` 欄位僅 JSON 相容（hscale 別名），不參與模擬
- Input scenario does **not** change rail `depends_on_*` in project JSON
- Export adds **edge** arrows: dep GPIO transition → output GPIO transition (Hi/Lo condition leaves)
- **Condition arrows**（GUI Export WaveDrom 對話框、API `edge_kinds`）：
  - `Hi and Lo`（預設）：Hi 與 Lo 條件各畫箭頭
  - `Hi only` / `Lo only`：只畫對應方向的箭頭
  - 常數：`WAVEDROM_EDGE_BOTH` / `WAVEDROM_EDGE_HI_ONLY` / `WAVEDROM_EDGE_LO_ONLY`；`wavedrom_edge_kinds_from_choice("hi"|"lo"|"both")`
- **Node 大小寫慣例**（WaveDrom 渲染）：小寫 node 多畫一顆字母標記（看得見），大寫為隱形錨點（箭頭照接、不畫字母）。`_NodeAllocator` 依 **lane 角色**分池（與 Hi/Lo 無關；三種 arrow 模式相同）：
  - **Output lane**（`o*`）：依時序優先小寫 `a–z` → 溢出大寫 → `0-9@#$%&?`
  - **Input lane**（`i*`）：依時序優先大寫 `A–Z` → 溢出符號 → 小寫
  - 分配流程：收集所有 edge 端點 → 依 `(sim step, lane name)` 排序 → 再取字；同一 `(lane, wave index)` 共用同一 node
  - Edge 格式：`{dep}-~>{out}`（例：`A-~>a`）；端點需全域唯一且為**單一字元**
  - 大型圖（如 x15dot-f）端點數 > 52 時各池會溢出，屬預期
- Multi-bit / clock lanes are not generated; add manually in Editor if needed

**Workflow for agents:**

1. Read scenario + `PowerSeqConfig` if changing simulation inputs.
2. Run or reason about `simulate()` → bit vectors → `values_to_wave()`.
3. Validate JSON structure (`signal` array, every lane has `name`+`wave`).
4. Paste JSON into [WaveDrom Editor](https://wavedrom.com/editor.html) to verify render.
5. For custom annotations (edges, clk), edit exported JSON or extend export code explicitly.

## Quick validation checklist

- [ ] `signal` is a non-empty array
- [ ] Each object lane has `name` and `wave`; `wave` length = number of time steps shown
- [ ] Bus lanes: count of `=` / data digits matches **data** entries
- [ ] Groups: first element of array is string label
- [ ] **config.hscale** is a positive integer if present
- [ ] Scenario `hi_mode` / `lo_mode`: `constant_0` | `constant_1` | `custom` | `depends`

## Additional resources

- Full symbol tables, edge grammar, head/foot SVG text: [reference.md](reference.md)
- Tutorial-aligned and project examples: [examples.md](examples.md)
