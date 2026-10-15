# pwrseq_gen 技術債與改善計畫

本檔記錄已盤點出的架構問題與處理順序。設計層級的功能提案另見 `doc/FUTURE.md`。

排序原則：**先建立安全網，再動結構，GUI 放最後**。GUI 是最大也最沒有自動化保護的區塊，
而前面幾步（條件 IR、pulse 解析收斂）正好會把它需要的純函式準備好。

---

## 核心問題：同一套條件語意有五份獨立實作

`PowerRail` 的 `depends_on_{hi,lo,force}_groups` 加上 `inv` / `use` / `group_inv` / `intra_op`
是整個專案的核心資料結構。目前有五個模組各自從頭走訪它一遍：

| 模組 | 把群組翻譯成 | 已接 IR |
|---|---|---|
| `codegen/verilog_generator.py` | Verilog 運算式 | ✅ `_VerilogCond` |
| `codegen/c_generator.py` | C 運算式 | ✅ `_CCond` |
| `timing/timing_sim.py` | 0/1 邏輯值 | ✅ `_SimCond` |
| `drawio/drawio_cell_export.py` | AND/OR 閘圖 | ✅ `_DrawioCond` / `_CondSignalKeys` |
| `timing/timing_export.py` | 時序箭頭的葉節點 | ✅ `_EdgeItems` |

一致性原本靠文件維持（`.cursor/rules/timing-sim-behavior.mdc` 開頭就寫著「修改 `timing_sim.py`
時必須與 `c_generator.py` / `verilog_generator.py` 對齊」）。**用文件維持五份實作的一致性，
是架構在求救**：每新增一個語意，就要記得同步五個地方，漏一個就產生「只有某種匯出格式錯」的 bug。
已修掉的兩個 Draw.io bug 都是這一類。

**此問題已解決**：`core/cond_ir.py` 是唯一實作，五個下游各自只寫一個 `CondVisitor` 渲染它。

---

## 已完成（安全網）

這些是後面所有項目的前提，不要退回。

- **黃金輸出測試** `tests/test_golden_exports.py` — 鎖住五個後端的完整輸出，基準檔在 `tests/golden/`。
  Draw.io 的隨機 diagram id 以 `random.seed()` 釘住；`.xlsm` 因 zip 內嵌時間戳改比對 import round-trip。
  要更新基準檔：`PWRSEQ_UPDATE_GOLDEN=1 pytest tests/test_golden_exports.py`。
- **交叉一致性測試** `tests/test_condition_consistency.py` — 把條件語意寫成一份 oracle，
  四個後端各自對照。已知分歧用**集合相等**而非 `xfail` 鎖住：新漂移會紅，**把已知分歧修好了也會紅**，
  逼你回來刪掉那筆記錄。
- **Draw.io `use` 誤判修正** — `_resolve_term` 原本只看 `use`、沒確認依賴是不是 output，
  替 input 畫出 RTL 裡不存在的 `xxx_hi`/`xxx_lo`。現由 `_dep_has_cond_signal` 統一判斷。
- **打包缺檔修正** — `core/paths.py` 補上 `sys._MEIPASS` 分支，`build.py` 指名打包 Excel 範本與
  `vbaProject.bin`。修正前打包版的 Excel 匯出一律 `FileNotFoundError`。
- **VBA 腳本移入 `src/excel/vba/`** — `excel_export` 原本在執行期把 `scripts/` 插進 `sys.path`
  再 import，是產品程式碼依賴開發腳本的反向相依。搬成正式模組後 `build.py` 不再需要
  `--paths scripts` 與那兩個 `--hidden-import`；`scripts/generate_excel_template.py` 改為
  `from excel.vba... import`（方向正確）。兩支的 `VBA_DIR` / `VBA_BIN` 原本各自用 `__file__`
  往上推算，現已改接 `core.paths.TEMPLATES_DIR`，打包後才指得對。
- **條件 IR `core/cond_ir.py`** — `resolve_condition(rail, kind, name_to_rail) -> CondTree`
  把 groups / inv / use / group_inv / intra_op 一次解析完。節點：`Const` / `Level` / `Cond` /
  `Not` / `Group`（group 內 intra_op）/ `AnyGroup`（group 間 OR）。樹的形狀刻意對齊 F-DEP-08
  的兩層結構而非任意布林樹，渲染端才不會把兩層搞混。`CondVisitor` 做成 ABC：日後新增節點型別，
  沒跟上的下游在**建構當下**就 `TypeError`。`test_condition_consistency.py` 的 oracle 已改成
  透過 visitor 讀 IR，IR 本身則由 `tests/test_cond_ir.py` 對照手寫期望值把關
  （否則 IR 寫錯會讓所有後端「一致地錯」）。
