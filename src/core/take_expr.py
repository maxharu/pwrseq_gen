"""take 取法運算式產生器（對照 PseqGeneratorNewFunction.txt 3.1~3.6）。

純字串建構：給定被引用訊號的維度與 row/col take，回傳引用它的 RHS Verilog 片段。
不含條件樹、不碰 emission／後端，供 Verilog（階段D）與之後 slice（階段E）共用。

2 維採列優先扁平索引 bus[row*M + col]（M=col 維度大小符號）。「All row 搭配逐 col」
屬跨步歸約（3.5），不能用單一 part-select，此步明確不支援並報錯。
"""
from dataclasses import dataclass

SAME = "same"
SPECIFIC = "specific"
ALL = "all"

_KINDS = frozenset({SAME, SPECIFIC, ALL})
_REDUCE = {"and": "&", "or": "|"}


@dataclass(frozen=True)
class Take:
    """單一軸的取法：Same / Specific(index 算式) / All(op=and|or, lo 下界)。

    lo 只給 ALL 用：All 歸約的範圍為 [NUM_ROW-1 : lo]，NUM_ROW > lo >= 0。
    lo=0 即整條 bus（與不帶下界的舊輸出相同）。
    """
    kind: str
    index: str = ""   # SPECIFIC 用：索引算式，如 "0"、"gv_row-1"
    op: str = "and"   # ALL 用：and | or
    lo: int = 0       # ALL 用：row 下界（整數常數）


def take_from_dict(d: dict | None) -> Take | None:
    """把序列化的 take dict（{kind,index,op,lo}）還原成 Take；None/空 → None。"""
    if not d:
        return None
    return Take(kind=d.get("kind", SAME), index=d.get("index", ""), op=d.get("op", "and"),
                lo=int(d.get("lo", 0)))


def _check_kind(t: Take) -> None:
    if t.kind not in _KINDS:
        raise ValueError(f"未知的 take 種類: {t.kind!r}")
    if t.kind == ALL and t.op not in _REDUCE:
        raise ValueError(f"All take 的 op 需為 and|or: {t.op!r}")
    if t.lo < 0:
        raise ValueError(f"row 下界 lo 需 >= 0: {t.lo}")
    if t.lo and t.kind != ALL:
        raise ValueError("只有 All 取法可帶下界 lo")


def _maybe_paren(term: str) -> str:
    """索引算式含 +/- 時加括號（進 *M 或與其他項相加才不會算錯優先權）。"""
    return f"({term})" if ("+" in term or "-" in term) else term


def _row_base(row: Take, gv_row: str) -> str:
    return gv_row if row.kind == SAME else _maybe_paren(row.index)


def _one_dim(bus: str, row: Take, gv_row: str, row_size: str) -> str:
    if row.kind == SAME:
        return f"{bus}[{gv_row}]"
    if row.kind == SPECIFIC:
        return f"{bus}[{row.index}]"
    if row.lo == 0:
        return f"{_REDUCE[row.op]}{bus}"  # ALL 整條
    if not row_size:
        raise ValueError("帶下界的 All 歸約需提供 row_size（row 維度大小符號）")
    return f"{_REDUCE[row.op]}{bus}[{row_size}-1 : {row.lo}]"  # ALL 範圍


def _two_dim(bus: str, row: Take, col: Take, col_size: str, gv_row: str, gv_col: str) -> str:
    if not col_size:
        raise ValueError("2 維引用需提供 col_size（col 維度大小符號）")
    if row.lo:
        # 範圍下界只作用於 1D；2D 的 row 範圍是跨步歸約（3.5），不支援
        raise ValueError("2 維引用的 row 不支援範圍下界 lo")

    row_all = row.kind == ALL
    col_all = col.kind == ALL

    if row_all and col_all:
        if row.op != col.op:
            raise ValueError("All row 與 All col 的歸約 op 需一致，否則無法以整條歸約表達")
        return f"{_REDUCE[row.op]}{bus}"  # 整條連續

    if row_all and not col_all:
        # 跨步 C 的 row 歸約無法用單一 part-select（3.5），此步不支援。
        raise ValueError("All row 搭配逐 col 為跨步歸約（strided），此步尚不支援")

    base = _row_base(row, gv_row)
    if col_all:  # row=Same/Specific + col=All → 連續窗 part-select
        if col.lo == 0:
            return f"{_REDUCE[col.op]}{bus}[{base}*{col_size} +: {col_size}]"
        # col 下界：比照 1D 的 ranged select，上界固定 NUM_COL-1（§6 延伸）
        off = f"{base}*{col_size}"
        return f"{_REDUCE[col.op]}{bus}[{off} + {col_size}-1 : {off} + {col.lo}]"

    col_term = gv_col if col.kind == SAME else _maybe_paren(col.index)
    return f"{bus}[{base}*{col_size} + {col_term}]"


def take_expr(
    bus: str,
    ref_ndim: int,
    row: Take | None = None,
    col: Take | None = None,
    *,
    col_size: str = "",
    row_size: str = "",
    gv_row: str = "gv_row",
    gv_col: str = "gv_col",
) -> str:
    """回傳引用 `bus`（被引用訊號）的 RHS 片段。

    ref_ndim：被引用訊號維度（0/1/2）。
    row/col：各軸 take；0 維皆不給、1 維只給 row、2 維兩者都給。
    col_size：2 維 col 維度大小符號（如 "NUM_CPU_MEM"）。
    row_size：1 維 row 維度大小符號（如 "NUM_CPU"），只在 All 帶下界 lo 時需要。
    """
    if ref_ndim == 0:
        if row is not None or col is not None:
            raise ValueError("0 維訊號無 take 選項")
        return bus

    if ref_ndim == 1:
        if row is None:
            raise ValueError("1 維引用需提供 row take")
        if col is not None:
            raise ValueError("1 維訊號只有 row 軸，不可給 col take")
        _check_kind(row)
        return _one_dim(bus, row, gv_row, row_size)

    if ref_ndim == 2:
        if row is None or col is None:
            raise ValueError("2 維引用需同時提供 row 與 col take")
        _check_kind(row)
        _check_kind(col)
        return _two_dim(bus, row, col, col_size, gv_row, gv_col)

    raise ValueError(f"ref_ndim 僅支援 0/1/2: {ref_ndim}")
