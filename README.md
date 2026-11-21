# Power Sequence Generator (`pwrseq_gen`)

電源時序（Power Sequence）設計工具。以圖形化介面編輯時序節點與條件，並從同一份設定一鍵產生 Verilog／C 程式碼、Draw.io 電路圖、Schemdraw 時序圖，以及 Excel 匯入／匯出範本。

> 平台：Windows（桌面 GUI，使用 CustomTkinter）。

## 功能

- **節點編輯**：Input／Output 節點、Hi／Lo／Force 三段條件、群組內 AND／OR／XOR 運算、debounce 設定；
  **vector 節點**（一個 base 展開成 N 個 bit、每 bit 條件獨立）與 **parameter**（具名整數常數，vector 寬度可用公式引用）。
  條件相依下拉在選取的相依為 vector 時**收合成一筆 base**（不逐 bit 展開）。**legacy 非維度向量**提供消費模式：
  同索引（`base[i]`，對應目前 bit）、全部（`&`，整組 AND）、任一（`|`，整組 OR）、指定 bit；按新增時於 GUI 層展開成具體
  `base[i]` 相依（儲存格式不變）。**維度向量**（有 `dim_params`）則改用相依列上的 **per-row 取法編輯器**（見下，§6）。
  條件分頁的 bit 以**複選框**呈現（Shift 連選）：勾選多個 bit 時為**即時共編**——編輯錨點 bit 會同步套用到其他勾選 bit，
  並自動替換同索引相依（`V[錨點]→V[目標]`，固定索引與 scalar 不動）。
- **全域維度（dimensions）**：parameter 面板直接以「**維度個數 [0/1/2]**」下拉宣告維度——選了 N 就長出 N 列
  「**名稱＋最大值**」欄位，填進去即同時建立該 parameter 並標記為維度1(row)/維度2(col)；本應用的 parameter
  就是維度本身（dims-only，不需另外新增 parameter）。該 parameter 的值即該維度最大值，供「維度＋slice」條件模型
  （取代舊 parametric）辨識 signal 的 2D bus 結構。
- **Signal 維度宣告**：節點宣告頁以「**維度 [0/1/2]**」下拉＋「**Bits**」維度 parameter 下拉取代舊的自由公式寬度欄位：
  0 維＝純量、1 維＝`[P1-1:0]`、2 維＝flat bus `[P1*P2-1:0]`；Bits 下拉只列**已宣告的全域維度**（row=維度1、col=維度2），
  所選維度存進 `dim_params` 供 take/slice 認得幾何；左側 Node 清單與卡片標記對 2 維訊號顯示 `[row×col]`（如 `[2×4]`）、
  其餘顯示 `[×N]`。
- **維度向量取法（§6）**：維度向量引用別的維度向量時，相依列上以「**取法**」下拉＋第二行 n/m 子選項授權合法 assign 形狀
  （`PseqGeneratorNewFunction.txt` §6）。選項/預設/映射由單一規則模組 `core/take_rules.py` 依「輸出維度×被引用維度」決定：
  1 維引用＝相對偏移／指定絕對／全部AND／全部OR（全部AND/OR 可帶 row 下界 n，即 `&oneDim[NUM_ROW-1 : n]`，`NUM_ROW > n >= 0`，n=0 為整條）；2 維引用＝row 偏移＋{指定 col／全 col OR／全 col AND}，輸出 2 維再加
  row 偏移＋col 偏移（含完全對齊 `gv_row*C+gv_col`）。非法組合（§3.4 輸出缺 gv_col、§3.5 跨步 All-row）直接不顯示。
  Verilog 以 generate-for 展開；C／sim／drawio／excel 的維度向量 take 仍為後續階段（Stage F）。slice 尚未實作，詳見
  `PseqGeneratorNewFunction.txt` 與 `ROADMAP.md`。
- **程式碼產生**：
  - Verilog（`verilog_generator.py`）
  - C（`c_generator.py`）
- **圖形匯出**：
  - Draw.io 電路圖（cell-centric 格線佈局，`drawio_*.py`）
  - 時序邏輯模擬引擎（供 Schemdraw 匯出使用，`timing_*.py`）
  - Schemdraw 時序圖（SVG／PNG／PDF，`schemdraw_export.py`）
- **Excel I/O**：`.xlsx`／`.xlsm` 開啟與儲存、Nodes／Conditions／Lists 工作表、xlsm 內建 VBA Sync 按鈕（`excel_import.py`、`excel_export.py`）。
- **即時預覽**：右側面板即時顯示 Verilog／C／Schemdraw，支援字級記憶、Undo／Redo、節點多選與拖拉重排。

