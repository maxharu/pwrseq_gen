"""條件語意的唯一來源：把 rail 的 depends_on_* 正規化成 CondTree。

Verilog / C / Draw.io / 模擬器 / 時序圖各自重刻過同一套依賴語意，沒有任何機制強迫
它們一致——Draw.io 曾經對 input 也去引用不存在的 `xxx_lo` 條件訊號，就是這樣來的。
`resolve_condition` 把 groups / inv / use / group_inv / intra_op 一次解析完，
下游只負責渲染。

樹的形狀刻意對齊 F-DEP-08 的兩層結構（group 內 intra_op、group 間 OR），
而不是任意的布林樹，所以渲染端不會把兩層搞混。同理，整組反相是 `Group.inv` 旗標
而不是外包一層 `Not`——Verilog 把單項 inv 寫成 `(~x)`、整組寫成 `!(a & b)`，
共用同一個 hook 只會逼渲染端去猜自己正在處理哪一層。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.constants import DEP_HIGH, DEP_LOW
from core.take_expr import Take, take_from_dict

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
        """單項 inv。整組反相走 `group(..., inv=True)`，兩者在 Verilog / C 的
        括號寫法不同，刻意不共用同一個 hook。"""

    @abstractmethod
    def group(self, op: str, items: list[Any], inv: bool) -> Any:
        """單一 group 內以 and / or / xor 結合，inv 為整組反相（group_inv）。"""

    @abstractmethod
    def any_group(self, groups: list[Any]) -> Any:
        """group 之間固定 OR。"""

    @abstractmethod
    def take_ref(self, node: "TakeRef") -> Any:
        """維度 vector 的 take 引用葉：沿 genvar 以 row/col take 索引被引用 bus
        （階段D）。葉節點，直接拿 node（含 base / use / ref_ndim / row / col / col_size）。"""


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
    inv: bool = False

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.group(self.op, [i.accept(visitor) for i in self.items], self.inv)


@dataclass(frozen=True)
class AnyGroup(CondTree):
    groups: tuple[CondTree, ...]

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.any_group([g.accept(visitor) for g in self.groups])


@dataclass(frozen=True)
class TakeRef(CondTree):
    """維度 vector 的 take 引用（Level/Cond 的維度版）。

    base：被引用 vector 的 base 名；use："level"（準位）或 "hi"/"lo"/"force"（條件線）。
    ref_ndim 與 col_size 由被引用 rail 的 dim_params 推得，幾何不入存。row/col 為 Take。
    葉節點，無子 CondTree，accept 直接把自己交給 visitor。"""
    base: str
    use: str
    ref_ndim: int
    row: Take | None = None
    col: Take | None = None
    col_size: str = ""

    def accept(self, visitor: CondVisitor) -> Any:
        return visitor.take_ref(self)


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
    get_take = getattr(rail, f"get_{kind}_take")

    nodes: list[CondTree] = []
    for gi, group in enumerate(groups):
        items = tuple(
            resolve_item(dep, get_inv(gi, ii, dep), get_use(gi, ii, dep), name_to_rail,
                         get_take(gi, ii))
            for ii, dep in enumerate(group)
        )
        nodes.append(Group(get_intra_op(gi), items, get_group_inv(gi)))
    return AnyGroup(tuple(nodes))


def resolve_item(dep: str, inv: bool, use: str, name_to_rail: dict,
                 take: dict | None = None) -> CondTree:
    """單一依賴項（含 inv）。take 非 None 且被引用 rail 有維度時 → TakeRef。"""
    leaf = resolve_dep(dep, use, name_to_rail, take)
    if not inv:
        return leaf
    # 反相常數在這裡就摺掉：四個下游本來各自做這件事（Verilog `~1'b1` 不會出現），
    # 留在下游就是四份重複。
    if isinstance(leaf, Const):
        return Const(1 - leaf.value)
    return Not(leaf)


def resolve_dep(dep: str, use: str, name_to_rail: dict, take: dict | None = None) -> CondTree:
    """單一依賴項的葉節點（不含 inv）。"""
    if dep == DEP_HIGH:
        return Const(1)
    if dep == DEP_LOW:
        return Const(0)
    dep_rail = name_to_rail.get(dep)
    if take and dep_rail is not None and getattr(dep_rail, "dim_params", None):
        return _take_ref(dep_rail, use, take)
    # use=hi/lo/force 只對有 PSEQCELL 的 output 有意義；其餘一律退化為讀準位
    if dep_rail is not None and dep_rail.seq_type == "output" and use in CONDITION_KINDS:
        return Cond(dep, use)
    return Level(dep)


def _take_ref(dep_rail, use: str, take: dict) -> "TakeRef":
    """由被引用 rail 的 dim_params 推幾何，組成 TakeRef（幾何不入存）。"""
    dims = list(dep_rail.dim_params)
    ndim = len(dims)
    resolved_use = (use if dep_rail.seq_type == "output" and use in CONDITION_KINDS
                    else "level")
    return TakeRef(
        base=dep_rail.group_base,
        use=resolved_use,
        ref_ndim=ndim,
        row=take_from_dict(take.get("row")),
        col=take_from_dict(take.get("col")),
        col_size=dims[1] if ndim == 2 else "",
    )
