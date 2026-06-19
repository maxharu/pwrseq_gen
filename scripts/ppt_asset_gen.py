"""Generate PNG/SVG assets for PowerSeqGen intro deck from project outputs."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASSETS = ROOT / "doc" / "ppt_assets"
DOC = ROOT / "doc"

sys.path.insert(0, str(SRC))

from config_models import PowerSeqConfig  # noqa: E402
from c_generator import generate_c  # noqa: E402
from drawio_export import generate_drawio  # noqa: E402
from schemdraw_export import export_schemdraw  # noqa: E402
from verilog_generator import generate_verilog  # noqa: E402
from wavedrom_sim import default_scenario_for_config  # noqa: E402

# Theme (matches deck)
BG = "#0F172A"
PANEL = "#1E293B"
BOX = "#334155"
ACCENT = "#38BDF8"
ACCENT2 = "#34D399"
TEXT = "#F8FAFC"
MUTED = "#94A3B8"
WIRE = "#64748B"


def _ensure_dir() -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    return ASSETS


def _save_fig(fig: plt.Figure, path: Path, dpi: int = 140) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return path


def _html_val(raw: str) -> str:
    return unescape(raw or "").replace("<br>", "\n")


def drawio_to_png(xml_path: Path, out_path: Path, *, dpi: int = 120) -> Path:
    tree = ET.parse(xml_path)
    cells: dict[str, tuple[float, float, float, float, str, str]] = {}
    edges: list[tuple[str, str]] = []

    for cell in tree.iter("mxCell"):
        cid = cell.get("id")
        if not cid:
            continue
        if cell.get("vertex") == "1":
            geo = cell.find("mxGeometry")
            if geo is None:
                continue
            w = float(geo.get("width") or 0)
            h = float(geo.get("height") or 0)
            if w <= 0 or h <= 0:
                continue
            x = float(geo.get("x") or 0)
            y = float(geo.get("y") or 0)
            val = _html_val(cell.get("value") or "")
            cells[cid] = (x, y, w, h, val, cell.get("style") or "")
        elif cell.get("edge") == "1":
            src, tgt = cell.get("source"), cell.get("target")
            if src and tgt and src in cells and tgt in cells:
                edges.append((src, tgt))

    if not cells:
        raise ValueError(f"No drawable cells in {xml_path}")

    xs = [c[0] for c in cells.values()] + [c[0] + c[2] for c in cells.values()]
    ys = [c[1] for c in cells.values()] + [c[1] + c[3] for c in cells.values()]
    pad = 50
    xmin, xmax = min(xs) - pad, max(xs) + pad
    ymin, ymax = min(ys) - pad, max(ys) + pad
    aspect = (xmax - xmin) / max(ymax - ymin, 1)
    fig_h = 7.0
    fig_w = min(16.0, max(10.0, fig_h * aspect))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymax, ymin)
    ax.axis("off")

    for src, tgt in edges:
        sx, sy, sw, sh, _, _ = cells[src]
        tx, ty, tw, th, _, _ = cells[tgt]
        ax.annotate(
            "",
            xy=(tx, ty + th / 2),
            xytext=(sx + sw, sy + sh / 2),
                arrowprops=dict(arrowstyle="-|>", color=WIRE, lw=1.7, shrinkA=2, shrinkB=2),
        )

    for x, y, w, h, val, style in cells.values():
        if "text" in style and "fillColor=none" in style:
            ax.text(x + w / 2, y + h / 2, val, ha="center", va="center", fontsize=10, color=TEXT)
            continue

        fc, ec = BOX, ACCENT
        if val in ("Q", "~Q") or "ellipse" in style:
            fc, ec = "#1E3A5F", ACCENT2
        elif val in ("H_Deb", "L_Deb"):
            fc, ec = PANEL, ACCENT
        elif not val.strip():
            fc, ec = PANEL, WIRE

        ax.add_patch(
            Rectangle((x, y), w, h, linewidth=1.0, edgecolor=ec, facecolor=fc, alpha=0.95)
        )
        if val and val not in ("H_Deb", "L_Deb", "Q", "~Q"):
            fs = 9 if len(val) > 12 else 10
            ax.text(
                x + w / 2,
                y + h / 2,
                val,
                ha="center",
                va="center",
                fontsize=fs,
                color=TEXT,
                wrap=True,
            )

    return _save_fig(fig, out_path, dpi=dpi)


def code_to_png(code: str, out_path: Path, *, title: str | None = None, max_lines: int = 22) -> Path:
    lines = code.splitlines()
    if len(lines) > max_lines:
        half = max_lines // 2 - 1
        lines = lines[:half] + ["// ..."] + lines[-(max_lines - half - 1) :]

    fig_h = min(7.5, 0.30 * len(lines) + (0.7 if title else 0.4))
    fig, ax = plt.subplots(figsize=(12, fig_h), facecolor=PANEL)
    ax.set_facecolor(PANEL)
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    y = 0.92
    if title:
        ax.text(0.03, y, title, fontsize=13, color=ACCENT, family="monospace", weight="bold")
        y -= 0.10

    line_h = (y - 0.05) / max(len(lines), 1)
    for i, line in enumerate(lines):
        ax.text(
            0.03,
            y - i * line_h,
            line.replace("\t", "    ")[:110],
            fontsize=11,
            color=TEXT,
            family="monospace",
            va="top",
        )

    return _save_fig(fig, out_path, dpi=130)


def json_snippet_to_png(data: dict, out_path: Path, *, title: str) -> Path:
    snippet = json.dumps(data, indent=2, ensure_ascii=False)
    return code_to_png(snippet, out_path, title=title, max_lines=22)


def crop_image(src: Path, out_path: Path, box: tuple[float, float, float, float]) -> Path:
    """Crop a provided image by fractional coordinates (left, top, right, bottom)."""
    with Image.open(src) as img:
        w, h = img.size
        crop = img.crop(
            (
                int(w * box[0]),
                int(h * box[1]),
                int(w * box[2]),
                int(h * box[3]),
            )
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_path)
    return out_path


def pipeline_diagram(out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 4.2), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.2)
    ax.axis("off")

    def box(x, y, w, h, label, color=ACCENT):
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=PANEL,
            edgecolor=color,
            linewidth=2,
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=TEXT, fontsize=11, weight="bold")

    def arrow(x1, y1, x2, y2):
        ax.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=14,
                color=MUTED,
                lw=2,
            )
        )

    box(0.3, 1.5, 2.0, 1.2, "JSON\nConfig", ACCENT)
    box(2.8, 1.5, 2.0, 1.2, "Validate\n(graph)", ACCENT2)
    for i, (label, color) in enumerate(
        [
            ("Verilog\n.v", ACCENT),
            ("C\n.c", ACCENT2),
            ("Draw.io\n.xml", "#A78BFA"),
            ("Schemdraw\n.svg/.png", "#FBBF24"),
        ]
    ):
        x = 5.3 + i * 1.55
        box(x, 1.5, 1.35, 1.2, label, color)

    arrow(2.3, 2.1, 2.8, 2.1)
    arrow(4.8, 2.1, 5.3, 2.1)
    for i in range(3):
        arrow(5.3 + i * 1.55 + 1.35, 2.1, 5.3 + (i + 1) * 1.55, 2.1)

    ax.text(6.0, 0.35, "Single source of truth  →  consistent RTL, firmware, diagrams, timing", ha="center", color=MUTED, fontsize=10)
    return _save_fig(fig, out_path)


def layer_architecture_diagram(out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 3.8), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.8)
    ax.axis("off")

    layers = [
        ("Input\n(+ NOT)", ACCENT, "PG / GPIO\nenable signals"),
        ("AND / NAND", ACCENT2, "Hi/Lo cond\ngroups (AND)"),
        ("OR / NOR", "#A78BFA", "Merge groups\n(OR across)"),
        ("PSEQCELL", "#FBBF24", "H_Deb / L_Deb\nQ / ~Q"),
        ("Output\nlabels", MUTED, "oRAIL names"),
    ]
    w = 2.0
    gap = 0.25
    x0 = 0.4
    for i, (title, color, sub) in enumerate(layers):
        x = x0 + i * (w + gap)
        patch = FancyBboxPatch(
            (x, 1.0),
            w,
            1.6,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            facecolor=PANEL,
            edgecolor=color,
            linewidth=2,
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, 2.05, title, ha="center", va="center", color=TEXT, fontsize=10, weight="bold")
        ax.text(x + w / 2, 1.35, sub, ha="center", va="center", color=MUTED, fontsize=8)
        if i < len(layers) - 1:
            ax.add_patch(
                FancyArrowPatch(
                    (x + w + 0.02, 1.8),
                    (x + w + gap - 0.02, 1.8),
                    arrowstyle="-|>",
                    mutation_scale=12,
                    color=WIRE,
                    lw=1.8,
                )
            )

    ax.text(6.0, 0.35, "Draw.io export: left → right layers + feedback routing (Q/~Q → upstream inputs)", ha="center", color=MUTED, fontsize=9)
    return _save_fig(fig, out_path)


def pseqcell_block_diagram(out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 8)
    ax.set_ylim(0, 4.5)
    ax.axis("off")

    outer = FancyBboxPatch(
        (1.5, 0.8),
        5.0,
        3.0,
        boxstyle="round,pad=0.02,rounding_size=0.1",
        facecolor=PANEL,
        edgecolor=ACCENT,
        linewidth=2,
    )
    ax.add_patch(outer)
    ax.text(4.0, 3.55, "PSEQCELL (reference: src/reference/PSEQCELL.v)", ha="center", color=ACCENT, fontsize=11, weight="bold")

    for label, x, y in [("iHi ← Hi cond", 0.3, 2.8), ("iLo ← Lo cond", 0.3, 1.6), ("iForce", 0.3, 0.5)]:
        ax.text(x, y, label, ha="left", va="center", color=MUTED, fontsize=9)
        ax.add_patch(FancyArrowPatch((1.2, y), (1.5, y), arrowstyle="-|>", color=WIRE, lw=1.5))

    for label, x, y, c in [
        ("H_Deb", 2.0, 2.6, ACCENT),
        ("L_Deb", 2.0, 1.4, ACCENT),
        ("Q → oRAIL", 5.8, 2.6, ACCENT2),
        ("~Q (FB)", 5.8, 1.4, ACCENT2),
    ]:
        patch = FancyBboxPatch(
            (x, y),
            1.4,
            0.55,
            boxstyle="round,pad=0.01,rounding_size=0.05",
            facecolor=BOX,
            edgecolor=c,
            linewidth=1.5,
        )
        ax.add_patch(patch)
        ax.text(x + 0.7, y + 0.28, label, ha="center", va="center", color=TEXT, fontsize=9)

    ax.text(4.0, 0.35, "Parameters: INIT, CYCLE_HI/LO, RECOVER, FORCE, CYCLE_SYNC, OD", ha="center", color=MUTED, fontsize=8)
    return _save_fig(fig, out_path)


def config_model_diagram(out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.5)
    ax.axis("off")

    nodes = [
        ("IN1\nInput + DEB", 0.8, 2.2, ACCENT),
        ("OUT1\nOutput rail", 4.5, 2.2, ACCENT2),
    ]
    for label, x, y, c in nodes:
        patch = FancyBboxPatch(
            (x, y),
            2.2,
            1.2,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor=PANEL,
            edgecolor=c,
            linewidth=2,
        )
        ax.add_patch(patch)
        ax.text(x + 1.1, y + 0.6, label, ha="center", va="center", color=TEXT, fontsize=10, weight="bold")

    ax.add_patch(
        FancyArrowPatch((3.0, 2.8), (4.5, 2.8), arrowstyle="-|>", color=ACCENT, lw=2, mutation_scale=14)
    )
    ax.text(3.75, 3.05, "Hi: IN1", ha="center", color=ACCENT, fontsize=9)
    ax.add_patch(
        FancyArrowPatch((3.0, 2.4), (4.5, 2.4), arrowstyle="-|>", color="#F87171", lw=2, mutation_scale=14)
    )
    ax.text(3.75, 2.15, "Lo: ~IN1 (inv)", ha="center", color="#F87171", fontsize=9)

    bullets = [
        "Rails: Input (debounce) or Output (PSEQCELL)",
        "Hi / Lo / Force conditions with AND-in-group, OR-across-groups",
        "Validation: unique names, missing refs, cycle detection",
    ]
    for i, b in enumerate(bullets):
        ax.text(0.5, 1.2 - i * 0.35, f"• {b}", ha="left", color=MUTED, fontsize=9)

    return _save_fig(fig, out_path)


def _npx_executable() -> str:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return npx
    raise FileNotFoundError("npx not found — install Node.js to render WaveDrom PNGs (legacy doc assets only)")


def render_wavedrom_png(wavejson_path: Path, out_path: Path) -> Path:
    cmd = [
        _npx_executable(),
        "--yes",
        "wavedrom-cli",
        "-i",
        str(wavejson_path),
        "-p",
        str(out_path),
        "-s",
        str(out_path.with_suffix(".svg")),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT, capture_output=True, text=True)
    return out_path


def _write_artifacts(stem: str, cfg: PowerSeqConfig, assets: Path) -> dict[str, Path]:
    xml = generate_drawio(cfg)
    xml_path = assets / f"{stem}.drawio.xml"
    xml_path.write_text(xml, encoding="utf-8")

    v_path = assets / f"{stem}.v"
    v_path.write_text(generate_verilog(cfg, output_filename=str(v_path)), encoding="utf-8")

    c_path = assets / f"{stem}.c"
    c_path.write_text(generate_c(cfg, output_filename=str(c_path)), encoding="utf-8")

    scenario = default_scenario_for_config(cfg)
    timing_png = assets / f"{stem}_timing.png"
    export_schemdraw(cfg, scenario, output_filename=str(timing_png))

    drawio_png = assets / f"{stem}_drawio.png"
    drawio_to_png(xml_path, drawio_png)

    return {
        "xml": xml_path,
        "verilog": v_path,
        "c": c_path,
        "timing_png": timing_png,
        "drawio_png": drawio_png,
    }


def generate_all_assets() -> dict[str, Path]:
    assets = _ensure_dir()
    out: dict[str, Path] = {}

    out["pipeline"] = pipeline_diagram(assets / "pipeline.png")
    out["layers"] = layer_architecture_diagram(assets / "layers.png")
    out["pseqcell"] = pseqcell_block_diagram(assets / "pseqcell_block.png")
    out["config_model"] = config_model_diagram(assets / "config_model.png")

    demo_json = DOC / "demo_json.json"
    demo_verilog = DOC / "demo_verilog.v"
    demo_c = DOC / "demo_c.c"
    demo_drawio_png = DOC / "demo_drawio_png.png"
    demo_drawio_xml = DOC / "demo_drawio_xml.xml"
    demo_wavedrom_png = DOC / "demo_wavedrom_png.png"
    demo_wavejson = DOC / "demo_wavedrow_json.json"
    demo_wave_config = DOC / "demo_wavedrom_config_json.json"

    for key, path in {
        "demo_json_file": demo_json,
        "demo_verilog_file": demo_verilog,
        "demo_c_file": demo_c,
        "demo_drawio_png": demo_drawio_png,
        "demo_drawio_xml": demo_drawio_xml,
        "demo_wavedrom_png": demo_wavedrom_png,
        "demo_wavedrom_json": demo_wavejson,
        "demo_wavedrom_config_json": demo_wave_config,
    }.items():
        if path.is_file():
            out[key] = path

    if demo_drawio_png.is_file():
        out["demo_drawio_zoom"] = crop_image(
            demo_drawio_png,
            assets / "demo_drawio_zoom.png",
            (0.25, 0.05, 1.0, 0.72),
        )

    if demo_wavedrom_png.is_file():
        out["demo_wavedrom_zoom"] = crop_image(
            demo_wavedrom_png,
            assets / "demo_wavedrom_zoom.png",
            (0.0, 0.05, 0.86, 0.65),
        )

    if demo_json.is_file():
        raw = json.loads(demo_json.read_text(encoding="utf-8"))
        rails = raw.get("rails", [])
        snippet = {
            "module_name": raw.get("module_name"),
            "pulses": raw.get("pulses", []),
            "rail_count": len(rails),
            "example_rails": [
                {
                    "name": r.get("name"),
                    "seq_type": r.get("seq_type"),
                    "hi": r.get("depends_on_hi", [])[:3],
                    "lo": r.get("depends_on_lo", [])[:3],
                }
                for r in rails[:4]
            ],
        }
        out["demo_json_snippet"] = json_snippet_to_png(
            snippet, assets / "demo_json_excerpt.png", title="doc/demo_json.json (provided input spec)"
        )

    if demo_verilog.is_file():
        lines = demo_verilog.read_text(encoding="utf-8").splitlines()
        port_lines = lines[28:70]
        pseq_lines = [ln for ln in lines if "PSEQCELL #(" in ln][:6]
        excerpt = "\n".join(port_lines + ["", "// PSEQCELL instances (excerpt)"] + pseq_lines)
        out["demo_verilog_snippet"] = code_to_png(
            excerpt,
            assets / "demo_verilog_excerpt.png",
            title="doc/demo_verilog.v (provided Verilog output)",
            max_lines=24,
        )

    if demo_c.is_file():
        lines = demo_c.read_text(encoding="utf-8").splitlines()
        struct_lines = lines[20:64]
        handler_lines = lines[155:168]
        excerpt = "\n".join(struct_lines[:18] + ["", "// Runtime conditions (excerpt)"] + handler_lines)
        out["demo_c_snippet"] = code_to_png(
            excerpt,
            assets / "demo_c_excerpt.png",
            title="doc/demo_c.c (provided C output)",
            max_lines=24,
        )

    return out


if __name__ == "__main__":
    paths = generate_all_assets()
    print(f"Generated {len(paths)} assets under {ASSETS}")
    for name, p in sorted(paths.items()):
        print(f"  {name}: {p.name}")
