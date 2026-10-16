"""Draw.io 畫出來的閘電路，真值表必須與 `CondTree` 相同。

`tests/test_condition_consistency.py` 只比對**葉節點**的渲染文字；閘的拓樸——哪種閘、
哪裡有反相泡泡、哪幾項餵進哪個閘——原本沒有任何測試涵蓋。`doc/FUTURE.md` 的三個
Draw.io 缺口能長期存在，就是因為這層是裸的。

守門方式刻意**不是**「比對閘樣式」：那只是把現行行為當成規格封存，缺口當初會一起被封進去。
這支把產出的 XML 反解成電路，在所有輸入組合下求值，再與 `resolve_condition()` 的布林求值
比對——錯誤的畫法不管長什麼樣，真值表都對不上。

反解而非戳內部函式，是因為要驗的就是「實際交付的那份 XML」。
"""
import itertools
import re
import xml.etree.ElementTree as ET

import pytest

from core.cond_ir import CondVisitor, resolve_condition
from core.config_models import PowerRail, PowerSeqConfig
from core.group_logic import eval_intra_op
from drawio import generate_drawio
from drawio.drawio_cell_export import AND_TREE_THRESHOLD
from drawio.drawio_geometry import STROKE_HI, STROKE_LO

DEPS = ["IN_A", "IN_B", "IN_C", "IN_D"]


# --------------------------------------------------------------------------
# 期望值：直接對 CondTree 求值
# --------------------------------------------------------------------------
class _BoolEval(CondVisitor):
    """在給定的輸入指派下求 CondTree 的值。"""

    def __init__(self, assignment: dict[str, int]):
        self.assignment = assignment

    def const(self, value: int) -> int:
        return value

    def level(self, name: str) -> int:
        return self.assignment[name]

    def cond(self, name: str, kind: str) -> int:  # pragma: no cover - 本檔不產生 cond 葉
        raise AssertionError("這支 oracle 的設定只用 input 當依賴")

    def invert(self, operand: int) -> int:
        return 1 - operand

    def group(self, op: str, items: list[int], inv: bool) -> int:
        v = eval_intra_op(op, items)
        return 1 - v if inv else v

    def any_group(self, groups: list[int]) -> int:
        return 1 if any(groups) else 0


def _expected(rail, hl, name_to_rail, assignment: dict[str, int]) -> int:
    return resolve_condition(rail, hl, name_to_rail).accept(_BoolEval(assignment))


# --------------------------------------------------------------------------
# 把產出的 XML 反解成電路
# --------------------------------------------------------------------------
_GATE_RE = re.compile(r"operation=(and|or|xor)")
_TAGS_RE = re.compile(r"<[^>]+>")


class _Circuit:
    """從 mxCell 重建的閘電路：節點 + 誰餵給誰。"""

    def __init__(self, root_id: str, kind: dict, fanin: dict):
        self.root_id = root_id
        self.kind = kind      # id -> ("label", text) | ("gate", op, negating)
        self.fanin = fanin    # id -> [上游 id]

    def eval(self, assignment: dict[str, int]) -> int:
        return self._eval(self.root_id, assignment, set())

    def _eval(self, nid: str, assignment: dict[str, int], seen: set[str]) -> int:
        assert nid not in seen, "畫出來的電路有迴路"
        node = self.kind[nid]
        if node[0] == "label":
            text = node[1]
            bare = text.lstrip("~")
            # 逐個 `~` 數，不然 `~~A` 會被當成只反相一次
            inversions = len(text) - len(bare)
            v = assignment[bare]
            return v if inversions % 2 == 0 else 1 - v
        _, op, negating = node
        vals = [self._eval(s, assignment, seen | {nid}) for s in self.fanin[nid]]
        v = eval_intra_op(op, vals)
        return 1 - v if negating else v

    def labels(self) -> list[str]:
        return [v[1] for v in self.kind.values() if v[0] == "label"]


def _parse_circuit(xml: str, hl: str) -> _Circuit | None:
    """反解單一 output 的 hi/lo 條件電路；完全沒畫閘時回 None。

    收尾那條進 Deb 的邊是唯一帶顏色的（hi 紅 / lo 綠），以它的來源當電路的根。
    """
    root = ET.fromstring(xml)
    stroke = STROKE_HI if hl == "hi" else STROKE_LO

    kind: dict = {}
    for cell in root.iter("mxCell"):
        if cell.get("vertex") != "1":
            continue
        style = cell.get("style") or ""
        cid = cell.get("id")
        if "logic_gates.logic_gate" in style:
            m = _GATE_RE.search(style)
            assert m, f"閘樣式解不出 operation: {style}"
            kind[cid] = ("gate", m.group(1), "negating=1" in style)
        elif style.startswith("text;") and "align=right" in style:
            kind[cid] = ("label", _TAGS_RE.sub("", cell.get("value") or "").strip())

    fanin: dict = {}
    root_id = None
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        src, tgt = cell.get("source"), cell.get("target")
        if f"strokeColor={stroke};" in (cell.get("style") or ""):
            assert root_id is None, f"{hl} 有一條以上的收尾邊"
            root_id = src
        elif src in kind and tgt in kind:
            fanin.setdefault(tgt, []).append(src)

    if root_id is None or root_id not in kind:
        return None
    return _Circuit(root_id, kind, fanin)


