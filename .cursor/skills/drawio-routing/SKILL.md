---
name: drawio-routing
description: >-
  pwrseq_gen Draw.io edge routing: (1) Input/input NOT → orthogonal auto;
  (2) Gate output → next-level input (incl. Deb) frozen waypoints, three shapes;
  (3) Feedback (FB) → five-segment frozen waypoints from Q/~Q/gate per
  FB_Routing.xml (same-source same-layer shares one X channel). Covers
  feedback_auto_edge_ids, _apply_feedback_routing,
  _build_feedback_source_layer_slots, freeze_edge_routing, _GateExitLanes,
  use=hi/lo passthrough exitX (AND right vs Deb placeholder).
  Use when modifying drawio_export.py wire logic or doc/DRAWIO_RULES.md wire sections.
---

# Draw.io Edge Routing (pwrseq_gen)

**三種走線制度**。座標與欄寬見 [drawio-placement](../drawio-placement/SKILL.md)。
完整規格：`doc/DRAWIO_RULES.md` §五、§八。

實作：`src/drawio_export.py`（emit + Pass 1–3 + `_apply_feedback_routing`）→ `src/layout_engine.py`（`freeze_edge_routing`、`restore_orthogonal_auto_routing`）。

程式對照：[reference.md](reference.md)。

**參考 XML（僅走法形狀，距離以程式常數為準）：**

| 檔案 | 內容 |
|------|------|
| `src/reference/FB_Routing.xml` | Cell FB 五段、Q／~Q 走廊、**同層扇出共用水平段** |
| `src/reference/PWRCELL.xml` | Cell 錨點：Q 對齊 H_Deb、~Q 對齊 L_Deb |

---

## Rule 3 — Feedback（FB）五段凍結走線 ★

回授邊**不走** Rule 1 自動正交；走 **Rule 2**（`edgeStyle=none` + 鎖定 waypoints）。Pass 3 後 `_apply_feedback_routing` 統一寫五段折點。

### 共通形狀（5 段）

```
來源錨點 → ①右 → ②上 → ③左（目標層 FB X 通道）→ ④上/下（到目標 Y）→ ⑤右（進目標）
```

| 段 | 說明 |
|----|------|
| ① | 自 exit 錨點水平向右（距離見 profile） |
| ② | **一律向上**（目標在下方亦然）；`p2y = ey − up_delta` |
| ③ | 水平向左至該**目標層** FB 垂直幹線 `p3x`（`p3y = p2y`） |
| ④ | 垂直至目標 entry Y（`p4y = ty`） |
| ⑤ | 水平向右至 entry X（AND／OR 左緣或 Deb entry） |

- 錨點 Y（`ey`）與第 ① 點 Y：**不做** `_align40`（避免 exit→首段斜線）
- 第 ②③ 點 Y、第 ③④ 點 X：做 `_align40`

### Cell FB：Q 與 ~Q

| 腳 | PWRCELL 位置 | 何時為 FB 來源 |
|----|--------------|----------------|
| **Q** | inner 右側、H_Deb 列 | `use=self`、**非 inv**（例：RSMRST → 下游 hi AND） |
| **~Q** | inner 右側、L_Deb 列 | **inv** 跨列回授（Pass 2：`not_gate_id` 直接綁 ~Q，不畫實體 output NOT） |

| Profile | ① 右移 | ② 上移 | 常數 |
|---------|--------|--------|------|
| **Q** | 40pt | 60pt（40+20） | `FB_Q_RIGHT`, `FB_Q_UP` |
| **~Q** | 80pt（2×40） | **140pt**（3×40+20；高於 Q 60pt，② 走廊不重疊） | `FB_NQ_RIGHT`, `FB_NQ_UP` |

`FB_Routing.xml` 示意（Q `ey=420`）：

- ② 走廊 `y=360`（`ey−60`）；~Q `ey=460` → ② `y=320`（`ey−140`）
- 同 source、同目標層（例：Ln-1 兩個 Dest）：共用 `(500,360)→(320,360)`，④ 再分到不同 `ty`

### gate profile（AND／NAND／OR／NOR output）

| ① | ② |
|---|---|
| 右至 **stub X**（與閘→下一級同一 `(1+n)×40` 通道） | 向上 60pt（`FB_Q_UP`） |

其後 ③④⑤ 同 Cell FB。

> ★ **OR→OR 不可用短 stub**：① 一律走該閘 catalog `stub_x(src)`（`(1+n)×40`，每顆閘各自一條），**不要**用 `src_right+40` 之類的共用短 stub——否則多條 OR 回授會擠在同一 OR 層 X 通道。placement 已為每顆閘預留此通道。`_apply_feedback_routing` 的 `profile == "gate"` 分支對所有目標層（含 or）統一用 `stub_x`。

### FB X 通道與同層水平共用 ★

**規則：同一 `source_id` 在每個目標層（and／or／cell）只佔 1 條 X 通道。**

