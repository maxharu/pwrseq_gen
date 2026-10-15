"""Golden-output regression for the five export backends.

Baselines live in `tests/golden/`. They are a byte-level contract: any change to
Verilog / C / Draw.io / Schemdraw / simulation output shows up here first.

Two sources of non-determinism are pinned so the comparison is meaningful:
  - Draw.io embeds a random 20-char diagram id -> `random.seed()` before export.
  - .xlsm is a zip with embedded timestamps -> compare an import round-trip instead.

Regenerate deliberately after reviewing the diff:
    PWRSEQ_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_exports.py
"""
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from codegen.c_generator import generate_c
from codegen.verilog_generator import generate_verilog
from core.config_models import PowerSeqConfig
from drawio import generate_drawio
from timing.schemdraw_export import generate_schemdraw_doc
from timing.timing_scenario_io import resolve_scenario
from timing.timing_sim import simulate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
DEMO_JSON = os.path.join(ROOT, "templates", "demo_json.json")
UPDATE = os.environ.get("PWRSEQ_UPDATE_GOLDEN") == "1"

HAS_DEMO = os.path.isfile(DEMO_JSON)
HAS_EXCEL_TEMPLATE = any(
    os.path.isfile(os.path.join(ROOT, "templates", n))
    for n in (
        "powerseq_nodes_template.xlsx",
        "powerseq_nodes_template_new.xlsm",
        "powerseq_nodes_template_fixed.xlsm",
        "powerseq_nodes_template.xlsm",
    )
)

pytestmark = pytest.mark.skipif(not HAS_DEMO, reason="templates/demo_json.json missing")


def _config() -> PowerSeqConfig:
    with open(DEMO_JSON, encoding="utf-8") as f:
        return PowerSeqConfig.from_dict(json.load(f))


def _as_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _first_difference(actual: str, expected: str) -> str:
    """Line-level diff summary — the Draw.io baseline is too large to dump whole."""
    a_lines, e_lines = actual.splitlines(), expected.splitlines()
    for i, (a, e) in enumerate(zip(a_lines, e_lines), start=1):
        if a != e:
            return f"line {i}:\n  expected: {e[:200]}\n  actual  : {a[:200]}"
    return f"line count: expected {len(e_lines)}, actual {len(a_lines)}"


def _check_golden(name: str, actual: str) -> None:
    path = os.path.join(GOLDEN_DIR, name)
    if UPDATE:
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(actual)
        pytest.skip(f"golden baseline rewritten: {name}")
    assert os.path.isfile(path), (
        f"missing baseline {name}; regenerate with PWRSEQ_UPDATE_GOLDEN=1"
    )
    with open(path, encoding="utf-8") as f:
        expected = f.read()
    assert actual == expected, f"{name} drifted from golden baseline\n{_first_difference(actual, expected)}"


def test_verilog_golden():
    _check_golden("demo.v", generate_verilog(_config(), "pwrseq_demo.v"))


def test_c_golden():
    _check_golden("demo.c", generate_c(_config(), "pwrseq_demo.c"))


def test_drawio_golden():
    random.seed(0)
    _check_golden("demo.drawio.xml", generate_drawio(_config()))


def test_schemdraw_doc_golden():
    cfg = _config()
    _check_golden("demo_schemdraw.json", _as_json(generate_schemdraw_doc(cfg, resolve_scenario(cfg))))


def test_simulation_golden():
    cfg = _config()
    result = simulate(cfg, resolve_scenario(cfg))
    _check_golden("demo_sim.json", _as_json({
        "steps": result.steps,
        "raw_inputs": result.raw_inputs,
        "output_values": result.output_values,
        "output_hi_cond": result.output_hi_cond,
        "output_lo_cond": result.output_lo_cond,
        "output_force_cond": result.output_force_cond,
        "output_states": result.output_states,
    }))


@pytest.mark.skipif(not HAS_EXCEL_TEMPLATE, reason="Excel template missing")
def test_excel_round_trip_golden(tmp_path):
    """.xlsm bytes carry timestamps, so lock the config that survives a save+load."""
    pytest.importorskip("openpyxl")
    from excel.excel_export import export_powerseq_to_excel
    from excel.excel_import import load_powerseq_from_excel

    out = str(tmp_path / "round_trip.xlsm")
    export_powerseq_to_excel(_config(), out)
    _check_golden("demo_excel_round_trip.json", _as_json(load_powerseq_from_excel(out).to_dict()))
