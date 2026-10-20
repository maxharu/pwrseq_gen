"""width 公式求值（width_expr → N）。

width 從「整數字串」升級成「可引用 parameter 的算式」後，求值規則只留這一份，讓
展開/收合/驗證/產生器都走同一個 `eval_width`、不各自 parse。刻意用 ast 白名單而非
`eval()`：只放行整數字面、parameter 名、`+ - * //`、括號與一元正負號，杜絕任意程式碼執行。
"""
import ast
from collections.abc import Mapping


class ParamExprError(ValueError):
    """width_expr 語法非法、引用未宣告 parameter、或含不允許節點時拋出。

    繼承 ValueError，讓既有「except ValueError 視為 width 無效」的呼叫端（excel 匯入等）
    不必改就能相容。
    """


def _param_map(parameters) -> dict[str, int]:
    """把 parameters（Parameter 序列或 name→value dict）正規化成名稱→整數值的對照。

    不直接 import Parameter（避免 core.config_models ↔ core.param_expr 循環）；改用 duck typing
    讀 `.name` / `.value`。
    """
    if parameters is None:
        return {}
    if isinstance(parameters, Mapping):
        return {str(k): int(v) for k, v in parameters.items()}
    return {str(p.name): int(p.value) for p in parameters}


def _eval_node(node: ast.AST, params: dict[str, int]) -> int:
    if isinstance(node, ast.Constant):
        # bool 是 int 的子類，明確擋掉，避免 True/False 被當 1/0
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise ParamExprError(f"width 只允許整數字面：{node.value!r}")
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in params:
            raise ParamExprError(f"width 引用未宣告的 parameter：{node.id}")
        return params[node.id]
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, params)
        right = _eval_node(node.right, params)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise ParamExprError("width 公式除以 0")
            return left // right
        raise ParamExprError("width 公式只支援 + - * //")
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return -_eval_node(node.operand, params)
        if isinstance(node.op, ast.UAdd):
            return _eval_node(node.operand, params)
        raise ParamExprError("width 公式只支援一元正負號")
    raise ParamExprError(f"width 公式不支援的語法：{type(node).__name__}")


def eval_width(width_expr, parameters=None) -> int:
    """由 width_expr 算出群組 bit 數 N。

    純整數字串（如 "2"）無需 parameters 即可求值，向後相容 A2/B 階段。公式引用 parameter 時
    傳入 parameters（Parameter 序列或 name→value dict）。語法/名稱/型別非法一律拋 ParamExprError。
    """
    expr = str(width_expr).strip()
    if not expr:
        raise ParamExprError("width 公式為空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ParamExprError(f"width 公式語法錯誤：{expr}") from e
    return _eval_node(tree.body, _param_map(parameters))
