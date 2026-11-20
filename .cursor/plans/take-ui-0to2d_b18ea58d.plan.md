---
name: take-ui-0to2d
overview: 在現有條件頁用 per-row「取法」下拉＋子選項列，讓使用者對 0~2 維被引用訊號完整授權 §6 的合法 assign 形狀；取法合法性/預設/映射集中到單一規則模組 core/take_rules.py。
todos:
  - id: take-rules
    content: 新增 core/take_rules.py（take_forms/default_form/form_to_take/take_to_form，編碼 §3.4/§3.5/§6）＋ tests/test_take_rules.py 紅測試
    status: pending
  - id: default-wire
    content: _expand_dep 維度向量改用 take_rules.default_form 產預設 take；移除 _symbolic_take/_mode_take/_drop_same_for
    status: pending
  - id: row-editor
    content: _add_cond_row 插入取法 kind 下拉＋第二行子選項（n/m 數字欄），讀寫 model.take；_VecDepHelper 增 owner_ndim/dep_ndim
    status: pending
  - id: hide-header-mode
    content: _refresh_vec_controls 對維度向量隱藏 header 模式/bit，legacy 維持原狀
    status: pending
  - id: gui-tests
    content: 擴充 tests/test_gui_take.py：選項隨維度、子選項列、寫回 model.take、Apply→verilog 覆蓋 §6 形狀（ripple/col偏移/1D←2D）
    status: pending
  - id: ci-docs
    content: ci.bat 全綠、golden byte 不變；同步 ROADMAP.md
    status: pending
isProject: false
---

# 條件頁 0~2 維取法 UI（§6）

以「取法」規則表驅動的 per-row 編輯器，覆蓋 `PseqGeneratorNewFunction.txt` §6 全部合法形狀。範圍限定新維度模型的維度向量；scalar / legacy 非維度向量不動。

## 決策（grilling 結論）

- 範圍：增量版，沿用現有 `CondSectionFrame`，不動 §4.4 大改版（Q1）。
- 規則單一來源：新增 `core/take_rules.py`，UI 可選項/預設/映射都讀它（Q2）。
- 相對偏移納入（Q3）；不支援的跨步 All-row 直接**不顯示**（Q4）。
- 只作用維度向量（Q5）；0 維/legacy 維持現狀。
- 流程：先選訊號、按 Add 加入（套預設取法），再於該列依維度編輯（Q6/Q11）。
- 不做即時 RHS 預覽，靠 Apply 後的 Verilog/C Preview（Q7）。
- 版面兩層：第一行 `[]inv [取用v] [取法v] Del`，第二行冒出該取法的數字子選項（Q9/Q12）。

## 取法清單（`take_rules` 枚舉，依 輸出維度 × 被引用維度）

- dep 0 維：無取法（直接引用）。
- dep 1 維：相對偏移 `gv_row±n`（子:偏移值 n）／指定絕對 `k`（子:索引 k）／全部AND `&`／全部OR `|`。預設=相對偏移 n=0 → `oneDim[gv_row]`。
- dep 2 維、輸出 1 維（§3.4：col 不得含 gv_col）：
  - row 偏移 + Specific col m → `twoDim[(gv_row±n)*C + m]`（子: n, m）
  - row 偏移 + All col OR → `|twoDim[(gv_row±n)*C +: C]`（子: n）
  - row 偏移 + All col AND → `&twoDim[(gv_row±n)*C +: C]`（子: n）
- dep 2 維、輸出 2 維：上 3 項 + row 偏移 + col 偏移 `gv_col±m` → `twoDim[(gv_row±n)*C + gv_col±m]`（子: n, m；n=m=0 即完全對齊）。
- 2 維 dep 的預設=「row 偏移 n=0 + Specific col m=0」→ `twoDim[gv_row*C + 0]`（Q8）。
- §3.5 跨步（All-row + 非 All-col）不列入任何清單（Q4 隱藏）。

索引字串約定（交給 `take_rules` 單點產生，對齊 `verilog_generator` 的 `GV_ROW/GV_COL`）：相對 n=0→`"gv_row"`、n≠0→`"gv_row+n"/"gv_row-n"`；絕對→`str(k)`；col 同理用 `gv_col`。這些字串丟進既有 `take_expr`（`Take.index` 吃任意算式）即產出正確 RHS。

