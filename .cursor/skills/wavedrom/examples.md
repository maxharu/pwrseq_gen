# WaveDrom Examples

Tutorial source: [wavedrom.com/tutorial.html](https://wavedrom.com/tutorial.html).

---

## 1. Minimal single signal

```json
{
  "signal": [
    { "name": "Alfa", "wave": "01.zx=ud.23.456789" }
  ]
}
```

`.` extends the prior level; mixed symbols show special states and bus transitions.

---

## 2. Clock comparison

```json
{
  "signal": [
    { "name": "pclk", "wave": "p......." },
    { "name": "Pclk", "wave": "P......." },
    { "name": "nclk", "wave": "n......." },
    { "name": "Nclk", "wave": "N......." },
    {},
    { "name": "clk0", "wave": "phnlPHNL" },
    { "name": "clk1", "wave": "xhlhLHl." }
  ]
}
```

---

## 3. Typical bus + wire (with clock)

```json
{
  "signal": [
    { "name": "clk", "wave": "P......" },
    { "name": "bus", "wave": "x.==.=x", "data": ["head", "body", "tail", "data"] },
    { "name": "wire", "wave": "0.1..0." }
  ]
}
```

---

## 4. Gaps and spacer

```json
{
  "signal": [
    { "name": "clk", "wave": "p.....|..." },
    { "name": "Data", "wave": "x.345x|=.x", "data": ["head", "body", "tail", "data"] },
    { "name": "Request", "wave": "0.1..0|1.0" },
    {},
    { "name": "Acknowledge", "wave": "1.....|01." }
  ]
}
```

---

## 5. Nested groups (tutorial Master/Slave)

```json
{
  "signal": [
    { "name": "clk", "wave": "p..Pp..P" },
    [
      "Master",
      [
        "ctrl",
        { "name": "write", "wave": "01.0...." },
        { "name": "read", "wave": "0...1..0" }
      ],
      { "name": "addr", "wave": "x3.x4..x", "data": "A1 A2" }
    ],
    {},
    [
      "Slave",
      ["ctrl", { "name": "ack", "wave": "x01x0.1x" }],
      { "name": "rdata", "wave": "x.....4x", "data": "Q2" }
    ]
  ]
}
```

---

## 6. DDR-style period / phase

```json
{
  "signal": [
    { "name": "CK", "wave": "P.......", "period": 2 },
    { "name": "CMD", "wave": "x.3x=x4x=x=x=x=x", "data": "RAS NOP CAS NOP NOP NOP NOP", "phase": 0.5 },
    { "name": "ADDR", "wave": "x.=x..=x........", "data": "ROW COL", "phase": 0.5 },
    { "name": "DQS", "wave": "z.......0.1010z." },
    { "name": "DQ", "wave": "z.........5555z.", "data": "D0 D1 D2 D3" }
  ]
}
```

---

## 7. config + head / foot

```json
{
  "signal": [
    { "name": "clk", "wave": "p...." },
    { "name": "Data", "wave": "x345x", "data": ["head", "body", "tail"] },
    { "name": "Request", "wave": "01..0" }
  ],
  "config": { "hscale": 2 },
  "head": { "text": "WaveDrom example", "tick": 0, "every": 2 },
  "foot": { "text": "Figure 100", "tock": 9 }
}
```

---

## 8. Edges (splines + sharp)

```json
{
  "signal": [
    { "name": "A", "wave": "01........0....", "node": ".a........j" },
    { "name": "B", "wave": "0.1.......0.1..", "node": "..b.......i" },
    { "name": "C", "wave": "0..1....0...1..", "node": "...c....h.." }
  ],
  "edge": [
    "a~b t1",
    "c-~>d time 3",
    "h~>i some text"
  ]
}
```

---

## 9. pwrseq_gen export shape (abbreviated)

From `generate_wavedrom()` — grouped inputs/outputs, head/foot text:

```json
{
  "head": { "text": "PWRSEQ_TOP power sequence (200 steps)" },
  "foot": { "text": "Input/output state only; cond true -> switch next step. steps=200" },
  "signal": [
    { "name": "iEKEY", "wave": "1..................................................................................................................................................................................................." },
    { "name": "oVDD_CORE", "wave": "0.1.." }
  ],
  "config": { "skin": "narrow" }
}
```

`wave`: flat runs use `1`/`0` plus `.` hold (200 highs = `1` + 199 dots); transitions use `0.1..`. No pulse/bus lanes in export.

---

## 10. Scenario snippet (simulation-only)

`output/x15snw_pseq_wavedrom_scenario.json` style:

```json
{
  "steps": 200,
  "inputs": {
    "EKEY": {
      "hi_mode": "constant_1",
      "hi_wave": "0",
      "lo_mode": "constant_0",
      "lo_wave": "0"
    },
    "PRIM_VR_EN": {
      "hi_mode": "depends",
      "hi_wave": "0",
      "lo_mode": "constant_0",
      "lo_wave": "0",
      "hi_groups": [["EKEY"]],
      "hi_inv_groups": [[false]],
      "hi_use_groups": [["self"]]
    }
  }
}
```

Custom stimulus example for `hi_mode: "custom"`:

```json
"hi_wave": "0.1.",
"lo_wave": "1..0"
```

---

## 11. Hand-edit after export

To add a clock row above exported rails, insert at the start of a group:

```json
{ "name": "clk", "wave": "p." }
```

Ensure the clock **wave** length matches the effective steps of other lanes (pad with `.`).