## 安裝與執行

### 快速啟動（Windows）

直接執行 `run.bat`，它會檢查 Python、必要時自動安裝相依套件，並啟動程式。

### 手動

需要 Python 3.8 以上。

```bash
pip install -r requirements.txt
python src/main.py
```

## 開發

安裝執行期與開發相依：

```bash
pip install -r requirements-dev.txt
```

執行測試：

```bash
pytest
```

> 測試以 `pyproject.toml` 設定 `pythonpath = ["src"]`，可直接 import `src/` 下的模組。

push / 開 PR 前跑完整 CI（lint + 測試，含黃金輸出比對）：

```bat
ci.bat
```

`.github/workflows/ci.yml` 直接呼叫同一支 `ci.bat`，所以本地與 CI 不會跑到不同指令。
Lint 規則定義在 `pyproject.toml` 的 `[tool.ruff.lint]`：只納管 `F`（真錯誤）、`E9`、
`I`（import 排序）、`RUF100`。

已盤點的技術債與改善順序見 [`ROADMAP.md`](ROADMAP.md)。

## 套件邊界

`codegen` / `drawio` / `excel` / `excel.vba` / `timing` / `pipeline` 各自在 `__init__.py` 宣告 `__all__`，
跨套件呼叫只走這層介面（`from drawio import generate_drawio`），套件內的模組是實作細節。
`core` 是例外——它是共用詞彙表（`PowerRail` / `safe_name` / `DEP_HIGH` …），
維持 `from core.config_models import PowerRail` 這種自我說明的深層 import。

相依方向是單向的：`core` 不相依任何套件，其餘套件往 `core` 走，`pipeline` 在各匯出套件之上，`gui` 在最外層。
Verilog／C／Draw.io／Schemdraw 的匯出一律經 `pipeline.export`：先 `validate`，沒過就不寫檔。
`gui` 與 `tools/json2drawio.py` 都走這個閘。
`excel` 與 `timing` 曾經互相 import、靠函式內的延後 import 才沒在 import 期炸掉，
現在那條環已經斷開（`merge_scenario_for_config` 只操作 `core` 型別，已歸位到 `core`）。

邊界由 `tests/test_package_api.py` 強制，不是靠慣例——包含「相依不得成環」這條，
而且它走 AST，**函式內的延後 import 一樣算**。測試本身不受規範：
白箱測試戳進實作細節是刻意的，那是測試不是契約。

## 專案結構

```
src/
  main.py                  進入點（設定 DPI 後啟動 GUI）
  core/                    資料模型與共用基礎
    config_models.py         PowerSeqConfig / PowerRail / ConditionConfig / VectorNode / Parameter、pulse 名稱解析
    param_expr.py            width 公式求值（eval_width，ast 白名單；整數或引用 parameter）
    timing_models.py         InputWaveSpec / TimingScenario
    naming.py                safe_name / internal_sig（含 vector bit 名 FOO[2]→FOO_2）
    constants.py             DEP_HIGH / DEP_LOW
    cond_ir.py               條件語意唯一來源：resolve_condition → CondTree
    cond_edit.py             條件編輯器的純資料模型（新增／刪除／拖放重排）
    config_edit.py           節點清單編輯：命名、批次刪除、重排後索引換算
    paths.py                 templates/ reference/ 路徑單一來源（含打包後）
    validator.py             設定驗證
    group_logic.py           群組 intra-op AND/OR/XOR
    version.py               版本／作者等單一來源
    project_session.py       文件狀態：path、dirty、undo 政策（不依賴 Tk）
    applog.py  snapshot_history.py  app_expiry.py
  timing/                  時序模擬與時序圖
    timing_sim.py            時序邏輯模擬引擎
    timing_export.py         匯出共用選項／edge helper
    timing_scenario_io.py    scenario JSON I/O / merge
    schemdraw_export.py      Schemdraw 時序圖
  codegen/                 verilog_generator.py / c_generator.py
  drawio/                  Draw.io 匯出（cell_export / geometry / options）
  excel/                   Excel 匯入／匯出與版面
    vba/                     VBA 嵌入（COM 需 Excel／zip 注入不需）
  pipeline/                匯出應用服務層：validate → 產生 → 寫檔
    export.py                export() / ExportResult（verilog / c / drawio / schemdraw）
  gui/                     CustomTkinter GUI（theme/widgets/panels/dialogs/settings/app）
  tools/                   json2drawio.py / build.py / build_onedir.py
  reference/               PSEQCELL 版面等匯出資產
ci.bat                   本地 CI（ruff + pytest；GitHub workflow 也呼叫這支）
tests/                   pytest 測試（邏輯層）
scripts/                 範本／資產產生腳本（依賴 src/，反向不成立）
templates/               Excel／Draw.io／時序圖範本與資產
```

