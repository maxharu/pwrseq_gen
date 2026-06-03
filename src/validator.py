"""
Power Sequence 配置驗證
- 循環依賴檢查
- 名稱唯一性
- 依賴存在性
"""
from config_models import PowerSeqConfig


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

    # Duplicate names
    dup = check_duplicate_names(config)
    if dup:
        errors.append(f"Duplicate rail names: {', '.join(dup)}")

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
