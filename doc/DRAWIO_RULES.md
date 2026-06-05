# Draw.io 圖表生成規則

本文件定義 Power Sequence 結構圖（Draw.io XML）的版面、樣式與連接規則。產圖程式（`drawio_export.py`）依此規則輸出，以減少人工二次調整。

**參考圖**：`src/reference/NOT.xml`（NOT 閘 40×20pt）、`src/reference/INPUT_NOT.xml`（input label 與 input NOT）、`src/reference/NAND.xml`（AND `group_inv`）、`src/reference/NOR.xml`（OR 反相）、`src/reference/LayoutRef.xml`（output O 側 NOT）、`src/reference/golden2.xml`（完整手動完成圖）。

**與 golden2 比對**：`python scripts/diff_golden2_export.py`（以 `golden.json` 匯出，對齊最右 input 錨點後比 vertex／edge／waypoint 數）；`--fail-on-diff` 可作 CI gate。

---

## 整體流程與版面

- **流向**：由左到右。
- **欄位順序**：**輸入欄** → **input NOT 區**（若有）→ **回授幹線區** → **GAP** → **AND／NAND 欄**（第一邏輯層）→ **OR／NOR 欄**（第二邏輯層，若有）→ **Cell 欄**（第三層）→ **輸出名稱欄**。
- **三層邏輯（X）**：OR／NOR **不**與 AND／NAND 同一欄；位於 AND／NAND **右側、Cell 左側**。無 OR 時 AND／NAND 直連 Cell（結構 A，跳過中間層）。
- **input→AND**：走 **label x+40** 垂線，不佔幹線寬。
- **回授幹線寬**：`_count_feedback_trunks` — 每個跨列、由來源列 **AND output** 出發的編號各 **40pt**，**RSMRST_N** 扇出只算 **1×40pt**（golden 典型為 6 條 = 240pt）。幹線區前後各 **1×GAP**（共 2 格）才到 AND 欄，與第八節公式中的 **+2** 同義（見第八節「+2 與 Input→AND 的對應」）。
- **範例流程**：`IN1 ---(水平)--->|AND|--->|OR|--->|Cell|---(水平)---> 輸出名稱`。反相時：`IN1 ---(水平)--->|NOT|---> ...` 或 `Cell.O ---(水平)--->|NOT|--->|AND|---> ...`。
- **Output 列順序**：依 `config.rails` **宣告順序**由上而下（非重心重排）。
- **走線鎖定**：匯出結尾呼叫 `freeze_edge_routing()`：補齊 stub／轉折 waypoints 後改 `edgeStyle=none`（Draw.io 開檔不重算）。**例外**：**從 input label 或 input NOT 出發**的邊改回 `orthogonalEdgeStyle` 並**清除 waypoints**（`restore_orthogonal_auto_routing`），交 Draw.io 自動正交走線。其餘邊不呼叫 `route_orthogonal`／A*。`layout_engine.layout_drawio()` 僅供**外部 XML** 選用後處理。

---

## 一、輸入訊號 (Input Signals)

| 項目 | 規則 |
| --- | --- |
| **位置** | 圖形最左側；水平 x 由右→左動態分配（見下方）。 |
| **命名** | 一律使用正向名稱（如 `SIG_1`），不再使用 `~SIG_1` 文字表達反相；反相由 NOT 閘呈現。 |
| **水平排列** | label **`rotation=90`**；依 **`config.rails` 宣告順序**由**右→左**，每欄 **40pt**；若**前一個**（圖上較右）input 有 NOT，下一個再左 **40pt**。 |
| **垂直位置** | 依 **`INPUT_NOT.xml`**：NOT 底 = 最上 Cell 上 −40pt（40pt 對齊）；label 底 = NOT 頂 − **20pt**（= `INPUT_LABEL_H`）。 |
| **走線出發** | `exitX=1`（轉 90° 後視覺為**先下**）；再沿 label **x+40pt** 垂直到目標高度後**向右**進閘。 |
| **連到閘** | **`orthogonalEdgeStyle`**，**不**寫 waypoints（匯出時清除路徑點，Draw.io 自動正交走線）。 |

---

