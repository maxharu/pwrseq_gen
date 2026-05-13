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
    檢查是否有循環依賴，有則回傳 True（排除 __HIGH__/__LOW__）
    Hi 與 Lo 依賴分開檢查：iHi 決定上電順序，iLo 決定關電順序。
    例如 SIG_3 iHi 依賴 SIG_2、SIG_2 iLo 依賴 SIG_3 不會形成循環（狀態不同）。
    僅當 Hi 圖或 Lo 圖各自內部有環時才算循環依賴。
    """
    const_deps = {"__HIGH__", "__LOW__"}

    def _has_cycle_in_graph(g: dict[str, list[str]]) -> bool:
        visited = set()
        for name in g:
            if name not in visited:
                if _has_cycle_dfs(name, g, visited, set()):
                    return True
        return False

    graph_hi = {
        r.name: [d for d in r.get_depends_on_hi_flat() if d not in const_deps]
        for r in config.rails
    }
    graph_lo = {
        r.name: [d for d in r.get_depends_on_lo_flat() if d not in const_deps]
        for r in config.rails
    }
    graph_force = {
        r.name: [d for d in r.get_depends_on_force_flat() if d not in const_deps]
        for r in config.rails
    }
    return (
        _has_cycle_in_graph(graph_hi)
        or _has_cycle_in_graph(graph_lo)
        or _has_cycle_in_graph(graph_force)
    )


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
