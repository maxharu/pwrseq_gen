"""Group-internal boolean ops (AND / OR / XOR) shared by generators and sim."""
from __future__ import annotations

INTRA_OPS = ("and", "or", "xor")
INTRA_OP_LABELS = ("AND", "OR", "XOR")


def normalize_intra_op(op: str | None) -> str:
    if not op:
        return "and"
    key = str(op).strip().lower()
    if key in INTRA_OPS:
        return key
    return "and"


def intra_op_label(op: str | None) -> str:
    return normalize_intra_op(op).upper()


def parse_intra_op_cell(raw) -> str:
    """Parse Excel/UI cell: AND/OR/XOR or empty → and."""
    if raw is None:
        return "and"
    s = str(raw).strip()
    if not s:
        return "and"
    return normalize_intra_op(s)


def is_legacy_group_inv_cell(raw) -> bool:
    """True when column holds Y/N group inv (pre-Operation column layout)."""
    if raw is None:
        return True
    s = str(raw).strip().upper()
    if not s:
        return True
    if s in ("Y", "N", "YES", "NO"):
        return True
    return False


def eval_intra_op(op: str | None, values: list[int]) -> int:
    if not values:
        return 0
    kind = normalize_intra_op(op)
    if kind == "and":
        return 1 if all(values) else 0
    if kind == "or":
        return 1 if any(values) else 0
    result = 0
    for v in values:
        result ^= 1 if v else 0
    return result


def verilog_intra_expr(terms: list[str], op: str | None) -> str:
    if not terms:
        return "1'b0"
    if len(terms) == 1:
        return f"({terms[0]})"
    kind = normalize_intra_op(op)
    if kind == "and":
        sep = " & "
    elif kind == "or":
        sep = " | "
    else:
        sep = " ^ "
    return f"({sep.join(terms)})"


def c_intra_expr(terms: list[str], op: str | None) -> str:
    if not terms:
        return "0"
    if len(terms) == 1:
        return f"({terms[0]})"
    kind = normalize_intra_op(op)
    if kind == "and":
        sep = " & "
    elif kind == "or":
        sep = " | "
    else:
        sep = " ^ "
    return f"({sep.join(terms)})"