## 二、邏輯閘 (AND / OR / NOT)

| 項目 | 規則 |
| --- | --- |
| **分層與左右順序（X）** | 三層邏輯欄（左→右）：**① AND／NAND** → **② OR／NOR**（有 OR 路徑時）→ **③ Cell**。② 在 ① 的**後一層**、③ 的**前一層**；**不**與 ① 共用同一欄 x，也**不**參與 AND global catalog 垂直鍊。 |
| **層級間距（固定）** | input↔回授幹線、回授↔AND 等仍用 **40pt**（`GAP`）；output 列距／NOT 偏移／多 AND 垂直距仍 **80pt**（`ROW_GAP`）。 |
| **欄位水平間距（動態）** | AND↔OR、AND↔Cell、OR↔Cell 之間距**非固定 40pt**，依全圖公式計算（見**第八節**）。 |
| **閘型** | AND / OR / NAND / NOR：`logic_gate`（80×40pt）；`group_inv` 時 AND→**NAND**（`negating=1;negSize=0.15`，見 `NAND.xml`）、OR 反相→**NOR**（見 `NOR.xml`）。獨立 NOT：`inverter_2`（40×20pt，僅 input／Cell O 側，見 `NOT.xml`）。 |
| **NOT 共用** | 任何 `inv=True` 的**單一依賴**皆用共用 NOT 閘。同一「來源 `d` + `use_mode`」**共用一顆 NOT**。**整組 AND/OR 反相**則用 NAND/NOR，不再外掛 NOT。 |
| **Input NOT 位置** | 依 **`INPUT_NOT.xml`**（皆 `rotation=90`）：**左 20pt**；旋轉後**視覺底邊**在**最上列 Cell 上緣之上 40pt**（`not_y + NOT_GATE_W − NOT_GATE_H/2 = cell_top − 40`）。 |
| **Input NOT 走線** | label → NOT、NOT → 下游閘：皆 **orthogonalEdgeStyle**、**無 waypoints**（Draw.io 自動；視覺仍為先下後右）。 |
| **Output NOT 位置** | 比照 input：相對 **~Q** 右緣 **+80pt**、上緣 **+40pt**（Cell 側 inv）。 |
| **AND/OR 整組反相** | `group_inv`：繪製 **NAND**／**NOR**（內建 `negating=1`），尺寸與 AND/OR 相同；輸出自閘右側直連下游。 |
| **Output NOT 走線** | O → NOT：與 input NOT 相同三折（水平 40pt → 垂直 → 水平進 NOT）。 |
| **Output 列堆疊** | 若該 output 有反相（需 O 側 NOT），**下一列 output** 從 NOT **下方**開始（比照 input 堆疊）。 |
| **AND 欄 x** | `and_col_x = post_input_x + left_channel_w + GAP`（左側回授幹線寬之後）。**全圖固定**。 |
| **OR / Cell 欄 x** | 每列依 `_RowGateLayout`：`or_col_x = and_col_x + AND_GATE_W + gap_and_or`；`cell_start_x = and_col_x + AND_GATE_W + gap_and_cell`（無 OR）或 `or_col_x + OR_GATE_W + gap_or_cell`（有 OR）。**各列 cell 起點可不同**，右側通道取 `max(cell_start_x)`。 |
| **AND／NAND 垂直定位** | **同一套規則**（`group_inv` 僅改 style 為 `negating=1`，catalog 序／Y 不變）：全圖依 `_build_and_catalog` **global 序**鍊式堆疊（`_chain_and_top_y`）；同列多顆間距 **80pt**；跨列取 `max(列內 nominal, 上一顆 + 80pt + slack)`。**不**因 NAND 另加高或另佔 catalog 編號。 |
| **OR／NOR 垂直定位（Y）** | 全圖依 `_build_or_catalog` **global 序**鍊式堆疊（`_chain_or_top_y`）；同列 Hi→Lo 間距 **40pt**；跨列取 `max(列內 nominal, 上一顆 + 80pt + slack)`。反相僅改 `negating=1`，catalog 序／Y 不變。 |
| **Cell 垂直定位（Y）** | 錨在 `row_py`（依 config 由上而下）；列距 = **ROW_GAP（80pt）** + **Cell 層 slack**（見下）。 |
| **Y 軸三層 slack（統一）** | 三層各自在**相鄰同層元件**間隙多留 **40pt**（**去重**：同一 gap 只 +1 格）。觸發通則：跨列 **output fb→本級 input**、**Input 直連後級 input**（**不含 Input→AND**）。詳見**第十節**。 |
| **Hi/Lo OR 錯開** | 同列同時有 Hi、Lo 兩個 OR／NOR 時，Lo 在 Hi **下方 40pt**（鍊式 nominal；slack 可再撐開）。 |
| **閘 output lane** | `_GateExitLanes`：AND/NAND/OR/NOR output→下一級 input 時，**同 Y 水平直連**（無 waypoint）；需轉角者先向右 **(1+n)×40pt**。**n** = 需 stub lane 的閘之全局序（由上而下）；**僅一條 output 且水平直連**的閘**不佔** n。Pass 1 替換邏輯 source 後會重繞。 |