# --------------------------------------------------------------------------
# 受測設定
# --------------------------------------------------------------------------
def _config(groups, *, intra_op, group_inv, item_inv, hl="hi") -> PowerSeqConfig:
    used = sorted({d for g in groups for d in g})
    rail = PowerRail("OUT", seq_type="output", cycle_hi=1, cycle_lo=1)
    setattr(rail, f"depends_on_{hl}_groups", [list(g) for g in groups])
    setattr(rail, f"depends_on_{hl}_intra_op", list(intra_op))
    setattr(rail, f"depends_on_{hl}_group_inv", list(group_inv))
    setattr(rail, f"depends_on_{hl}_inv_groups", [list(g) for g in item_inv])
    setattr(rail, f"depends_on_{hl}_use_groups", [["self"] * len(g) for g in groups])
    return PowerSeqConfig(
        rails=[
            *[
                PowerRail(n, seq_type="input", deb_enable=False, cycle_hi=1, cycle_lo=1)
                for n in used
            ],
            rail,
        ]
    )


# group 形狀：涵蓋單項／多項、單組／多組
SHAPES = [
    [["IN_A"]],
    [["IN_A", "IN_B"]],
    [["IN_A"], ["IN_B"]],
    [["IN_A", "IN_B"], ["IN_C"]],
    [["IN_A"], ["IN_B"], ["IN_C"]],
    [["IN_A", "IN_B"], ["IN_C", "IN_D"]],
]


def _cases():
    for shape in SHAPES:
        n = len(shape)
        for ops in itertools.product(("and", "or", "xor"), repeat=n):
            for ginv in itertools.product((False, True), repeat=n):
                yield shape, list(ops), list(ginv)


ALL_CASES = list(_cases())


def _check(shape, ops, ginv, item_inv, hl) -> None:
    """匯出、反解、在所有輸入組合下與條件樹比對。"""
    cfg = _config(shape, intra_op=ops, group_inv=ginv, item_inv=item_inv, hl=hl)
    rail = cfg.rails[-1]
    name_to_rail = {r.name: r for r in cfg.rails}
    names = sorted({d for g in shape for d in g})

    circuit = _parse_circuit(generate_drawio(cfg), hl)
    assert circuit is not None, "有 group 卻沒畫出任何電路"

    bad = [
        a
        for a in (
            dict(zip(names, bits))
            for bits in itertools.product((0, 1), repeat=len(names))
        )
        if circuit.eval(a) != _expected(rail, hl, name_to_rail, a)
    ]
    assert not bad, (
        f"畫出來的電路與條件樹不符：{shape} op={ops} group_inv={ginv} item_inv={item_inv}\n"
        f"對不上的輸入指派：{bad}"
    )


@pytest.mark.parametrize("hl", ["hi", "lo"])
@pytest.mark.parametrize(
    "shape,ops,ginv",
    ALL_CASES,
    ids=[
        f"{len(s)}g{'-'.join(str(len(g)) for g in s)}_{'+'.join(o)}_{''.join('I' if v else '.' for v in gi)}"
        for s, o, gi in ALL_CASES
    ],
)
def test_drawn_circuit_matches_the_condition_tree(shape, ops, ginv, hl):
    _check(shape, ops, ginv, [[False] * len(g) for g in shape], hl)


@pytest.mark.parametrize("hl", ["hi", "lo"])
@pytest.mark.parametrize(
    "shape,ops,ginv",
    ALL_CASES,
    ids=[
        f"{len(s)}g{'-'.join(str(len(g)) for g in s)}_{'+'.join(o)}_{''.join('I' if v else '.' for v in gi)}"
        for s, o, gi in ALL_CASES
    ],
)
def test_drawn_circuit_matches_the_condition_tree_with_item_inv(shape, ops, ginv, hl):
    """同上，但每個 group 的第一項加上單項反相——單項 inv 與整組 inv 的互動是重點。"""
    _check(shape, ops, ginv, [[ii == 0 for ii in range(len(g))] for g in shape], hl)


# 滿 AND_TREE_THRESHOLD 時 `_wire_and_branch` / `_wire_or_fanin` 會拆成 child + merge
# 兩層，上面的小形狀碰不到這條路徑。這裡用固定 op（不做 product，3^8 太多）各掃一次。
TREE_DEPS = [f"IN_{i}" for i in range(AND_TREE_THRESHOLD)]
TREE_SHAPES = {
    "one-wide-group": [TREE_DEPS],              # 單組滿 8 項 → group 內兩層
    "many-single-groups": [[d] for d in TREE_DEPS],  # 8 個單項組 → 根 OR 兩層
}
TREE_GINV = {"none": lambda n: [False] * n, "all": lambda n: [True] * n,
             "alt": lambda n: [i % 2 == 0 for i in range(n)]}
TREE_CASES = [
    (sn, s, op, gn)
    for sn, s in TREE_SHAPES.items()
    for op in ("and", "or", "xor")
    for gn in TREE_GINV
]


@pytest.mark.parametrize("hl", ["hi", "lo"])
@pytest.mark.parametrize("item_inv_first", [False, True], ids=["plain", "iteminv"])
@pytest.mark.parametrize(
    "shape_name,shape,op,ginv_name",
    TREE_CASES,
    ids=[f"{sn}_{op}_ginv-{gn}" for sn, _, op, gn in TREE_CASES],
)
def test_two_level_gate_tree_matches_the_condition_tree(
    shape_name, shape, op, ginv_name, item_inv_first, hl
):
    n = len(shape)
    item_inv = [[item_inv_first and ii == 0 for ii in range(len(g))] for g in shape]
    _check(shape, [op] * n, TREE_GINV[ginv_name](n), item_inv, hl)
