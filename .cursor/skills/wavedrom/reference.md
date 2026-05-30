# WaveDrom Reference

Source: [Hitchhiker's Guide to the WaveDrom](https://wavedrom.com/tutorial.html).

---

## Core model

- **WaveJSON** describes a timing diagram.
- **WaveLane** = `{ name, wave, ...optional }`.
- **wave**: one character per **time period**; `.` repeats the previous symbol for one more period.

---

## Logic and special states

| Symbol | Typical use |
|--------|-------------|
| `0` | Low |
| `1` | High |
| `.` | Continue previous value |
| `x` | Unknown |
| `z` | High impedance |
| `=` | Data/bus (label from **data**) |
| `2`–`9` | Data field index (hex nibble style) |
| `a`–`f` | Extended data indices |
| `u` `d` | Up / down (analog-style) |
| `|` | Gap in the diagram |

Multi-bit example from tutorial:

```javascript
{ name: "bus", wave: "x.==.=x", data: ["head", "body", "tail", "data"] }
```

---

## Clock symbols

Clocks are **not** plain square waves; they use dedicated glyphs (two transitions per cycle):

| Symbol | Description |
|--------|-------------|
| `p` | Positive clock (one style) |
| `P` | Positive clock (alternate style) |
| `n` | Negative clock |
| `N` | Negative clock (alternate) |
| `h` `H` `l` `L` | Half-period / gated fragments |
| Mixed strings | e.g. `phnlPHNL`, `xhlhLHl.` for gating effects |

---

## Groups, spacers, gaps

**Spacer lane:** empty object `{}` inserts blank vertical space.

**Gap in time:** `|` inside **wave**, e.g. `"0.1..0|1.0"`.

**Group:**

```javascript
['Master',
  ['ctrl',
    { name: 'write', wave: '01.0....' },
    { name: 'read',  wave: '0...1..0' }
  ],
  { name: 'addr', wave: 'x3.x4..x', data: 'A1 A2' }
]
```

- First array element: group title (string).
- Remaining elements: lanes, nested groups, or `{}`.
- Groups may nest arbitrarily.

---

## period and phase

Per-lane:

- **period** (number): stretch clock/data lanes (e.g. DDR `period: 2`).
- **phase** (number): horizontal offset of lane vs default (e.g. `0.5`).

---

## config

```javascript
config: { hscale: 2 }   // integer > 0, horizontal scale
config: { skin: 'narrow' }  // only first diagram on page
```

---

## head and foot

```javascript
head: { text: 'Title', tick: 0, every: 2 },
foot: { text: 'Figure 1', tock: 9 }
```

- **tick** — labels on vertical grid lines.
- **tock** — labels between grid lines.
- **every** — show tick/tock every N cycles only.
- **text** — caption; may use JsonML / SVG **tspan** trees with classes:
  `h1`–`h6`, `muted`, `warning`, `error`, `info`, `success`, or inline SVG attributes.

---

## Nodes and edges (arrows)

Assign **node** on lanes (`.` = no node at that position):

```javascript
{ name: 'A', wave: '01........0....', node: '.a........j' }
```

**edge** array connects node letters:

### Splines (curved)

| Syntax | Shape |
|--------|-------|
| `a~b` | Spline between a and b |
| `<~>` `<-~>` | Bidirectional variants |
| `~>` `-~>` `~->` | Directed splines |

Example: `edge: ['a~b t1', 'c-~>d time 3', 'h~>i some text']`

### Sharp (orthogonal)

| Syntax | Shape |
|--------|-------|
| `-` `-|` `-|-` | Straight / elbow |
| `<->` `<-|>` | Bidirectional |
| `->` `-|>` `-|->` `\|->` | Directed |
| `+` | Branch |

Example: `edge: ['b-|a t1', 'c-|->e t4', 'g<->h 3 ms']`

Optional label after node pair: `'a~b t1'` — text follows the connection spec.

---

## pwrseq_gen: values_to_wave

`src/wavedrom_sim.py` compresses `list[int]` of `0`/`1` for the editor:

- One step: `'0'` or `'1'`.
- Flat run of N>2: `str(level) + '.' * (N - 2) + str(level)` (e.g. three highs → `"1.1"`).
- Mixed runs: dot-joined transitions (`0.1..`).

Never emit `{level}{count}` like `1200` — WaveDrom reads `2`–`9` as bus/data, not repeat counts.

Export uses only `0`, `1`, `.` (no clocks/buses). Scenario `custom` waves may use the full alphabet via `expand_wave_pattern`.

---

## Scenario JSON (simulation input)

Per input rail in `WaveDromScenario`:

| Field | Values |
|-------|--------|
| `hi_mode` / `lo_mode` | `constant_0`, `constant_1`, `custom`, `depends` |
| `hi_wave` / `lo_wave` | WaveDrom pattern when mode is `custom` |
| `hi_groups` / `lo_groups` | AND groups of signal names |
| `hi_inv_groups` / `lo_inv_groups` | Invert flags per group member |
| `hi_use_groups` / `lo_use_groups` | `self` or other names for cond evaluation |

Groups OR together; inside a group AND. Mirrors GUI Cond semantics; does not alter saved `depends_on_*` on rails.

---

## Rendering checklist

1. Valid JSON (double quotes in files).
2. No trailing commas.
3. **data** as string (`"A B C"`) or array — both appear in tutorial.
4. Open in [Editor](https://wavedrom.com/editor.html) — syntax errors often show blank lanes.
5. Large `wave` strings (200+ steps): use **config.hscale** or Editor zoom for readability.