---

## 三、Power Sequence Cell（PWRCELL.xml 結構）

| 項目 | 規則 |
| --- | --- |
| **結構** | 每個 output 由 5 個獨立 `mxCell`（`parent="1"`，**無 group**）：inner 80×80 + H_Deb 50×20 + L_Deb 50×20 + Q 20×20 + ~Q 20×20（Q／~Q 內嵌 inner 右側）。 |
| **inner** | `rounded=0`，位於 `(px, py)`。 |
| **H_Deb / L_Deb** | `rounded=1`；H 在 `(px, py+10)`，L 在 `(px, py+50)`。 |
| **Q / ~Q** | `rounded=1`；Q 在 `(px+60, py+10)`，~Q 在 `(px+60, py+50)`；Q 為輸出 anchor。 |
| **輸入線樣式** | 連 **H_Deb**：**實心綠**（`#059669`）。連 **L_Deb**：**實心紅**（`#dc2626`）。**一律實線**（無虛線）。 |
| **輸出到名稱** | 自 Q **右側**拉**單段水平**邊至輸出名稱文字框，無轉角、無小圓圈。 |

---

## 四、輸出訊號 (Output Signals)

| 項目 | 規則 |
| --- | --- |
| **位置** | Cell 右方；**Cell 右緣 → 輸出名稱**淨空固定 **120pt**（`OUTPUT_NAME_GAP`）。若**任一** output 需 O 側 NOT（`outputs_with_not` 非空），**全列**改 **200pt**（+80pt `ROW_GAP`）。 |
| **命名** | 與 rail 名稱相同（如 `SIG_2`）。 |
| **連接** | Q 右側 → 水平 → 輸出名稱文字框左側。 |
| **對齊** | 輸出名稱 y 與 Q 垂直置中，使邊保持水平。 |
| **程式** | `_output_name_channel_gap(any_output_not)` → `output_name_offset_x = CELL_GROUP_W + gap`。 |

---

## 五、連接線 (Connectors / Wires)

| 項目 | 規則 |
| --- | --- |
| **線寬** | 一律 **2pt**（`strokeWidth=2`）。 |
| **交叉** | **弧線跳接**（`jumpStyle=arc`，`jumpSize=6`）。 |
| **線型** | **一律實線**（`dashed=0`）。 |
| **顏色** | 預設黑 `#000000`；Hi 路徑綠 `#059669`；Lo 路徑紅 `#dc2626`。 |
| **正交** | 全圖 **`orthogonalEdgeStyle`**；匯出時以 waypoints **鎖定**通道，避免 Draw.io 重算。 |
| **Source / Destination 連接** | 連到 source 與 destination 時**一律先走水平段**；水平段長度**至少 40pt**（`MIN_HORIZ_STUB = GRID`）。 |
| **不穿越元件** | 走線不得穿過其他 vertex（含 cell、閘、label）；繞道由左幹線區與 gap 內 stub lane 處理。 |
| **重疊** | **相同 source**：允許**水平**重疊、**垂直**不重疊。**不同 source**：水平／垂直皆盡量錯開（固定規則，不可調）。 |
| **Input** | 右→左每欄 40pt；前一個有 NOT 則下一個再左 40pt；NOT 底 = 最上 Cell 上 −40pt；label 底 = NOT 頂 −20pt；**先下後右**。 |
| **閘 output** | AND/NOR output→下一級 input：**同 Y 直連**；否則先 **(1+n)×40pt**（n = 需 stub 的閘序，**不含**僅一條水平直連 output 的閘）再轉。**跨列**亦在 **同一 stub lane x** 上垂直，再水平進 target（不再另走 cell 右側 `_ChannelAllocator` 幹線）。 |
| **Waypoints** | 簡單邊可 0 點；複雜邊 2／4 點；**不清除** waypoints。 |
| **NOT 後 inv 邊** | Pass 3 將 inv 邊 source 改接 NOT 輸出；自 NOT **右側**水平出發連至 AND/OR。 |

