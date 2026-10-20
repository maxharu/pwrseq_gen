"""C11 parameter GUI 接線測試（需顯示；無顯示則 skip）。

只驗接線：
  1. ParameterPanel 模型層：新增 / 刪除 / 去重 / 無效值。
  2. RailEditorFrame width 公式保留與 N 展開（經 get_parameters）。
  3. 插入 parameter 下拉把名稱插進 width 欄位。
  4. parameter 值變更 → 重算展開 N。

語意正確性由 core 層測試保證。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import Parameter, PowerRail


def _vector_rails(width_expr: str, n: int) -> list[PowerRail]:
    return [
        PowerRail(f"V[{i}]", seq_type="output", group_base="V", bit_index=i, width_expr=width_expr)
        for i in range(n)
    ]


class TestParameterPanel:
    def _panel(self, ctk_root, captured):
        from gui.panels import ParameterPanel
        return ParameterPanel(ctk_root, on_change=lambda ps: captured.append(ps))

    def test_add_parameter(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel.entry_name.insert(0, "NUM_CPU")
            panel.entry_value.insert(0, "2")
            panel._on_add()
            assert captured
            assert [(p.name, p.value) for p in captured[-1]] == [("NUM_CPU", 2)]
        finally:
            panel.destroy()

    def test_duplicate_name_rejected(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel.set_parameters([Parameter("NUM_CPU", 2)])
            panel.entry_name.insert(0, "NUM_CPU")
            panel.entry_value.insert(0, "3")
            _param, err = panel._parse_new()
            assert err is not None
        finally:
            panel.destroy()

    def test_invalid_value_rejected(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel.entry_name.insert(0, "X")
            panel.entry_value.insert(0, "abc")
            _param, err = panel._parse_new()
            assert err is not None
        finally:
            panel.destroy()

    def test_delete_parameter(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel.set_parameters([Parameter("A", 1), Parameter("B", 2)])
            panel._on_row_press(0)
            panel._on_del()
            assert captured
            assert [p.name for p in captured[-1]] == ["B"]
        finally:
            panel.destroy()


class TestRailEditorWidthFormula:
    def test_width_formula_preserves_and_expands(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2)]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("NUM_CPU*2", 4),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params,
        )
        try:
            rails = ed.get_rails()
            assert len(rails) == 4  # NUM_CPU*2 = 4
            assert all(r.width_expr == "NUM_CPU*2" for r in rails)
            assert [r.name for r in rails] == ["V[0]", "V[1]", "V[2]", "V[3]"]
        finally:
            ed.destroy()

    def test_insert_parameter_into_width(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2)]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("1", 1),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params,
        )
        try:
            ed.entry_width.delete(0, "end")
            ed._on_insert_param("NUM_CPU")
            assert "NUM_CPU" in ed.entry_width.get()
            rails = ed.get_rails()
            assert len(rails) == 2  # NUM_CPU = 2
            assert all(r.width_expr == "NUM_CPU" for r in rails)
        finally:
            ed.destroy()

    def test_param_value_change_reexpands(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2)]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("NUM_CPU*2", 4),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params,
        )
        try:
            assert len(ed.get_rails()) == 4
            params[0] = Parameter("NUM_CPU", 3)
            assert len(ed.get_rails()) == 6  # NUM_CPU*2 = 6
        finally:
            ed.destroy()