- **group 組裝的回歸保護** `tests/test_cond_render.py` — `tests/golden/` 只鎖
  `templates/demo_json.json`，而那份 config 全是單一 group、`intra_op` 預設 and、
  沒有 `group_inv`，所以 group 組裝那層原本毫無保護（注入「group 間改成 &」與
  「`intra_op` 一律 and」兩個 bug，黃金測試照樣綠）。現用一份覆蓋多 group /
  xor / or / `group_inv` / 空 group / 舊格式扁平欄位的合成 config 補上，
  期望值取自接 IR 之前的輸出。**其餘後端接 IR 時要在這裡各加一組。**
- **五個下游全部已接 IR** — `_VerilogCond`、`_CCond`、`_SimCond`、`_DrawioCond`、
  `_EdgeItems`（外加 `_CondSignalKeys` 收 Draw.io 要拉線的條件訊號）。原本各自的走訪
  （`_dep_expr`、`_c_dep_expr` / `_groups_to_c_expr`、`_eval_dep` / `_eval_groups`、
  `_resolve_term` / `_dep_has_cond_signal`、`_unique_group_deps`）全部移除。
  驗證方式一致：合成 config 加三份真實 config，新舊輸出逐字元比對（Verilog 368 條
  assign、C 80660 B、模擬 198623 B、Draw.io 570457 B、Schemdraw 32039 B / 427 條箭頭
  皆相同），再對每個 visitor 注入六個 bug 確認全部轉紅。
- **`timing_export.format_rail_condition` 已刪除** — 它是第五份實作，而且寫錯（忽略
  `intra_op` 與 `group_inv`、`_dep_label` 沒檢查依賴是不是 output），但查證後發現
  **整個 repo 沒有任何呼叫者**，那些錯誤標籤從未被輸出。連同只服務它的 `_dep_label`
  一起刪掉，不改變任何行為。
- **`timing_sim._eval_spec_groups` 的語意差異已記錄** — 那是 InputWaveSpec 的激勵條件
  （不是 `depends_on_*`），空 group 直接略過、`use=hi/lo` 查不到時 fallback 到該 rail
  的準位而非 0。只有葉節點借用 IR，output 分支維持原樣並在 docstring 註明。
- **四套 pulse 名稱解析器已收斂** — `core.config_models` 新增 `pulse_suffix` 與
  `parse_pulse_period`，`c_generator._pulse_time_field`、`timing_sim._pulse_scale_units`、
  `drawio_geometry._deb_time_text` 全部改走這兩支，`_parse_pulse_period` 刪除。
  原本兩處分歧：Draw.io 自己重刻去前綴、不走 `normalize_pulse_name`，所以 `Pulse-1us`
  這類含 `.`/`-`/空白的名稱在 Verilog / C / 模擬器都正規化成 `Pulse_1us`，Draw.io 卻解不出
  週期、debounce 標籤顯示 `0s`；模擬器則是 `Pulse_xus` 解不出數字退回 1、`Pulse_xms`
  退回 1000 的不對稱 fallback。兩者都只在名稱異常時才觸發，三份真實 config 的 pulse
  全為標準寫法，因此五個後端輸出逐字元不變；`tests/test_pulse_name.py` 用別名對照
  （`iPulse_1us` / `Pulse-1us` / `Pulse 1us` / `Pulse.2ms`）把一致性鎖住，六個注入 bug 全紅。
- **CI 已建立** — 根目錄 `ci.bat`（`ruff check` + `pytest`，黃金輸出比對本來就在
  `tests/test_golden_exports.py` 裡），`.github/workflows/ci.yml` 直接呼叫同一支，
  所以本地與 CI 不可能跑到不同指令。已驗證 lint 與測試任一失敗都會讓 `ci.bat` 回非零。

  ruff 規則刻意只開 `F` / `E9` / `I` / `RUF100`。開預設全集會有 282 筆，其中
  blind-except 80 筆、try-except-pass 53 筆來自 GUI「預覽／繪圖失敗不要讓視窗掛掉」
  的既定取向，那是設計決策不該由 linter 逼著改；星號 import 的 `F403`/`F405` 與
  facade 的 `F401` 用 per-file-ignores 排除。導入時順手清掉 unused import 15、
  unsorted-imports 40、失效 noqa 9，以及三個賦值後沒用的變數（`verilog_generator`
  的 `successors` / `externals` 連同只服務它們的 `_get_successors` 一起移除）。
  42 個檔案被重排 import，五個後端輸出逐字元不變。
