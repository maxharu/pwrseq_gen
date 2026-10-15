"""程式碼產生：Verilog / C。

對外介面只有這兩支；其餘符號是實作細節，由 `tests/test_package_api.py` 把關。
"""
from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog

__all__ = ["generate_c", "generate_verilog"]
