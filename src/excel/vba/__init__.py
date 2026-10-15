"""VBA 嵌入：COM（需 Excel）與 zip 注入（不需 Excel）兩條路徑。"""
from excel.vba.embed_excel_vba import add_sync_button_inplace, embed_vba, refresh_vba_inplace
from excel.vba.inject_vba_zip import inject_vba_zip

__all__ = [
    "add_sync_button_inplace",
    "embed_vba",
    "inject_vba_zip",
    "refresh_vba_inplace",
]
