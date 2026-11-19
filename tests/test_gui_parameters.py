"""parameter / 維度 GUI 接線測試（需顯示；無顯示則 skip）。

只驗接線：
  1. ParameterPanel（dims-only）：選維度個數即長出 N 列名稱＋最大值，on_change 回 (params, dims)；
     名稱空白/最大值非正整數沿用舊值；set_from_config 載入。
  2. RailEditorFrame 維度宣告：0/1/2 維 → width_expr 與 dim_params（經 get_parameters/get_dimensions）。

語意正確性由 core 層測試保證。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import Parameter, PowerRail


def _vector_rails(width_expr: str, n: int, dims: list[str] | None = None) -> list[PowerRail]:
    return [
        PowerRail(
            f"V[{i}]", seq_type="output", group_base="V", bit_index=i,
            width_expr=width_expr, dim_params=list(dims or []),
        )
        for i in range(n)
    ]


class TestParameterPanel:
    """維度即 parameter（dims-only）：選維度個數即長出 N 列名稱＋最大值，on_change 回 (params, dims)。"""

    def _panel(self, ctk_root, captured):
        from gui.panels import ParameterPanel
        return ParameterPanel(
            ctk_root, on_change=lambda ps, ds: captured.append((ps, ds)))

    def test_pick_count_creates_default_dims(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("2")
            params, dims = captured[-1]
            assert dims == ["P1", "P2"]
            assert [(p.name, p.value) for p in params] == [("P1", 2), ("P2", 2)]
        finally:
            panel.destroy()

    def test_edit_name_and_max(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("1")
            panel._name_entries[0].delete(0, "end")
            panel._name_entries[0].insert(0, "NUM_CPU")
            panel._val_entries[0].delete(0, "end")
            panel._val_entries[0].insert(0, "4")
            panel._commit_rows()
            params, dims = captured[-1]
            assert dims == ["NUM_CPU"]
            assert [(p.name, p.value) for p in params] == [("NUM_CPU", 4)]
        finally:
            panel.destroy()

    def test_reduce_count_drops_dim(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("2")
            panel._on_dim_count("1")
            _params, dims = captured[-1]
            assert dims == ["P1"]
        finally:
            panel.destroy()

    def test_count_zero_empties(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("1")
            panel._on_dim_count("0")
            params, dims = captured[-1]
            assert dims == []
            assert params == []
        finally:
            panel.destroy()

    def test_empty_name_keeps_prior(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("1")
            panel._name_entries[0].delete(0, "end")  # 清空名稱
            panel._commit_rows()
            assert panel._params[0].name == "P1"  # 沿用舊名，不會變空
        finally:
            panel.destroy()

    def test_invalid_max_keeps_prior(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel._on_dim_count("1")
            panel._val_entries[0].delete(0, "end")
            panel._val_entries[0].insert(0, "abc")
            panel._commit_rows()
            assert panel._params[0].value == 2  # 非正整數沿用舊值
        finally:
            panel.destroy()

    def test_set_from_config_loads(self, ctk_root):
        captured: list = []
        panel = self._panel(ctk_root, captured)
        try:
            panel.set_from_config(
                [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)],
                ["NUM_CPU", "NUM_CPU_MEM"])
            assert panel.opt_dim_count.get() == "2"
            assert panel._dimensions() == ["NUM_CPU", "NUM_CPU_MEM"]
            assert len(panel._name_entries) == 2
        finally:
            panel.destroy()


class TestRailEditorDimensions:
    def test_two_dim_signal_expands_and_stores_dims(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)]
        dims = ["NUM_CPU", "NUM_CPU_MEM"]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("NUM_CPU*NUM_CPU_MEM", 16, dims),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params, get_dimensions=lambda: dims,
        )
        try:
            rails = ed.get_rails()
            assert len(rails) == 16  # 2 * 8
            assert all(r.width_expr == "NUM_CPU*NUM_CPU_MEM" for r in rails)
            assert all(r.dim_params == dims for r in rails)
        finally:
            ed.destroy()

    def test_change_dim_count_rewidths(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)]
        dims = ["NUM_CPU", "NUM_CPU_MEM"]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("NUM_CPU", 2, ["NUM_CPU"]),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params, get_dimensions=lambda: dims,
        )
        try:
            assert len(ed.get_rails()) == 2  # 1D: NUM_CPU = 2
            ed.var_dim_count.set("2")
            ed._on_dim_count_changed("2")
            rails = ed.get_rails()
            assert len(rails) == 16  # 2D: NUM_CPU * NUM_CPU_MEM = 16
            assert all(r.width_expr == "NUM_CPU*NUM_CPU_MEM" for r in rails)
        finally:
            ed.destroy()

    def test_zero_dim_is_scalar(self, ctk_root):
        from gui.widgets import RailEditorFrame

        params = [Parameter("NUM_CPU", 2)]
        ed = RailEditorFrame(
            ctk_root, _vector_rails("NUM_CPU", 2, ["NUM_CPU"]),
            get_all_rails=lambda: [], get_pulses=lambda: ["PSEQ"],
            get_parameters=lambda: params, get_dimensions=lambda: ["NUM_CPU"],
        )
        try:
            ed.var_dim_count.set("0")
            ed._on_dim_count_changed("0")
            rails = ed.get_rails()
            assert len(rails) == 1
            assert rails[0].group_base is None
            assert rails[0].dim_params == []
        finally:
            ed.destroy()