- **`requires-python` 已修正為 `>=3.10`** — 原本寫 `>=3.8`，但 72 個 `.py` 只有 18 個有
  `from __future__ import annotations`，其餘直接用 `list[str]` / `str | None` 當註解，
  在 3.8/3.9 上 import 當下就會炸。宣告與實際支援範圍本來就不一致。
- **GUI 預覽失敗時看不到錯誤訊息的 bug 已修** — 兩個預覽 worker 寫成
  `except Exception as e: self.after(0, lambda: ...str(e))`，但 Python 在 except 區塊
  結束時會隱含 `del e`，lambda 延後執行時 `str(e)` 丟 NameError，使用者什麼都看不到。
  由 ruff `F821` 發現，現在也由 CI 的 `F` 規則守住。
- **套件邊界已成為真的 API** — `codegen` / `drawio` / `excel` / `excel.vba` / `timing`
  各自在 `__init__.py` 宣告 `__all__`，`gui` / `tools` / `scripts` 與跨套件呼叫全部改走
  這層介面。`core` 刻意維持深層 import：它是共用詞彙表（`PowerRail` / `safe_name` /
  `DEP_HIGH` …），性質接近 stdlib，收成單一扁平命名空間反而讓
  `from core.config_models import PowerRail` 這種自我說明的寫法更難讀。

  `drawio_export.py` 已刪除。它 51 行裡有 35 行是從 `drawio_geometry` re-export 34 個
  符號，實際被引用的只有 8 個、且全部只有 `tests/test_drawio_cell.py` 在用（本來就能直接
  從 `drawio_geometry` 拿）；產品程式從它只取 `generate_drawio` 一個名字。`generate_drawio`
  改由 `drawio/__init__.py` 直接提供。

  邊界由 `tests/test_package_api.py` 強制（AST 掃 `src/` 與 `scripts/`，跨套件 import 必須
  指向套件而非模組），六個注入違規全紅。`tests/` 明文豁免：白箱測試戳進實作細節是刻意的。

  `excel` 與 `timing` 互相依賴，兩邊的 import 本來就寫在函式內以避開循環，改走套件介面後
  仍維持延後並補上註解說明原因。`excel/vba/__init__.py` 會 eager import COM 那支，但
  `win32com` 是在各函式內才 import，所以沒有 pywin32 的機器上仍可正常載入。

### 三條已經是可執行護欄的約束

比文件可靠，改壞了會紅：

| 約束 | 護欄 |
|---|---|
| `templates/` 含未追蹤的客戶檔案，打包只能逐一指名，**不可整包帶入** | `tests/test_packaging.py::test_templates_dir_is_never_bundled_wholesale` |
| 模擬器不模擬 Force（`_SimCond.cond` 對 `kind="force"` 回定值 0） | `tests/test_condition_consistency.py` 的 `KNOWN_SIM_DIVERGENCE` |
| 跨套件呼叫只能走 `__init__.py` 宣告的介面 | `tests/test_package_api.py` |

---

## 待辦

### 1. 模擬器補上 Force

`_SimCond.cond` 對 `kind="force"` 目前回定值 0。模擬器內部其實算得出 force 條件（會傳進 `fsm.commit`），
只是沒發布成 `out_force` 讓下游依賴讀取，所以是實作缺口而非設計決定——
`timing-sim-behavior.mdc` 寫的是 `use="force"` 應該參考該 rail 的條件。

- **verify**：移除 `KNOWN_SIM_DIVERGENCE` 後 `test_condition_consistency.py` 仍綠

### 2. （最後）GUI 抽純函式

`app.py` + `widgets.py` + `panels.py` 約 4400 行，headless 下測試幾乎全 skip——
等於這 4400 行沒有自動化保護。

不過直接操作 group 結構的地方只有 45 處，而且**全部集中在 `widgets.py`**
（`app.py` 與 `panels.py` 皆為 0）。所以這一項的實際範圍比行數看起來小得多，
是一次可收斂的重構，不是全面改寫。

把「編輯 config 的邏輯」抽成 `core` 的純函式（輸入 config + 使用者動作，輸出新 config），
widget 只負責綁 Tk 變數。這是讓 GUI 邏輯擺脫 Tk、能進 CI 的唯一辦法。

---

## 待確認

- `src/x15_pseq.v` 自 `efed7e4` 起被 git 追蹤，而 remote 為公開 repo。
  需確認是否應留在版控中（或連歷史一併清除）。
