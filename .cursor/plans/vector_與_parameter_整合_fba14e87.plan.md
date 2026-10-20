---
name: Vector 與 Parameter 整合
overview: 單一有序計畫：先把 PowerRail 拆成身份+條件並引入 vector（扁平 rails + 群組 metadata），讓 Verilog 收合群組成 bus、C 逐 rail 展成 N 個 cell；再疊上 parameter（具名常數 + width 公式 + 模組頭宣告）。cond_ir 與既有無 vector 的黃金輸出全程不變。
todos:
  - id: a1-extract-cond
    content: "A1 身份/條件分層: core 新增 ConditionConfig（搬入 depends_on_{hi,lo,force}_* 與 get_* 存取器）；PowerRail 改組合 cond:ConditionConfig 並 @property 委派所有既有屬性/方法，使 cond_ir / _cond_kind_to_dict / 五後端 / excel / widgets 零改動。verify: ci.bat 全綠且 tests/golden/ byte 不變；注入委派漏接欄位的退化轉紅。"
    status: completed
  - id: a2-vector-model
    content: "A2 vector 模型+序列化: 新增 VectorNode（base/seq_type/width_expr 字串/每 bit ConditionConfig）與 elaborate()→N 個 PowerRail（base[i]）；PowerRail 加群組 metadata（group_base/bit_index/width_expr）。to_dict 收合同群組 rail 成一筆、from_dict 展開（width_expr 為整數字串時 N=int）。相容舊 JSON（無群組=width 1）。verify: 先寫紅測試—含 vector 的 config round-trip 相等、舊 demo_json.json 載入後 to_dict byte 不變。"
    status: completed
  - id: a3-naming-validate
    content: "A3 命名/驗證: 擴充 naming.safe_name 處理 [](FOO[2]->FOO_2)；validator 新增展開後 identifier 撞名、width 整數>0 檢查。verify: 撞名/非正整數案例轉紅，既有輸出不變。"
    status: completed
  - id: a4-group-ops
    content: "A4 群組批次: PowerSeqConfig 整組 rename（base 改名→所有 bit + 全部引用更新）與整組刪除/搬移；core/config_edit.py 的 next_rail_name/delete_indices/move_item 支援群組。verify: 群組 rename/delete 後條件樹引用一致，注入退化轉紅。"
    status: completed
  - id: b5-generators-int
    content: "B5 產生器(整數寬度): Verilog 遇群組 rail 只在 bit 0 收合輸出一條 bus [k-1:0] + 加寬內部 wire（主線 {s}、{s}_hi/_lo/_force、input {s}_deb）+ 一個 PSEQCELL/DEB WIDTH=k，body assign 用 bit 0 代表；抽 _width_prefix/_width_param + 群組 bit0 判斷 helper。C 逐 rail 自然產生 N 個 pwrcell（零結構改動）。verify: 新 fixture 鎖定 Verilog bus/wire/WIDTH 與 C 的 N 個 member；無 vector 的 golden demo.v / power.c byte 不變。"
    status: completed
  - id: b6-gui-vector
    content: "B6 vector GUI(方案甲-卡片內分頁): 每張節點卡片頂部 [宣告|條件] 分段鈕，各節點獨立切換。宣告分頁=整個 IO 身份+物理參數(含 Vector 勾選框 + width 欄位；Output: Timing(PSEQCELL)、Input: Debounce，全 bit 共用)；條件分頁=逐 bit—Output: Hi/Lo/Force(CondSectionFrame)、Input: Timing Hi/Lo(input_wave_frame/InputWaveCondFrame)，vector 顯示 Bit 選擇器([0]/[1]/...)、單一節點不顯示。左側 NodeListPanel 維持一列一 Node(vector 不展開 bit)，僅加 vector 標記(如 base [×N])；選取/排序/多選不變，對 vector 的 rename/delete 整組作用(接 A4)。verify: 不依 Tk 的模型層斷言(分層後條件樹不變) + widget 接線測試(分頁切換 / Bit 選擇器 / vector 標記顯示)。"
    status: completed
  - id: b7-excel-vector
    content: "B7 Excel vector: Nodes sheet 加 Width/Bits 欄（excel_template_layout + scripts/generate_excel_template.py）；excel_import/excel_export 支援 vector 收合/展開，Conditions 以 bit 名引用。verify: 含 vector 的 round-trip 綠、黃金 excel round-trip 不變。"
    status: completed
  - id: c8-param-data
    content: "C8 parameter 資料+eval_width: 新增 Parameter dataclass + PowerSeqConfig.parameters（有序，to_dict/from_dict，舊檔→空清單）；core/param_expr.py 的 eval_width(expr,parameters) 用 ast 白名單求值（整數/parameter 名/+ - * // 括號/一元負，禁 eval()）；from_dict 展開群組改走 eval_width，width_expr 可為公式。verify: 單元測試 NUM_CPU*2 / NUM_CPU*NUM_CPU_MEM / 非法 / 未宣告名稱→錯誤；含 parameter+公式 width 的 config round-trip。"
    status: completed
  - id: c9-param-gen
    content: "C9 產生器宣告: Verilog Parameter Declare 段輸出 #(parameter NAME = VAL,...)（對齊），group 收合的 bus/WIDTH 改用符號 width_expr([(EXPR)-1:0]/.WIDTH((EXPR)))；C 檔頭(#include 後/struct 前)輸出 parameter #define 區塊（無 parameters 不輸出），#define 僅具名常數、body 不引用。verify: 新 fixture 鎖定 #(parameter) / #define / 符號寬度；無 parameter 的 golden 不變。"
    status: completed
  - id: c10-param-validate
    content: "C10 parameter 驗證: parameter 名合法/不重複/正整數；width 公式僅引用已宣告 parameter 且 eval_width>0。錯誤訊息沿用可點擊跳轉格式。verify: 每類無效輸入各一約紅測試轉紅，正常 config 綠。"
    status: completed
  - id: c11-param-gui
    content: "C11 parameter GUI: 新增 ParameterPanel（比照 PulsePanel）置於左欄 Timing Signals 上方，接進 app.py（存 config.parameters、觸發重算與 dirty、值變更時重算受影響群組的展開 N）；RailEditorFrame 的 width 欄位擴充成接受公式 + 「插入 parameter」下拉。另：左欄 Nodes / Parameters / Timing Signals 三區各自加可收合標題（點標題展開/收合，預設展開；Nodes 區維持 weight 撐滿）。verify: ParameterPanel 模型層測試 + 插入 parameter 後 width_expr 正確 + 改值重展開 + 三區收合切換 widget 測試。"
    status: completed
  - id: d12-docs
    content: "D12 文件/skill 同步: README 套件結構/相容性（ConditionConfig、群組 metadata、parameters/width_expr 預設）、ROADMAP 標記本輪、doc/FUTURE 相關項、.cursor/skills（excel-template、drawio-placement）與條件相關 rules；記下『body 迴圈化（Verilog generate / C 陣列，走乙）』為後續項。verify: github-upload-docs-sync 檢查一致、ci.bat 全綠。"
    status: completed
