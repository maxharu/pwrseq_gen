"""專案檔案位置（開發樹與 PyInstaller 打包後）。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_DIR.parent


def _bundle_dir() -> Path | None:
    """PyInstaller 的解壓目錄；未打包時回 None。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", SRC_DIR))
    return None


def _data_dir(name: str) -> Path:
    """打包後資源平鋪在解壓目錄下，開發樹則在專案根目錄。"""
    bundle = _bundle_dir()
    return (bundle / name) if bundle else (PROJECT_ROOT / name)


# PyInstaller 在載入任何應用模組前就設好 sys.frozen，所以這裡 import 期取值是正確的
TEMPLATES_DIR = _data_dir("templates")


def reference_dir() -> Path:
    bundle = _bundle_dir()
    return (bundle / "reference") if bundle else (SRC_DIR / "reference")
