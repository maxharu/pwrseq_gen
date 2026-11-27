# pwrseq_gen 技術債與改善計畫

本檔記錄已盤點出的架構問題與處理順序。設計層級的功能提案另見 `doc/FUTURE.md`。

排序原則：**先建立安全網，再動結構，GUI 放最後**。GUI 是最大也最沒有自動化保護的區塊，
而前面幾步（條件 IR、pulse 解析收斂）正好會把它需要的純函式準備好。

條件 IR 那一輪的項目已全部完成（見「已完成（安全網）」）。下方「待辦」是之後再次架構審視
盤點出來的新一輪。

---

## 核心問題（大部分已解決）：同一套條件語意曾有五份獨立實作

保留這一段是為了說明 `core/cond_ir.py` 為什麼存在。拿掉之後，下一個讀的人會看到一層
沒人解釋得清楚的 IR，然後很合理地想把它拆掉。

`PowerRail` 的 `depends_on_{hi,lo,force}_groups` 加上 `inv` / `use` / `group_inv` / `intra_op`
是整個專案的核心資料結構。曾經有五個模組各自從頭走訪它一遍：

| 模組 | 把群組翻譯成 | 已接 IR |
|---|---|---|
| `codegen/verilog_generator.py` | Verilog 運算式 | ✅ `_VerilogCond` |
| `codegen/c_generator.py` | C 運算式 | ✅ `_CCond` |
| `timing/timing_sim.py` | 0/1 邏輯值 | ✅ `_SimCond` |
| `drawio/drawio_cell_export.py` | AND/OR 閘圖 | ✅ `_DrawioCond` / `_CondSignalKeys`（葉節點 + 閘拓樸） |
| `timing/timing_export.py` | 時序箭頭的葉節點 | ✅ `_EdgeItems` |

一致性原本靠文件維持（`.cursor/rules/timing-sim-behavior.mdc` 開頭就寫著「修改 `timing_sim.py`
時必須與 `c_generator.py` / `verilog_generator.py` 對齊」）。**用文件維持五份實作的一致性，
是架構在求救**：每新增一個語意，就要記得同步五個地方，漏一個就產生「只有某種匯出格式錯」的 bug。
已修掉的兩個 Draw.io bug 都是這一類。

**已解決**：`core/cond_ir.py` 是唯一實作，五個下游各自只寫一個 `CondVisitor` 渲染它。

Draw.io 的閘拓樸是最後補上的（待辦第 2 項）。在那之前，`drawio_geometry` 的閘形狀函式
簽名都是 `(r: PowerRail, hl: str, gi: int)`，直接從原始模型讀 `intra_op` 與 `group_inv`，
完全沒碰 `CondTree`——同一支匯出器的葉節點走 IR、閘走原始欄位，同一份資料解讀兩次。
現在改由 `_GroupPlan` 把 `op` / `inv` 跟著樹一起帶下去。

（`drawio_cell_export` 另外還有幾處直接讀 `get_hi_groups()`，但那是 `len(g)` 算區塊高度、
`_max_group_inputs` 算寬度，純版面計算，不算重複實作。）

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
- **五個下游的葉節點全部已接 IR** — `_VerilogCond`、`_CCond`、`_SimCond`、`_DrawioCond`、
  `_EdgeItems`（外加 `_CondSignalKeys` 收 Draw.io 要拉線的條件訊號）。Draw.io 的**閘拓樸
  不在這一輪範圍內**，是在待辦第 2 項才補上的。原本各自的走訪
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
- **模擬器已模擬 Force** — `SimResult` 新增 `output_force_cond`，`_SimCond.cond` 的三個
  通道（hi / lo / force）改成統一查表。模擬器本來就算得出 force 條件（會傳進 `fsm.commit`），
  只是沒發布出來，所以下游 `use="force"` 一律讀到 0。`KNOWN_SIM_DIVERGENCE` 已移除。

  同一個缺口有第二處：`_eval_spec_groups` 的 output 分支只認 `use=hi/lo`，`force` 會悄悄
  fallback 成讀該 rail 的**準位**。兩處一併修掉，InputWaveSpec 的激勵條件現在也讀得到
  force 條件。

  三個實際 config 的 `output_force_cond` 全為 0，所以這個分歧在出貨資料上是潛在的而非
  已發生的：`demo_json.json` 的 `PCH_PWROK` 沒宣告 Force 條件（F-DEP-06 預設 0），整條
  `PVCCDD2_EN.force` → `PSU_EN.force` 因此 AND 成 0。黃金基準只多了新鍵、既有內容零變動，
  所以改用專門的端對端測試驗證傳播（`TestForceCondition` / `TestForceConditionInInputWaveSpec`），
  八個注入退化全紅。

