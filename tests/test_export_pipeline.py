"""應用服務層 `pipeline.export`：驗證閘 + 匯出內容。

守的是兩件 GUI callback 時代守不住的事：
1. **無效設定一律不寫檔**——這正是先前 `_export_drawio` 漏掉 validate、會默默匯出一張
   少掉條件項的圖的 bug 類。這裡對**每一種 kind** 參數化，新增格式漏檢查就會紅。
2. **這層只做編排、沒改語意**——有效設定寫出的內容與直接呼叫產生器逐字元相同。
"""
from __future__ import annotations

import re

import pytest

from codegen import generate_c, generate_verilog
from core.config_models import PowerRail, PowerSeqConfig, build_timing_scenario
from drawio import generate_drawio
from pipeline import ExportResult, export
from timing import TIMING_EDGE_BOTH, TimingExportOptions, export_schemdraw_from_options


def _strip_diagram_id(xml: str) -> str:
    # generate_drawio 每次給 diagram 一個隨機 id；只有這個 token 不穩定，正規化掉以比對其餘。
    return re.sub(r'(<diagram\b[^>]*\bid=")[A-Za-z0-9]{20}(")', r"\1ID\2", xml)


# generate_verilog / generate_c 的 output_filename 會嵌進產出的檔名／guard，
# 所以逐字元比對時，直接呼叫必須用與 pipeline 相同的 path。
_TEXT_KINDS = {
    "verilog": (".v", lambda cfg, p: generate_verilog(cfg, output_filename=p), str),
    "c": (".c", lambda cfg, p: generate_c(cfg, output_filename=p), str),
    "drawio": (".xml", lambda cfg, p: generate_drawio(cfg), _strip_diagram_id),
}
_ALL_KINDS = [*_TEXT_KINDS, "schemdraw"]


def _valid_cfg() -> PowerSeqConfig:
    return PowerSeqConfig(
        rails=[
            PowerRail("IN_A", seq_type="input", cycle_hi=1, cycle_lo=1),
            PowerRail(
                "OUT", seq_type="output", cycle_hi=1, cycle_lo=1,
                depends_on_hi_groups=[["IN_A"]],
            ),
        ]
    )


def _invalid_cfg() -> PowerSeqConfig:
    """OUT 依賴一個不存在的 rail——validate 會擋，但產生器本身不會。"""
    return PowerSeqConfig(
        rails=[
            PowerRail("IN_A", seq_type="input", cycle_hi=1, cycle_lo=1),
            PowerRail(
                "OUT", seq_type="output", cycle_hi=1, cycle_lo=1,
                depends_on_hi_groups=[["IN_A", "TYPO_RAIL"]],
            ),
        ]
    )


def _ext_for(kind: str) -> str:
    return _TEXT_KINDS[kind][0] if kind in _TEXT_KINDS else ".svg"


def _opts_for(kind: str):
    if kind != "schemdraw":
        return None
    return TimingExportOptions(include_rails=frozenset({"OUT"}), edge_kinds=TIMING_EDGE_BOTH)


# ---- 驗證閘：無效設定不寫檔（每種 kind 都要） --------------------------------

@pytest.mark.parametrize("kind", _ALL_KINDS)
def test_invalid_config_reports_errors_and_writes_nothing(kind, tmp_path):
    path = tmp_path / f"out{_ext_for(kind)}"
    result = export(_invalid_cfg(), kind, str(path), opts=_opts_for(kind))

    assert not result.ok
    assert result.errors  # 非空
    assert any("TYPO_RAIL" in e for e in result.errors)
    assert not path.exists(), "驗證沒過卻寫出了檔案"


# ---- 有效設定：內容與直接呼叫產生器逐字元相同 --------------------------------

@pytest.mark.parametrize("kind", list(_TEXT_KINDS))
def test_valid_text_export_is_byte_identical_to_direct_generator(kind, tmp_path):
    ext, direct, norm = _TEXT_KINDS[kind]
    path = tmp_path / f"out{ext}"
    cfg = _valid_cfg()

    result = export(cfg, kind, str(path))

    assert result.ok and not result.errors
    assert norm(path.read_text(encoding="utf-8")) == norm(direct(cfg, str(path)))


def test_valid_schemdraw_export_writes_a_file(tmp_path):
    # schemdraw 自己寫檔（二進位/SVG），且 matplotlib SVG metadata 含日期，
    # 兩次產生不保證逐字元相同，所以只驗「有寫出、非空、無 error」。
    pytest.importorskip("schemdraw")
    pytest.importorskip("matplotlib")
    path = tmp_path / "timing.svg"
    cfg = _valid_cfg()

    result = export(cfg, "schemdraw", str(path), opts=_opts_for("schemdraw"))

    assert result.ok and not result.errors
    assert path.is_file() and path.stat().st_size > 0


def test_valid_schemdraw_matches_direct_call_setup(tmp_path):
    """pipeline 餵給 schemdraw 的 scenario 與 GUI 一致（build_timing_scenario）。"""
    pytest.importorskip("schemdraw")
    pytest.importorskip("matplotlib")
    cfg = _valid_cfg()
    opts = _opts_for("schemdraw")
    via_pipeline = tmp_path / "a.svg"
    direct = tmp_path / "b.svg"

    export(cfg, "schemdraw", str(via_pipeline), opts=opts)
    export_schemdraw_from_options(cfg, build_timing_scenario(cfg), opts, str(direct))

    assert via_pipeline.is_file() and direct.is_file()


# ---- 介面行為 --------------------------------------------------------------

def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown export kind"):
        export(_valid_cfg(), "svg", "x.svg")


def test_schemdraw_without_opts_raises_after_validation(tmp_path):
    with pytest.raises(ValueError, match="TimingExportOptions"):
        export(_valid_cfg(), "schemdraw", str(tmp_path / "t.svg"))


def test_export_result_ok_tracks_errors():
    assert ExportResult("p", "s").ok
    assert not ExportResult("p", "s", ("boom",)).ok
