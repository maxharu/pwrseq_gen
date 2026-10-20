"""識別子命名：Verilog / C / 內部訊號共用。"""
from __future__ import annotations


def safe_name(name: str) -> str:
    """將名稱轉為合法識別子（. - 空白 → _；vector 的 [i] → _i）。

    vector bit 的 canonical 名是 base[i]（如 FOO[2]），產生 Verilog/C 識別子時要去掉中括號：
    `[` → `_`、`]` 去除，故 FOO[2] → FOO_2。展開後的撞名（FOO[2] 與字面 FOO_2）由 validator 擋。
    """
    return (
        name.replace(".", "_").replace("-", "_").replace(" ", "_")
        .replace("[", "_").replace("]", "")
    )


def internal_sig(name: str) -> str:
    """內部訊號名稱：全小寫，供 wire / assign / C member 使用。"""
    return safe_name(name).lower()
