# Draw.io routing — code map

## FB 常數（`drawio_export.py`）

| 常數 | 值 | 用途 |
|------|-----|------|
| `FB_Q_RIGHT` | `GRID` (40) | Cell Q ①右移 |
| `FB_Q_UP` | `GRID + 20` (60) | Q／gate ②上移 |
| `FB_NQ_RIGHT` | `2 * GRID` (80) | Cell ~Q ①右移 |
| `FB_NQ_UP` | `3 * GRID + 20` (140) | ~Q ②上移（> Q 60pt） |
| `STROKE_FEEDBACK` | `#2563eb` | 回授邊預設藍 |

參考：`src/reference/FB_Routing.xml`、`src/reference/PSEQCELL.xml`（RTL `PSEQCELL.v`）。

## Rule 3 — `_apply_feedback_routing`

| Function | Role |
|----------|------|
| `_feedback_profile` | `src_id` → `"q"` / `"nq"` / `"gate"` |
| `_feedback_edge_tgt_layer` | target id → `"and"` / `"or"` / `"cell"` |
| `_build_feedback_source_layer_slots` | `(src_id, layer) → slot`；**同 source 同層 1 通道** |
| `_feedback_channel_x` | ③ 垂直幹線 X |
| `_cell_fb_channel_base_x` | cell 層 FB 區起點 |
| `_or_fb_channel_base_x` | or 層 FB 區起點 |
| `_vertex_geom` / `_anchor_xy` | exit／entry 錨點 |
| `_apply_feedback_routing` | 五段 waypoints + `_style_to_frozen_none` |
| `_apply_feedback_edge_color` | 藍色；保留 Hi／Lo |
| `_supplement_traced_feedback_edges` | 補標 RSMRST Q／~Q、departing AND |

### 五段座標（實作）

```
p1 = (p1x, ey)           # Q: p1x=ex+40; ~Q: ex+80; gate: stub_x
p2 = (p1x, ey - up)      # ② 一律向上；Q/gate up=60, ~Q up=140
p3 = (p3x, p2y)          # p3x = _feedback_channel_x(layer, slot[(src_id,layer)])
p4 = (p3x, ty)
p5 = (entry_x, ty)
```

`fb_align`: `[(T,F), (T,T), (T,T), (T,F), (T,F)]` — 僅 ②③ 的 Y、③④ 的 X 做 `_align40`。

### Slot 分配（同層水平共用）

```text
for each feedback edge:
  layer = _feedback_edge_tgt_layer(tgt_id)
  sources_by_layer[layer].add(src_id)

for layer, sorted(src_ids):
  slots[(src_id, layer)] = min(index, cap-1)
```

扇出：同 `(src_id, layer)` 的多條邊 → 相同 `p3x`、`p2y`；`p4y`／`entry_x` 依目標而異。

## Export finale（`generate_drawio` 末段）

| 順序 | Function | Rule |
|------|----------|------|
| 1 | `_supplement_traced_feedback_edges` | 補 `feedback_auto_edge_ids` |
| 2 | `_apply_feedback_routing` | **Rule 3** |
| 3 | `freeze_edge_routing` | Rule 2（skip input sources） |
| 4 | `restore_orthogonal_auto_routing` | **Rule 1**（input only） |
| 5 | `_apply_feedback_edge_color` | 著色 |
| 6 | `_apply_edge_wire_style` | strokeWidth、jumpStyle |

## 回授邊判定（emit / Pass 1）

| Function | Role |
|----------|------|
| `_build_layout_feedback_dep_keys` | 佈局回授 dep 鍵 |
| `_mark_layout_feedback_edge` | → `feedback_auto_edge_ids` |
| `_mark_traced_layout_feedback_edge` | 回溯標記 |
| `_pass1_is_layout_feedback` | Pass 1 仍為回授 |
| `_wire_and_dep_non_input` | AND 入邊分路 |
| `_count_feedback_trunks` | 左側 `feedback_n` |
| `_departing_and_index` | AND Output trunk # |
| `_count_cell_fb_to_deb` | `fb_cell`（gap 公式，≠ 走線 slot 鍵） |

Scripts: `scripts/list_feedback_paths.py`, `scripts/enumerate_feedback.py`.

## Rule 1 emit

Sets: `in_label_id`, `input_not_src_ids` → `input_auto_src_ids`。

## Rule 2 emit — `_GateExitLanes`（非回授）

| Method | Shape |
|--------|-------|
| *(horizontal)* | 同 Y 直連 |
| `wire_vertical` | 右→上/下 |
| `wire_via_channel` | 右→上/下→右 |

### `use=hi/lo` → H_Deb／L_Deb（單一依賴）

| Function | Role |
|----------|------|
| `_use_hi_lo_deb_placeholder_exit` | `use in (hi,lo)` 且 `from_id ∈ _deb_placeholder_ids` |
| `_style_edge_to_gate_entry` | AND 入邊：同上，logic_out → `exitX=1` |
| emit 單一 hi/lo | `style_*_to_cell_left` vs `style_*_to_cell` 依上式 |
| Pass 1 | 僅 `source ∈ h_deb_ids/l_deb_ids` 且 `exitX=0` → 換 logic pin + `_rewire_pass1_logic_edge` |

## Cell Q／~Q（Pass 2/3）

| Function | Role |
|----------|------|
| `_source_id` | `use=self` → Q；hi/lo → logic_out |
| `_coerce_cell_out_id` | inner→Q／~Q；inv 時 Q→~Q |
| `_logic_output_pin` | 列內邏輯扇出腳 |
| Pass 2 output inv | `not_gate_id` → `nq_box_id_map[d]` |
| Pass 3 | inv 邊 source→~Q；清 emit waypoints |

## Tests

| Test | Asserts |
|------|---------|
| `test_cell_q_feedback_second_segment_always_up` | Q ② = 60pt up |
| `test_cell_nq_feedback_second_segment_up_140pt` | ~Q ② = 140pt up |
| `test_same_source_fb_shares_one_channel_x_per_layer` | 同 source 同層單一 `p3x` |
| `test_hi_use_upstream_and_exits_from_gate_right` | `use=hi` + 上游 AND → `exitX=1` |
| `test_drawio_export_edges_use_orthogonal_or_frozen` | Rule 1 vs 2 分工 |
| `test_gate_exit_lanes.py` | stub、`wire_via_channel` |