---

## 六、檢查清單

- [ ] 左→右：輸入 →（NOT 區）→ 通道 → AND → OR → Cell → 輸出名稱。
- [ ] Input：自 label **右側水平**出發；config 順序堆疊；有 NOT 者下一個 input 在 NOT 下方。
- [ ] NOT：input 右 80pt／下 40pt；output O 比照；同一 `(d, use_mode)` 共用一顆。
- [ ] Cell：4 個獨立 mxCell；Hi 綠、Lo 紅、皆實線；O→名稱水平無轉角。
- [ ] 走線：2pt、arc jump、正交；source/dest 水平段 ≥ 40pt；不穿元件。
- [ ] 重疊：預設同 source 可水平重疊；垂直段 y 重疊者分不同 x 通道。
- [ ] AND↔OR↔Cell 水平間距：依第八節公式（n、m、fb、豁免）；非固定 40pt。
- [ ] 同 Y 直連：AND/OR output 與下一級 input 同軸時，欄間少 1 格（40pt）。
- [ ] 已知區段差異：左幹線／中間 gap／Y slack 計數是否需與第八節對齊（見**第九節**）。

### 常數摘要

| 常數 | 值 | 說明 |
| --- | --- | --- |
| GAP | 40 | 固定格距（input↔回授↔AND 等）；**不含** AND↔OR↔Cell 動態欄寬。 |
| ROW_GAP | 80 | 列距、input 上 AND、`NOT_OFFSET_X`、多 AND 垂直距。 |
| GRID | 40 | 格距；`NOT_OFFSET_Y`（下 40pt）、`NOT_TURN_X`（水平折返 +40pt）、水平連接最短段。 |
| INPUT_NOT_ABOVE_CELL | 40 | input NOT 底邊至最上 Cell 上緣淨空（40pt 對齊）。 |
| INPUT_NOT_LABEL_TO_NOT_GAP | 20 | label 底邊至 NOT 頂（= `INPUT_LABEL_H`，`INPUT_NOT.xml`）。 |
| INPUT_NOT_LEFT | 20 | input NOT 在 label 左側偏移。 |
| INPUT_LABEL_W / H | 80 / 20 | 輸入標籤寬高。 |
| NOT_GATE_W / H | 40 / 20 | NOT 閘（`NOT.xml`）。 |
| NOT_OFFSET_X / Y | 80 / 40 | NOT 左上角相對 label 右緣／上緣（或 O 右緣／上緣）。 |
| NOT_TURN_X | 40 | label/O→NOT 水平折返距離。 |
| NOT_STACK_GAP | 20 | NOT 下方至下一 input／output 列的間距。 |
| OUTPUT_NAME_GAP | 120 | Cell 右緣 → 輸出名稱欄淨空（pt）。 |
| OUTPUT_NAME_NOT_EXTRA | 80 | 任一 output NOT 時全列再加（= ROW_GAP）。 |
| EDGE_STROKE_WIDTH | 2 | 線寬。 |
| EDGE_JUMP_STYLE / SIZE | arc / 6 | 交叉跳接。 |
| STROKE_HI / LO / DEFAULT | #059669 / #dc2626 / #000000 | 線色。 |

---

## 七、匯出（GUI / CLI）

