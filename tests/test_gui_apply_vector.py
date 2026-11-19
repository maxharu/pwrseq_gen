"""Regression：新增 scalar 節點後於編輯器轉 vector 並 Apply，不得產生幻影 bit。

Bug：`_apply_node` 先依「apply 前的 scalar config」算出 rail span，接著 `_push_undo()`
內部的 `_collect_config()` 會把 `config.rails` 覆寫成「編輯器已 vector 化」的多條，使 span
過期，slice 殘留一條重複 bit → 左欄 marker 顯示 [×3]（實際只有 2 bit），需再按一次 Apply
才修正。這裡鎖住：單次 Apply 後 config 無重複、左欄 marker 正確。

需要顯示；headless 無 Tk 則 skip（與其他 GUI 測試一致）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("customtkinter")

from core.config_models import Parameter


def _make_app(dim_value: int):
    from gui.app import PowerSeqGUI
    try:
        app = PowerSeqGUI()
    except Exception as e:
        pytest.skip(f"CustomTkinter/display unavailable: {e}")
    app.withdraw()
    # 宣告一個全域維度 NUM_CPU（最大值＝dim_value），供編輯器的維度下拉把節點轉成 1 維 vector。
    app.config_obj.parameters = [Parameter("NUM_CPU", dim_value)]
    app.config_obj.dimensions = ["NUM_CPU"]
    return app


def _vectorize_editor(ed) -> None:
    """用維度模型把節點轉成 1 維 vector（寬度＝NUM_CPU），刻意不觸發任何 _collect_config。"""
    ed.var_dim_count.set("1")
    ed._render_dim_bits()
    ed._dim_menus[0].set("NUM_CPU")


class TestApplyNewVectorNoPhantomBit:
    def test_single_apply_width2_no_duplicate(self):
        app = _make_app(2)
        try:
            app._add_rail()  # scalar（config 僅一條，尚未有任何 vector 展開）
            cf = app.collapsible_frames[-1]
            base = cf.base_name()
            # 前置條件：apply 前 config 仍是單一 scalar（模擬快速操作、preview 尚未觸發）
            assert len(app.config_obj.rails) == 1

            _vectorize_editor(cf.editor)
            app._apply_node(len(app.collapsible_frames) - 1)

            names = [r.name for r in app.config_obj.rails]
            assert names == [f"{base}[0]", f"{base}[1]"], names
            assert len(names) == len(set(names)), f"duplicate bit: {names}"
            # 左欄 marker 必須是 [×2]（bug 會是 [×3]）
            assert app.node_list.node_labels() == [f"{base} [\u00d72]"], app.node_list.node_labels()
        finally:
            app.destroy()

    def test_single_apply_width3_no_duplicate(self):
        app = _make_app(3)
        try:
            app._add_rail()
            cf = app.collapsible_frames[-1]
            base = cf.base_name()
            assert len(app.config_obj.rails) == 1

            _vectorize_editor(cf.editor)
            app._apply_node(len(app.collapsible_frames) - 1)

            names = [r.name for r in app.config_obj.rails]
            assert names == [f"{base}[0]", f"{base}[1]", f"{base}[2]"], names
            assert len(names) == len(set(names)), f"duplicate bit: {names}"
            assert app.node_list.node_labels() == [f"{base} [\u00d73]"], app.node_list.node_labels()
        finally:
            app.destroy()
