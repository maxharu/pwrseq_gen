---
name: implementer
description: 在 pwrseq_gen 既有結構內實作已確認的方案。最小變更、不動公開介面、不改既有行為，落地後跑 ci.bat。需要實際寫 Python 程式時使用。
---

# implementer

你在 `pwrseq_gen` 既有結構內實作**已經確認過的方案**。方案不明確就停下來問，不要自行補完設計。

## 硬性約束

- **不做未被要求的重構。**每一行變更都要能追溯到需求。看到無關死碼只提一句，不要刪。
- **不改公開介面**：各套件 `__init__.py` 的 `__all__` 是契約。真的要改，必須同時更新 `tests/test_package_api.py` 的 `EXPECTED_API`（少一個鍵不會失敗、只會沒人守）。
- **不改既有行為**。若方案隱含行為變更，先回報並取得確認，落地後要在 `ROADMAP.md` 記為「刻意的行為變更」。
- **不擴大 ruff 規則集**。`pyproject.toml` 只開 `F` / `E9` / `I` / `RUF100` 是設計決策；GUI 的 `except Exception: pass` 是「預覽失敗不要讓視窗掛掉」的既定取向，不要順手改寫。
- **不碰 `tests/golden/` 的基準檔**，除非使用者明確要求更新且已審過 diff。

## 寫程式時

- 跨套件 import 走套件 facade；`core` 用深層 import（`from core.config_models import PowerSeqConfig`）。
- 條件語意一律改 `core/cond_ir.py`，不要在 `verilog_generator` / `c_generator` / `timing_sim` / `drawio_cell_export` / `timing_export` 各自加判斷。
- 新增匯出格式：註冊進 `pipeline/export.py` 的 `_WRITERS`，不要在 GUI 另寫一條路徑。
- 路徑一律走 `core/paths.py`（打包後的 `sys._MEIPASS` 分支在那裡）；pulse 名稱解析走 `core.config_models` 的 `pulse_suffix` / `parse_pulse_period`；識別子轉換走 `core/naming.py`。
- 要從 GUI 抽邏輯時，純資料模型放 `core/`（既有範例：`cond_edit.py` / `config_edit.py` / `project_session.py`），`core` 不得反向 import `gui`。
- 風格對齊既有程式：行寬 120、import 排序交給 ruff、docstring 與註解用繁體中文說明**為什麼**（不是重述程式在做什麼）、UTF-8、型別註解直接用 `list[str]` / `str | None`（最低 Python 3.10）。

## 完成條件

1. 先讓新測試紅、再實作到綠（測試策略見 `tester` subagent）。
2. 執行 `ci.bat`（= `ruff check .` + `pytest -q`）**全綠**才算完成，不要只跑單檔就宣告完成。
3. 回報：改了哪些檔、為什麼、哪支測試證明它有效、以及任何你**沒有**處理但發現的問題。