- **GUI 的編輯邏輯已抽成純資料模型** — 原本的盤查結論與這份文件先前的描述不同：
  42 處 `depends_on_*` 其實只集中在兩段扁平的欄位對應，沒什麼邏輯；真正棘手的是
  **`CondSectionFrame` 根本沒有模型**——每項依賴的 `inv` / `use` 只存在 Tk 變數裡、
  以 `(gi, ii)` 為 key，widget 本身就是模型。於是每次新增／刪除／拖放重排都得把九個
  平行集合一起重新索引，約 210 行純索引算術，而且因為與 widget 銷毀綁在一起而完全
  無法測試。

  `core/cond_edit.py` 的 `CondEditModel` 把 groups 與平行的 inv / use / group 層設定
  收成一份純資料，結構操作變成單純的 list 操作（`_reorder_groups` 從 51 行變成 6 行），
  widget 改成「改模型 → `_rebuild_groups_ui()` 重繪」。重繪之所以可行，正是因為 inv/use
  不再只存在 Tk 變數裡——那 210 行外科手術式的重映射，存在的理由就是為了迴避重繪。
  `widgets.py` 淨減少 294 行。

  `core/config_edit.py` 收了 `app.py` 的節點清單操作：`next_rail_name`、
  `delete_indices`（必須由大到小刪）、`move_item`、`remap_index_after_move`。最後這支
  原本是 `app.py` 裡的 staticmethod，純歸純、但一行測試都沒有。

  驗證方式與前面各項不同：GUI 不在任何黃金路徑上，**無法用位元比對證明等價**。改以
  `CondEditModel.from_rail` → 模型 → 寫回之後**解析出的條件樹必須完全相同**當作等價證明
  （條件樹正是五個後端實際消費的東西），加上 343 組三連操作的形狀不變量、以及 widget 層
  測試證明接線正確（重繪後 Tk 變數與模型一致、改 Tk 變數有寫回模型）。十二個注入退化
  全紅——其中兩個一開始是綠的，補上缺的測試後才變紅。

  順帶修掉一個長期的測試偶發：這個環境下一個 process 只能可靠地建立一次 Tk root，而
  `_can_create_ctk()` 在 import 期就先建了一個又毀掉，所以後續 `ctk.CTk()` 會偶發
  `couldn't read file ".../init.tcl": No error`。改由 `conftest.py` 的 session 級
  `ctk_root` fixture 共用唯一的 root。

### 三條已經是可執行護欄的約束

比文件可靠，改壞了會紅：

| 約束 | 護欄 |
|---|---|
| `templates/` 含未追蹤的客戶檔案，打包只能逐一指名，**不可整包帶入** | `tests/test_packaging.py::test_templates_dir_is_never_bundled_wholesale` |
| 跨套件呼叫只能走 `__init__.py` 宣告的介面 | `tests/test_package_api.py` |
| 套件相依不得成環（延後 import 也算，否則只是把循環藏起來） | `tests/test_package_api.py::test_package_dependencies_are_acyclic` |
| 條件編輯器的 inv / use 必須與 groups 同形狀（再加平行欄位時尤其容易漏） | `tests/test_cond_edit.py` 的 `assert_shape`，含 343 組三連操作 |

---

## 待辦

延續同一條排序原則：先建立安全網，再動結構，GUI 放最後。

### 1. 閘拓樸的真值表 oracle ✅ 已完成（`tests/test_drawio_gate_topology.py`）

`tests/test_condition_consistency.py` 只比對**葉節點**的渲染文字，閘的形狀完全在覆蓋範圍外。
這就是 `doc/FUTURE.md`「Draw.io 條件繪圖缺口」那三項能長期存在的結構性原因。

守門方式不要做成「比對閘樣式」——那只是把現行行為當成規格封存，這三個 bug 當初會一起被
封進去。要比的是**真值表**：匯出器反正已經決定了閘形狀、哪些標籤帶 `~`、哪幾項餵進哪個閘，
把這些收成描述結構，寫個小求值器，在所有輸入組合下對照 `resolve_condition()` 的布林求值。

- **好處**：「畫出來的圖與資料不符」這類 bug 從「只能靠人看出來」變成「CI 會紅」。
  這類 bug 的失效模式是所有失效裡最糟的一種——不會當掉、不會報錯，使用者會照著錯的圖
  去接板子。而且它掃全組合，不依賴「剛好有人做出那種設定」：`FUTURE.md` 前兩項在現有
  16 份設定上零命中，正是它們能一直沒被發現的原因。
  順帶替 `FUTURE.md` 的 `combine_op` 鋪路——那份文件自己點出「收集型 visitor 會完全
  合法地忽略新的 `op` 而不報錯」，真值表是唯一擋得住這件事的東西。
- **verify**：這支測試對 `FUTURE.md` 那三項都要是紅的——前兩項是真值表不符，
  第三項（Force 不畫）是少了一整個條件項

**落地結果**：1416 個組合（group 形狀 × intra_op × group_inv × 單項 inv × hi/lo，含 n≥8 的
兩層閘樹）。修正前 948 紅 / 396 綠，且失敗全部來自 `group_inv`，與「只有單項群組壞掉」的
手算預測完全吻合。`FUTURE.md` 第 3 項（Force）這支抓不到：畫不出來的項在 `_DrawioCond` 就被丟掉，
匯出端與期望端都看不到它，不構成真值表差異。

注入退化驗證（5 項全紅）：merge 閘忽略整組反相 / merge 閘永遠反相 / child 閘一律當 AND /
merge 閘一律當 OR / 單項 `group_inv` 又被吞掉。第三項一開始是**綠的**——當時 fixture 沒有
任何群組滿 8 項，兩層閘樹那條路徑根本沒被畫出來，補上 `TREE_SHAPES` 才蓋到。

### 2. Draw.io 的閘拓樸改由 `CondTree` 驅動 ✅ 已完成

`doc/FUTURE.md` 列的三個 Draw.io 缺口有共同根因：**閘拓樸從來沒有遷移到條件 IR**。
`drawio_geometry` 裡每一支閘形狀函式的簽名都是 `(r: PowerRail, hl: str, gi: int)`——原始模型、
通道字串、群組索引，沒有任何一支碰過 `CondTree`；但同一支匯出器的葉節點是走 `resolve_condition`
的（`_DrawioCond`）。同一份資料被解讀了兩次，走兩條互不相干的路徑。

