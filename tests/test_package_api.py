"""套件邊界：跨套件呼叫只能走各套件 `__init__.py` 宣告的對外介面。

沒有這支測試的話，「對外介面」只是慣例——下次有人寫
`from drawio.drawio_cell_export import generate_drawio` 不會有任何東西擋，
邊界就一次性地腐蝕掉了（這正是 `drawio_export.py` 那 34 個 re-export 的由來）。

規則：`src/` 與 `scripts/` 裡，若 import 的頂層套件與呼叫端不同，目標必須是一個
**套件**（有 `__init__.py` 的目錄），不能是套件內的模組。

兩個例外，都是刻意的：
  - `core` 是共用詞彙表（PowerRail / safe_name / DEP_HIGH …），性質接近 stdlib，
    收成單一扁平命名空間只會讓 `from core.config_models import PowerRail` 這種
    自我說明的寫法變得更難讀。
  - `tests/` 本身不受規範：白箱測試本來就會戳進實作細節，那是測試不是契約。
"""
import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

# 不受邊界規範的目標套件（理由見 module docstring）
EXEMPT_TARGETS = {"core"}

EXPECTED_API = {
    "codegen": ["generate_c", "generate_verilog"],
    "drawio": ["DrawioExportOptions", "generate_drawio"],
    "excel": [
        "apply_nodes_sheet_header_rows",
        "build_signal_dropdown_entries",
        "export_powerseq_to_excel",
        "load_powerseq_from_excel",
        "load_timing_scenario_from_excel",
        "node_sheet_headers",
    ],
    "timing": [
        "TIMING_EDGE_BOTH",
        "TIMING_EDGE_HI_ONLY",
        "TIMING_EDGE_LO_ONLY",
        "TimingExportOptions",
        "default_scenario_for_config",
        "export_schemdraw",
        "export_schemdraw_from_options",
        "generate_schemdraw_doc",
        "merge_scenario_for_config",
        "render_schemdraw_png_bytes",
        "timing_edge_kinds_from_choice",
    ],
}


def _is_package(dotted: str) -> bool:
    return os.path.isfile(os.path.join(SRC, *dotted.split("."), "__init__.py"))


def _top_package_of(path: str) -> str:
    """呼叫端所屬的頂層套件；`scripts/` 與 `src/main.py` 不屬於任何套件。"""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    parts = rel.split("/")
    if parts[0] == "src" and len(parts) > 2:
        return parts[1]
    return ""


def _python_files():
    for base in ("src", "scripts"):
        for dirpath, _, filenames in os.walk(os.path.join(ROOT, base)):
            if "__pycache__" in dirpath:
                continue
            for fn in filenames:
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def _cross_package_module_imports() -> list[str]:
    """回傳所有「跨套件但指向模組而非套件」的 import，格式為可讀的違規描述。"""
    violations = []
    for path in _python_files():
        consumer = _top_package_of(path)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            target_top = node.module.split(".")[0]
            if not _is_package(target_top):
                continue  # 不是本專案的套件（stdlib / 第三方）
            if target_top in (consumer, *EXEMPT_TARGETS):
                continue
            if _is_package(node.module):
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            violations.append(f"{rel}:{node.lineno}: from {node.module} import ...")
    return violations


def test_cross_package_imports_go_through_the_package_api():
    violations = _cross_package_module_imports()
    assert not violations, (
        "跨套件 import 必須指向套件而非模組，例如 `from drawio import generate_drawio`：\n"
        + "\n".join(violations)
    )


@pytest.mark.parametrize("pkg,names", sorted(EXPECTED_API.items()))
def test_package_declares_its_public_api(pkg, names):
    """__all__ 是契約本身，改動對外介面要同時改這裡。"""
    module = __import__(pkg)
    assert sorted(module.__all__) == names
    for name in names:
        assert hasattr(module, name), f"{pkg}.__all__ 列了 {name} 但套件沒有這個屬性"


def test_vba_subpackage_declares_its_own_api():
    """excel.vba 是獨立的子套件介面，不併進 excel 的扁平命名空間。"""
    import excel.vba

    assert sorted(excel.vba.__all__) == [
        "add_sync_button_inplace",
        "embed_vba",
        "inject_vba_zip",
        "refresh_vba_inplace",
    ]
