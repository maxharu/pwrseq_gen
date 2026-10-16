"""匯出的應用服務層：驗證 → 產生 → 寫檔，一個不綁 Tk 的呼叫點。

把這段從 GUI callback 抽出來，**不是**因為 `app.py` 太大，而是為了讓「前置檢查的一致性」
變成可測的。抽出來以前，每種格式各自在自己的 Tk method 裡決定要不要先 `validate`——結果
Draw.io 漏了，一份 `depends_on` 打錯字的設定會默默匯出一張少掉該條件項的圖（`_DrawioCond`
會把不在 valid 集合裡的項丟掉），不當掉也不報錯。

集中在這裡之後，validate 是唯一且無法繞過的閘：任何 `kind` 的無效設定都不會寫出檔案，
而「新增格式漏掉檢查」不再是沒人看得到的事，而是 `tests/test_export_pipeline.py` 會紅。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from codegen import generate_c, generate_verilog
from core.config_models import PowerSeqConfig, build_timing_scenario
from core.validator import validate
from drawio import generate_drawio
from timing import (
    TIMING_EDGE_HI_ONLY,
    TIMING_EDGE_LO_ONLY,
    TimingExportOptions,
    export_schemdraw_from_options,
)


@dataclass(frozen=True)
class ExportResult:
    """一次匯出的結果。`errors` 非空代表驗證沒過、**沒有寫出任何檔案**。"""

    path: str
    summary: str
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _export_verilog(cfg: PowerSeqConfig, path: str, opts) -> str:
    _write_text(path, generate_verilog(cfg, output_filename=path))
    return f"Generated Verilog: {os.path.basename(path)}"


def _export_c(cfg: PowerSeqConfig, path: str, opts) -> str:
    _write_text(path, generate_c(cfg, output_filename=path))
    return f"Generated C: {os.path.basename(path)}"


def _export_drawio(cfg: PowerSeqConfig, path: str, opts) -> str:
    _write_text(path, generate_drawio(cfg))
    return f"Exported: {os.path.basename(path)}"


def _edge_label(edge_kinds: str) -> str:
    if edge_kinds == TIMING_EDGE_HI_ONLY:
        return "Hi arrows"
    if edge_kinds == TIMING_EDGE_LO_ONLY:
        return "Lo arrows"
    return "Hi+Lo arrows"


def _export_schemdraw(cfg: PowerSeqConfig, path: str, opts: TimingExportOptions | None) -> str:
    if opts is None:
        raise ValueError("schemdraw export 需要 opts (TimingExportOptions)")
    scenario = build_timing_scenario(cfg)
    export_schemdraw_from_options(cfg, scenario, opts, path)
    n = len(opts.include_rails)
    return (
        f"Exported Schemdraw ({n} lanes, {_edge_label(opts.edge_kinds)}): "
        f"{os.path.basename(path)}"
    )


# kind -> writer(cfg, path, opts) -> summary；只有 schemdraw 會用到 opts
_WRITERS: dict[str, Callable[[PowerSeqConfig, str, object], str]] = {
    "verilog": _export_verilog,
    "c": _export_c,
    "drawio": _export_drawio,
    "schemdraw": _export_schemdraw,
}


def export(
    cfg: PowerSeqConfig,
    kind: str,
    path: str,
    *,
    opts: TimingExportOptions | None = None,
) -> ExportResult:
    """驗證設定後，依 `kind` 產生並寫檔。

    驗證沒過時回傳帶 `errors` 的結果且**不寫檔**。產生過程的例外（I/O、schemdraw 未安裝等）
    不在這裡吞——讓呼叫端決定怎麼呈現。`opts` 只有 `kind="schemdraw"` 會用到。
    """
    writer = _WRITERS.get(kind)
    if writer is None:
        raise ValueError(f"unknown export kind: {kind!r}")

    ok, errs = validate(cfg)
    if not ok:
        return ExportResult(
            path,
            f"{len(errs)} validation error(s); nothing written",
            tuple(errs),
        )

    summary = writer(cfg, path, opts)
    return ExportResult(path, summary)
