"""B7 Excel vector 收合/展開 round-trip 測試。

守住兩件事：
  1. 含 vector 的 config 經 Excel export→import round-trip 後，群組 metadata（group_base/
     bit_index/width_expr）與逐 bit 條件保留；Nodes sheet 收合成一列（Width 欄），Conditions
     以 bit 名（base[i]）引用。
  2. core 的 rail→node 切分 group_rails_into_nodes 正確（scalar 自成一節點、連續 bit 收合）。

無 vector 的黃金 excel round-trip 不變由 tests/test_golden_exports.py 把關。
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_edit import group_rails_into_nodes
from core.config_models import ConditionConfig, PowerRail, PowerSeqConfig, VectorNode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES = (
    "powerseq_nodes_template.xlsx",
    "powerseq_nodes_template_new.xlsm",
    "powerseq_nodes_template_fixed.xlsm",
    "powerseq_nodes_template.xlsm",
)
HAS_TEMPLATE = any(os.path.isfile(os.path.join(ROOT, "templates", n)) for n in _TEMPLATES)


class TestGroupRailsIntoNodes:
    def test_scalar_and_vector_split(self):
        en = PowerRail("EN", seq_type="input")
        vout = VectorNode("VOUT", "output", "2", [ConditionConfig(), ConditionConfig()]).elaborate()
        nodes = group_rails_into_nodes([en] + vout)
        assert [len(n) for n in nodes] == [1, 2]
        assert nodes[0][0].name == "EN"
        assert [r.name for r in nodes[1]] == ["VOUT[0]", "VOUT[1]"]


def _vector_config() -> PowerSeqConfig:
    en = PowerRail("EN", seq_type="input", deb_enable=False)
    vout = VectorNode(
        base="VOUT",
        seq_type="output",
        width_expr="2",
        bit_conds=[
            ConditionConfig(depends_on_hi_groups=[["EN"]]),
            ConditionConfig(depends_on_lo_groups=[["EN"]]),
        ],
    )
    return PowerSeqConfig(module_name="VEC", pulses=["Pulse_1us"], rails=[en] + vout.elaborate())


@pytest.mark.skipif(not HAS_TEMPLATE, reason="excel template missing")
class TestExcelVectorRoundTrip:
    def test_round_trip_preserves_vector(self):
        pytest.importorskip("openpyxl")
        from excel.excel_export import export_powerseq_to_excel
        from excel.excel_import import load_powerseq_from_excel

        cfg = _vector_config()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            out = f.name
        try:
            export_powerseq_to_excel(cfg, out)
            cfg2 = load_powerseq_from_excel(out)
        finally:
            os.unlink(out)

        # 展開回扁平 rails：EN + VOUT[0] + VOUT[1]
        assert [r.name for r in cfg2.rails] == ["EN", "VOUT[0]", "VOUT[1]"]
        vout = [r for r in cfg2.rails if r.group_base == "VOUT"]
        assert [r.bit_index for r in vout] == [0, 1]
        assert all(r.width_expr == "2" for r in vout)
        # 逐 bit 條件以 bit 名引用、各自獨立
        assert vout[0].get_hi_groups() == [["EN"]]
        assert vout[1].get_lo_groups() == [["EN"]]

    def test_nodes_sheet_collapses_vector_to_one_row(self):
        pytest.importorskip("openpyxl")
        from openpyxl import load_workbook

        from excel.excel_export import export_powerseq_to_excel

        cfg = _vector_config()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            out = f.name
        try:
            export_powerseq_to_excel(cfg, out)
            ws = load_workbook(out)["Nodes"]
            # 資料列：EN（col1）、VOUT（收合成一列，Width 欄=2）
            names = [ws.cell(4 + i, 1).value for i in range(2)]
            assert names == ["EN", "VOUT"]
            # Width 欄為第 11 欄
            assert str(ws.cell(5, 11).value) == "2"
        finally:
            os.unlink(out)
