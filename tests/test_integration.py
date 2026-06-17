"""整合測試：載入 JSON、驗證、產生 Verilog、Draw.io"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig
from validator import validate
from verilog_generator import generate_verilog
from drawio_export import generate_drawio


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
DEMO_JSON = os.path.join(PROJECT_ROOT, "doc", "demo_json.json")


class TestLoadSampleConfigs:
    """載入專案內 JSON 設定檔"""

    def test_load_sample_config(self):
        path = os.path.join(OUTPUT_DIR, "sample_config.json")
        if not os.path.exists(path):
            pytest.skip("sample_config.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) > 0
        ok, _ = validate(cfg)
        assert ok, "sample_config should be valid"

    def test_load_debug_config(self):
        path = os.path.join(OUTPUT_DIR, "debug.json")
        if not os.path.exists(path):
            pytest.skip("debug.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) >= 3
        ok, errs = validate(cfg)
        assert ok, f"debug.json should be valid: {errs}"

    def test_load_test_deb_config(self):
        path = os.path.join(OUTPUT_DIR, "test_deb.json")
        if not os.path.exists(path):
            pytest.skip("test_deb.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        ok, errs = validate(cfg)
        assert ok, f"test_deb.json should be valid: {errs}"


class TestFullPipeline:
    """完整流程：JSON -> Config -> Validate -> Verilog"""

    def test_sample_config_to_verilog(self):
        path = os.path.join(OUTPUT_DIR, "sample_config.json")
        if not os.path.exists(path):
            pytest.skip("sample_config.json not found")
        with open(path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        ok, errs = validate(cfg)
        assert ok, errs
        out = generate_verilog(cfg, output_filename="sample.v")
        assert "`timescale" in out
        assert "module sample" in out
        assert "`ifndef SAMPLE_V" in out
        assert "endmodule" in out

    def test_debug_config_to_verilog(self):
        path = os.path.join(OUTPUT_DIR, "debug.json")
        if not os.path.exists(path):
            pytest.skip("debug.json not found")
        with open(path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        ok, errs = validate(cfg)
        assert ok, errs
        out = generate_verilog(cfg, output_filename="my_pwrseq.v")
        assert "module my_pwrseq" in out
        assert "PSEQCELL" in out
        assert "DEB" in out
        # 應有 SIG_2, SIG_3 的 output
        assert "oSIG_2" in out
        assert "oSIG_3" in out

    def test_cell_centric_drawio_from_demo(self):
        """Cell-centric：每個 output 一個 group、走線全 orthogonal auto。"""
        with open(DEMO_JSON, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        root = ET.fromstring(generate_drawio(cfg))
        outputs = [r for r in cfg.rails if r.seq_type == "output"]
        groups = [c for c in root.iter("mxCell") if c.get("connectable") == "0"]
        assert len(groups) == len(outputs)
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            assert "orthogonalEdgeStyle" in (c.get("style") or "")


X15DOT_XLSM = os.path.join(PROJECT_ROOT, "templates", "x15dot.xlsm")


@pytest.mark.skipif(not os.path.isfile(X15DOT_XLSM), reason="x15dot.xlsm missing")
class TestX15dotCellGrid:
    """x15dot 大圖：cell-centric grid 可產生。"""

    def test_x15dot_produces_cell_groups(self):
        from excel_import import load_powerseq_from_excel

        cfg = load_powerseq_from_excel(X15DOT_XLSM)
        root = ET.fromstring(generate_drawio(cfg))
        outputs = [r for r in cfg.rails if r.seq_type == "output"]
        groups = [c for c in root.iter("mxCell") if c.get("connectable") == "0"]
        assert len(groups) == len(outputs)
        assert len(list(root.iter("mxCell"))) > len(outputs) * 5
