---
name: 1D All 歸約加下界
overview: "把 1D 被引用訊號的 All AND/OR 取法擴充成 `|oneDim[NUM_ROW-1 : n]`（NUM_ROW > n >= 0），n=0 時輸出與現在完全相同。範圍只作用於 1D row 軸，不影響 2D。"
todos:
  - id: take-expr-lo
    content: "take_expr: Take 加 lo，_one_dim 支援 |bus[ROW-1:lo]，lo=0 維持 |bus；tests/test_take_expr.py 紅→綠"
    status: in_progress
  - id: ir-row-size
    content: cond_ir TakeRef 加 row_size，resolve_item 從 dim_params[0] 帶入；tests/test_take_ir.py
    status: pending
  - id: take-rules-n
    content: "take_rules: ALL_ROW_AND/OR 加 n 欄，form_to_take/take_to_form round-trip；tests/test_take_rules.py"
    status: pending
  - id: validator-lo
    content: "validator: 0 <= lo < 最大 NUM_ROW；tests/test_validator.py"
    status: pending
  - id: gui-n
    content: "widgets: All 形狀子選項多 n 欄；tests/test_gui_take.py"
    status: pending
  - id: ci-docs
    content: ci.bat 全綠、golden byte 不變；同步 ROADMAP.md 與 PseqGeneratorNewFunction.txt §6
    status: pending
isProject: false
---

# 1D All 歸約加下界

目標：`|oneDim` 改成 `|oneDim[NUM_ROW-1 : n]`，`NUM_ROW > n >= 0`。n 是整數常數，表示 row 下界。n=0 時輸出仍為 `|oneDim`（與現在 byte 相同）。

## 設計
- **取法資料**：[src/core/take_expr.py](src/core/take_expr.py) 的 `Take` 新增 `lo: int = 0`，只給 `kind=ALL` 用。`take_from_dict` / `form_to_take` 只在 `lo != 0` 時寫入 `"lo"` 鍵，舊檔與黃金輸出不變。
- **渲染**：`_one_dim` 新增 `row_size` 參數（NUM_ROW 符號）。`lo == 0` 輸出 `|bus`；`lo > 0` 輸出 `|bus[NUM_ROW-1 : lo]`。2D 的 `_two_dim` 不變。
- **IR 傳遞**：[src/core/cond_ir.py](src/core/cond_ir.py) `TakeRef` 新增 `row_size: str = ""`，由 `resolve_item` 從被引用 rail 的 `dim_params[0]` 帶入（與現有 `col_size` 同一做法）。只改資料傳遞，不改語意。
- **取法規則**：[src/core/take_rules.py](src/core/take_rules.py) 的 `ALL_ROW_AND` / `ALL_ROW_OR` 加 `needs=(("n", "下界"),)`，`default_form` 的 n 仍為 0；`form_to_take` / `take_to_form` 補上 n 的 round-trip。
- **驗證**：[src/core/validator.py](src/core/validator.py) 檢查 `0 <= lo`，且 `lo < NUM_ROW` 的最大值（parameter 預設值）。RTL 是符號式，實際 N 小於最大值時的越界由使用者負責，這點要在訊息中說明。
- **GUI**：[src/gui/widgets.py](src/gui/widgets.py) 的取法子選項列，All 形狀多一個 n 數字欄（沿用 `ROWOFF_*` 的 n 欄寫法）。

## 不做的事
- 2D 不支援範圍（跨步歸約，§3.5）。
- n 不接受 parameter 算式，只接受整數。
- 不改 `cond_ir` 的節點種類，不動 Verilog 以外後端（C / sim / drawio / timing 維持 NotImplementedError 佔位）。

## 驗證
- `tests/test_take_expr.py`：`lo=0` 輸出 `|bus`；`lo=1` 輸出 `|bus[NUM_ROW-1 : 1]`；AND 同理。
- `tests/test_take_rules.py`：ALL 形狀含 n 欄、n round-trip。
- `tests/test_take_ir.py`：`TakeRef.row_size` 由 `dim_params[0]` 帶入。
- `tests/test_validator.py`：n<0、n≥最大 NUM_ROW 回報錯誤。
- `tests/test_gui_take.py`：All 形狀顯示 n 欄，寫回 `model.take["lo"]`。
- `ci.bat` 全綠，`tests/golden/` byte 不變。
- 文件：ROADMAP「§6 取法 UI」補一行，PseqGeneratorNewFunction.txt §6 補 `|oneDim[NUM_ROW-1 : n]` 形狀。