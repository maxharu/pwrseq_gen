"""
將 VBA 巨集嵌入 openpyxl 產生的 xlsx，另存為 xlsm。
需要本機安裝 Microsoft Excel，且啟用「信任對 VBA 專案物件模型的存取」。

用法:
  python scripts/embed_excel_vba.py <input.xlsx> <output.xlsm>
"""
from __future__ import annotations

import os
import sys

VBA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates",
    "vba",
)
BAS_MODULE = "PwrSeqSync.bas"
THISWORKBOOK_CODE = "ThisWorkbook.cls"
SHEET_NODES_CODE = "SheetNodes.cls"
SHEET_CONFIG_CODE = "SheetConfig.cls"
NODES_SHEET_NAME = "Nodes"
CONFIG_SHEET_NAME = "Config"
SYNC_BUTTON_SHEET_NAME = NODES_SHEET_NAME
SYNC_BUTTON_NAME = "btnSyncOutput"
SYNC_BUTTON_CAPTION = "Sync Conditions"
SYNC_BUTTON_MACRO = "RequestSyncFromNodes"
XL_OPENXML_MACRO = 52


def _read_vba_body(path: str) -> str:
    # Excel VBA CodeModule expects system ANSI; UTF-8 BOM is also accepted on recent builds.
    with open(path, encoding="utf-8-sig") as fh:
        lines = fh.readlines()
    body: list[str] = []
    for line in lines:
        if line.startswith("Attribute "):
            continue
        body.append(line)
    return "".join(body).strip() + "\n"


def _apply_vba_modules(wb, vba_dir: str = VBA_DIR) -> None:
    bas_path = os.path.join(vba_dir, BAS_MODULE)
    tw_path = os.path.join(vba_dir, THISWORKBOOK_CODE)
    sheet_nodes_path = os.path.join(vba_dir, SHEET_NODES_CODE)
    sheet_config_path = os.path.join(vba_dir, SHEET_CONFIG_CODE)
    if not all(
        os.path.isfile(p)
        for p in (bas_path, tw_path, sheet_nodes_path, sheet_config_path)
    ):
        raise FileNotFoundError(f"VBA 來源不存在: {vba_dir}")

    vbproj = wb.VBProject
    for comp in list(vbproj.VBComponents):
        if comp.Name == "PwrSeqSync":
            vbproj.VBComponents.Remove(comp)

    vbproj.VBComponents.Import(bas_path)

    tw = vbproj.VBComponents("ThisWorkbook").CodeModule
    if tw.CountOfLines > 0:
        tw.DeleteLines(1, tw.CountOfLines)
    tw.AddFromString(_read_vba_body(tw_path))

    nodes_ws = None
    for i in range(1, wb.Worksheets.Count + 1):
        ws = wb.Worksheets(i)
        if ws.Name == NODES_SHEET_NAME:
            nodes_ws = ws
            break
    if nodes_ws is None:
        raise RuntimeError(f"找不到工作表: {NODES_SHEET_NAME}")

    sheet_mod = vbproj.VBComponents(nodes_ws.CodeName).CodeModule
    if sheet_mod.CountOfLines > 0:
        sheet_mod.DeleteLines(1, sheet_mod.CountOfLines)
    sheet_mod.AddFromString(_read_vba_body(sheet_nodes_path))

    config_ws = _find_sheet(wb, CONFIG_SHEET_NAME)
    if config_ws is None:
        raise RuntimeError(f"找不到工作表: {CONFIG_SHEET_NAME}")
    config_mod = vbproj.VBComponents(config_ws.CodeName).CodeModule
    if config_mod.CountOfLines > 0:
        config_mod.DeleteLines(1, config_mod.CountOfLines)
    config_mod.AddFromString(_read_vba_body(sheet_config_path))


def _find_sheet(wb, sheet_name: str):
    for i in range(1, wb.Worksheets.Count + 1):
        ws = wb.Worksheets(i)
        if ws.Name == sheet_name:
            return ws
    return None


def _remove_sync_button(ws) -> None:
    for i in range(ws.Shapes.Count, 0, -1):
        shape = ws.Shapes(i)
        if shape.Name == SYNC_BUTTON_NAME:
            shape.Delete()


def add_sync_button(wb) -> None:
    """Place a form-control button on the nodes sheet."""
    xl_button_control = 0
    ws = _find_sheet(wb, SYNC_BUTTON_SHEET_NAME)
    if ws is None:
        raise RuntimeError(f"找不到工作表: {SYNC_BUTTON_SHEET_NAME}")
    _remove_sync_button(ws)
    # Top-right of data area (row 1 hint row); units: points
    btn = ws.Shapes.AddFormControl(xl_button_control, 720, 8, 220, 30)
    btn.Name = SYNC_BUTTON_NAME
    btn.OnAction = SYNC_BUTTON_MACRO
    btn.TextFrame.Characters().Text = SYNC_BUTTON_CAPTION


def add_sync_button_inplace(xlsm_path: str) -> None:
    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("請先安裝: pip install pywin32") from exc

    xlsm_abs = os.path.abspath(xlsm_path)
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = None
    try:
        wb = excel.Workbooks.Open(xlsm_abs)
        add_sync_button(wb)
        wb.Save()
        wb.Close(SaveChanges=False)
        wb = None
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        excel.Quit()


def refresh_vba_inplace(xlsm_path: str, vba_dir: str = VBA_DIR) -> None:
    """更新既有 xlsm 的 VBA，保留工作表資料。"""
    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("請先安裝: pip install pywin32") from exc

    xlsm_abs = os.path.abspath(xlsm_path)
    if not os.path.isfile(xlsm_abs):
        raise FileNotFoundError(xlsm_abs)

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = None
    try:
        wb = excel.Workbooks.Open(xlsm_abs)
        _apply_vba_modules(wb, vba_dir)
        add_sync_button(wb)
        wb.Save()
        wb.Close(SaveChanges=False)
        wb = None
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        excel.Quit()


def embed_vba(xlsx_path: str, xlsm_path: str, vba_dir: str = VBA_DIR) -> None:
    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("請先安裝: pip install pywin32") from exc

    xlsx_abs = os.path.abspath(xlsx_path)
    xlsm_abs = os.path.abspath(xlsm_path)
    if not os.path.isfile(xlsx_abs):
        raise FileNotFoundError(xlsx_abs)

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = None
    try:
        wb = excel.Workbooks.Open(xlsx_abs)
        _apply_vba_modules(wb, vba_dir)
        add_sync_button(wb)
        if os.path.isfile(xlsm_abs):
            os.remove(xlsm_abs)
        wb.SaveAs(xlsm_abs, FileFormat=XL_OPENXML_MACRO)
        wb.Close(SaveChanges=False)
        wb = None
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        excel.Quit()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__.strip())
        return 2
    embed_vba(args[0], args[1])
    print(f"Wrote: {os.path.abspath(args[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