isProject: true
---

# Vector 節點與 Parameter 宣告（整合計畫）

把原「vector 分層」與「parameter 宣告」兩份合併為單一有序計畫。vector 是地基、parameter 疊其上，故**先做 vector 核心，再做 parameter 層**。依 `workflow.mdc`：每階段先紅測試 → 最小實作 → ci.bat 全綠 → 才進下一步；GUI 放各自區塊的最後。

## 現況核心問題

[`PowerRail`](src/core/config_models.py) 是 god object，身份（`name`/`seq_type`/`pulse_*`/`deb_*`/`cycle_*`/`init`/`force_val`）與條件（`depends_on_{hi,lo,force}_*` + 一堆 `get_*`）混在一起；節點恆為單一 bit，無 vector、無 parameter。

## 已確認的設計決策

- **vector = 陣列式**：N bit 展開成 N 個獨立 `PowerRail`（canonical 名 `base[i]`），config 以**扁平 rails + 群組 metadata** 保存，序列化收合成一筆。
- **每 bit 條件完全獨立**；條件只引用**具體 bit**（`FOO[2]`）→ `cond_ir` 與五後端葉節點不動。
- **身份 / 條件分層**（Extract Class）：抽出 `ConditionConfig`，`PowerRail` 委派，呼叫點零改動。
- **GUI 分層對稱**：宣告頁只留身份＋物理參數（Output: Timing(PSEQCELL)／Input: Debounce）；「條件」統一移到逐 bit 的條件步驟—Output 顯示 Hi/Lo/Force（`CondSectionFrame`）、Input 顯示 Timing Hi/Lo（`input_wave_frame`/`InputWaveCondFrame` sim 刺激），兩者並列、依選取 bit 的型別切換。
- **GUI 導覽（方案甲）**：身份/條件用「卡片內 `[宣告|條件]` 分段鈕」切換，各節點獨立；條件分頁的 Bit 選擇器只在 vector 出現（單一節點不顯示）。左側 `NodeListPanel` 維持**一列一 Node（vector 不展開 bit）**，加 vector 標記（`base [×N]`）；vector 的選取／rename／delete 整組作用（接 A4）。
- **左欄版面**：由上而下為 Nodes（`NodeListPanel`，weight 撐滿）／**Parameters（`ParameterPanel`，置於 Timing Signals 上方）**／Timing Signals（`PulsePanel`）。三區各自加可收合標題（點標題展開/收合，預設展開）。
- **Verilog 收合**：遇群組 rail 只在 bit 0 收合輸出一條 bus（`[k-1:0]` / `[(公式)-1:0]`）+ 加寬 wire + 一個 PSEQCELL `WIDTH`；per-bit body 先用 bit 0 代表。
- **C**：扁平 rails 已是 N 個 → 逐 rail 自然產生 N 個 `pwrcell`；parameter 以 `#define` 做對照。
- **parameter**：config 層 `(name,value)` 清單，輸出 Verilog `#(parameter ...)` 與 C `#define`；vector width 可為引用 parameter 的公式。
- **body 先不動（走乙再做）**：Verilog generate 迴圈 / C 陣列迴圈、真正 per-bit 條件渲染。

