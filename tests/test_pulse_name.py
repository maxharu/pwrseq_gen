"""四套 pulse 名稱解析器的一致性：同一個名稱在 Verilog / C / 模擬器 / Draw.io 眼中的解讀。

`drawio_geometry` 原本自己重刻了 `iPulse_`/`Pulse_` 去前綴、沒走 `normalize_pulse_name`，
因此含 `.` / `-` / 空白的名稱會「Verilog 認得、Draw.io 認不得」——debounce 標籤直接變成
`0s`。模擬器那套則有另一個不對稱：`Pulse_xus` 解不出數字時退回 1，`Pulse_xms` 卻退回 1000。

四套現在都走 `core.config_models` 的 `pulse_suffix` / `parse_pulse_period`。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest

from codegen.c_generator import _pulse_time_field
from core.config_models import (
    normalize_pulse_name,
    parse_pulse_period,
    pulse_suffix,
    pulse_verilog_name,
)
from drawio.drawio_geometry import _deb_time_text
from timing.timing_sim import _pulse_scale_units


def _views(name: str) -> dict:
    """同一個 pulse 名稱在四個後端眼中的樣子。"""
    return {
        "verilog": pulse_verilog_name(name),
        "c_field": _pulse_time_field(name),
        "scale": _pulse_scale_units(name),
        "deb_3": _deb_time_text(3, name),
    }


# 正規化後指向同一個 pulse 的別名寫法
ALIASES = [
    ("Pulse_1us", "iPulse_1us"),
    ("Pulse_1us", "Pulse-1us"),
    ("Pulse_1us", "Pulse 1us"),
    ("Pulse_2ms", "iPulse-2ms"),
    ("Pulse_2ms", "Pulse.2ms"),
]


@pytest.mark.parametrize("canonical,alias", ALIASES)
def test_aliases_are_read_the_same_by_every_backend(canonical, alias):
    assert normalize_pulse_name(alias) == canonical
    assert _views(alias) == _views(canonical)


@pytest.mark.parametrize("name,period,unit,scale,field", [
    ("Pulse_1us", 1, "us", 1, "t_1us"),
    ("Pulse_32us", 32, "us", 32, "t_32us"),
    ("Pulse_1ms", 1, "ms", 1000, "t_1ms"),
    ("Pulse_100ms", 100, "ms", 100000, "t_100ms"),
])
def test_canonical_names_parse_consistently(name, period, unit, scale, field):
    assert parse_pulse_period(name) == (period, unit)
    assert _pulse_scale_units(name) == scale
    assert _pulse_time_field(name) == field
    assert _deb_time_text(3, name) == f"{3 * period}{unit}"


@pytest.mark.parametrize("name", ["High", "default", ""])
def test_names_meaning_no_pulse_gating_have_no_period(name):
    assert pulse_suffix(name) is None
    assert parse_pulse_period(name) is None
    assert _pulse_time_field(name) is None
    assert _pulse_scale_units(name) == 1
    assert _deb_time_text(3, name) == "0s"


@pytest.mark.parametrize("name", ["Pulse_xus", "Pulse_xms", "Pulse_us", "My.Pulse_1us"])
def test_unparseable_period_degrades_the_same_way_for_every_unit(name):
    """解不出數字時一律當成「沒有週期」，不因為結尾是 us 還是 ms 而不同。"""
    assert parse_pulse_period(name) is None
    assert _pulse_scale_units(name) == 1
    assert _deb_time_text(3, name) == "0s"


def test_c_still_names_a_time_field_for_an_unparseable_name():
    """C 的 time 欄位名直接取自名稱（值由使用者填），所以不需要解得出週期。"""
    assert _pulse_time_field("My.Pulse_1us") == "t_My_Pulse_1us"
    assert pulse_verilog_name("My.Pulse_1us") == "iMy_Pulse_1us"