## 實作

### 1. core/take_rules.py（新，純函式，單一來源）
- `take_forms(out_ndim, dep_ndim) -> list[TakeForm]`：回合法形狀（含 label、需要哪些數字欄 n/m），§3.4/§3.5 由此收斂。
- `default_form(out_ndim, dep_ndim) -> (form_id, n, m)`：上述預設。
- `form_to_take(form_id, n, m) -> {"row":{...}, "col"?:{...}}`：產生符合 `core/take_expr.take_from_dict` 的 dict。
- `take_to_form(take) -> (form_id, n, m)`：回填下拉用（round-trip 顯示）。
- 不新增節點型別、不碰 `take_expr` 的 emission；只在 take dict 層工作。

### 2. 落地預設：以 take_rules 取代散落邏輯
- [src/gui/widgets.py](src/gui/widgets.py) `RailEditorFrame._expand_dep`：dep 為維度向量時回 `([base0], None, default_take)`（用 `take_rules.default_form`＋`form_to_take`），取代現有 `_symbolic_take`/`_mode_take`；`_drop_same_for` 由規則清單取代後移除。legacy 向量維持逐 bit。

### 3. per-row 取法編輯器（兩層版面）
- [src/gui/widgets.py](src/gui/widgets.py) `CondSectionFrame._add_cond_row`：目前一列 `row` 內有 `label / Inv / use combo / Del`。改成在 `use combo` 與 `Del` 之間插入 **取法 kind 下拉**；並把 `row` 容器改為可容納「第二行子選項」（新增一個子 frame，依選到的 form 顯示 `偏移值 n` /`欄索引 m` /`欄偏移 m` 數字欄）。
- 下拉選項與預設來自 `take_rules.take_forms(out_ndim, dep_ndim)`；變更即寫回 `self.model.take[gi][ii] = form_to_take(...)`，並 `_fire_change()`。
- dep 0 維/legacy/scalar：不顯示取法控制（維持現狀）。
- `_VecDepHelper` 增 `owner_ndim()` 與 `dep_ndim(sel)`（由 `RailEditorFrame._dim_count` / `_dep_dim_params` 提供），讓 `CondSectionFrame` 不自行理解維度。

### 4. 隱藏維度向量的 header 模式下拉
- [src/gui/widgets.py](src/gui/widgets.py) `CondSectionFrame._refresh_vec_controls`：dep 為維度向量時隱藏「模式＋bit」（取法改在相依列上）；legacy 向量維持原模式/bit 行為。

### 5. 模型層
- `CondEditModel.take`（[src/core/cond_edit.py](src/core/cond_edit.py)）B4 已就位並 round-trip；本階段僅由新 widget 讀寫，無需改模型。

## 測試（紅→綠）

- `tests/test_take_rules.py`（新）：每個 (out_ndim, dep_ndim) 的 `take_forms` 清單、預設、`form_to_take`↔`take_to_form` round-trip；驗證輸出 1 維時不含 gv_col 項、2 維才有 col 偏移；跨步 All-row 不出現。
- `tests/test_gui_take.py`（擴充）：下拉選項隨維度增減、選到帶數字的 form 時子選項列出現、改值寫回 `model.take`；Apply→`generate_verilog` 對幾個 §6 形狀正確（含 ripple `gv_row-1`、col 偏移 `gv_col`、1D←2D `&...[+:C]`）。
- 既有 `take_expr`/`cond_ir`/verilog 測試不動；golden byte 不變（無維度向量 golden）。

## 收尾
- `ci.bat` 全綠、golden byte 不變。
- 文件同步 `ROADMAP.md`（階段D 之後新增「§6 取法 UI」條目，標明 take_rules 單一來源、legacy 不動、其他後端仍 Stage F 佔位）。
- 依規則不自動 commit/push。

## 非目標（本階段不做）
- §4.4 條件頁大改版（分組標籤/Slice/規則清單）。
- §3.5 跨步 All-row 歸約的實作。
- C/sim/drawio/excel 的 take 材質化（Stage F）。
- 自由運算式逃生口（§3.6.2）。