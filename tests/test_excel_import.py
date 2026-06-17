"""Tests for excel_import.py"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import DEFAULT_PULSE
from excel_import import load_powerseq_from_excel, parse_signal_cell
from wavedrom_sim import DEP_HIGH, DEP_LOW, InputWaveSpec, WaveDromScenario


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_XLSX = os.path.join(ROOT, "templates", "powerseq_nodes_template.xlsx")


class TestParseSignalCell:
    def test_invert_and_use_suffix(self):
        assert parse_signal_cell("!RSMRST_N") == ("RSMRST_N", True, "self")
        assert parse_signal_cell("OUT|Hi Cond") == ("OUT", False, "hi")
        assert parse_signal_cell("Low") == (DEP_LOW, False, "self")
        assert parse_signal_cell("High") == (DEP_HIGH, False, "self")


@pytest.mark.skipif(not os.path.isfile(TEMPLATE_XLSX), reason="template xlsx missing")
class TestLoadTemplate:
    def test_load_sample_workbook(self):
        cfg = load_powerseq_from_excel(TEMPLATE_XLSX)
        assert cfg.module_name == "PWRSEQ_TOP"
        assert len(cfg.rails) == 3
        assert [r.name for r in cfg.rails] == ["EKEY", "PRIM_VR_EN", "PCH_P0V85A_EN"]

        ekey = cfg.rails[0]
        assert ekey.seq_type == "input"
        assert ekey.deb_enable is True
        assert ekey.deb_cycle_hi == 2

        pch = cfg.rails[2]
        assert pch.seq_type == "output"
        hi_groups = pch.get_hi_groups()
        assert hi_groups == [["EKEY", "PRIM_VR_EN", "RSMRST_N"]]
        assert pch.depends_on_hi_inv_groups[0] == [False, False, True]
        lo_groups = pch.get_lo_groups()
        assert lo_groups == [[DEP_LOW]]

        assert cfg.pulses == ["Pulse_1us", "Pulse_2ms"]
        assert cfg.wavedrom_scenario is not None
        assert cfg.wavedrom_scenario.get("steps") == 50
        assert "inputs" not in cfg.wavedrom_scenario
        ekey = next(r for r in cfg.rails if r.name == "EKEY")
        assert ekey.hi_mode == "custom"
        assert ekey.hi_wave == "01"
        assert ekey.lo_mode == "constant_0"
        prim = next(r for r in cfg.rails if r.name == "PRIM_VR_EN")
        assert prim.hi_mode == "depends"
        assert prim.hi_groups == [["EKEY"]]

    def test_roundtrip_dict_keys(self):
        cfg = load_powerseq_from_excel(TEMPLATE_XLSX)
        d = cfg.to_dict()
        assert "rails" in d
        assert d["rails"][2]["depends_on_hi_groups"] == [["EKEY", "PRIM_VR_EN", "RSMRST_N"]]
        assert cfg.rails[2].pulse_hi == "Pulse_2ms"


X15DOT_XLSM = os.path.join(ROOT, "templates", "x15dot.xlsm")


class TestLastUsedRow:
    def test_scan_finds_last_row_beyond_template_floor(self):
        from openpyxl import Workbook

        from excel_import import DATA_START_ROW, last_used_row

        wb = Workbook()
        ws = wb.active
        ws.cell(DATA_START_ROW, 1, value="FIRST")
        ws.cell(350, 1, value="LAST")
        assert last_used_row(ws, min_row=DATA_START_ROW, max_col=5) == 350

    def test_scan_empty_returns_below_start(self):
        from openpyxl import Workbook

        from excel_import import DATA_START_ROW, last_used_row

        wb = Workbook()
        ws = wb.active
        assert last_used_row(ws, min_row=DATA_START_ROW, max_col=5) == DATA_START_ROW - 1


@pytest.mark.skipif(not os.path.isfile(X15DOT_XLSM), reason="x15dot.xlsm missing")
class TestLoadX15Dot:
    def test_late_output_conditions_loaded(self):
        """Output Conditions 超過 row 200 的訊號仍應載入 Hi/Lo（x15dot row 202+）。"""
        cfg = load_powerseq_from_excel(X15DOT_XLSM)
        rail = next(r for r in cfg.rails if r.name == "M_NP_CPU1_FPGA_RESET_N_OD")
        assert rail.get_hi_groups() == [
            ["CPU1_DDR_NP_RST_N", "PLD_CPU1_MEM_NP_PWRGD_OD"]
        ]
        assert rail.get_lo_groups() == [["CPU1_DDR_NP_RST_N"]]
        assert rail.depends_on_lo_inv_groups[0] == [True]