這也解釋了為什麼 Force 畫不出來：`hl` 從頭到尾只會是 `"hi"` 或 `"lo"`，Force 在閘這一層
**結構上無法表達**，不是忘了畫。

`FUTURE.md` 的第 1、2 項其實是同一個 bug，一次修掉：

- `FUTURE.md` 第 1 項的 `len(groups[gi]) < 2` 不是隨便寫的——單項群組根本不會畫 merge 閘，bubble 沒地方掛，
  而 `src/reference/` 只有 AND/NAND/OR/NOR/XOR/XNOR 六種圖形，**沒有 NOT**。但不需要新圖形：
  單項群組的 `¬(op(A))` 對 and / or / xor 三種 op 都等於 `¬A`，而這支匯出器**已經會**把單項
  反相畫成標籤前綴 `~`（`_DrawioCond.invert`）。把 bubble 從不存在的閘下推到標籤即可，
  零新圖形、零版面變動。
- 修好上一點之後，`¬a ∨ ¬b` 會畫成兩個 `~` 標籤餵進一個普通 OR 閘——這是對的。於是
`_or_output_not` 再無存在理由，**刪掉它就修好 `FUTURE.md` 第 2 項**。它本來就只是針對
前一項的補償，而且 De Morgan 推反了（`¬a∨¬b` 是 NAND，不是 NOR）。

有個更乾淨的判準可以證明 `_or_output_not` 本來就錯：IR 的根節點 `AnyGroup` **連 `inv` 欄位
都沒有**，沒有任何資料能授權「把根 OR 畫成 NOR」。輸出在 IR 裡找不到對應欄位的函式，
定義上就是在自己發明語意。

- **好處**：直接修掉兩個會畫出錯誤電路圖的 bug，而且程式是**變少**的——`_or_output_not`
  整支刪掉、`_group_output_not` 的特例消失。但真正的收益是消滅「同一份資料兩條解讀路徑」：
  之後語意再擴充（`FUTURE.md` 的 `combine_op`）只要改 IR 加一個 `any_group`，不必記得
  還有第二條路徑要同步——而「忘記同步」正是本檔開頭那一段講的整類 bug 來源。
  同時解開 Force 的死結：`hl` 只有 hi/lo 是結構性阻擋，改走 `CondTree` 之後三個通道
  一視同仁，`FUTURE.md` 第 3 項才有辦法做。
- **verify**：已掃過 `doc/` / `templates/` / `output/` 全部 16 份設定，這兩條路徑**零命中**，
  所以 `tests/golden/demo.drawio.xml` 不會變。可以安心落地，但**黃金測試證明不了它有效**
  ——必須另外加一份專門踩這兩條路徑的 fixture，並確認上一項的真值表 oracle 在修正前是紅的

**落地結果**：`golden/demo.drawio.xml` 如預期 byte 不變。做法是新增 `_GroupPlan`
（`op` / `inv` / `terms`），讓閘的種類與反相跟著樹一起傳下去，取代「拿 group 索引回查
`PowerRail`」——順帶修掉一個 `FUTURE.md` 沒記的 bug：`any_group` 會丟掉畫不出來的整組，
丟掉之後 `gi` 就對不回原始模型，會讀到**別組**的 `intra_op` / `group_inv`。
`tests/test_cond_render.py` 的 `MIXED` fixture 本來就踩在這個條件上。

刪掉的函式：`_get_intra_op`、`_group_output_not`、`_or_output_not`、`_or_gate_style`，
以及早就沒人用的 `_and_gate_style`。單項群組的反相改下推到標籤，`¬¬A` 摺回 `A`。

### 3. 匯出流程抽出應用服務層（`pipeline/export.py`）✅ 已完成

**這一項有已確認、使用者可見的 bug，不是預防性重構。**

`gui` 是 4700 行、佔 `src` 的 47%，裡面 288 個 method 綁在 Tk 類別上、只有 9 個
module-level 函式，而整個 `tests/` 只有 `test_gui_logic.py` 碰得到它。問題不是「GUI 很大」，
是**匯出流程的編排邏輯住在 Tk callback 裡**——因此沒有第二個呼叫者，三條匯出路徑的前置
檢查不一致就這樣活了下來：

| 方法 | `validate()` | `_collect_config()` |
|---|---|---|
| `_generate_code`（Verilog / C） | 有 | 1 次 |
| `_export_schemdraw` | 有 | 1 次 |
| `_export_drawio` | **沒有** | **2 次** |

後果已實測，不是推論。一份 `depends_on` 打錯字的設定：

```
validate -> False ["'OUT' depends on non-existent rail: 'TYPO_RAIL'"]
generate_drawio 成功，長度 2997
圖裡有 IN_A 嗎  : True
圖裡有 TYPO_RAIL: False
```

Verilog 會被擋下來，Draw.io 會**成功匯出一張少了那個條件項的圖，而且不出任何警告**——因為
`_DrawioCond` 本來就會把不在 `valid` 集合裡的項默默丟掉。這跟待辦第 1、2 項修的閘拓樸 bug
是同一種失效模式（不當掉、不報錯、使用者照著錯的圖接板子），差別只在入口是 GUI，所以連
真值表 oracle 都攔不到：oracle 餵進去的設定是合法的。

`src/tools/json2drawio.py`（65 行）的存在本身就是這個缺口的證據——想在沒有 Tk 的情況下跑
一次匯出，唯一的辦法是重寫一遍。

做法是在 `core` 之上、`gui` 之下加一層 use-case 模組，把「驗證 → 產生 → 寫檔」變成可呼叫的
純函式：

