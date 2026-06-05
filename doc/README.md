# Power Sequence Generator

以 PSEQCELL 為基礎的自動 Power Sequence 產生器，包含 Python GUI、Verilog 產生與 Draw.io 依賴關係圖匯出功能。

## 功能

- **GUI 配置**：使用 CustomTkinter 建立依賴關係與參數，Accordion 折疊式編輯器
- **驗證**：循環依賴、名稱重複、依賴存在性檢查
- **Verilog 產生**：自動產生 PSEQCELL / DEB 實例與 iHi/iLo 連接
- **Draw.io 匯出**：產生依賴關係圖 XML（匯出前可設定走線重疊選項）；input 自右側水平出發、NOT 右 80pt／下 40pt；拓撲排序、通道分配、正交避障路由。詳見 [doc/DRAWIO_RULES.md](doc/DRAWIO_RULES.md)
- **CLI 批次轉換**：`json2drawio.bat` 不開 GUI 即可將 JSON 轉 Draw.io XML
- **匯出格式**：JSON 設定檔、Verilog 模組、Draw.io XML

## 安裝

```bash
pip install -r requirements.txt
```

或直接雙擊 `run.bat`（會自動安裝相依套件並啟動）。

## 打包成 Windows EXE

```bash
pip install -r requirements-build.txt
python src/build.py
```

或直接雙擊 `build.bat`。打包完成後 `dist\PowerSeqGen` 資料夾內會產生 `PowerSeqGen.exe`。

## 使用方式

```bash
python src/main.py
```

或雙擊 `run.bat`。

## 操作說明

1. **新增 Node**：點擊「+ Add」加入 Sequence Node
2. **編輯**：點擊標題列展開 Node，設定名稱、類型、CYCLE、依賴關係
3. **依賴**：在 Hi Cond / Lo Cond 中加入依賴項，支援分組（組內 AND、組間 OR）、反相、Hi Cond / Lo Cond use mode
4. **儲存/載入**：以 JSON 格式儲存或載入設定
5. **產生 Verilog**：驗證通過後產生 Verilog 檔
6. **匯出 Draw.io**：在對話框設定走線重疊選項後產生 XML，以 diagrams.net 開啟（規則見 `doc/DRAWIO_RULES.md`）
7. **釘選**：點擊右上角 📌 按鈕將視窗釘選至螢幕最上層

## 專案結構

```
pwrseq_gen/
├── src/                     # 原始碼
│   ├── main.py              # 進入點
│   ├── gui.py               # GUI 主程式
│   ├── config_models.py     # 資料模型
│   ├── validator.py         # 驗證邏輯
│   ├── verilog_generator.py # Verilog 產生器
│   ├── drawio_export.py     # Draw.io XML 匯出
│   ├── drawio_export_options.py  # 匯出走線重疊選項
│   ├── drawio_dialog.py     # Export Draw.io 對話框
│   ├── layout_engine.py     # 正交路由、水平段補齊、交叉最小化
│   ├── json2drawio.py       # CLI 批次轉換工具
│   ├── build.py             # PyInstaller 打包腳本
│   └── reference/           # C/Verilog 參考元件（PSEQCELL.v、pwrcell.c/.h）
├── tests/                   # 自動化測試
├── output/                  # 程式產生的檔案
├── doc/                     # 文件
│   ├── README.md
│   ├── 操作說明.md
│   ├── 需求表.md
│   └── DRAWIO_RULES.md
├── run.bat                  # 啟動腳本
├── json2drawio.bat          # CLI 批次轉換（JSON → Draw.io XML）
├── build.bat                # 打包腳本
├── git_push.bat             # Git 推送腳本
├── requirements.txt         # 執行依賴
└── requirements-build.txt   # 打包依賴
```

## 節點類型

- **Output**：輸出 `oXXX`，可設 Hi/Lo 依賴、CYCLE_HI/LO、INIT、Timing Pulse
- **Input**：輸入 `iXXX`，供其他節點依賴，可啟用 Debounce

## 依賴邏輯

- **iHi**：無依賴接 `1'b1`；有依賴時支援 Node / Hi Cond / Lo Cond use mode
- **iLo**：無依賴接 `1'b0`；有依賴時依設定
- **分組**：Group 內 AND、Group 間 OR
- **Timing**：支援 "High" 選項，Verilog 中轉換為 `1'b1`

## 注意事項

- 產生的 Verilog 需與 `PSEQCELL.v和 DEB.v` 一起編譯
- `iPulse` 訊號由 IO 輸入，需由外部提供
- Draw.io XML 以 [diagrams.net](https://app.diagrams.net) 開啟

