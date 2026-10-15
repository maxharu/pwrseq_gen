"""節點清單的編輯操作（新增命名、批次刪除、重排後的索引換算）。

從 `gui/app.py` 抽出來。這些都是純索引與命名邏輯，原本綁在 Tk 事件處理裡一行都測不到，
但算錯的後果是使用者的節點資料被改到錯的那一筆。

只收「算錯會出事」的部分；單純的 `append` / 指派留在呼叫端，包起來只是多一層轉呼叫。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

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
