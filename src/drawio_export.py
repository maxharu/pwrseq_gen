"""Draw.io export entry point (cell-centric grid)."""
from __future__ import annotations

from config_models import PowerSeqConfig
from drawio_export_options import DrawioExportOptions
from drawio_geometry import (  # noqa: F401 — re-export for callers
    AND_GATE_H,
    AND_GATE_W,
    CELL_GROUP_H,
    CELL_GROUP_W,
    CELL_H_DEB_H,
    CELL_H_DEB_W,
    CELL_H_DEB_Y,
    CELL_INNER_H,
    CELL_INNER_W,
    CELL_L_DEB_H,
    CELL_L_DEB_W,
    CELL_L_DEB_Y,
    CELL_O_H,
    CELL_O_W,
    CELL_O_X,
    CELL_O_Y,
    CONST_DEPS,
    GAP,
    GRID,
    INPUT_LABEL_H,
    OR_GATE_H,
    OR_GATE_W,
    STROKE_DEFAULT,
    STROKE_HI,
    STROKE_LO,
    _PSEQCELL_STYLE_H_DEB,
    _PSEQCELL_STYLE_INNER,
    _PSEQCELL_STYLE_L_DEB,
    _PSEQCELL_STYLE_O,
    _and_gate_style,
    _deb_port_label,
    _escape_xml,
    _or_gate_style,
)


def generate_drawio(
    config: PowerSeqConfig,
    *,
    options: DrawioExportOptions | None = None,
) -> str:
    """Generate cell-centric Draw.io XML (single-page grid)."""
    from drawio_cell_export import generate_drawio as _generate

    return _generate(config, options=options)
