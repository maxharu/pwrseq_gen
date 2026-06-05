"""Draw.io 匯出選項（走線重疊規則）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DrawioExportOptions:
    """控制同 source / 同 destination 是否允許水平或垂直走線重疊。"""

    same_source_horiz: bool = True
    same_source_vert: bool = False
    same_dest_horiz: bool = False
    same_dest_vert: bool = False

    @classmethod
    def defaults(cls) -> DrawioExportOptions:
        return cls()
