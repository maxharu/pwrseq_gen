"""take 取法規則表（對照 PseqGeneratorNewFunction.txt §3.4 / §3.5 / §6）。

單一來源：給定「輸出維度 × 被引用維度」，枚舉合法的取法形狀（UI 下拉選項）、
預設形狀、以及「形狀 + 數字(n/m) ←→ take dict」的雙向映射。

本模組只在 take dict 層工作（dict 格式對齊 core.take_expr.take_from_dict），
不新增節點型別、不碰 emission。非法組合（§3.4 輸出缺軸不得用 gv_col、
§3.5 跨步 All-row）一律不列入 take_forms，等同 UI 隱藏。

genvar 名稱約定需與 codegen.verilog_generator 的 GV_ROW/GV_COL 一致。
"""
from dataclasses import dataclass, field

GV_ROW = "gv_row"
GV_COL = "gv_col"

# ---- 形狀 id ----
REL_ROW = "rel_row"                    # 1 維：相對偏移 gv_row±n
ABS_ROW = "abs_row"                    # 1 維：指定絕對 k
ALL_ROW_AND = "all_row_and"            # 1 維：&oneDim
ALL_ROW_OR = "all_row_or"              # 1 維：|oneDim
ROWOFF_SPEC_COL = "rowoff_spec_col"    # 2 維：row 偏移 + Specific col m
ROWOFF_ALLCOL_OR = "rowoff_allcol_or"  # 2 維：row 偏移 + All col OR
ROWOFF_ALLCOL_AND = "rowoff_allcol_and"  # 2 維：row 偏移 + All col AND
ROWOFF_COLOFF = "rowoff_coloff"        # 2 維(輸出2維)：row 偏移 + col 偏移 gv_col±m


@dataclass(frozen=True)
class TakeForm:
    """一個取法形狀：id、顯示標籤、需要哪些數字欄（(欄位名, 標籤) 清單）。"""
    id: str
    label: str
    needs: tuple = field(default_factory=tuple)


_FORMS = {
    REL_ROW: TakeForm(REL_ROW, "相對偏移", (("n", "偏移值"),)),
    ABS_ROW: TakeForm(ABS_ROW, "指定(絕對)", (("n", "索引"),)),
    # 1D All 的 n 是 row 下界：|oneDim[NUM_ROW-1 : n]，n=0 即整條 bus
    ALL_ROW_AND: TakeForm(ALL_ROW_AND, "全部AND", (("n", "下界"),)),
    ALL_ROW_OR: TakeForm(ALL_ROW_OR, "全部OR", (("n", "下界"),)),
    ROWOFF_SPEC_COL: TakeForm(ROWOFF_SPEC_COL, "row偏移+指定col",
                              (("n", "row偏移值"), ("m", "欄索引"))),
    # All col 的 m 是 col 下界：|bus[base*C + C-1 : base*C + m]，m=0 即整列連續窗（複用 m slot）
    ROWOFF_ALLCOL_OR: TakeForm(ROWOFF_ALLCOL_OR, "row偏移+全col OR", (("n", "row偏移值"), ("m", "col下界"))),
    ROWOFF_ALLCOL_AND: TakeForm(ROWOFF_ALLCOL_AND, "row偏移+全col AND", (("n", "row偏移值"), ("m", "col下界"))),
    ROWOFF_COLOFF: TakeForm(ROWOFF_COLOFF, "row偏移+col偏移",
                            (("n", "row偏移值"), ("m", "欄偏移"))),
}


def take_forms(out_ndim: int, dep_ndim: int) -> list[TakeForm]:
    """回合法取法形狀清單（§3.4/§3.5 已收斂）。dep 0 維回空（直接引用）。"""
    if dep_ndim <= 0:
        return []
    if dep_ndim == 1:
        return [_FORMS[i] for i in (REL_ROW, ABS_ROW, ALL_ROW_AND, ALL_ROW_OR)]
    # dep 2 維
    ids = [ROWOFF_SPEC_COL, ROWOFF_ALLCOL_OR, ROWOFF_ALLCOL_AND]
    if out_ndim == 2:  # 輸出有 gv_col 才可 col 偏移（§3.4）
        ids.append(ROWOFF_COLOFF)
    return [_FORMS[i] for i in ids]


