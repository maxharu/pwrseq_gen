---
name: dimension-slice-model
overview: 整組移除 parametric 自由運算式，改以「維度 + slice」模型重建條件授權；先落地不涉及條件內容的骨架（parameter 維度、signal 0/1/2 維宣告、Verilog 宣告字串），後續階段再做 take 選項與 slice。
todos:
  - id: stage-a-remove
    content: 階段A：移除 parametric 全鏈路（pexpr/pexpr_build 模組、config_models ParametricNode 與 pexpr_*/param_node、verilog/c/sim/validator 的 parametric 路徑、widgets ParametricCondFrame 與建構器、相關測試）；ci.bat 全綠且 golden byte 不變
    status: pending
  - id: stage-b-param-dim
    content: 階段B：Parameter 維度骨架（PowerSeqConfig.dimensions 0~2、預設=最大值、round-trip、ParameterPanel 維度個數下拉、validator 驗證、測試與文件）
    status: pending
  - id: stage-c-signal-dim
    content: 階段C：Signal 維度宣告骨架（0/1/2 維→width_expr、dim_params 儲存、GUI 維度下拉＋Bits []x[]、Verilog [P1*P2-1:0] 宣告、測試與文件）
    status: pending
isProject: false
---

# 以「維度 + slice」取代 parametric：分階段實作計畫

依 `PseqGeneratorNewFunction.txt`。本輪決策：**parametric 整組移除**、**先搭骨架**、**先出計畫**。每階段遵守 workflow：紅測試 → 最小實作 → `ci.bat` 全綠 → 文件同步；commit/push 僅在你明確要求時才做。golden 位元鎖維持（`tests/golden/*`）。

## 已確認的前提與後果
- `tests/golden` 未使用 parametric，移除後 `demo.v/.c/.drawio/demo_sim/demo_schemdraw` 應 byte 不變。
- `src/core/param_expr.py`（`eval_width`）與 `test_param_expr.py` 是**寬度公式**，非 parametric，保留且後續 2D `P1*P2` 會用到。
- **不保留逃生口**：x15 的遮罩歸約 / OR-NOT 組合 / runtime mux（前述缺口 A/E/C）在骨架與近期階段無法表達，延到後續 take/slice 階段再評估，屬已接受限制。
- 舊 config 若含 `"parametric"` 區塊：`from_dict` 改為**忽略並由 validator 給警告**，不崩（預設做法，非硬錯）。

## 階段 A — 移除 parametric（清地基，保持全綠）
目標：刪掉 parametric 全鏈路，`ci.bat` 綠、golden byte 不變。
- 刪模組：`src/core/pexpr.py`、`src/core/pexpr_build.py`。
- `src/core/config_models.py`：移除 `ParametricNode`、`PowerRail.pexpr_hi/lo/force`、`param_node`、`_param_group_to_dict`、`_expand_parametric_dict`、`_group_to_dict` 的 `head.param_node` 分支、`_VECTOR_META_KEYS` 的 `"parametric"`、`from_dict` 的 `if "parametric" in r` 分支、`from core import pexpr`。
- `src/codegen/verilog_generator.py`：移除 `_emit_parametric_cond`、genvar 宣告區塊（約 437-453）、`param_node` 分支、`import pexpr`。
- `src/codegen/c_generator.py`：移除 `_c_param_body` 與 `r.pexpr_*` 分支（約 384-391）、`import pexpr`。
- `src/timing/timing_sim.py`：移除 pexpr 具體求值路徑（約 629-677）、`import pexpr`。
- `src/core/validator.py`：移除 `check_parametric` 與其呼叫（103-152、293-294）、`import pexpr`。
- `src/gui/widgets.py`：移除 `ParametricCondFrame` 與 `_ParamKind/_ParamBranch/_ParamTermRow`、`var_param`/`_chk_param`、`_get_parametric_rails`、`_apply_param_availability`、param tab 接線、`pexpr`/`pexpr_build`/`ParametricNode` 匯入。
- 刪測試：`test_parametric_model/verilog/c/wire.py`、`test_pexpr.py`、`test_pexpr_build.py`、`test_gui_parametric.py`（`test_param_generators.py` 先確認是 parameter 發射而非 parametric，是則保留）。
- 驗收：`ci.bat` 全綠；`test_golden_exports.py` byte 不變。

## 階段 B — Parameter 維度（骨架 1）
目標：parameter 具備 0~2 個「全域維度」概念，預設值＝最大值。
- 模型：`PowerSeqConfig` 新增 `dimensions: list[str]`（0~2 個，指向既有 `parameters` 中的名稱；該 parameter 的 `value` 即最大值）。`to_dict/from_dict` round-trip；空則不輸出該鍵（保持既有 config byte 不變）。
- GUI：`src/gui/panels.py` `ParameterPanel` 加「維度個數 [0/1/2]」下拉，並標示哪些 parameter 是維度1/維度2。
- 驗證（`validator.py`）：維度數 0~2；維度名需存在於 parameters、不重複；最大值 ≥ 1。
- 紅測試：`test_parameters.py`/新 `test_dimensions.py` 覆蓋 round-trip 與驗證。
- 文件：`README`/`ROADMAP` 說明維度概念。

## 階段 C — Signal 維度宣告（骨架 2）
目標：signal 可選 0/1/2 維，宣告頁 Bits 改 `[]x[]`，產出對應 Verilog 宣告。
- 模型：signal 維度 → `width_expr`：0→`"1"`（純量）、1→`P1`、2→`P1*P2`（沿用 `VectorNode`/`width_expr` 與 `eval_width`）。於 vector 群組 dict 與 `PowerRail` 存 `dim_params: list[str]`（所選 0~2 維名），供後續 take/slice 認得 row=P1 / col=P2。
- GUI：`src/gui/widgets.py` `RailEditorFrame` 宣告列把「Vector 勾選＋width 輸入」改為「維度 [0/1/2]」下拉＋Bits 兩個 parameter 下拉（預設 1）；移除 Parametric（A 已刪）。
- Verilog：確認 `_width_prefix`/`_width_msb` 對 `P1*P2` 產出 `[P1*P2-1:0]`；必要時對齊文件寫法 `[<P1> * <P2> - 1:0]`。
- 紅測試：宣告 round-trip、0/1/2 維 Verilog 宣告字串；新測試自帶小 config，demo golden 不動。
- 文件：同步「Signal 宣告」節與 UI 畫面。

## 後續階段（本輪不展開，列出供排序）
- D：take 選項（Same / Specific(+相對偏移) / All AND|OR）IR + Verilog（文件 3.2–3.6）。
- E：slice（符號述詞、分組標籤、else、row/col 軸）IR + generate-for 發射（文件 4）。
- F：C / sim / drawio / excel 後端接上新條件。
- G：GUI 條件頁（slice 群組 + take 下拉 + 選擇器切換編輯器，文件 4.4）。

## 風險與回溯點
- 每階段結束 `ci.bat` 全綠且 golden byte 不變才進下一階段；A 是純移除，若 golden 變動代表誤觸向量/純量路徑，須回溯。
- B/C 的儲存欄位（`dimensions`、`dim_params`）是後續 take/slice 的地基，命名與語意一旦定稿盡量不改。