## 統一架構

```mermaid
flowchart TD
  subgraph authoring [作者/持久化層]
    VN["VectorNode: base + seq_type + width_expr(字串) + 每 bit ConditionConfig"]
  end
  subgraph canonical [記憶體 canonical]
    Rails["config.rails: 扁平 PowerRail (一 bit 一筆) + 群組 metadata"]
    Params["config.parameters: (name,value)"]
  end
  subgraph gen [產生器]
    V["Verilog: 收合群組→bus + #(parameter)"]
    C["C: 逐 rail→N pwrcell + #define"]
    DT["drawio / timing: 逐 bit"]
  end
  VN -->|"from_dict 展開 (eval_width)"| Rails
  VN -->|"to_dict 收合"| VN
  Rails --> V
  Rails --> C
  Rails --> DT
  Params --> V
  Params --> C
```

### 設計模式

- **Extract Class + 委派（Facade）**：`ConditionConfig` 收 `depends_on_*`，`PowerRail` 組合並 `@property` 委派，下游零改動。
- **Elaboration / Builder**：`VectorNode` → N 個 `PowerRail`（`base[i]`）；`eval_width` 決定 N。
- **Adapter（持久化邊界）**：`to_dict` 收合群組、`from_dict` 展開，相容舊 JSON（無群組 = width 1、無 parameters = 空清單）。
- **群組收合（Verilog 專屬）**：以群組 metadata 判斷「是否 bit 0」決定收合輸出。

### 命名與範圍

- bit canonical 名 = `base[i]`；擴充 [`naming.py`](src/core/naming.py) `safe_name` 使 `FOO[2]`→合法 identifier `FOO_2`；新增展開後撞名驗證。
- `width_expr` **一律存字串**（整數期 `"2"`、parameter 期 `"NUM_CPU*2"`），`_width_prefix` 整數→`[k-1:0]`、公式→`[(expr)-1:0]`。
- `ConditionConfig` 只收 `depends_on_{hi,lo,force}_*`；input-wave 的 `hi_groups/...` 留在節點層。
- `cond_ir`/`codegen`/`timing`/`drawio`/`validator` 對**無 vector/parameter 的既有 config 行為不變**，靠 [`tests/golden/`](tests/golden) byte 鎖定反證。

## 分階段順序

A. Vector 核心：1 分層 → 2 模型/序列化 → 3 命名/驗證 → 4 群組批次操作
B. Vector 產出/介面：5 產生器（整數寬度）→ 6 GUI → 7 Excel
C. Parameter 層：8 資料+eval_width → 9 產生器宣告（Verilog `#(parameter)` + 符號寬度 / C `#define`）→ 10 驗證 → 11 GUI
D. 12 文件/skill 同步
