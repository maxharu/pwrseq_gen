"""條件編輯器的純資料模型（Hi / Lo / Force 共用）。

GUI 的 `CondSectionFrame` 原本沒有模型：每一項依賴的 `inv` / `use` 只存在 Tk 變數裡、
以 `(gi, ii)` 為 key，widget 本身就是模型。於是每次新增／刪除／拖放重排都得把九個平行
集合（groups、inv_vars、use_vars、group_inv_vars、group_intra_op_vars、rows、
group_frames…）一起重新索引，約 210 行純索引算術，而且因為與 widget 銷毀綁在一起而
完全無法測試。

這裡把 groups 與其平行的 inv / use / group 層設定收成一份純資料，結構操作就只是單純的
list 操作，widget 只負責依模型重繪。

形狀不變量（由 `normalize()` 維持）：
  - `groups` 至少有一個 group（可以是空的）
  - `inv` / `use` 與 `groups` **同形狀**（逐 group 等長）
  - `group_inv` / `group_intra_op` 與 `groups` **等長**
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.config_models import PowerRail
from core.constants import DEP_HIGH, DEP_LOW
from core.group_logic import normalize_intra_op


def _fit(seq, n: int, filler):
    """補到 n 長或截斷到 n 長。"""
    out = list(seq)
    if len(out) < n:
        out += [filler] * (n - len(out))
    return out[:n]


def _move_order(n: int, from_idx: int, to_idx: int) -> list[int] | None:
    """把 from_idx 移到 to_idx 之後的索引排列；索引越界或根本沒動則回 None。"""
    if from_idx == to_idx:
        return None
    if not (0 <= from_idx < n) or not (0 <= to_idx < n):
        return None
    order = list(range(n))
    order.insert(to_idx, order.pop(from_idx))
    return order


def _initial(groups_val, flat_val: dict, gi: int, ii: int, name: str, default):
    """沿用 widget 原本的取值順序：先查 groups 版，缺了才退回以名稱為 key 的扁平版。"""
    if groups_val:
        try:
            return groups_val[gi][ii]
        except IndexError:
            pass
    return flat_val.get(name, default)


@dataclass
class CondEditModel:
    """一個 kind（hi / lo / force）的條件編輯狀態。"""

    groups: list[list[str]] = field(default_factory=lambda: [[]])
    inv: list[list[bool]] = field(default_factory=list)
    use: list[list[str]] = field(default_factory=list)
    group_inv: list[bool] = field(default_factory=list)
    group_intra_op: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.normalize()

    # ---- 不變量 ----
    def normalize(self) -> None:
        """補齊／截斷所有平行結構，使其符合形狀不變量。"""
        self.groups = [list(g) for g in self.groups] or [[]]
        n = len(self.groups)
        self.group_inv = [bool(x) for x in _fit(self.group_inv, n, False)]
        self.group_intra_op = [
            normalize_intra_op(x) for x in _fit(self.group_intra_op, n, "and")
        ]
        self.inv = [
            [bool(x) for x in _fit(self.inv[gi] if gi < len(self.inv) else [], len(g), False)]
            for gi, g in enumerate(self.groups)
        ]
        self.use = [
            [str(x) for x in _fit(self.use[gi] if gi < len(self.use) else [], len(g), "self")]
            for gi, g in enumerate(self.groups)
        ]

    # ---- 結構操作 ----
    def add_group(self) -> None:
        self.groups.append([])
        self.inv.append([])
        self.use.append([])
        self.group_inv.append(False)
        self.group_intra_op.append("and")

    def remove_group(self, gi: int) -> bool:
        """刪除整個 group；刪到一個不剩時重設為單一空 group。"""
        if not (0 <= gi < len(self.groups)):
            return False
        for seq in (self.groups, self.inv, self.use, self.group_inv, self.group_intra_op):
            del seq[gi]
        if not self.groups:
            self.groups, self.inv, self.use = [[]], [[]], [[]]
            self.group_inv, self.group_intra_op = [False], ["and"]
        return True

    def add_dep(self, gi: int, name: str, *, inv: bool = False, use: str = "self") -> bool:
        if not (0 <= gi < len(self.groups)):
            return False
        self.groups[gi].append(name)
        self.inv[gi].append(bool(inv) and not is_const_dep(name))
        self.use[gi].append(str(use))
        return True

    def remove_dep(self, gi: int, ii: int) -> bool:
        if not (0 <= gi < len(self.groups)) or not (0 <= ii < len(self.groups[gi])):
            return False
        for seq in (self.groups[gi], self.inv[gi], self.use[gi]):
            del seq[ii]
        return True

    def reorder_dep(self, gi: int, from_idx: int, to_idx: int) -> bool:
        if not (0 <= gi < len(self.groups)):
            return False
        order = _move_order(len(self.groups[gi]), from_idx, to_idx)
        if order is None:
            return False
        for seq in (self.groups[gi], self.inv[gi], self.use[gi]):
            seq[:] = [seq[o] for o in order]
        return True

    def reorder_groups(self, from_idx: int, to_idx: int) -> bool:
        order = _move_order(len(self.groups), from_idx, to_idx)
        if order is None:
            return False
        for seq in (self.groups, self.inv, self.use, self.group_inv, self.group_intra_op):
            seq[:] = [seq[o] for o in order]
        return True

    # ---- 讀出（契約與 CondSectionFrame 的 getter 相同：跳過空 group）----
    def _filled(self) -> list[int]:
        return [gi for gi, g in enumerate(self.groups) if g]

    def to_groups(self) -> list[list[str]]:
        return [list(self.groups[gi]) for gi in self._filled()]

    def to_inv_groups(self) -> list[list[bool]]:
        return [list(self.inv[gi]) for gi in self._filled()]

    def to_use_groups(self) -> list[list[str]]:
        return [list(self.use[gi]) for gi in self._filled()]

    def to_group_inv(self) -> list[bool]:
        return [self.group_inv[gi] for gi in self._filled()]

    def to_group_intra_op(self) -> list[str]:
        return [self.group_intra_op[gi] for gi in self._filled()]

    def to_inv_flat(self) -> dict[str, bool]:
        """以名稱為 key，同名跨 group 時後者覆蓋前者（沿用原行為）。"""
        return {
            name: self.inv[gi][ii]
            for gi, g in enumerate(self.groups)
            for ii, name in enumerate(g)
        }

    def to_use_flat(self) -> dict[str, str]:
        return {
            name: self.use[gi][ii]
            for gi, g in enumerate(self.groups)
            for ii, name in enumerate(g)
        }

    def to_flat_deps(self) -> list[str]:
        return [d for g in self.to_groups() for d in g]

    # ---- 載入 ----
    @classmethod
    def from_initial(
        cls,
        groups,
        inv_groups=None,
        use_groups=None,
        inv_flat=None,
        use_flat=None,
        group_inv=None,
        group_intra_op=None,
    ) -> CondEditModel:
        """以 groups 版為主、以名稱為 key 的扁平版為備援，組出模型。

        `High` / `Low` 這類常數依賴不帶 inv（原 widget 不畫 Inv 核取方塊）。
        """
        groups = [list(g) for g in (groups or [[]])]
        inv_groups = inv_groups or []
        use_groups = use_groups or []
        inv_flat = inv_flat or {}
        use_flat = use_flat or {}
        return cls(
            groups=groups,
            inv=[
                [
                    False
                    if is_const_dep(name)
                    else bool(_initial(inv_groups, inv_flat, gi, ii, name, False))
                    for ii, name in enumerate(g)
                ]
                for gi, g in enumerate(groups)
            ],
            use=[
                [
                    str(_initial(use_groups, use_flat, gi, ii, name, "self"))
                    for ii, name in enumerate(g)
                ]
                for gi, g in enumerate(groups)
            ],
            group_inv=list(group_inv or []),
            group_intra_op=list(group_intra_op or []),
        )

    @classmethod
    def from_rail(cls, rail: PowerRail, kind: str) -> CondEditModel:
        """從 PowerRail 的某個 kind 讀出編輯狀態。"""
        return cls.from_initial(
            groups=getattr(rail, f"get_{kind}_groups")(),
            inv_groups=getattr(rail, f"depends_on_{kind}_inv_groups", None),
            use_groups=getattr(rail, f"depends_on_{kind}_use_groups", None),
            inv_flat=getattr(rail, f"depends_on_{kind}_inv", None),
            use_flat=getattr(rail, f"depends_on_{kind}_use", None),
            group_inv=getattr(rail, f"depends_on_{kind}_group_inv", None),
            group_intra_op=getattr(rail, f"depends_on_{kind}_intra_op", None),
        )


def is_const_dep(name: str) -> bool:
    """`__HIGH__` / `__LOW__` 是常數節點，沒有準位可反相。"""
    return name in (DEP_HIGH, DEP_LOW)