- **GUI**：**Export Draw.io**（Ctrl+E）直接開啟存檔對話框，走線重疊規則固定為 `DrawioExportOptions.defaults()`（同 source 水平可重疊、其餘不重疊）。
- **CLI**：`json2drawio.py` 同樣使用上述預設值。

| 規則 | 值 |
| --- | --- |
| 同 source：水平重疊 | 允許 |
| 同 source：垂直重疊 | 不允許 |
| 同 destination：水平重疊 | 不允許 |
| 同 destination：垂直重疊 | 不允許 |

選項型別：`DrawioExportOptions`（`drawio_export_options.py`），僅供程式內部／`layout_engine` 使用，GUI 不提供調整。

---

## 八、欄位水平間距（AND / OR / Cell）

AND 欄與 OR 欄、Cell 欄之間的水平淨空由全圖計數決定，**所有列共用同一 gap 數值**（但無 OR 的列只用到 AND→Cell；有 OR 的列用到 AND→OR 與 OR→Cell）。

### 共通規則（Gate Channel Gap）

閘與 Cell 之間的 X 通道區，不論拓撲為 **AND→Cell** 或 **AND→OR→Cell**，每一段皆用**同一公式**；差別只在該段的 `base`／`fb`／`exempt` 參數。

```text
segment_pt = max(0, base + 2 + fb − exempt + gn×2) × 40
```

| 項 | 意義 |
| --- | --- |
| **base** | 該段要容納的閘 output **stub lane** 數（全圖 AND 總數 **n**，或 OR 總數 **m**） |
| **+2** | 通道區**兩側各 1 格 GAP**（= Input→AND 幹線前後 GAP 同義） |
| **fb** | 該段需額外留給 **feedback 走線** 的格數（依段而異，見下） |
| **exempt** | 可**水平直連**、不需垂直 stub 的 AND/OR 數（同 Y 且無跨列 AND 回授） |
| **gn** | 該段 **AND/OR output 接 NOT** 的閘數；每顆 **+2 格（+80pt）**、**+40pt 下方**保留（見 `reference/AND_NOT.xml`、`OR_NOT.xml`） |

程式：`_gate_gap_width(base, fb, exempt)`；各段參數由 `_compute_row_gate_layouts` 代入。

#### 結構 A — AND→Cell（該列 hi/lo 皆無 OR）

僅 **一段**：

```text
AND 右緣 ──[ base=n, fb=fb_cell, exempt=exempt_ac ]──► Cell 左緣
```

#### 結構 B — AND→OR→Cell（該列某 band 有 OR，即 groups ≥ 2）

**兩段**（公式相同，參數不同）：

```text
AND 右緣 ──[ base=n, fb=fb_or, exempt=exempt_ao ]──► OR 左緣
OR  右緣 ──[ base=m, fb=fb_cell, exempt=exempt_oc ]──► Cell 左緣
```

| 結構 | 段 | base | fb | exempt |
| --- | --- | --- | --- | --- |
| **A** AND→Cell | AND→Cell | n | fb_cell | exempt_ac |
| **B** AND→OR→Cell | AND→OR | n | fb_or | exempt_ao |
| **B** AND→OR→Cell | OR→Cell | m | fb_cell | exempt_oc |

`power.json` 全圖無 OR → **結構 A**；`RSMRST_N` lo AND 有 `group_inv` → 繪 **NAND**，欄寬與一般 AND 相同（**18 格** = 720pt）。

### 符號（皆為全圖總數）

| 符號 | 定義 | 程式 |
| --- | --- | --- |
| **n** | AND 閘總數 | `_count_total_and_gates` |
| **m** | OR 閘總數 | `_count_total_or_gates` |
| **fb** | **Cell fb**：跨列、**use=self** 的 output → 下游 **H_Deb/L_Deb**（同一 source 只算 1；PG 不算）。**不含** use=hi/lo 邏輯鏈、**不含** 進 AND/OR | `_count_cell_fb_to_deb` |
| **fb_or** | 有 OR 路徑上，來源為 **output** 的不重複 signal（AND→OR 欄；非 Cell→Deb fb） | `_count_total_output_deps_to_or_path` |
| **+2** | 通道區**兩側各 1 格**固定邊界（= **GAP×2**），對應 Input→AND 的「幹線前 GAP + 幹線後 GAP」 | — |
| **exempt** | 可水平直連、不需垂直 stub 的 AND/OR 數（見下） | `_count_direct_horizontal_exempts` |

