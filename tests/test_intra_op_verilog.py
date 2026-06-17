"""Verilog codegen with group intra-op AND/OR/XOR."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerRail, PowerSeqConfig
from verilog_generator import generate_verilog


def test_lo_xor_group_in_verilog():
    cfg = PowerSeqConfig(
        rails=[
            PowerRail("A", seq_type="input"),
            PowerRail(
                "OUT",
                seq_type="output",
                depends_on_lo_groups=[["A", "__HIGH__"]],
                depends_on_lo_intra_op=["xor"],
            ),
        ],
    )
    out = generate_verilog(cfg)
    assert "assign out_lo = (a_deb ^ 1'b1);" in out


def test_lo_or_group_in_verilog_uses_pipe():
    cfg = PowerSeqConfig(
        rails=[
            PowerRail("A", seq_type="input", deb_enable=False),
            PowerRail("B", seq_type="input", deb_enable=False),
            PowerRail(
                "OUT",
                seq_type="output",
                depends_on_lo_groups=[["A", "B"]],
                depends_on_lo_intra_op=["or"],
            ),
        ],
    )
    out = generate_verilog(cfg)
    assert "assign out_lo = (iA | iB);" in out
    assert "||" not in out.split("assign out_lo")[1].split(";")[0]