```python
# src/pipeline/export.py
@dataclass(frozen=True)
class ExportResult:
    path: str
    summary: str                      # GUI 拿去餵 _status_msg
    errors: tuple[str, ...] = ()      # 非空代表沒寫檔

def export(cfg: PowerSeqConfig, kind: str, path: str, *, opts=None) -> ExportResult:
    """所有匯出共用同一套前置檢查——verilog / c / drawio / schemdraw 不得各寫一份。"""
```

`gui` 縮成「收集設定 → 選路徑 → 呼叫 → 把 `ExportResult` 畫出來」，`tools/json2drawio.py`
改成呼叫同一支。

- **好處**：先修掉上面那個會讓使用者拿到錯誤電路圖的 bug。但結構上的收益是**讓「前置檢查
  一致性」變成可測的**——目前它完全不可測，因為那段邏輯在 Tk method 裡，而且每新增一種
  匯出格式就要有人記得補 `validate()`，漏掉不會有任何東西擋。抽出來之後可以直接斷言
  「每一種 `kind` 對同一份無效設定都回非空 `errors`」，新格式漏檢查會紅。
  順帶解決「無頭匯出只能重寫一遍」：`tools/` 不必再是 `gui` 的影子實作。
- **跟第 4 項的關係**：那一項抽的是 `ProjectSession`（文件狀態——path、dirty、history），
  這一項抽的是 use case（動作序列），不同軸向、不衝突。這項排在前面是因為它有已確認的
  bug，第 4 項目前是預防性的。
- **verify**：`test_export_pipeline.py` 不需要 Tk 就能跑。最低門檻是參數化掃過所有 `kind`：
  無效設定一律回非空 `errors` 且**不得寫出檔案**；有效設定寫出的內容要與直接呼叫
  `generate_verilog` / `generate_drawio` 等逐字元相同（證明這層只做編排、沒改語意）。
  落地前先確認「`_export_drawio` 對無效設定仍會匯出」這條是紅的。
  另外要記得在 `tests/test_package_api.py` 的 `EXPECTED_API` 加 `pipeline` 一項——那支測試
  是參數化跑 `EXPECTED_API` 的鍵，少一個鍵不會失敗、只會沒人守，新套件的對外介面就脫韁了。

**落地結果**：新增 `pipeline` 套件（`export(cfg, kind, path, *, opts=None) -> ExportResult`），
四種 `kind`（verilog / c / drawio / schemdraw）共用同一個 validate 閘。`gui` 的四個匯出
method 全部改走它，`tools/json2drawio.py` 也是。`test_export_pipeline.py` 參數化掃過每種
`kind`：無效設定一律回非空 `errors` 且 `tmp_path` 下不產生檔案；有效設定的 verilog / c /
drawio 與直接呼叫產生器逐字元相同（drawio 只正規化掉每次隨機的 diagram id，schemdraw 因
matplotlib SVG metadata 含日期不穩定，只驗有寫出、非空）。`EXPECTED_API` 已加 `pipeline`。

一個刻意的取捨：**validate 現在只在 pipeline 這一個閘，GUI 不再逐路徑自己 validate。**
代價是無效設定會先選完存檔路徑才跳錯（以前 code-gen 路徑是先擋再開對話框），但即時預覽本來
就一直顯示「N errors」，使用者按匯出前就看得到，所以實務上不算退步；換來的是「有沒有先
驗證」不再是每條路徑各自記得的事。`app.py` 的「no rails 不開對話框」仍是 GUI 的 UX 前置
（drawio / schemdraw 有、code-gen 沒有，沿用原行為，用 `require_rails` 旗標表示）。

### 4. （最後）`app.py` 抽出 `ProjectSession` ✅ 已完成

`PowerSeqGUI(ctk.CTk)` 有 45 個不同的 `self.*`。要抽的不是「再多幾個純函式」，而是其中
真正可分離的那 7 個：`config_obj`、`_current_path`、`_dirty`、`_history`、`_saving`、
`_recent`、`_base_title`。這是一個 document / session 物件；其餘 38 個是 widget、算繪世代
計數器、分隔拖曳狀態，那些是貨真價實的 UI，抽出來沒有意義。

`core/snapshot_history.py` 已經把 undo/redo 的**機制**抽出去了，留在 `app.py` 的是**政策**：
什麼時候該壓一個快照、什麼算「改過」、path 與 dirty 怎麼合成標題。這些正好是會造成
「使用者工作遺失」的那類 bug，而且目前一行測試都沒有。

- **好處**：「使用者工作遺失」那類 bug 從不可測變成可測。這些邏輯目前綁在 Tk 上，等於
  沒有辦法測，所以一行測試都沒有——具體會被守住的是：存檔後 dirty 沒消、undo 回到存檔點
  時 dirty 狀態不對、存檔途中重入。這是整份清單裡唯一直接影響「使用者會不會弄丟工作」的項目。
  另一個效果是 `app.py` 剩下的 38 個 `self.*` 全是真 UI，之後改預覽或版面不會再誤觸文件狀態。
- **verify**：`open` / `save` / `mark_edited` / `undo` / `redo` / `title` / `is_dirty`
  不需要 Tk 就能測；重點放在 dirty 與 history 的交互（存檔後 dirty 要消、undo 回到存檔點
  時 dirty 的狀態、`_saving` 期間的重入）