def default_form(out_ndim: int, dep_ndim: int) -> tuple[str | None, int, int]:
    """預設形狀 (form_id, n, m)。dep 0 維回 (None, 0, 0)。"""
    if dep_ndim <= 0:
        return (None, 0, 0)
    if dep_ndim == 1:
        return (REL_ROW, 0, 0)            # oneDim[gv_row]
    return (ROWOFF_SPEC_COL, 0, 0)        # twoDim[gv_row*C + 0]


def _row_expr(n: int) -> str:
    if n == 0:
        return GV_ROW
    return f"{GV_ROW}+{n}" if n > 0 else f"{GV_ROW}{n}"


def _col_expr(m: int) -> str:
    if m == 0:
        return GV_COL
    return f"{GV_COL}+{m}" if m > 0 else f"{GV_COL}{m}"


def form_to_take(form_id: str | None, n: int = 0, m: int = 0) -> dict | None:
    """形狀 + 數字 → take dict（對齊 take_expr.take_from_dict）。None/直接引用回 None。"""
    if form_id is None:
        return None
    if form_id == REL_ROW:
        return {"row": {"kind": "specific", "index": _row_expr(n)}}
    if form_id == ABS_ROW:
        return {"row": {"kind": "specific", "index": str(n)}}
    if form_id in (ALL_ROW_AND, ALL_ROW_OR):
        row = {"kind": "all", "op": "and" if form_id == ALL_ROW_AND else "or"}
        if n:
            row["lo"] = n  # 只在非零時寫入，舊格式（無 lo）與 n=0 的輸出不變
        return {"row": row}
    if form_id == ROWOFF_SPEC_COL:
        return {"row": {"kind": "specific", "index": _row_expr(n)},
                "col": {"kind": "specific", "index": str(m)}}
    if form_id in (ROWOFF_ALLCOL_OR, ROWOFF_ALLCOL_AND):
        col = {"kind": "all", "op": "or" if form_id == ROWOFF_ALLCOL_OR else "and"}
        if m:
            col["lo"] = m  # col 下界，只在非零時寫入（m=0 的輸出與舊格式不變）
        return {"row": {"kind": "specific", "index": _row_expr(n)}, "col": col}
    if form_id == ROWOFF_COLOFF:
        return {"row": {"kind": "specific", "index": _row_expr(n)},
                "col": {"kind": "specific", "index": _col_expr(m)}}
    raise ValueError(f"未知的 take 形狀: {form_id!r}")


def _parse_offset(expr: str, gv: str) -> int:
    """'gv_row' → 0；'gv_row-1' → -1；'gv_row+2' → 2。"""
    if expr == gv:
        return 0
    return int(expr[len(gv):])


def take_to_form(take: dict | None) -> tuple[str | None, int, int]:
    """take dict → (form_id, n, m)，供下拉回填。None/空 → (None, 0, 0)。"""
    if not take:
        return (None, 0, 0)
    row = take.get("row") or {}
    col = take.get("col")
    rkind = row.get("kind", "same")
    # row 偏移值 n（same 視為 0；specific 相對解析；absolute 由下方另記）
    if col is None:
        # 1 維 dep
        if rkind == "all":
            lo = int(row.get("lo", 0))
            return (ALL_ROW_AND if row.get("op") == "and" else ALL_ROW_OR, lo, 0)
        idx = str(row.get("index", GV_ROW))
        if rkind == "same" or idx.startswith(GV_ROW):
            return (REL_ROW, _parse_offset(idx or GV_ROW, GV_ROW), 0)
        return (ABS_ROW, int(idx), 0)
    # 2 維 dep：row 恆相對偏移
    ridx = str(row.get("index", GV_ROW)) if rkind != "same" else GV_ROW
    n = _parse_offset(ridx, GV_ROW) if ridx.startswith(GV_ROW) else 0
    ckind = col.get("kind", "same")
    if ckind == "all":
        lo = int(col.get("lo", 0))  # col 下界回填 m slot
        return (ROWOFF_ALLCOL_AND if col.get("op") == "and" else ROWOFF_ALLCOL_OR, n, lo)
    cidx = str(col.get("index", GV_COL)) if ckind != "same" else GV_COL
    if ckind == "same" or cidx.startswith(GV_COL):
        return (ROWOFF_COLOFF, n, _parse_offset(cidx, GV_COL))
    return (ROWOFF_SPEC_COL, n, int(cidx))