### 基本公式

```text
gap_pt = max(0, base + 2 + fb − exempt) × 40
```

其中 `base` 為 **n**（AND 相關欄）或 **m**（OR→Cell 欄）。

### +2 與 Input→AND 的對應

整張圖的 X 通道區都採**「兩側各 1 格 GAP + 中間走線格」**：

```text
Input → AND：  [GAP] + feedback_n×40 + [GAP]  → AND 左緣
AND → OR/Cell：[GAP] + (n + fb − exempt)×40 + [GAP]  → 下一欄左緣（含在單一 gap 寬內）
```

- Input→AND 在程式裡是**分開**兩段 `GAP`（`post_input_x` 與 `and_col_x` 之間夾回授幹線）。
- AND→OR／AND→Cell／OR→Cell 則把**同一語意**的 2 格併入公式常數 **+2**，與中間的 **n**（或 **m**）、**fb**、**exempt** 加總後一次算出欄寬。

因此 **+2 = Input→AND 的 GAP×2**（出口側 1 格 + 入口側 1 格）；中間格數則依各區段計數不同（左側用 `feedback_n`，AND 右側用 `n + fb − exempt`）。其餘未統一項目見**第九節**。

> 「三種 gap」= 共通規則在結構 A/B 各段的參數表（見上）。

### 三種 gap（參數對照）

| 情境 | base | fb | exempt | 用途 |
| --- | --- | --- | --- | --- |
| **無 OR 列**（結構 A） | n | fb_cell | exempt_ac | AND 右緣 → Cell 左緣 |
| **有 OR 列**（結構 B）— AND→OR | n | fb_or | exempt_ao | AND 右緣 → OR 左緣 |
| **有 OR 列**（結構 B）— OR→Cell | m | fb_cell | exempt_oc | OR 右緣 → Cell 左緣 |

程式：`_gate_gap_width(n, fb, exempt)` → `_compute_row_gate_layouts`。

### 同 Y 直連豁免（exempt）

若 AND/OR 的 output 與下一級 input **同 Y 軸**（中心 Y 相差 ≤ 2pt），且**沒有**跨列回授到其他列 **AND input**（回授必走垂直，**不得 exempt**），則在對應 gap 公式中 **exempt += 1**（少留 1 格 = 40pt）。

| exempt | 條件 |
| --- | --- |
| **exempt_ac** | 該 band **無 OR**；AND 同 Y 對齊 H_Deb/L_Deb；**無**跨列→他列 AND（`use=hi/lo/self` 皆算） |
| **exempt_ao** | 該 band **有 OR**；AND 同 Y 對齊 OR；**無**跨列→他列 AND |
| **exempt_oc** | 該 band **有 OR**；OR 同 Y 對齊 Deb |

中心 Y 參考：H_Deb `py+20`、L_Deb `py+60`、Hi OR `py+20`、Lo OR `py+60`（OR 高 40pt）。

### 範例（`output/power.json`）

| 項目 | 值 |
| --- | --- |
| n | 16 |
| m | 0 |
| fb_cell | **2**（`PCH_PWROK`、`RSMRST_N`；use=self 跨列進 Deb） |
| exempt_ac | **2**（`PCH_P3V3A_EN`、`PCH_PWROK`；其餘 hi AND 有跨列→他列 AND 回授或 Y 不對齊） |
| feedback_n（左側，對照） | 6（240pt 幹線區；見第九節①） |
| AND→Cell 格數 | 16 + 2 + **2** − **2** = **18** |
| AND 右 → Cell 左 | **720pt** |

---

## 九、通道規則：已對齊項目與已知差異

本節記錄 X/Y 版面在**設計意圖**與**現行程式**之間尚未完全統一之處（**不含** Cell→OutputName 右側 `_ChannelAllocator`，該段本來就採不同模型）。後續若收斂為「全圖一套公式」，可優先處理標 ★ 者。

