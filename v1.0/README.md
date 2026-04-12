# Power Sequence Generator

以 PSEQCELL 為基礎的自動 Power Sequence 產生器，包含 Python GUI 與 Verilog 產生功能。

## 功能

- **GUI 配置**：使用 CustomTkinter 建立依賴關係與參數
- **驗證**：循環依賴、名稱重複、依賴存在性檢查
- **匯出**：JSON 設定檔、Verilog 模組
- **Verilog 產生**：自動產生 PSEQCELL 實例與 iHi/iLo 連接

## 安裝

```bash
pip install -r requirements.txt
```

## 使用方式

```bash
python main.py
```

或直接執行 GUI：

```bash
python gui.py
```

## 操作說明

1. **新增 Rail**：點擊「+ 新增 Rail」加入 power rail
2. **編輯**：在右側表單填寫名稱、勾選「上電即輸出 High」、CYCLE_HI/LO、依賴關係
3. **依賴**：勾選「依賴於」的 checkbox 表示此 rail 需等該 rail 完成後才能啟動
4. **儲存/載入**：以 JSON 格式儲存或載入設定
5. **產生 Verilog**：驗證通過後可產生 Verilog 檔

## 專案結構

```
pwrseq_gen/
├── PSEQCELL.v           # 單階 power sequence 控制元件
├── config_models.py     # 資料模型
├── validator.py        # 驗證邏輯
├── verilog_generator.py # Verilog 產生器
├── gui.py               # GUI 主程式
├── main.py              # 進入點
├── requirements.txt
└── README.md
```

## 節點類型（依需求表）

- **output**：輸出 `oXXX`，可設 Hi/Lo 依賴、CYCLE
- **input**：輸入 `iXXX`，供其他節點依賴

## 依賴邏輯

- **iHi**：無依賴接 `1'b1`；有依賴時：output 用輸出，input 用輸入
- **iLo**：無依賴接 `1'b0`；有依賴時依設定

## 注意事項

- 產生的 Verilog 需與 `PSEQCELL.v` 一起編譯
- 請確保 `PSEQCELL.v` 在 include path 或同一目錄
- `iPulse_Hi` / `iPulse_Lo` / `iPulse_Force` 由 IO 輸入，需由外部提供
