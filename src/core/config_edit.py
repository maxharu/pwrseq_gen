"""節點清單的編輯操作（新增命名、批次刪除、重排後的索引換算）。

從 `gui/app.py` 抽出來。這些都是純索引與命名邏輯，原本綁在 Tk 事件處理裡一行都測不到，
但算錯的後果是使用者的節點資料被改到錯的那一筆。

只收「算錯會出事」的部分；單純的 `append` / 指派留在呼叫端，包起來只是多一層轉呼叫。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

from core.param_expr import eval_width

T = TypeVar("T")


def next_rail_name(existing: Sequence[str], prefix: str = "SIG") -> str:
    """產生不與 `existing` 衝突的新節點名，如 `SIG_4`。

    從 `len(existing) + 1` 起算而非從 1 起算：一般情況下第一次就命中，不必從頭試。
    """
    taken = set(existing)
    n = len(existing) + 1
    while f"{prefix}_{n}" in taken:
        n += 1
    return f"{prefix}_{n}"


def delete_indices(items: list[T], indices: Iterable[int]) -> list[int]:
    """就地刪除多個索引，回傳實際刪掉的索引（由大到小）。

    **必須由大到小刪**，否則刪掉前面的項目會讓後面的索引整個位移。回傳值讓呼叫端
    能用同樣的順序處理與它平行的清單（例如對應的 widget）。
    """
    removed = []
    for i in sorted({i for i in indices if 0 <= i < len(items)}, reverse=True):
        del items[i]
        removed.append(i)
    return removed


def move_item(items: list[T], from_idx: int, to_idx: int) -> bool:
    """把 from_idx 的項目移到 to_idx；索引越界或沒動則回 False。"""
    if from_idx == to_idx:
        return False
    if not (0 <= from_idx < len(items)) or not (0 <= to_idx < len(items)):
        return False
    items.insert(to_idx, items.pop(from_idx))
    return True


def group_rails_into_nodes(rails: Sequence) -> list[list]:
    """把扁平 rails 依連續 group_base 收成「節點」清單：scalar 自成單元素 list，
    vector 的連續 bit（同 group_base）收成一個 list。

    序列化／Excel 收合與 GUI 的「一列一 Node」都需要這個 rail→node 的切分；集中一份，
    避免各處各自 while 迴圈切分而語意漂移。vector bit 在 rails 必為連續（見 group_span）。
    """
    nodes: list[list] = []
    i = 0
    n = len(rails)
    while i < n:
        base = getattr(rails[i], "group_base", None)
        if base is None:
            nodes.append([rails[i]])
            i += 1
            continue
        group = [rails[i]]
        i += 1
        while i < n and getattr(rails[i], "group_base", None) == base:
            group.append(rails[i])
            i += 1
        nodes.append(group)
    return nodes


def node_spans(rails: Sequence) -> list[tuple[int, int]]:
    """每個節點在扁平 rails 的 (start, count)；順序與 group_rails_into_nodes 一致。"""
    spans: list[tuple[int, int]] = []
    start = 0
    for node in group_rails_into_nodes(rails):
        spans.append((start, len(node)))
        start += len(node)
    return spans


def rail_index_to_node_index(rails: Sequence, rail_idx: int) -> int | None:
    """扁平 rail 索引 → 所屬節點索引；越界回 None。"""
    for ni, (start, count) in enumerate(node_spans(rails)):
        if start <= rail_idx < start + count:
            return ni
    return None


def node_index_to_rail_span(rails: Sequence, node_idx: int) -> tuple[int, int] | None:
    """節點索引 → 扁平 rail 的 (start, count)；越界回 None。"""
    spans = node_spans(rails)
    if 0 <= node_idx < len(spans):
        return spans[node_idx]
    return None


def move_node(rails: list, from_node: int, to_node: int) -> bool:
    """把第 from_node 個節點整塊移到第 to_node 個節點位置（node 座標，pop+insert 語意）。

    就地改 rails；vector 的連續 bit 當成一塊一起走。越界或沒動回 False。保留 rail 物件 identity。
    """
    nodes = group_rails_into_nodes(rails)
    n = len(nodes)
    if from_node == to_node:
        return False
    if not (0 <= from_node < n) or not (0 <= to_node < n):
        return False
    block = nodes.pop(from_node)
    nodes.insert(to_node, block)
    rails[:] = [r for node in nodes for r in node]
    return True


def delete_nodes(rails: list, node_indices: Iterable[int]) -> list[int]:
    """刪除指定節點（node 座標），回傳實際刪掉的 node 索引（由大到小）。就地改 rails。

    vector 整組一起刪；引用被刪 bit 的條件保持原樣（dangling，由 validator 反映），
    與單一節點刪除的既有行為一致。
    """
    nodes = group_rails_into_nodes(rails)
    removed: list[int] = []
    for ni in sorted({i for i in node_indices if 0 <= i < len(nodes)}, reverse=True):
        del nodes[ni]
        removed.append(ni)
    rails[:] = [r for node in nodes for r in node]
    return removed


def set_group_metadata(
    bits: Sequence, base: str | None, width_expr: str, dim_params: Sequence | None = None,
) -> None:
    """把一組 bit rails 蓋上群組 metadata；base=None 表 scalar（清掉群組、width_expr=1、dim_params 清空）。

    GUI 卡片收集回 config 時走這裡，群組 metadata 的規則（bit_index 連號、共用 width_expr、
    共用 dim_params）只有一份，不會各處各自蓋而漂移。dim_params 是所選 0~2 維名（row、col）。
    """
    if base is None:
        for r in bits:
            r.group_base = None
            r.bit_index = 0
            r.width_expr = "1"
            r.dim_params = []
        return
    dims = list(dim_params or [])
    for i, r in enumerate(bits):
        r.group_base = base
        r.bit_index = i
        r.width_expr = width_expr
        r.dim_params = list(dims)


def vector_shape_label(node: Sequence, parameters=None) -> str:
    """vector 群組的形狀標記：2 維→`"{row}×{col}"`（以 parameter 值代入），其餘→`"×{N}"`。

    row＝eval_width(dim_params[0])、col＝eval_width(dim_params[1])；無法求值或乘積 ≠ N 時退回 `"×N"`。"""
    n = len(node)
    head = node[0] if n else None
    dims = list(getattr(head, "dim_params", None) or []) if head is not None else []
    if len(dims) == 2:
        try:
            row = eval_width(dims[0], parameters)
            col = eval_width(dims[1], parameters)
            if row > 0 and col > 0 and row * col == n:
                return f"{row}\u00d7{col}"
        except (ValueError, TypeError):
            pass
    return f"\u00d7{n}"


def width_expr_from_dims(dim_params: Sequence | None) -> str:
    """由所選維度名推 vector 寬度公式：0 維→"1"（純量）、1 維→P1、2 維→"P1*P2"。

    維度名即 parameter 名（最大值），乘積交由 eval_width 以具體 parameter 值求 N。"""
    dims = [str(d) for d in (dim_params or []) if d][:2]
    if not dims:
        return "1"
    return "*".join(dims)


def flatten_node_rails(nodes: Iterable[Sequence]) -> list:
    """node 清單（每個是 bit rails 的 list）→ 扁平 rails；GUI 卡片收集回 config 用。"""
    return [r for node in nodes for r in node]


def resize_list(items: Sequence[T], n: int, factory) -> list[T]:
    """把 items 調整成長度 n：多截少補（factory(i) 造新項），保留既有項目。

    vector 卡片在 width/Vector 勾選改變時用這個增減 per-bit 狀態（條件或 wave），
    已填好的 bit 不被洗掉。
    """
    out = list(items[:n])
    for i in range(len(out), n):
        out.append(factory(i))
    return out


def group_span(rails: Sequence, base: str) -> tuple[int, int] | None:
    """回傳 `group_base == base` 的連續區段 (start, count)；找不到回 None。

    vector 的 bit 在 config.rails 必為連續（from_dict 展開與 elaborate 都連續 append），
    所以整組可用單一區段表示，群組的刪除／搬移就能復用既有的索引算術，而不必另立資料結構。
    """
    indices = [i for i, r in enumerate(rails) if getattr(r, "group_base", None) == base]
    if not indices:
        return None
    return indices[0], len(indices)


def move_group(items: list[T], start: int, count: int, to_idx: int) -> bool:
    """把 items[start:start+count] 整塊移到以 to_idx（移除該塊後的座標）起算的位置。

    這是 `move_item` 的群組版：越界夾住，位置沒變則回 False。就地改 items。
    """
    if count <= 0 or start < 0 or start + count > len(items):
        return False
    block = items[start:start + count]
    rest = items[:start] + items[start + count:]
    to_idx = max(0, min(to_idx, len(rest)))
    if to_idx == start:
        return False
    items[:] = rest[:to_idx] + block + rest[to_idx:]
    return True


def remap_index_after_move(idx: int | None, from_idx: int, to_idx: int) -> int | None:
    """某項目被移動後，原本指向 idx 的游標該指向哪裡。

    被移動的那一項跟著走；夾在中間的項目往反方向位移一格。
    """
    if idx is None:
        return None
    if idx == from_idx:
        return to_idx
    if from_idx < to_idx:
        if from_idx < idx <= to_idx:
            return idx - 1
    elif to_idx < from_idx:
        if to_idx <= idx < from_idx:
            return idx + 1
    return idx
