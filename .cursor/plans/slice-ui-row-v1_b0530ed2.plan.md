---
name: slice-ui-row-v1
overview: 為維度訊號實作 V1 的 row-axis slice：GUI 以「每-row 下拉標籤 + 群組選擇器」取代維度向量的 per-bit 選擇器，底層以「扁平 depends_on_* = else、cond.slices = 非 else 群組」儲存，Verilog 以 generate-for 的 if/else-if/else 展開；col 與兩軸同切列為後續階段。
todos:
  - id: red-tests
    content: 先寫紅測試：config slices round-trip + 舊檔缺鍵相容 + 不切片位元不變；resolve_sliced_condition 分支；verilog row-sliced 的 if/else-if/else；validator 不可達警告；gui 群組選擇器取代 bit 選擇器。
    status: pending
  - id: model
    content: config_models.ConditionConfig 加 slices 欄位 + to_dict/from_dict（非空才寫、缺鍵=不切片）。
    status: pending
  - id: ir
    content: cond_ir 加 resolve_sliced_condition 與述詞 helper；不切片回單一 (None, tree)。
    status: pending
  - id: verilog
    content: verilog_generator._emit_dim_vector_cond 改走 branches，多組展開 if/else-if/else。
    status: pending
  - id: backends-guard
    content: c_generator/timing_sim/drawio_cell_export/timing_export 對有 slices 的訊號 raise NotImplementedError 佔位。
    status: pending
  - id: validator
    content: validator 對代表值 N 下不可達述詞發警告。
    status: pending
  - id: gui
    content: RailEditorFrame 維度向量：Row 分組下拉 + 群組選擇器取代 per-bit；Apply 寫 else=扁平、非 else=cond.slices。
    status: pending
  - id: ci-docs
    content: ci.bat 全綠、golden byte 不變；同步 PseqGeneratorNewFunction.txt §4.4 與 ROADMAP.md。
    status: pending
isProject: false
---

# Slice UI — V1 row-axis 切片

## 範圍
- V1 只做 **row 軸** slice，作用於 1D 訊號與 2D 訊號的 row 軸；col slice 與「兩軸同切」為後續階段。
- 成員指定用 **每-row 下拉標籤**（枚舉 `0..max-1`）；`max` 取自 `dim_params[0]` 對應 `Parameter.value`。
- 維度向量（`dim_params` 非空）的條件頁，用 **切片軸(固定 row，V1 隱藏下拉) + Row 分組面板 + 群組選擇器** 取代現有 per-bit `Bit:` 選擇器；legacy 非維度向量維持 per-bit 不變。
- 群組管理最小化：row 下拉「新增...」長群組、空群組自動移除、`else` 恆在底且唯一不可刪改；V1 無上移/下移。

## 資料模型（相容性為核心）
- 在 [src/core/config_models.py](src/core/config_models.py) 的 `ConditionConfig` 新增 `slices` 欄位：有序的「非 else 群組」清單，每組 = `pred`(符號述詞字串，如 `gv_row==0 || gv_row==1`) + 與扁平同構的 `depends_on_{hi,lo,force}_{groups,inv_groups,use_groups,group_inv,intra_op,take_groups}`。
- **扁平 `depends_on_*` 永遠就是 else / catch-all 組**；`slices` 只裝非 else 群組。
- `to_dict` 只在 `slices` 非空時寫出 `slices` 鍵；`from_dict` 缺鍵 → 空 → 不切片。→ 舊 JSON 自動相容、不切片訊號序列化位元不變、`tests/golden/` 不動。

## 條件語意（IR 單一來源，見不變量 4）
- 在 [src/core/cond_ir.py](src/core/cond_ir.py) 新增 `resolve_sliced_condition(rail, kind, name_to_rail) -> list[tuple[str | None, CondTree]]`：每個非 else 群組一筆 `(pred, tree)`，最後一筆 `(None, flat_else_tree)`。每組條件走與現有 `resolve_condition` 完全相同的 group/inv/use/intra_op/take 解析。
- 不切片 → 回傳單一 `[(None, resolve_condition(...))]`，既有行為不變。
- 述詞渲染（枚舉 row → `gv_row==k || ...`）放在 `cond_ir` 的小 helper，不寫進後端。

## Verilog 展開
- 改 [src/codegen/verilog_generator.py](src/codegen/verilog_generator.py) 的 `_emit_dim_vector_cond`（約 208-237 行）：每個 kind 從 `resolve_sliced_condition` 取 branches。單筆（不切片）維持現在的單行 `assign`；多筆則在 for 內層展開 `if (gv_row pred) assign ...; else if ... ; else assign <else>;`，2D 時包在 `gv_col` 內層迴圈體外層（row 述詞用 `gv_row`）。

## 其他後端（V1 範圍閘）
- `c_generator` / `timing_sim` / `drawio_cell_export` / `timing_export`：偵測到訊號有 `slices` 時 `raise NotImplementedError` 佔位（沿用 take 擴充當時的做法）；不切片路徑完全不動。

## 驗證
- 改 [src/core/validator.py](src/core/validator.py)：代表值 N(=`Parameter.value`) 下某述詞不可達 → **警告**（不報錯）；絕對 row ≥ 實際 N 不觸發也不報錯。

## GUI
- 改 [src/gui/widgets.py](src/gui/widgets.py) 的 `RailEditorFrame`：維度向量時以群組選擇器取代 `Bit:` 選擇器（`_sync_bit_selector` / `_build_bit_editor` 分支）。
  - Row 分組面板：列 `row0..max-1`，每列一個下拉 `[現有群組..., else, 新增...]`。
  - 群組選擇器：切到哪組就在單一編輯 host 顯示該組的 Hi/Lo/Force `CondSectionFrame`（沿用 `CondEditModel`）。
  - Apply：else 組寫回扁平 `depends_on_*`，非 else 群組寫回 `cond.slices`；空群組移除。

## 文件同步
- `PseqGeneratorNewFunction.txt` §4.4：標註 V1 已實作範圍（row 軸、每-row 下拉）與尚未（col/兩軸）。
- `ROADMAP.md`：slice 由「未實作」更新為「V1 row-axis 完成」。

## 不做
- col 軸、兩軸同切、區段選擇器（第一個/最後一個/前 k）、上移/下移重排 → 後續階段。
- 不改 `cond_ir` 既有節點種類、不改五後端的不切片路徑行為。