**落地結果**：新增 `core/project_session.py` 的 `ProjectSession`，接管七個文件狀態
（`config` / `path` / `dirty` / `saving` / `history` / `base_title` / `recent`）與政策
（存檔點、undo 回存檔點後 dirty、存檔重入）。`PowerSeqGUI` 保留 `config_obj` 當指向
`session.config` 的 property alias，所以約 40 個 node 編輯 handler 一行都不用改。放 `core/`
而非 `gui/`：`recent` 以依賴注入傳入（只需要 `.add`），core 不反向 import gui。
`tests/test_project_session.py`（11 個）不需要 Tk。

**一個刻意的行為變更**：undo/redo 回到「上次存檔／載入時的內容」時，dirty 現在會消、標題
的 `*` 跟著不見——以前是無條件 `dirty=True`。做法是 session 記一個「存檔點快照」，還原後
比對目前內容是否偏離它。存檔點用**正規化後的顯示內容**（`_collect_config`）錨定，和 undo
比對用的是同一把尺，否則 `_collect_config` 補預設／清空 `timing_scenario` 造成的差異會讓
undo 回到載入狀態時 dirty 誤判。`_saving` 改走 `begin_save()` 的原子 check-and-set，比原本
「先讀旗標、collect、再設旗標」少一個 collect 失敗會卡住存檔鎖的窗口。

---

## 已完成（vector 節點 + parameter 宣告）

這一輪是**功能擴充**，不是技術債清理，但沿用同一條安全網原則：每階段先紅測試 →
最小實作 → `ci.bat` 全綠；**無 vector / 無 parameter 的既有 config 產生的黃金輸出
（`tests/golden/`）byte 全程不變**，`cond_ir` 與五個後端的條件語意一行未動。

### A 區：vector 核心

- **A1 身份／條件分層** — `PowerRail` 是 god object，身份與條件混在一起。抽出
  `ConditionConfig` 收 `depends_on_{hi,lo,force}_*` 與 `get_*` 存取器，`PowerRail` 改組合
  `cond: ConditionConfig` 並以 `@property` 委派所有既有屬性／方法，使 `cond_ir`、五後端、
  excel、widgets **呼叫點零改動**。等價證明：`tests/golden/` byte 不變 + 委派漏接欄位的注入退化轉紅。
- **A2 vector 模型／序列化** — 新增 `VectorNode`（`base` / `seq_type` / `width_expr` 字串 /
  每 bit `ConditionConfig`）與 `elaborate()` → N 個 `PowerRail`（`base[i]`）；`PowerRail` 加群組
  metadata（`group_base` / `bit_index` / `width_expr`）。`to_dict` 收合同群組成一筆、`from_dict`
  展開。相容舊 JSON（無群組 = width 1）。
- **A3 命名／驗證** — `naming.safe_name` 處理 `[]`（`FOO[2]`→`FOO_2`）；`validator` 新增展開後
  identifier 撞名與 width 正整數檢查。
- **A4 群組批次** — `PowerSeqConfig` 整組 rename（base 改名 → 所有 bit + 全部引用更新）與整組
  刪除／搬移；`core/config_edit.py` 的 `next_rail_name` / `delete_indices` / `move_item` 支援群組。

### B 區：vector 產出／介面

- **B5 產生器（整數寬度）** — Verilog 遇群組 rail 只在 bit 0 收合輸出一條 bus（`[k-1:0]` +
  加寬 wire + 單一 `PSEQCELL` / `DEB` `WIDTH=k`），body assign 先用 bit 0 的條件代表整條 bus；
  C 逐 rail 自然產生 N 個 `pwrcell`（零結構改動）。
- **B6 vector GUI（卡片內分頁）** — 每張節點卡片頂部 `[宣告|條件]` 分段鈕；宣告頁＝身份＋物理
  參數（含 Vector 勾選 + width 欄位），條件頁＝逐 bit（vector 顯示 Bit 選擇器）。左欄
  `NodeListPanel` 維持一列一 Node（vector 不展開），加 `base [×N]` 標記；三區各自加可收合標題。
- **B7 Excel vector** — Nodes sheet 加 `Width/Bits` 欄（key `width`），`excel_import` / `excel_export`
  支援 vector 收合／展開，Conditions 以 bit 名 `base[i]` 引用。

### C 區：parameter 層

- **C8 資料 + eval_width** — 新增 `Parameter(name, value)` 與有序的 `PowerSeqConfig.parameters`
  （`to_dict` 僅非空時輸出該鍵、舊檔 → 空清單）；`core/param_expr.py` 的 `eval_width(expr, parameters)`
  用 **ast 白名單**求值（整數字面、已宣告 parameter 名、`+ - * //`、括號、一元正負；拒 `**` / float /
  bool / 未宣告名 / `__import__`，**不碰 `eval()`**）。`ParamExprError(ValueError)` 讓既有
  `except ValueError` 呼叫者照舊接住。`from_dict` 展開群組改走帶 parameters 的 `eval_width`，
  `width_expr` 可為公式；公式字串本身原樣保留。
- **C9 產生器宣告** — Verilog「Parameter Declare」段輸出對齊的 `#(parameter NAME = VAL, ...)`
  （無則沿用 `//    No parameters` 佔位）；群組寬度符號化：整數 `[k-1:0]` / `.WIDTH(k)`、公式
  `[(EXPR)-1:0]` / `.WIDTH((EXPR))`。C 檔頭（`#include` 後、struct 前）輸出 `#define` 區塊
  （無 parameter 不輸出；body 仍用展開後的具體 N）。
- **C10 驗證** — parameter 名需為合法識別子、不重複、值為正整數；width 公式僅能引用已宣告
  parameter 且 `eval_width > 0`，未宣告 → 判為無效寬度。訊息沿用 `'<name>'` 可點擊跳轉格式。
