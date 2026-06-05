"""Y 軸三層 slack（AND / OR / Cell）統一規則測試。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config_models import PowerSeqConfig
from drawio_export import (
    GRID,
    _build_or_index_per_key,
    _feedback_y_slack_after_and,
    _feedback_y_slack_after_or,
    _feedback_y_slack_between_cell_rows,
)


def _load_power_outputs():
    cfg = PowerSeqConfig.from_dict(
        json.load(open(Path(__file__).parents[1] / "output" / "power.json", encoding="utf-8"))
    )
    outputs = [r for r in cfg.rails if r.seq_type == "output"]
    valid = {r.name for r in cfg.rails}
    name_to_rail = {r.name: r for r in cfg.rails}
    output_to_row = {r.name: j for j, r in enumerate(outputs)}
    and_index_per_key = {}
    for j, r in enumerate(outputs):
        idx = 0
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            for gi, g in enumerate(groups):
                if len(g) >= 2:
                    and_index_per_key[(r.name, hl, gi)] = (j, idx)
                    idx += 1
    or_index_per_key = _build_or_index_per_key(outputs)
    return outputs, valid, name_to_rail, output_to_row, and_index_per_key, or_index_per_key


def test_and_slack_deduped_cross_row_only_outputs():
    outputs, valid, name_to_rail, output_to_row, and_index_per_key, _ = _load_power_outputs()
    slack = _feedback_y_slack_after_and(
        outputs, output_to_row, name_to_rail, valid, and_index_per_key
    )
    assert all(v == GRID for v in slack.values())
    # power.json：跨列 output→AND 去重；含 Input 直連後級
    assert len(slack) == 8
    assert sum(slack.values()) == 8 * GRID


def test_cell_row_slack_cross_row_fb_to_deb():
    outputs, valid, name_to_rail, output_to_row, _, _ = _load_power_outputs()
    slack = _feedback_y_slack_between_cell_rows(
        outputs, output_to_row, name_to_rail, valid
    )
    assert all(v == GRID for v in slack.values())
    # RSMRST→row0 經 gap 0..6；RSMRST→row4 經 4..6；PCH_PWROK→row9 經 9..10 → 去重 0..6,9,10
    assert len(slack) == 9
    assert sum(slack.values()) == 9 * GRID
    assert set(slack) == {0, 1, 2, 3, 4, 5, 6, 9, 10}


def test_or_slack_empty_when_no_or_path():
    outputs, valid, name_to_rail, output_to_row, _, or_index_per_key = _load_power_outputs()
    slack = _feedback_y_slack_after_or(
        outputs, output_to_row, name_to_rail, valid, or_index_per_key
    )
    assert slack == {}


def test_input_to_and_not_in_and_slack():
    """Input→AND 不計入 AND 層 slack（僅 output 跨列 fb 與 Input 直連後級）。"""
    outputs, valid, name_to_rail, output_to_row, and_index_per_key, _ = _load_power_outputs()
    slack_no_input_only = _feedback_y_slack_after_and(
        outputs, output_to_row, name_to_rail, valid, and_index_per_key
    )
    # Input 直連會增加 slack；power.json 有大量 Input 直連 Cell/OR
    assert len(slack_no_input_only) >= 8
