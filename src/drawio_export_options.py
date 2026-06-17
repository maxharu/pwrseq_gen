"""Draw.io 匯出選項（走線重疊規則）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DrawioExportOptions:
    """Draw.io 匯出選項（Cell-centric grid）。"""

    grid_columns: int | None = None
    margin: int = 40

    @classmethod
    def defaults(cls) -> DrawioExportOptions:
        return cls()