- **C11 parameter GUI** — 新增 `ParameterPanel`（比照 `PulsePanel` 的 name=value 清單、可收合，
  置左欄 Timing Signals 上方），接進 `app.py`（存 `config.parameters`、觸發 dirty 與重算；值變更時
  以 `to_dict`/`from_dict` round-trip 重算受影響群組的展開 N，無效 width 交 validator 回報不中斷 UI）。
  `RailEditorFrame` 的 width 欄位改接受公式（`_parse_width` 走 `eval_width`、失敗回退整數）、
  `get_rails` 保留 `width_expr` 符號字串，並加「插入 parameter」下拉。

### 刻意延後（走乙，見 `doc/FUTURE.md`）

B5 當時 body assign 先用 bit 0 的條件代表整條 bus；該限制已在後續「Verilog vector 條件逐 bit
展開」一輪移除（見下），跨 bit 葉節點參照也已索引化（見下）。仍延後的只剩**可選的 `generate`
迴圈收合行數**（非正確性缺口，見 `doc/FUTURE.md`）。

### 追加（獨立小輪）：C vector 輸出甲案化

**一個刻意的輸出形狀變更**：C 產生器對 vector 群組原本逐 bit 攤平成 N 份獨立成員
（`pwrcell_t vout_0; vout_1; …` + 各自的 init / handle / 條件），現改為**陣列宣告
`pwrcell_t base[N];` + 所有引用走索引 `base[i]`**（static initializer、`pwrcell_Init`、
`pwrcell_handle`、條件賦值 LHS，以及條件式裡引用其他 bit `.condition` 的 RHS——`_CCond`
改吃 `name_to_rail` 以 `base[i]` 輸出）。**條件仍逐 bit 展開**（每 bit 一行，不做 `for` 迴圈），
保留每 bit 條件可不同。Verilog、`cond_ir` 與非群組 rail 的成員名一律不變。

### 追加（獨立小輪）：C vector handle 迴圈化

**接續甲案的另一個刻意輸出形狀變更**：vector 的 `pwrcell_handle` 從 N 行離散呼叫改為
**「GPIO 表 + `for` 迴圈」**——對每個 vector base 輸出一張 `static const pwrseq_gpio_ref_t
base_gpio[N]`（每 bit 填 header 既有的 `<MACRO>_PORT`（`GPIO_T*` port 指標）/ `<MACRO>_BIT`
（pin 整數）），再用 `for (UINT8 i = 0; i < N; i++) pwrcell_handle(&var.base[i], arg_hi, arg_lo,
base_gpio[i].port, base_gpio[i].pin);` 取代。typedef `pwrseq_gpio_ref_t` 自成一體寫進產出 C 檔
（不需改 firmware），只在有 vector 時出現。time 引數（arg_hi/arg_lo）全 bit 共用，取 bit 0 代表；
**條件賦值與 static initializer 仍逐 bit**（刻意不迴圈，保 per-bit 獨立）。非群組 rail 的 handle
行完全不變。

兩輪都只影響**含 vector 的 C 輸出**：`tests/golden/demo_vector.c` 鎖住新形狀；
無 vector 的 `tests/golden/demo.c` byte 不變。剩下的 Verilog `generate` 迴圈與 C 條件賦值迴圈化
仍記在 `doc/FUTURE.md`。

### 追加（獨立小輪）：Verilog vector 條件逐 bit 展開

**一個刻意的輸出形狀變更**：Verilog 的 vector condition assign 從「bit 0 的條件代表整條 bus」
（`assign base_hi = …`）改為**逐 bit 索引展開**——群組的 head 蔓開該群組所有 bit（依 `bit_index`），
每 bit 渲染**自己的**條件：`assign base_hi[i] = …;` / `base_lo[i]` / `base_force[i]`，每 bit 三行後
空一行，`No-condition` 注解沿用（該 bit 的樹是 `Const` 才加）。非群組 rail 的 assign 完全不變（無索引）。
condition wire（`wire [k-1:0] base_hi, …`）、單一 `PSEQCELL`/`DEB` WIDTH=k、bus port、
`Continuous Assignment` 全部不變，只有 condition assign 區塊改成逐 bit。這才真正輸出 bit 1..N-1
各自的條件（先前被收合忽略）。

只影響**含 vector 的 Verilog 輸出**；無 vector 的 `tests/golden/demo.v` byte 不變（非群組路徑沒動），
新形狀由 `tests/test_vector_generators.py` 的逐 bit 測試鎖定。

### 追加（獨立小輪）：Verilog 跨 bit 葉節點參照索引化

**接續逐 bit 展開的正確性修補**：某 vector bit 的條件若引用**別 vector 的具體 bit**（如 `VOUT[i]`
的條件依賴 `PG[i]`），`_VerilogCond` 原本把葉節點名直接過 `internal_sig`，產出收合後根本不存在的
訊號 `pg_0` / `pg_0_deb` / `pg_0_hi`。現改為：被參照 rail 有 `group_base` 時，葉節點渲染成收合 bus
的索引 `<bus>[bit_index]`，分四類——output 準位 `pg[i]`、input 無 deb `iPG[i]`、input 有 deb
`pg_deb[i]`、`cond`（iHi/iLo/iForce）`pg_{kind}[i]`；`<bus>` 用 `_group_sig`/`_group_port`，
`i` 用 `bit_index`。非群組 rail 的渲染完全不變，`cond_ir` 語意不動（只改 `_VerilogCond` 渲染層）。
`tests/test_vector_generators.py::TestVerilogCrossBitLeaf` 覆蓋四類；`demo.v` byte 不變。