實作：`_build_feedback_source_layer_slots` → `(src_id, layer) → slot`（**非**依 `tgt_row` 分 slot）。

| 情境 | 行為 |
|------|------|
| 同 source 扇出至多目標（同層） | 共用 `p2y` 與 ③ 水平段；④ 各走至不同 `ty` |
| 不同 source（同層） | `slot` 遞增（+40pt／格） |

| 目標層 | `p3x` 基準 | 佈局容量（placement） |
|--------|------------|------------------------|
| **and** | `channel_x_left + slot×40` | `feedback_n` |
| **or** | `_or_fb_channel_base_x + slot×40` | `fb_or` |
| **cell**（H/L_Deb） | `_cell_fb_channel_base_x + slot×40` | `fb_cell` |

佈局預留寬度（gap 公式）見 [drawio-placement](../drawio-placement/SKILL.md) §8；走線 slot 與預留 `fb_*` 計數模型不同（左幹線 vs AND→Cell 通道）。

#### cell 幹線避讓被佔用車道 ★

cell `p3x` 基準算出後可能落在 OR→Cell gap 內**已被佔用**的垂直車道（尤其 OR 閘 gate-exit stub），造成 `~Q`／cell 回授與 OR 回授路線重疊。`_apply_feedback_routing` 預掃描兩類佔用車道，cell 幹線往左（朝 OR 欄）逐格挪到空車道：

| 佔用來源 | 取得方式 |
|---------|---------|
| 既有正向邊垂直段 | 掃 XML 各 edge waypoints 的垂直段 x |
| gate-profile 回授 ① stub | 一律 `stub_x(src)`（catalog `(1+n)×40`，每顆閘各自一條，含 OR→OR） |

- 下限 `and_col_x + AND_GATE_W + GAP`；**同一 source 同層仍共用一條** `p3x`（`source_cell_x` 快取，勿因避讓拆成多條）。

### 顏色

`_apply_feedback_edge_color`：預設 **藍** `#2563eb`；已是 Hi 綠／Lo 紅者**保留**。

### 測試

| 測試 | 驗證 |
|------|------|
| `test_cell_q_feedback_second_segment_always_up` | Q ② 向上 60pt |
| `test_cell_nq_feedback_second_segment_up_140pt` | ~Q ② 向上 140pt |
| `test_same_source_fb_shares_one_channel_x_per_layer` | 同 source 同層僅 1 個 `p3x` |
| `test_hi_use_upstream_and_exits_from_gate_right` | `use=hi` 且上游 AND 已存在 → `exitX=1` |

---

## 回授邊集合（`feedback_auto_edge_ids`）

僅集合內的邊會跑 `_apply_feedback_routing`。

### 累加時機

| 階段 | 函式 |
|------|------|
| emit | `_mark_layout_feedback_edge`、`_mark_traced_layout_feedback_edge`、`_wire_and_dep_non_input` |
| Pass 1 | `_pass1_is_layout_feedback`（佔位換 logic pin 後仍回授 → 清 waypoints） |
| 匯出末段 | `_supplement_traced_feedback_edges`（RSMRST Q／~Q、departing AND 跨列補標） |

### `layout_feedback_dep_keys`（跨列）

- `d == "RSMRST_N"`
- `d == "PCH_PWROK"` 且單一 Deb、`inv=True`
- 多輸入 AND 且 `_departing_and_index` 非空（AND Output，不含 RSMRST_N）

列舉：`scripts/enumerate_feedback.py`、`scripts/list_feedback_paths.py`。

### 佈局回授四類（X／Y 留空用）

| 類別 | 摘要 |
|------|------|
| **RSMRST_N** | 跨列 `RSMRST_N`；左幹線 1 桶 |
| **RSMRST_N NOT** | lo inv → 上游 L_Deb（source=~Q） |
| **PCH_PWROK** | lo inv → 上游 L_Deb |
| **AND Output** | departing AND → 下游 AND |

`feedback_n = len(trunk_and) + (1 if has_rsmrst else 0)`。

---

## Rule 1 — Input（含 input NOT）

| Item | Value |
|------|--------|
| **edgeStyle** | `orthogonalEdgeStyle` |
| **Waypoints** | 清除 |
| **適用** | input label、`input_not_src_ids` |

```python
restore_orthogonal_auto_routing(root, input_auto_src_ids)  # 不含 feedback
```

---

## Rule 2 — 閘 Output → 下一級（非回授）

| Item | Value |
|------|--------|
| **edgeStyle** | `edgeStyle=none` |
| **Stub** | `(1+n)×40pt`（n＝該閘在所屬層 stub lane gap 的**本地序**）|

| # | 型態 | 條件 |
|---|------|------|
| 1 | 右 | 同 Y（≤2pt） |
| 2 | 右→上/下 | 閘→閘 |
| 3 | 右→上/下→右 | 閘→Deb |

跨列非回授正向：`wire_via_channel`（emit 凍結）。

#### stub lane 序 n 每層各自從 0 數 ★

