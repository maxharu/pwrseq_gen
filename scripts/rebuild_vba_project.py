"""
從 templates/vba/*.bas 重建 vbaProject.bin（需 Excel + pywin32 + AccessVBOM）。
改過 VBA 原始碼後執行:
  python scripts/rebuild_vba_project.py
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBA_BIN = os.path.join(ROOT, "templates", "vba", "vbaProject.bin")


def main() -> int:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from generate_excel_template import main as gen_main, OUT_PATH
    import shutil
    import zipfile

    # 強制走 COM embed，避免 zip-inject 舊 vbaProject.bin 覆蓋剛改的 .bas/.cls
    bak = VBA_BIN + ".bak"
    had_bin = os.path.isfile(VBA_BIN)
    if had_bin:
        shutil.move(VBA_BIN, bak)
    try:
        gen_main()
    finally:
        if had_bin and os.path.isfile(bak):
            os.remove(bak)
    if not os.path.isfile(OUT_PATH):
        print("產生 xlsm 失敗")
        return 1

    with zipfile.ZipFile(OUT_PATH, "r") as zf:
        data = zf.read("xl/vbaProject.bin")
    os.makedirs(os.path.dirname(VBA_BIN), exist_ok=True)
    with open(VBA_BIN, "wb") as fh:
        fh.write(data)
    print(f"Updated: {VBA_BIN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