### 已對齊

| 項目 | 說明 |
| --- | --- |
| **+2 = GAP×2** | Input→AND 幹線前後各 1 格，與 AND→OR/Cell 公式常數 **+2** 同義（第八節）。 |
| **40pt 格距** | 各區段通道皆以 `GRID`／`GAP` = 40pt 為 1 格。 |
| **AND↔OR↔Cell** | 三種 gap 共用 `_gate_gap_width`；差別只在 `base`／`fb`／`exempt` 參數。 |

### 已知差異

#### ① ★ 左側幹線格 vs 中間走線格（計數模型不同）

兩側 **+2** 已對齊。AND→Cell 的 **fb** 已改為 **Cell output→Cell Deb**（`use=self`、跨列）；**不含** use=hi/lo 進 Deb、**不含** 進 AND。左側仍用 `feedback_n`（跨列→AND 幹線）。

| | Input→AND（左側） | AND→Cell（中間 fb） |
| --- | --- | --- |
| 中間格 | `feedback_n` | `n + fb_cell − exempt` |
| fb 算什麼 | 跨列→AND 幹線 | 跨列 **use=self** → 下游 **Deb** only |

`output/power.json`：`feedback_n=6`，`fb_cell=2`，`n=16`，`exempt_ac=2` → 16+2+2−2=**18** 格（720pt）。

#### ② 左側「預留寬度」vs「實際走線」

| 項目 | 現況 |
| --- | --- |
| 預留 | `left_channel_w = feedback_n × 40`；`channel_x_left = post_input_x`（區域**左緣**固定一個 x） |
| 分配 | **無** `_ChannelAllocator`；未在幹線區內逐條分 lane |
| Input→AND | 走 label **`x+40` bus**，**不佔**幹線區 |
| 跨列 output→AND | 多數走 **cell 右緣 stub → `and_col_x`**（`wire_hv_to`），未必用滿 `feedback_n` 條垂直幹線 x |
| 中間段 | AND/OR 用 `_GateExitLanes.stub_x` 在 gap 區內向右 stub |

→ 左側是「依 trunk 數砍寬度」，走線機制與中間 stub lane **不同**。

#### ③ ★ X 軸回授 vs Y 軸回授

| | X 左側 `_count_feedback_trunks` | Y 三層 slack（第十節） |
| --- | --- | --- |
| 範圍 | **只算跨列** → AND | AND：跨列 output→AND + Input 直連後級；OR／Cell 見第十節 |
| 去重 | 來源 AND 編號去重；RSMRST 1 條 | **各層 gap 去重**（每 gap 最多 +40pt） |
| `power.json` | 6 格 → 240pt 幹線區 | AND 8 gap／320pt；Cell 9 gap／360pt |

回授在 **X 砍寬**與 **Y 加 slack** 的計數範圍仍不完全相同（X 不含 Input 直連）；Y 三層規則已統一去重。

#### ④ 中間段內部：三種 gap 參數各異

即使共用 `_gate_gap_width`，**base**／**fb** 仍分三套：

| gap | base | fb |
| --- | --- | --- |
| AND→Cell | **n** | fb |
| AND→OR | **n** | **fb_or**（僅 OR 路徑上的 output） |
| OR→Cell | **m** | fb |

同一張圖若混有「有 OR／無 OR」列，`cell_start_x` 會**因列而異**（無 OR 列用 `gap_and_cell`，有 OR 列用 `gap_and_or` + `gap_or_cell`）。

#### ⑤ 靜態公式 n vs 動態 `_GateExitLanes`

| | 欄寬公式 | 實際走線 |
| --- | --- | --- |
| 假設 | **n** = 全圖 AND/OR **catalog 序**（#1 起） | `stub_x` = 閘右緣 + **(1+n)×40pt**（固定，非 per-edge 遞增） |
| 風險 | 一顆 AND 只預留 1 格 | 同一 cell 多條回授邊時，stub 深度可能 **> 1 格** |

#### ⑥ exempt 僅適用 X 中間段