---

## 進行中（以「維度 + slice」取代 parametric）

舊的「參數化向量條件 v2（freeexpr + domain 迴圈，pexpr）」已**整組移除**，改以 `PseqGeneratorNewFunction.txt`
描述的「維度 + slice」模型重建條件授權。非 parametric 的黃金輸出（`tests/golden/`）byte 全程不變。分階段落地：

- **階段A（已完成）— 移除 parametric 全鏈路**：刪 `core/pexpr.py`、`core/pexpr_build.py`；
  `config_models` 移除 `ParametricNode`、`PowerRail.pexpr_{hi,lo,force}`、`param_node`、`"parametric"` 收合格式
  （`from_dict` 遇舊鍵略過不載入）；verilog/c/sim/validator 的 parametric 路徑與 `check_parametric` 一併移除；
  GUI 移除 `ParametricCondFrame` 與 Parametric 切換。`eval_width`（寬度公式）保留，後續 2D `P1*P2` 會用到。
- **階段B（已完成）— Parameter 全域維度骨架**：`PowerSeqConfig.dimensions`（0～2 個，指向 parameter 名稱，
  維度1＝row、維度2＝col，parameter 值即最大值）；`to_dict` 非空才輸出、`from_dict` 正規化並最多取 2 個；
  `validator.check_dimensions`（個數 0～2、名稱存在、不重複、最大值 ≥ 1）；`ParameterPanel` 改為對齊
  `PseqGeneratorNewFunction.txt` §1 的 dims-only 流程——「維度個數」下拉選 N 即長出 N 列「名稱＋最大值」欄位，
  parameter 即維度本身（不需另外新增 parameter），`on_change(params, dims)` 單一回呼。
  `tests/test_dimensions.py`、`tests/test_gui_parameters.py`。
- **階段C（已完成）— Signal 維度宣告骨架**：signal 可選 0/1/2 維 → `width_expr`（0→`"1"`、1→`P1`、2→`P1*P2`，
  由 `config_edit.width_expr_from_dims` 單一來源推導）；群組 dict／`PowerRail` 存 `dim_params`（非空才序列化、round-trip）；
  `RailEditorFrame` 宣告列改「維度 [0/1/2]」下拉＋Bits 維度 parameter 下拉（只列全域維度，無維度時沿用舊 `width_expr`，
  不破壞既有向量）；Verilog 2D flat bus 走既有公式路徑 `[(P1*P2)-1:0]`。`tests/test_dimensions.py`、`tests/test_gui_parameters.py`。
- **階段D（進行中）— take 取法＋符號化 generate-for**：讓維度 vector 的條件以「head 一份符號條件＋每引用項帶 row/col take」
  表達，Verilog 改走 generate-for，修好「1 維輸出引用 2 維訊號」的列優先幾何 bug（原本 `sig_4[i]` 直接對應 → 正確
  `sig_4[gv_row*M + col-take]`）。分步：
  - D1 運算式產生器 `core/take_expr.py`（`Take`／`take_expr`／`take_from_dict`，對照 3.1~3.6）：0 維直接引用、1 維 row take
    （Same／Specific(+相對偏移)／All AND|OR）、2 維列優先扁平 `bus[row*M + col]` 的乾淨組合；「All row 搭配逐 col」跨步歸約（3.5）
    明確不支援並報錯。`tests/test_take_expr.py`。
  - B1 存儲：`ConditionConfig` 加 `depends_on_{kind}_take_groups`（與 use_groups 平行 per-group per-item，幾何不入存），
    非空才序列化、round-trip、舊檔 byte 不變。
  - B2 IR：`cond_ir` 新增葉節點 `TakeRef` 與 `CondVisitor.take_ref`（abstract，強制六個 visitor 面對）；`resolve_item` 對
    「被引用 rail 有 dim_params＋帶 take」包成 `TakeRef`；Verilog visitor 走 `take_expr` 符號渲染，C／sim／drawio／時序
    四後端先放 `NotImplementedError` 佔位（無維度 config 不觸發 → ci 綠）。
  - B3 Verilog generate-for：`group_base` 且 `dim_params` 的 vector condition assign 改 `for(gv_row[/gv_col])`＋具名 scope；
    legacy vector（無 dim_params）續走逐 bit，byte 不變。`tests/test_take_ir.py`。
  - B4 GUI 條件頁 take 編輯：`CondEditModel` 加 `take` 平行欄（`from_rail`/`from_initial` 載入、`add_dep(take=)`、
    `to_take_groups`），`CondSectionFrame.get_take_groups` → `_apply_output_sections` 回寫 `rail.depends_on_{kind}_take_groups`；
    `RailEditorFrame._expand_dep` 在「owner 與 dep 皆維度向量」時改走 symbolic take（只掛 base[0] 把手，幾何由 take 承載），
    1 維 owner 參照 2 維來源時 row=same、col 由模式下拉決定（全部AND／任一OR／指定欄），其餘向量續走 legacy 逐 bit。
    owner 維度 < dep 維度時模式下拉移除「同索引」（對缺的軸無意義，`_drop_same_for` 經 `_VecDepHelper` 注入 `CondSectionFrame`）。
    `tests/test_cond_edit_take.py`、`tests/test_gui_take.py`。
