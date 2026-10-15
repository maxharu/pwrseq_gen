"""條件語意的唯一來源：把 rail 的 depends_on_* 正規化成 CondTree。

Verilog / C / Draw.io / 模擬器 / 時序圖各自重刻過同一套依賴語意，沒有任何機制強迫
它們一致——Draw.io 曾經對 input 也去引用不存在的 `xxx_lo` 條件訊號，就是這樣來的。
`resolve_condition` 把 groups / inv / use / group_inv / intra_op 一次解析完，
下游只負責渲染。

樹的形狀刻意對齊 F-DEP-08 的兩層結構（group 內 intra_op、group 間 OR），
而不是任意的布林樹，所以渲染端不會把兩層搞混。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.constants import DEP_HIGH, DEP_LOW

CONDITION_KINDS = ("hi", "lo", "force")

# 沒有任何 group 時的預設條件：Hi 恆真、Lo/Force 恆假（F-DEP-06）
_EMPTY_DEFAULT = {"hi": 1, "lo": 0, "force": 0}


class CondVisitor(ABC):
    """渲染 CondTree。

    刻意做成 ABC：日後新增節點型別時這裡會多一個 abstract method，沒跟上的下游在
    *建構當下* 就 TypeError，而不是默默少處理一種語意。
    """

    @abstractmethod
    def const(self, value: int) -> Any:
        """常數 0 / 1（__LOW__ / __HIGH__）。"""

    @abstractmethod
    def level(self, name: str) -> Any:
        """該節點的實際準位：input 的腳位，或 output 讀回的輸出。"""

    @abstractmethod
    def cond(self, name: str, kind: str) -> Any:
        """某 output 的 Hi/Lo/Force 條件訊號。"""

    @abstractmethod
    def invert(self, operand: Any) -> Any:
        """單項 inv 或整組 group_inv。"""

    @abstractmethod
    def group(self, op: str, items: list[Any]) -> Any:
        """單一 group 內以 and / or / xor 結合。"""

    @abstractmethod
    def any_group(self, groups: list[Any]) -> Any:
        """group 之間固定 OR。"""


class CondTree(ABC):
    @abstractmethod
    def accept(self, visitor: CondVisitor) -> Any:
        """後序遍歷：子節點先渲染，visitor 只拿到已渲染的結果。"""


@dataclass(frozen=True)
class Const(CondTree):
    value: int

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.const(self.value)


@dataclass(frozen=True)
class Level(CondTree):
    name: str

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.level(self.name)


@dataclass(frozen=True)
class Cond(CondTree):
    name: str
    kind: str

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.cond(self.name, self.kind)


@dataclass(frozen=True)
class Not(CondTree):
    operand: CondTree

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.invert(self.operand.accept(visitor))


@dataclass(frozen=True)
class Group(CondTree):
    op: str
    items: tuple[CondTree, ...]

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.group(self.op, [i.accept(visitor) for i in self.items])


@dataclass(frozen=True)
class AnyGroup(CondTree):
    groups: tuple[CondTree, ...]

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.any_group([g.accept(visitor) for g in self.groups])


def resolve_condition(rail, kind: str, name_to_rail: dict) -> CondTree:
    """rail 的 kind（hi / lo / force）條件樹。"""
    if kind not in _EMPTY_DEFAULT:
        raise ValueError(f"unknown condition kind: {kind}")

    groups = getattr(rail, f"get_{kind}_groups")()
    if not groups:
        return Const(_EMPTY_DEFAULT[kind])

    get_inv = getattr(rail, f"get_{kind}_inv")
    get_use = getattr(rail, f"get_{kind}_use")
    get_group_inv = getattr(rail, f"get_{kind}_group_inv")
    get_intra_op = getattr(rail, f"get_{kind}_intra_op")

    nodes: list[CondTree] = []
    for gi, group in enumerate(groups):
        items = tuple(
            _item(dep, get_inv(gi, ii, dep), get_use(gi, ii, dep), name_to_rail)
            for ii, dep in enumerate(group)
        )
        node: CondTree = Group(get_intra_op(gi), items)
        if get_group_inv(gi):
            node = Not(node)
        nodes.append(node)
    return AnyGroup(tuple(nodes))


def _item(dep: str, inv: bool, use: str, name_to_rail: dict) -> CondTree:
    leaf = resolve_dep(dep, use, name_to_rail)
    return Not(leaf) if inv else leaf


def resolve_dep(dep: str, use: str, name_to_rail: dict) -> CondTree:
    """單一依賴項的葉節點（不含 inv）。"""
    if dep == DEP_HIGH:
        return Const(1)
    if dep == DEP_LOW:
        return Const(0)
    dep_rail = name_to_rail.get(dep)
    # use=hi/lo/force 只對有 PSEQCELL 的 output 有意義；其餘一律退化為讀準位
    if dep_rail is not None and dep_rail.seq_type == "output" and use in CONDITION_KINDS:
        return Cond(dep, use)
    return Level(dep)
