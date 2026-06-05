"""Smoke tests for golden2 export diff."""
import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config_models import PowerSeqConfig
from drawio_export import generate_drawio
from drawio_golden_diff import diff_golden2_export, parse_drawio_xml

GOLDEN_JSON = ROOT / "src/reference/golden.json"
GOLDEN2_XML = ROOT / "src/reference/golden2.xml"


def test_parse_golden2_and_export():
    with open(GOLDEN_JSON, encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))
    export_xml = generate_drawio(cfg)
    ref = parse_drawio_xml(GOLDEN2_XML.read_text(encoding="utf-8"))
    act = parse_drawio_xml(export_xml)
    assert len(ref.vertices) > 50
    assert len(act.vertices) > 20
    assert len(ref.edges) > 50
    assert len(act.edges) > 20


def test_diff_report_runs():
    with open(GOLDEN_JSON, encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))
    report = diff_golden2_export(cfg, generate_drawio(cfg), str(GOLDEN2_XML))
    text = report.format_text()
    assert "=== Draw.io golden2 diff ===" in text
    assert "normalize offset" in text
