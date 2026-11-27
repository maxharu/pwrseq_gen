"""
Power Sequence 配置驗證
- 循環依賴檢查
- 名稱唯一性
- 依賴存在性
"""
import re

from core.config_models import PowerSeqConfig, eval_width
from core.naming import safe_name

_PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def check_duplicate_names(config: PowerSeqConfig) -> list[str]:
    """檢查 Rail 名稱是否重複"""
    names = [r.name for r in config.rails]
    seen = set()
    duplicates = []
    for n in names:
        if n in seen:
            duplicates.append(n)
        seen.add(n)
    return duplicates


def check_identifier_collisions(config: PowerSeqConfig) -> list[tuple[str, str, str]]:
    """展開後兩個不同節點名若 collapse 到同一個 Verilog/C 識別子，回傳 (name, other, ident)。

    vector 的 bit 名 base[i] 經 safe_name 變成 base_i，可能與字面節點 base_i 撞號——
    純名稱唯一性（check_duplicate_names）看不出來，但產生出來的程式會變成兩個同名訊號。
    """
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for r in config.rails:
        ident = safe_name(r.name)
        first = seen.get(ident)
        if first is None:
            seen[ident] = r.name
        elif first != r.name:  # 同名重複由 check_duplicate_names 負責
            collisions.append((r.name, first, ident))
    return collisions


def check_invalid_width(config: PowerSeqConfig) -> list[tuple[str, str]]:
    """vector 群組的 width_expr 若非正整數，回傳 (base, width_expr)。

    A2 階段 width 一律是整數字串；非正整數（0/負/非數）會讓展開失敗或產生空群組。
    每個 group_base 只檢查一次。
    """
    bad: list[tuple[str, str]] = []
    checked: set[str] = set()
    for r in config.rails:
        if r.group_base is None or r.group_base in checked:
            continue
        checked.add(r.group_base)
        try:
            if eval_width(r.width_expr, config.parameters) <= 0:
                bad.append((r.group_base, r.width_expr))
        except (ValueError, TypeError):
            bad.append((r.group_base, r.width_expr))
    return bad


def check_parameters(config: PowerSeqConfig) -> list[str]:
    """parameter 名需為合法識別子且不重複、值需為正整數；回傳可點擊格式的錯誤訊息。"""
    errors: list[str] = []
    seen: set[str] = set()
    for p in getattr(config, "parameters", None) or []:
        name = p.name or ""
        if not _PARAM_NAME_RE.match(name):
            errors.append(f"'{name}' is not a valid parameter name (must be an identifier)")
        elif name in seen:
            errors.append(f"'{name}' is a duplicate parameter name")
        else:
            seen.add(name)
        if isinstance(p.value, bool) or not isinstance(p.value, int) or p.value <= 0:
            errors.append(
                f"'{name}' has invalid parameter value '{p.value}' (must be a positive integer)"
            )
    return errors


