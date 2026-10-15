# Power Sequence Generator (`pwrseq_gen`)

電源時序（Power Sequence）設計工具。以圖形化介面編輯時序節點與條件，並從同一份設定一鍵產生 Verilog／C 程式碼、Draw.io 電路圖、Schemdraw 時序圖，以及 Excel 匯入／匯出範本。

> 平台：Windows（桌面 GUI，使用 CustomTkinter）。

## 功能

- **節點編輯**：Input／Output 節點、Hi／Lo／Force 三段條件、群組內 AND／OR／XOR 運算、debounce 設定。
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

已盤點的技術債與改善順序見 [`ROADMAP.md`](ROADMAP.md)。

## 專案結構

```
src/
  main.py                  進入點（設定 DPI 後啟動 GUI）
  core/                    資料模型與共用基礎
    config_models.py         PowerSeqConfig / PowerRail
    timing_models.py         InputWaveSpec / TimingScenario
    naming.py                safe_name / internal_sig
    constants.py             DEP_HIGH / DEP_LOW
    paths.py                 templates/ reference/ 路徑單一來源（含打包後）
    validator.py             設定驗證
    group_logic.py           群組 intra-op AND/OR/XOR
    version.py               版本／作者等單一來源
    applog.py  snapshot_history.py  app_expiry.py
  timing/                  時序模擬與時序圖
    timing_sim.py            時序邏輯模擬引擎
    timing_export.py         匯出共用選項／edge helper
    timing_scenario_io.py    scenario JSON I/O / merge
    schemdraw_export.py      Schemdraw 時序圖
  codegen/                 verilog_generator.py / c_generator.py
  drawio/                  Draw.io 匯出（export / cell_export / geometry / options）
  excel/                   Excel 匯入／匯出與版面
    vba/                     VBA 嵌入（COM 需 Excel／zip 注入不需）
  gui/                     CustomTkinter GUI（theme/widgets/panels/dialogs/settings/app）
  tools/                   json2drawio.py / build.py / build_onedir.py
  reference/               PSEQCELL 版面等匯出資產
tests/                   pytest 測試（邏輯層）
scripts/                 範本／資產產生腳本（依賴 src/，反向不成立）
templates/               Excel／Draw.io／時序圖範本與資產
```

## 術語

圖層、走線通道等專案術語請參考 `.cursor/rules/pwrseq-terminology.mdc`。

## 授權

Copyright © 2026 Haru. All rights reserved.
