# pwrseq_gen 技術債與改善計畫

本檔記錄已盤點出的架構問題與處理順序。設計層級的功能提案另見 `doc/FUTURE.md`。

排序原則：**先建立安全網，再動結構，GUI 放最後**。GUI 是最大也最沒有自動化保護的區塊，
而前面幾步（條件 IR、pulse 解析收斂）正好會把它需要的純函式準備好。

---

## 核心問題：同一套條件語意有五份獨立實作

`PowerRail` 的 `depends_on_{hi,lo,force}_groups` 加上 `inv` / `use` / `group_inv` / `intra_op`
是整個專案的核心資料結構。目前有五個模組各自從頭走訪它一遍：

| 模組 | 把群組翻譯成 |
|---|---|
| `timing/timing_sim.py` | 0/1 邏輯值（`_eval_dep` / `_eval_groups`） |
| `codegen/verilog_generator.py` | Verilog 運算式（`_dep_expr`） |
| `codegen/c_generator.py` | C 運算式（`_c_dep_expr`） |
| `drawio/drawio_cell_export.py` | AND/OR 閘圖（`_resolve_term`） |
| `timing/timing_export.py` | 時序箭頭的葉節點 |

一致性目前靠文件維持（`.cursor/rules/timing-sim-behavior.mdc` 開頭就寫著「修改 `timing_sim.py`
時必須與 `c_generator.py` / `verilog_generator.py` 對齊」）。**用文件維持五份實作的一致性，
是架構在求救**：每新增一個語意，就要記得同步五個地方，漏一個就產生「只有某種匯出格式錯」的 bug。
已修掉的兩個 Draw.io bug 都是這一類。

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

### 兩條已經是可執行護欄的約束

比文件可靠，改壞了會紅：

| 約束 | 護欄 |
|---|---|
| `templates/` 含未追蹤的客戶檔案，打包只能逐一指名，**不可整包帶入** | `tests/test_packaging.py::test_templates_dir_is_never_bundled_wholesale` |
| 模擬器不模擬 Force（`_eval_dep` 對 `use="force"` 回定值 0） | `tests/test_condition_consistency.py` 的 `KNOWN_SIM_DIVERGENCE` |

---

## 待辦

### 1. 抽條件 IR

`core` 提供唯一的 `resolve_condition(rail, kind) -> CondTree`，把 groups / inv / use /
intra_op / group_inv 一次性正規化解析完。

待決定：`CondTree` 設計成**純資料**（dataclass，下游各自 match/render），
還是**帶 visitor**（下游提供 const / level / cond / and / or / xor / not 等 callback）。
後者能保證沒有下游漏掉新增的節點型別——而「漏掉語意」正是 Draw.io bug 的成因。

- **verify**：`test_condition_consistency.py` 的 oracle 改成直接走 `CondTree`，黃金輸出 byte 不變

### 2. 五個下游改成只負責渲染 `CondTree`

`timing_sim`、`verilog_generator`、`c_generator`、`drawio_cell_export`、`timing_export`。

- **一次只改一個**，verify：每改完一個，黃金輸出仍 byte 不變

### 3. 四套 pulse 名稱解析器收進 `core`

`config_models.normalize_pulse_name`、`c_generator._pulse_time_field`、
`timing_sim._pulse_scale_units`、`drawio_geometry._parse_pulse_period`。
前三套都會先走 `normalize_pulse_name`，只有 `drawio_geometry` 那套自己重刻了 `iPulse_`/`Pulse_`
去前綴，因此不做 `safe_name` 正規化——名稱含 `.` 或 `-` 時與其他三套解讀不一致。

- **verify**：加一支 `My.Pulse_1us` 的四套一致性測試

### 4. 最小可行 CI

`.github/workflows/` 目前是空的，根目錄沒有 `ci.bat`（但 user rule 要求 push 前跑）。
內容只要三件事：`pytest` + `ruff`（兼管 import 排序）+ 黃金輸出比對。linter 要加進 `requirements-dev.txt`。

### 5. 把套件邊界做成真的 API

除了 `gui/`（已宣告 `run_gui`），其餘七個 `__init__.py` 都只有一行 docstring，
所有呼叫端都 import 深層路徑（`from drawio.drawio_cell_export import ...`）。
測試跨進內部的程度也不低：8 個測試檔 import 了 21 個私有符號。
這代表「套件內部」實際上沒有內部可言，任何內部重構都會打破測試。

讓 `gui/` 與 `tools/` 只依賴 `from drawio import generate_drawio`。
私有符號的白箱測試可以留，但要清楚那是白箱測試，不是契約。
同時清掉 `drawio_export.py` 對 `drawio_geometry` 的 34 個符號 re-export facade（大多無人使用）。

### 6. 模擬器補上 Force

`_eval_dep` 對 `use="force"` 目前回定值 0。模擬器內部其實算得出 force 條件（會傳進 `fsm.commit`），
只是沒發布成 `out_force` 讓下游依賴讀取，所以是實作缺口而非設計決定——
`timing-sim-behavior.mdc` 寫的是 `use="force"` 應該參考該 rail 的條件。

- **verify**：移除 `KNOWN_SIM_DIVERGENCE` 後 `test_condition_consistency.py` 仍綠

### 7. （最後）GUI 抽純函式

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
