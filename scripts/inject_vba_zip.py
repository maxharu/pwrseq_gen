"""
將預先建立的 xl/vbaProject.bin 併入 xlsx，輸出 xlsm（不需 Excel COM）。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from xml.etree import ElementTree as ET

VBA_BIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates",
    "vba",
    "vbaProject.bin",
)

CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
VBA_REL_TYPE = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"
MACRO_WORKBOOK_CT = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
XLSX_WORKBOOK_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"


def _ensure_content_types(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    has_bin_default = any(
        el.tag == f"{CT_NS}Default" and el.get("Extension") == "bin"
        for el in root
    )
    if not has_bin_default:
        default = ET.Element(f"{CT_NS}Default")
        default.set("Extension", "bin")
        default.set("ContentType", "application/vnd.ms-office.vbaProject")
        root.insert(0, default)

    for el in root.findall(f"{CT_NS}Override"):
        if el.get("PartName") == "/xl/workbook.xml":
            el.set("ContentType", MACRO_WORKBOOK_CT)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _ensure_workbook_rel(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    for el in root.findall(f"{REL_NS}Relationship"):
        if el.get("Type") == VBA_REL_TYPE:
            return xml_bytes

    ids = []
    for el in root.findall(f"{REL_NS}Relationship"):
        match = re.match(r"rId(\d+)", el.get("Id", ""))
        if match:
            ids.append(int(match.group(1)))
    next_id = max(ids, default=0) + 1

    rel = ET.Element(f"{REL_NS}Relationship")
    rel.set("Id", f"rId{next_id}")
    rel.set("Type", VBA_REL_TYPE)
    rel.set("Target", "vbaProject.bin")
    root.append(rel)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def inject_vba_zip(xlsx_path: str, xlsm_path: str, vba_bin_path: str = VBA_BIN) -> None:
    if not os.path.isfile(vba_bin_path):
        raise FileNotFoundError(vba_bin_path)

    with tempfile.TemporaryDirectory() as tmp:
        staging = os.path.join(tmp, "pack")
        with zipfile.ZipFile(xlsx_path, "r") as zin:
            zin.extractall(staging)

        shutil.copy2(vba_bin_path, os.path.join(staging, "xl", "vbaProject.bin"))

        ct_path = os.path.join(staging, "[Content_Types].xml")
        with open(ct_path, "rb") as fh:
            ct_bytes = fh.read()
        with open(ct_path, "wb") as fh:
            fh.write(_ensure_content_types(ct_bytes))

        rel_path = os.path.join(staging, "xl", "_rels", "workbook.xml.rels")
        with open(rel_path, "rb") as fh:
            rel_bytes = fh.read()
        with open(rel_path, "wb") as fh:
            fh.write(_ensure_workbook_rel(rel_bytes))

        if os.path.isfile(xlsm_path):
            os.remove(xlsm_path)
        with zipfile.ZipFile(xlsm_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for folder, _, files in os.walk(staging):
                for name in files:
                    full = os.path.join(folder, name)
                    arc = os.path.relpath(full, staging).replace("\\", "/")
                    zout.write(full, arc)


WB_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
WB_REL_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

_GOLDEN_BUTTON_ASSETS = (
    "xl/drawings/drawing1.xml",
    "xl/drawings/vmlDrawing1.vml",
    "xl/ctrlProps/ctrlProp1.xml",
)

_GOLDEN_CT_DEFAULTS = (
    ("vml", "application/vnd.openxmlformats-officedocument.vmlDrawing"),
)

_GOLDEN_CT_OVERRIDES = (
    ("/xl/drawings/drawing1.xml", "application/vnd.openxmlformats-officedocument.drawing+xml"),
    ("/xl/ctrlProps/ctrlProp1.xml", "application/vnd.ms-excel.controlproperties+xml"),
)


def _resolve_sheet_part(zf: zipfile.ZipFile, sheet_name: str) -> str | None:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {el.get("Id"): el.get("Target") for el in rels.findall(f"{REL_NS}Relationship")}
    for sh in wb.findall(f"{WB_NS}sheet"):
        if sh.get("name") != sheet_name:
            continue
        rid = sh.get(WB_REL_ATTR)
        target = rel_map.get(rid or "")
        if not target:
            return None
        if target.startswith("/"):
            return target.lstrip("/")
        return f"xl/{target}"
    return None


def _sheet_rels_path(sheet_part: str) -> str:
    base, name = os.path.split(sheet_part)
    return f"{base}/_rels/{name}.rels"


def _extract_sync_button_snippet(sheet_xml: bytes) -> str | None:
    text = sheet_xml.decode("utf-8")
    match = re.search(
        r"<drawing r:id=\"rId\d+\"/>.*?<legacyDrawing r:id=\"rId\d+\"/>"
        r".*?<mc:AlternateContent[\s\S]*?</mc:AlternateContent>",
        text,
    )
    return match.group(0) if match else None


def _patch_sheet_xml_with_button(sheet_xml: bytes, snippet: str) -> bytes:
    text = sheet_xml.decode("utf-8")
    text = re.sub(r"<drawing r:id=\"rId\d+\"/>", "", text)
    text = re.sub(r"<legacyDrawing r:id=\"rId\d+\"/>", "", text)
    text = re.sub(
        r"<mc:AlternateContent[\s\S]*?</mc:AlternateContent>",
        "",
        text,
    )
    if "</worksheet>" not in text:
        return sheet_xml
    return text.replace("</worksheet>", snippet + "</worksheet>").encode("utf-8")


def _merge_content_types_for_button(ct_bytes: bytes, golden_ct_bytes: bytes) -> bytes:
    root = ET.fromstring(ct_bytes)
    golden = ET.fromstring(golden_ct_bytes)

    def has_default(ext: str) -> bool:
        return any(
            el.tag == f"{CT_NS}Default" and el.get("Extension") == ext
            for el in root
        )

    def has_override(part: str) -> bool:
        return any(
            el.tag == f"{CT_NS}Override" and el.get("PartName") == part
            for el in root
        )

    for ext, ctype in _GOLDEN_CT_DEFAULTS:
        if not has_default(ext):
            for el in golden.findall(f"{CT_NS}Default"):
                if el.get("Extension") == ext:
                    root.insert(0, copy_ct_element(el))
                    break

    for part, ctype in _GOLDEN_CT_OVERRIDES:
        if not has_override(part):
            ov = ET.Element(f"{CT_NS}Override")
            ov.set("PartName", part)
            ov.set("ContentType", ctype)
            root.append(ov)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def copy_ct_element(el: ET.Element) -> ET.Element:
    new_el = ET.Element(el.tag)
    new_el.attrib.update(el.attrib)
    return new_el


def copy_sync_button_from_golden(
    xlsm_path: str,
    golden_xlsm_path: str,
    *,
    nodes_sheet_name: str = "Nodes",
) -> bool:
    """Copy Sync Conditions form button from golden xlsm (openpyxl save strips drawings)."""
    if not os.path.isfile(golden_xlsm_path) or not os.path.isfile(xlsm_path):
        return False

    with zipfile.ZipFile(golden_xlsm_path, "r") as zg:
        golden_nodes = _resolve_sheet_part(zg, nodes_sheet_name)
        if not golden_nodes:
            return False
        snippet = _extract_sync_button_snippet(zg.read(golden_nodes))
        golden_rels_path = _sheet_rels_path(golden_nodes)
        if not snippet or golden_rels_path not in zg.namelist():
            return False
        golden_rels = zg.read(golden_rels_path)
        golden_ct = zg.read("[Content_Types].xml")
        assets = {a: zg.read(a) for a in _GOLDEN_BUTTON_ASSETS if a in zg.namelist()}

    if len(assets) != len(_GOLDEN_BUTTON_ASSETS):
        return False

    with tempfile.TemporaryDirectory() as tmp:
        staging = os.path.join(tmp, "pack")
        with zipfile.ZipFile(xlsm_path, "r") as zin:
            zin.extractall(staging)

        wb_path = os.path.join(staging, "xl", "workbook.xml")
        with open(wb_path, "rb") as fh:
            wb = ET.fromstring(fh.read())
        rels_path = os.path.join(staging, "xl", "_rels", "workbook.xml.rels")
        with open(rels_path, "rb") as fh:
            rels = ET.fromstring(fh.read())
        rel_map = {el.get("Id"): el.get("Target") for el in rels.findall(f"{REL_NS}Relationship")}
        target_nodes = None
        for sh in wb.findall(f"{WB_NS}sheet"):
            if sh.get("name") != nodes_sheet_name:
                continue
            rid = sh.get(WB_REL_ATTR)
            target = rel_map.get(rid or "")
            if target:
                target_nodes = f"xl/{target}"
            break

        if not target_nodes:
            return False

        sheet_path = os.path.join(staging, target_nodes.replace("/", os.sep))
        with open(sheet_path, "rb") as fh:
            sheet_bytes = fh.read()
        with open(sheet_path, "wb") as fh:
            fh.write(_patch_sheet_xml_with_button(sheet_bytes, snippet))

        target_rels_path = os.path.join(staging, _sheet_rels_path(target_nodes).replace("/", os.sep))
        os.makedirs(os.path.dirname(target_rels_path), exist_ok=True)
        with open(target_rels_path, "wb") as fh:
            fh.write(golden_rels)

        for arc, data in assets.items():
            out = os.path.join(staging, arc.replace("/", os.sep))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as fh:
                fh.write(data)

        ct_path = os.path.join(staging, "[Content_Types].xml")
        with open(ct_path, "rb") as fh:
            ct_bytes = fh.read()
        with open(ct_path, "wb") as fh:
            fh.write(_merge_content_types_for_button(ct_bytes, golden_ct))

        os.remove(xlsm_path)
        with zipfile.ZipFile(xlsm_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for folder, _, files in os.walk(staging):
                for name in files:
                    full = os.path.join(folder, name)
                    arc = os.path.relpath(full, staging).replace("\\", "/")
                    zout.write(full, arc)

    return True
