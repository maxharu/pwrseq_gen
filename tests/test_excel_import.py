"""Tests for excel_import.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from excel_import import parse_signal_cell
from wavedrom_sim import DEP_HIGH, DEP_LOW


class TestParseSignalCell:
    def test_invert_and_use_suffix(self):
        assert parse_signal_cell("!RSMRST_N") == ("RSMRST_N", True, "self")
        assert parse_signal_cell("OUT|Hi Cond") == ("OUT", False, "hi")
        assert parse_signal_cell("Low") == (DEP_LOW, False, "self")
        assert parse_signal_cell("High") == (DEP_HIGH, False, "self")


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
