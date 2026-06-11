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