- **§6 取法 UI（已完成）— 條件頁 per-row 取法編輯器**：以 `core/take_rules.py` 為單一規則來源，依
  「輸出維度 × 被引用維度」枚舉合法取法形狀（`take_forms`）、預設（`default_form`）與 `形狀+n/m ↔ take dict`
  映射（`form_to_take`／`take_to_form`），§3.4（輸出缺軸不得用 gv_col）、§3.5（跨步 All-row 不列入＝隱藏）
  由此收斂。GUI（[src/gui/widgets.py](src/gui/widgets.py)）：維度向量相依不再用 header 模式/bit，改在相依列上
  兩層呈現「取法下拉＋第二行 n/m 子選項」，變更即寫回 `model.take`、隨 `get_rails` 帶出；
  `_expand_dep` 加入時套 `take_rules` 預設 take（取代 `_symbolic_take`/`_drop_same_for`）。
  1 維 dep：相對偏移／指定絕對／全部AND／全部OR；2 維 dep：row 偏移 + {指定col／全col OR／全col AND}，
  輸出 2 維再加 row 偏移 + col 偏移（gv_col，n=m=0 即完全對齊）。scalar／legacy 非維度向量維持原狀。
  `tests/test_take_rules.py`、`tests/test_gui_take.py`、`tests/test_take_ir.py::TestVerilogSection6Forms`。
- **1D All 歸約加下界（已完成）**：1D 被引用訊號的 All AND/OR 取法多一個數字欄 n，產出
  `|oneDim[NUM_ROW-1 : n]`（`NUM_ROW > n >= 0`）。n=0 即整條 bus，輸出與舊版 byte 相同；
  x15 的 `|oCPU_PRSNT[NUM_CPU-1:1]` 即 n=1 的形狀。實作：`Take` 新增 `lo`（只給 ALL 用，
  序列化時 n=0 不寫入），`TakeRef` 新增 `row_size`（由 `dim_params[0]` 帶入），`take_rules`
  的 ALL 形狀加 `("n", "下界")`，validator 檢查 `0 <= lo < 最大 NUM_ROW`（以 parameter 預設值為畫布，
  實際 N 更小時的越界由使用者負責）。2D 的 row 範圍是跨步歸約（§3.5），明確不支援。
  `tests/test_take_expr.py`、`tests/test_take_rules.py`、`tests/test_take_ir.py`、
  `tests/test_validator.py::TestTakeLowerBound`、`tests/test_gui_take.py::TestAllRowLowerBoundCell`。
- **Slice V1（row 軸，已完成）**：§4 的 slice 切片落地到 row 軸（1D 與 2D 的 row 軸）。
  資料模型（[src/core/config_models.py](src/core/config_models.py)）：`ConditionConfig.slices: list[SliceGroup]`，
  `SliceGroup{rows, axis, cond}` 為非 else 群組的有序清單，扁平 `depends_on_*` 本身即 else；`slices` 非空才序列化，
  舊檔與非切片 config → golden byte 不變。IR（[src/core/cond_ir.py](src/core/cond_ir.py)）：`resolve_sliced_condition`
  把 head 展開成 `[(述詞, 解析後條件), …, (None, else)]`，`render_row_predicate` 產 `gv_row==k` 的 `||` 連接；
  語意仍單源於 `resolve_condition`。Verilog（[src/codegen/verilog_generator.py](src/codegen/verilog_generator.py)）：
  維度 vector 條件由 `_emit_dim_vector_cond` 在多群組時展成 generate-for 內 `if/else if/else`，單群組沿用原本單行 assign。
  其餘四後端（C／sim／drawio／timing_export）以 `assert_backend_no_slices` 佔位報 `NotImplementedError`（無切片不觸發）。
  validator `check_slice_reachability` 對 `k >= 最大 NUM_ROW` 的不可達 row 出警告（不阻擋匯出）。GUI
  （[src/gui/widgets.py](src/gui/widgets.py)）：維度輸出的條件頁改「per-row 群組下拉 + 群組選擇器切換編輯器」
  （取代逐 bit 勾選），群組選項＝現有群組 + else + 「新增…」，空群組自動移除、else 恆最後唯一。
  `tests/test_slice.py`、`tests/test_slice_gui.py`、`tests/test_gui_vector.py`。
- **Slice col 軸（已完成）**：§4.2／§4.3 的 col 單軸切片（只適用 2D 訊號）。`SliceGroup` 加 `axis`（預設
  `"row"`，**只有 col 才序列化 `axis` 鍵** → row／舊檔 byte 不變）；`resolve_sliced_condition` 依群組 `axis`
  選 genvar（col 以 `gv_col` 呼叫 `render_row_predicate` 得 `gv_col==k`）；Verilog 的 if 鏈本就落在內層
  `for(gv_col)` 內（§4.3(2)），col 述詞原位插入、形狀 `assign vv_kind[gv_row*NUM_COL + gv_col]`。
  validator：`check_slice_reachability` 的 col 軸比 `NUM_COL`（dim_params[1]）；新增 `validate()` 守門
  「axis=col 但非 2D → 報錯」。GUI：Bit 選擇器上方新增「切片軸」下拉（2D 給 row/col、1D 只有 row），
  分組標籤隨軸切換，**切軸清空目前分組、新軸從全 else 重來**（else 扁平條件保留）。其餘後端仍以
  `assert_backend_no_slices` 擋 col slice（訊息更新為 row/col）。`tests/test_slice_col.py`、`tests/test_slice_gui.py`。
- **後續**：§4.4 slice 的兩者軸（row＋col 巢狀）與區段選擇器（前 k 個／指定 k／其餘）；
  §3.6.2 自由運算式逃生口；階段F 把 C／sim／drawio／excel 的 `take_ref`／slice 佔位換成具體材質化（`take_cells`）。