def check_dimensions(config: PowerSeqConfig) -> list[str]:
    """全域維度驗證：個數 0~2、名稱需存在於 parameters、不重複、該 parameter 最大值 ≥ 1。"""
    errors: list[str] = []
    dims = getattr(config, "dimensions", None) or []
    if len(dims) > 2:
        errors.append(f"Too many dimensions ({len(dims)}); at most 2 are allowed")
    param_values = {p.name: p.value for p in getattr(config, "parameters", None) or []}
    seen: set[str] = set()
    for name in dims:
        if name in seen:
            errors.append(f"'{name}' is a duplicate dimension")
            continue
        seen.add(name)
        if name not in param_values:
            errors.append(f"dimension '{name}' is not a defined parameter")
        else:
            value = param_values[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                errors.append(
                    f"dimension '{name}' has invalid max value '{value}' (must be an integer >= 1)"
                )
    return errors


def check_take_lower_bounds(config: PowerSeqConfig) -> list[str]:
    """All 歸約的下界 lo：須為整數、0 <= lo < 對應維度最大值。

    row 下界（|oneDim[NUM_ROW-1 : lo]）只允許 1 維來源；col 下界
    （|bus[base*C + NUM_COL-1 : base*C + lo]）只允許 2 維來源的 All col 歸約。
    row 的 2D 範圍是跨步歸約（§3.5）、不支援。NUM_ROW/NUM_COL 是符號式，這裡以 parameter
    預設值（最大值）為畫布檢查；實際 N 更小時的越界由使用者負責。
    """
    errors: list[str] = []
    rail_by_name = {r.name: r for r in config.rails}
    param_values = {p.name: p.value for p in getattr(config, "parameters", None) or []}

    def _check(axis: str, rail_name: str, dep: str, node: dict, dim: str | None) -> None:
        """單一軸的 lo 檢查：axis 用於錯誤訊息（row/col），dim 為該軸對應 parameter 名。"""
        lo = node["lo"]
        if node.get("kind") != "all":
            errors.append(f"'{rail_name}' sets a {axis} lower bound on non-All take for '{dep}'")
            return
        if dim is None:
            errors.append(f"'{rail_name}' {axis} lower bound on '{dep}' requires a "
                          f"{'1-dim' if axis == 'row' else '2-dim'} source")
            return
        if isinstance(lo, bool) or not isinstance(lo, int) or lo < 0:
            errors.append(
                f"'{rail_name}' has invalid {axis} lower bound '{lo}' for '{dep}' "
                f"(must be an integer >= 0)"
            )
            return
        max_value = param_values.get(dim)
        if isinstance(max_value, int) and not lo < max_value:
            errors.append(
                f"'{rail_name}' {axis} lower bound {lo} on '{dep}' must be < {dim} (max {max_value})"
            )

    for rail in config.rails:
        for kind in ("hi", "lo", "force"):
            groups = getattr(rail, f"get_{kind}_groups")()
            get_take = getattr(rail, f"get_{kind}_take")
            for gi, group in enumerate(groups):
                for ii, dep in enumerate(group):
                    take = get_take(gi, ii) or {}
                    target = rail_by_name.get(dep)
                    dims = list(getattr(target, "dim_params", None) or []) if target else []
                    row = take.get("row") or {}
                    if "lo" in row:
                        # row 下界只允許 1 維來源（dims[0]）；2D 來源視為無合法軸。
                        _check("row", rail.name, dep, row, dims[0] if len(dims) == 1 else None)
                    col = take.get("col") or {}
                    if "lo" in col:
                        # col 下界只允許 2 維來源（dims[1]）。
                        _check("col", rail.name, dep, col, dims[1] if len(dims) >= 2 else None)
    return errors


def check_slice_reachability(config: PowerSeqConfig) -> list[str]:
    """Slice 群組的 row 述詞在代表值（parameter 預設=最大值）下是否可達 → 警告清單（不報錯）。

    §4.1(5)：絕對 row k 在實例 N <= k 時不可達（符號上仍合法），只警告。row 軸最大值取自
    該 rail 第一維 dim_params[0] 對應 parameter 的 value。刻意不併入 validate() 的錯誤，
    以免擋下匯出（符號 RTL 對任何 N 仍成立）。"""
    warnings: list[str] = []
    param_values = {p.name: p.value for p in getattr(config, "parameters", None) or []}
    for rail in config.rails:
        slices = getattr(rail, "slices", None) or []
        if not slices:
            continue
        dims = list(getattr(rail, "dim_params", None) or [])
        max_n = param_values.get(dims[0]) if dims else None
        if not isinstance(max_n, int):
            continue
        name = rail.group_base or rail.name
        for sg in slices:
            for k in sg.rows:
                if k >= max_n:
                    warnings.append(
                        f"'{name}' slice row {k} is unreachable at representative size "
                        f"{dims[0]}={max_n}"
                    )
    return warnings


def check_missing_deps(config: PowerSeqConfig) -> list[tuple[str, str]]:
    """檢查 depends_on_hi / depends_on_lo 中的名稱是否存在（排除 __HIGH__/__LOW__ 常數）"""
    valid_names = {r.name for r in config.rails}
    const_deps = {"__HIGH__", "__LOW__"}
    missing = []
    for rail in config.rails:
        deps = (
            rail.get_depends_on_hi_flat()
            + rail.get_depends_on_lo_flat()
            + rail.get_depends_on_force_flat()
        )
        for dep in deps:
            if dep not in const_deps and dep not in valid_names:
                missing.append((rail.name, dep))
    return missing


def _has_cycle_dfs(
    name: str,
    graph: dict[str, list[str]],
    visited: set[str],
    path: set[str],
) -> bool:
    """DFS 偵測循環"""
    visited.add(name)
    path.add(name)
    for neighbor in graph.get(name, []):
        if neighbor not in visited:
            if _has_cycle_dfs(neighbor, graph, visited, path):
                return True
        elif neighbor in path:
            return True
    path.remove(name)
    return False


def check_circular_dependency(config: PowerSeqConfig) -> bool:
    """
    檢查是否有循環依賴，有則回傳 True（排除 __HIGH__/__LOW__）。

    以 (rail, 欄位) 為節點建單一有向圖；每條依賴依其 use 連到目標欄位：
    - use="hi"/"lo"/"force"：連到該節點的對應 condition 欄位
    - use="self"：連到「引用端所在欄位」（與 C 產生器 self→.{kind}.condition 一致）
    輸入節點 / __HIGH__ / __LOW__ 視為葉節點（無出邊）。

    如此 Hi 與 Lo 等不同狀態欄位天然分屬不同節點：
    - SIG_3.hi 依賴 SIG_2、SIG_2.lo 依賴 SIG_3 → 不成環（欄位不同）。
    - EN.hi 引用自己的 EN.lo → 邊 (EN,hi)->(EN,lo)，只要 EN.lo 不回指 EN.hi 就不成環。
    僅同欄位自我引用（EN.hi -> EN.hi）等真正組合迴圈才會被判定為循環。
    """
    const_deps = {"__HIGH__", "__LOW__"}
    cols = ("hi", "lo", "force")
    rail_by_name = {r.name: r for r in config.rails}
    groups_getter = {
        "hi": lambda r: r.get_hi_groups(),
        "lo": lambda r: r.get_lo_groups(),
        "force": lambda r: r.get_force_groups(),
    }
    use_getter = {
        "hi": lambda r: r.get_hi_use,
        "lo": lambda r: r.get_lo_use,
        "force": lambda r: r.get_force_use,
    }

    def node(name: str, col: str) -> str:
        return f"{name}\x00{col}"

    graph: dict[str, list[str]] = {}
    for r in config.rails:
        for col in cols:
            src = node(r.name, col)
            graph.setdefault(src, [])
            get_use = use_getter[col](r)
            for gi, group in enumerate(groups_getter[col](r)):
                for ii, dep in enumerate(group):
                    if dep in const_deps:
                        continue
                    target = rail_by_name.get(dep)
                    if target is None or target.seq_type == "input":
                        continue  # input / 不存在：葉節點，無出邊
                    use = get_use(gi, ii, dep)
                    tcol = use if use in cols else col  # "self" → 引用端欄位
                    graph[src].append(node(dep, tcol))

    visited: set[str] = set()
    for n in graph:
        if n not in visited:
            if _has_cycle_dfs(n, graph, visited, set()):
                return True
    return False


def validate(config: PowerSeqConfig) -> tuple[bool, list[str]]:
    """
    完整驗證，回傳 (是否通過, 錯誤訊息列表)
    """
    errors = []

    # Parameters (name legal/unique, value positive int)
    errors.extend(check_parameters(config))

    # Global dimensions (count 0~2, exist in parameters, unique, max >= 1)
    errors.extend(check_dimensions(config))

    # 1D All-reduction row lower bound (0 <= lo < max NUM_ROW)
    errors.extend(check_take_lower_bounds(config))

    # Duplicate names
    dup = check_duplicate_names(config)
    if dup:
        errors.append(f"Duplicate rail names: {', '.join(dup)}")

    # Identifier collisions after expansion (vector FOO[2] vs literal FOO_2)
    for name, other, ident in check_identifier_collisions(config):
        errors.append(
            f"'{name}' and '{other}' map to the same identifier '{ident}'"
        )

    # Vector width must be a positive integer
    for base, wexpr in check_invalid_width(config):
        errors.append(
            f"'{base}' has invalid width '{wexpr}' (must be a positive integer)"
        )

    # Missing dependencies
    missing = check_missing_deps(config)
    if missing:
        for rail, dep in missing:
            errors.append(f"'{rail}' depends on non-existent rail: '{dep}'")

    # Circular dependency
    if check_circular_dependency(config):
        errors.append("Circular dependency detected in depends_on")

    # Empty name
    for r in config.rails:
        if not r.name or not r.name.strip():
            errors.append("Rail with empty name exists")
            break

    return len(errors) == 0, errors