## 資料模型與相容性

- **身份／條件分層**：`PowerRail` 只保留身份（`name` / `seq_type` / `pulse_*` / `cycle_*` / `deb_*` / `init` / `force_val`），
  條件（`depends_on_{hi,lo,force}_*` 與對應 `get_*` 存取器）收進 `ConditionConfig`，`PowerRail` 以 `@property`
  委派，呼叫點、`cond_ir` 與五個後端零改動。
- **Vector 節點**：`VectorNode`（`base` / `seq_type` / `width_expr` 字串 / 每 bit 的 `ConditionConfig`）的 `elaborate()`
  依 `eval_width(width_expr)` 展開成 N 個獨立 `PowerRail`（canonical 名 `base[i]`），每個帶群組 metadata
  （`group_base` / `bit_index` / `width_expr`）。config 以**扁平 rails + 群組 metadata** 保存：`to_dict` 把同群組收合成
  一筆（保留 `width_expr` 字串）、`from_dict` 以 `eval_width(width_expr, parameters)` 展開。Verilog 把群組收合成一條 bus
  （`[k-1:0]` 或公式 `[(EXPR)-1:0]` + 單一 `PSEQCELL WIDTH`），但 condition assign 逐 bit 索引展開
  （`assign base_hi[i] = …`，每 bit 渲染自己的條件）；C 收合成陣列 `pwrcell_t base[N]`
  並以索引 `base[i]` 引用；`pwrcell_handle` 收成「GPIO 表（`pwrseq_gpio_ref_t base_gpio[N]`）+ `for`
  迴圈」，條件賦值仍逐 bit（保留每 bit 條件可不同）。
- **Parameter**：`PowerSeqConfig.parameters` 是有序的 `Parameter(name, value)` 清單；vector 寬度公式可引用
  （Verilog 產生 `#(parameter NAME = VAL, ...)`、C 產生 `#define`）。`width_expr` 一律存字串（整數期 `"2"`、
  公式期如 `"NUM_CPU*2"`）。
- **全域維度（dimensions）**：`PowerSeqConfig.dimensions` 是 0～2 個 parameter 名稱（維度1＝row、維度2＝col），
  該 parameter 的值即該維度最大值。`to_dict` 僅在非空時輸出 `"dimensions"` 鍵（空則省略，舊檔 byte 不變）、
  `from_dict` 做型別正規化並最多取前 2 個。validator 檢查個數 0～2、名稱需存在於 `parameters`、不重複、最大值 ≥ 1。
  這是「維度＋slice」條件模型的地基（取代已移除的 parametric）；take 選項與 slice 條件在後續階段實作。
- **Signal 維度（`dim_params`）**：vector 群組可帶 0～2 個維度名（`PowerRail.dim_params`，row＝`dim_params[0]`、
  col＝`dim_params[1]`）。GUI 宣告頁用「維度 [0/1/2]」下拉＋Bits 維度下拉決定 `width_expr`（0→`"1"`、1→`P1`、
  2→`P1*P2`，沿用 `eval_width`），`dim_params` 隨群組收合進 `to_dict`（非空才輸出）/`from_dict` round-trip，
  2D flat bus 的 Verilog 宣告即公式路徑 `[(P1*P2)-1:0]`。無 `dim_params` 的既有向量沿用原 `width_expr`（骨架不破壞舊檔）。
- **舊檔相容**：`to_dict` / `from_dict` 就是存檔格式本身，無版本號、無 migration 層。舊 JSON 缺欄位一律給預設——
  **無群組 metadata = 單一節點（`width_expr` 預設 `"1"`）**、**無 `parameters` = 空清單**；且 `to_dict` 僅在
  `parameters` 非空時才輸出該鍵，確保無 parameter 的舊檔產生的輸出 byte 不變（由 `tests/golden/` 鎖定）。

## 術語

圖層、走線通道等專案術語請參考 `.cursor/rules/pwrseq-terminology.mdc`。

## 授權

Copyright © 2026 Haru. All rights reserved.
