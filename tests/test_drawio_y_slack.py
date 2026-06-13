"""Y 軸三層 slack（AND / OR / Cell）統一規則測試。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config_models import PowerSeqConfig
from drawio_export import (
    AND_GATE_DY,
    GRID,
    OR_GATE_OFFSET_HI_Y,
    OR_GATE_OFFSET_LO_Y,
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
        for hl, groups in [("hi", r.get_hi_groups()), ("lo", r.get_lo_groups())]:
            base = OR_GATE_OFFSET_HI_Y if hl == "hi" else OR_GATE_OFFSET_LO_Y
            idx = 0
            for gi, g in enumerate(groups):
                if len(g) >= 2:
                    and_index_per_key[(r.name, hl, gi)] = (j, base + idx * AND_GATE_DY)
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
    # RSMRST_N row7：q+nq 皆在 gap6（僅來源列與上一列之間）；Q／~Q 不共用 → gap6 累加 80pt
    assert slack == {6: 2 * GRID, 10: GRID}
    assert sum(slack.values()) == 3 * GRID


def test_cell_row_slack_rsmrst_collects_q_and_nq_profiles():
    """RSMRST 同時有 Q→AND 與 ~Q→Deb 跨列回授，Cell slack 須合併 q／nq profile。"""
    outputs, valid, name_to_rail, output_to_row, _, _ = _load_power_outputs()
    profiles: dict[str, set[str]] = {}
    for tgt in outputs:
        tgt_row = output_to_row[tgt.name]
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                for ii, d in enumerate(group):
                    if d != "RSMRST_N":
                        continue
                    if name_to_rail[d].seq_type != "output":
                        continue
                    src_row = output_to_row.get(d)
                    if src_row is None or src_row == tgt_row:
                        continue
                    use = (
                        tgt.get_hi_use(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_use(gi, ii, d)
                    )
                    if use != "self":
                        continue
                    inv = (
                        tgt.get_hi_inv(gi, ii, d)
                        if hl == "hi"
                        else tgt.get_lo_inv(gi, ii, d)
                    )
                    profiles.setdefault(d, set()).add("nq" if inv else "q")
    assert profiles["RSMRST_N"] == {"q", "nq"}


def test_cell_row_slack_q_and_nq_do_not_share_y_channel():
    """同 Cell 的 Q／~Q ③ 段各佔一條 Y 走廊；同 gap 須累加而非覆寫。"""
    outputs, valid, name_to_rail, output_to_row, _, _ = _load_power_outputs()
    slack = _feedback_y_slack_between_cell_rows(
        outputs, output_to_row, name_to_rail, valid
    )
    assert slack[6] == 2 * GRID


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
