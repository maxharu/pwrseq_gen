"""專案檔案位置（開發樹與 PyInstaller 打包後）。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_DIR.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def reference_dir() -> Path:
    """PyInstaller onefile 時資源在 sys._MEIPASS/reference。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "reference"
    return SRC_DIR / "reference"
