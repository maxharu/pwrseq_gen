"""識別子命名：Verilog / C / 內部訊號共用。"""
from __future__ import annotations


def safe_name(name: str) -> str:
    """將名稱轉為合法識別子（. - 空白 → _）。"""
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


def internal_sig(name: str) -> str:
    """內部訊號名稱：全小寫，供 wire / assign / C member 使用。"""
    return safe_name(name).lower()