`_build_gate_lane_indices` 對 AND／OR 兩層用**獨立**計數器：AND stub lane 在 **AND→OR gap**、OR stub lane 在 **OR→Cell gap**，是不同物理通道區，OR 迴圈前 `lane` 必須**歸零重數**。若沿用 AND 跑完的全域序，OR 每顆閘的 n 會多算 AND 佔掉的格數 → 出口通道整批右移、最後一顆擠到 Cell 欄邊界（`(1+n)×40` 落在 Cell 入口）；正向被 `max_lx` 夾回一格、回授仍用邊界值，於是同一閘正向與回授分走兩條通道。

- 同一閘的**正向與回授共用**這條 lane（`stub_x(id)` 對 catalog 閘冪等）。
- 症狀：某 OR/NOR 閘正向 stub 與其回授 ① stub 差 40pt（正向在 `cell_col−40`、回授在 `cell_col`）。
- placement 的 OR→Cell gap 寬度（`_gate_gap_width`）本就用 OR 層**本地**閘數預留，本地編號才與之對齊。

### `use=hi`／`use=lo` 透傳 → 本列 H_Deb／L_Deb ★

單一依賴、`use=hi` 或 `use=lo`（取上游該列 logic 輸出）時，**exit 錨點**依來源種類決定，不可一律 `exitX=0`。

| 來源（emit 時 `from_id`） | exit | 樣式 | 後續 |
|-------------------------|------|------|------|
| 上游 **H/L_Deb 佔位符** | **左** `exitX=0` | `style_*_to_cell_left` | **Pass 1** 換成 `hi/lo_logic_out_id` + `exitX=1` + `_rewire_pass1_logic_edge` |
| 上游 **logic_out 已存在**（AND／OR／Q／~Q） | **右** `exitX=1` | `style_*_to_cell` | emit 即 `wire_via_channel`／stub waypoints；**不**等 Pass 1 |

判定：`_use_hi_lo_deb_placeholder_exit(from_id, use_mode)`（與 `_style_edge_to_gate_entry` 同一條件）。

典型：`PVNNAON_EN`／`PVCCIO_EN`／`PVCC1V8_EN` 的 Hi（`use=hi` → 上游 PCH_* AND 右側）必須 `exitX=1`。

Pass 1 僅處理 **source 為本列 H/L_Deb 佔位符** 的邊（`exitX=0` in style）；已為 AND/OR 的邊不在此列。

#### `_rewire_pass1_logic_edge` 進 OR／AND 要用真正入口錨點 Y ★

改接後 `wire_via_channel` 收尾的 entry Y **必須用該邊 `entryY` 算出的入口錨點**，不可用閘中心（`id_to_y_center`）。OR／AND 的輸入 pin 在 `entryY=0.25/0.75`（離中心 ±10pt）；若用中心收尾，freeze 會為了補回真正錨點而多插一個折角，正向邊就從 3 段變成 5 段（曾誤判成回授）。

- 實作：caller 解析 `entry_ay=_style_float(sty,"entryY",0.5)` 傳入；`_entry_y = round(_ty + (entry_ay-0.5)*OR_GATE_H)`（AND 同理用 `AND_GATE_H`）。
- 症狀：AND／OR→OR 正向（含 `use=hi/lo` 跨列）出現 `(stub,center)(near_or,center)(near_or,entry)` 的 10pt 小折角。

---

## Export finale

```
generate_drawio() 主圖 + NOT Pass 1–3
  → _supplement_traced_feedback_edges
  → _apply_feedback_routing              # Rule 3
  → freeze_edge_routing(skip_source_ids=input)
  → restore_orthogonal_auto_routing(input only)  # Rule 1
  → _apply_feedback_edge_color
  → _apply_edge_wire_style
```

---

## 修改檢查

- [ ] 新 FB 邊已加入 `feedback_auto_edge_ids`？
- [ ] Q／~Q／gate：①② 距離、② **一律向上**？
- [ ] 同 source 同層共用 1 條 `p3x`（`_build_feedback_source_layer_slots`）？
- [ ] 佈局 `feedback_n`／`fb_cell`／`fb_or` 與走線 slot 容量一致？
- [ ] input 在 `input_auto_src_ids`；非 FB 閘邊仍 Rule 2 三型態？
- [ ] `use=hi/lo` 透傳：僅 Deb **佔位符** `exitX=0`；logic_out 已存在則 `exitX=1`？
- [ ] Pass 1 改接進 OR／AND：收尾 entry Y 用 `entryY` 錨點（非閘中心），避免 freeze 補折角變多段？
- [ ] `_build_gate_lane_indices`：OR 迴圈前 `lane` 歸零（每層 stub lane 各自從 0 數），OR 出口不被推到 Cell 欄邊界、正向與回授共用同一通道？
- [ ] `pytest tests/test_gate_exit_lanes.py tests/test_integration.py`

## See also

- [reference.md](reference.md)
- [drawio-placement](../drawio-placement/SKILL.md)
- `doc/DRAWIO_RULES.md` §五、§八
