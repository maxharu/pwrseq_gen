"""整合測試：載入 JSON、驗證、產生 Verilog、Draw.io"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config_models import PowerSeqConfig
from drawio_export import generate_drawio


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_JSON = os.path.join(PROJECT_ROOT, "doc", "demo_json.json")


class TestFullPipeline:
    """完整流程：JSON -> Config -> Draw.io"""

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