同 Y 直連的 **exempt** 只減 AND→OR/Cell 的 gap；**不**減左側 `feedback_n`、**不**減 Y 軸 slack。若回授理論上可水平直穿，左/Y 仍照原規則留空。

#### ⑦ Input 欄寬度（獨立公式）

Input 區寬度由 `_input_band_width` 決定（每 input 40pt、有 NOT 者再堆疊），**不在** `n+2+fb` 體系內。屬獨立左端區塊。

#### ⑧ Cell→OutputName（固定淨空）

Cell 右緣至輸出名稱：**120pt**；若圖中**任一** output 需 O 側 NOT，**所有列**皆 **200pt**（120+80）。跨列 output→OR／Deb 等走 **stub lane**（`(1+n)×40`），不再另分配 cell 右側垂直幹線。

### 收斂方向（備忘，非現行規則）

若將來要統一 Input→AND 與 AND→Cell，常見優先序：

1. ★ 對齊 **fb** 與 **feedback_n** 的計數範圍（跨列／同列、去重鍵）。
2. ★ 對齊 **X 幹線**與 **Y slack** 的回授計數。
3. 左側幹線區是否改為 `_ChannelAllocator` 或與中間共用 stub 模型。
4. 將 **exempt** 語意延伸到左/Y（若設計上需要）。

---

## 十、Y 軸三層 slack（AND／OR／Cell 統一規則）

三層邏輯閘與 Cell 列距共用同一套**垂直走線留空**模型：在該層**相鄰元件**之間多留 **40pt**（`GRID`），**同一 gap 去重**（`_mark_y_gap`／直接賦值 `GRID`）。

**通則：** 本級需為跨列 **output 回授到本級 input**，或 **Input 直連後級 input**（**Input→AND 不算**）時，在該層最近間隙加 slack。

| 層 | 相鄰元件 | 函式 | 觸發條件 |
| --- | --- | --- | --- |
| **AND／NAND** | global catalog 相鄰兩顆 | `_feedback_y_slack_after_and` | 跨列 **output→AND input**；**Input 直連 OR／NOR／Cell**（`len(group)==1`） |
| **OR／NOR** | global catalog 相鄰兩顆 | `_feedback_y_slack_after_or` | 跨列 **Cell fb→OR input**（OR 列、`len==1` output）；**Input 直連 Cell**；**AND 直連 Cell**（無 OR 列、`len≥2`） |
| **Cell** | 相鄰兩 **output 列** | `_feedback_y_slack_between_cell_rows` | 跨列 **Cell output（use=self）→ 下游 H_Deb／L_Deb** |

**鍊式定位：**

- AND／NAND：`_chain_and_top_y`（既有）
- OR／NOR：`_chain_or_top_y`（global 序；同列 Hi→Lo +40pt；跨列 +80pt + slack）
- Cell：`row_y_base` 累加時在 `ROW_GAP` 後再加 `cell_row_slack[row]`（gap `j` = row `j` 與 `j+1` 之間，0-based）

**與 X 軸 fb 的關係：** X 仍用 `fb_cell`／`fb_or`／`feedback_n` 砍欄寬；Y slack **獨立**撐開垂直間距，兩者互補。

**`power.json` 典型值（去重後）：** AND slack 8 gap／320pt；Cell 列 slack 9 gap／360pt；無 OR 路徑故 OR slack 為 0。

---

## 相關檔案

| 檔案 | 說明 |
| --- | --- |
| `src/drawio_export.py` | `generate_drawio(config, options=...)` 主匯出邏輯。 |
| `src/drawio_export_options.py` | 走線重疊規則 dataclass（固定預設值）。 |
| `src/layout_engine.py` | 可選 `layout_drawio()` 後處理**外部** XML（`route_orthogonal`、`minimize_crossings` 等）；**主匯出不經此路徑**。 |
| `src/reference/NOT.xml` | NOT 閘元件參考。 |
| `src/reference/LayoutRef.xml` | Input + NOT 版面與走線參考。 |
| `src/reference/LayoutRef_Output_With_NOT.drawio.xml` | Output O + NOT 參考。 |
| `doc/需求表.md` | F-DIO-01～F-DIO-16 需求對照。 |
