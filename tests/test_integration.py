"""整合測試：載入 JSON、驗證、產生 Verilog、Draw.io"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from config_models import PowerSeqConfig
from validator import validate
from verilog_generator import generate_verilog
from drawio_export import generate_drawio


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLoadSampleConfigs:
    """載入專案內 JSON 設定檔"""

    def test_load_sample_config(self):
        path = os.path.join(PROJECT_ROOT, "sample_config.json")
        if not os.path.exists(path):
            pytest.skip("sample_config.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) > 0
        ok, _ = validate(cfg)
        assert ok, "sample_config should be valid"

    def test_load_debug_config(self):
        path = os.path.join(PROJECT_ROOT, "debug.json")
        if not os.path.exists(path):
            pytest.skip("debug.json not found")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        cfg = PowerSeqConfig.from_dict(d)
        assert len(cfg.rails) >= 3
        ok, errs = validate(cfg)
        assert ok, f"debug.json should be valid: {errs}"

    def test_load_test_deb_config(self):
        path = os.path.join(PROJECT_ROOT, "test_deb.json")
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
        path = os.path.join(PROJECT_ROOT, "sample_config.json")
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
        path = os.path.join(PROJECT_ROOT, "debug.json")
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

    def test_debug_config_to_drawio_matches_golden_structure(self):
        """用 debug.json 產生 Draw.io，與 debug_golden.xml 比對：有 waypoints 的邊 (source,target) 一致"""
        json_path = os.path.join(PROJECT_ROOT, "debug.json")
        golden_path = os.path.join(PROJECT_ROOT, "debug_golden.xml")
        if not os.path.exists(json_path) or not os.path.exists(golden_path):
            pytest.skip("debug.json or debug_golden.xml not found")
        with open(json_path, encoding="utf-8") as f:
            cfg = PowerSeqConfig.from_dict(json.load(f))
        xml_out = generate_drawio(cfg)
        root = ET.fromstring(xml_out)

        def edges_with_waypoints(xml_root):
            out = set()
            for cell in xml_root.findall(".//mxCell[@edge='1']"):
                src, tgt = cell.get("source"), cell.get("target")
                if src is None or tgt is None:
                    continue
                geo = cell.find("mxGeometry")
                if geo is not None and geo.find("Array") is not None:
                    out.add((src, tgt))
            return out

        golden_root = ET.parse(golden_path).getroot()
        got = edges_with_waypoints(root)
        want = edges_with_waypoints(golden_root)
        assert got == want, f"Draw.io edges with waypoints differ: got {got}, want {want}"
