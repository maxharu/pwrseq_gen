"""C8：Parameter 資料模型與 PowerSeqConfig.parameters 的序列化/展開。

重點：舊檔（無 parameters）to_dict 不得多出 parameters 鍵（byte 不變）；含 parameter 的 config
要能有序 round-trip；vector 的 width_expr 可為公式，展開 N 由 eval_width 算，但 width_expr 字串
本身要保留（C9 Verilog 符號寬度要用）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import Parameter, PowerRail, PowerSeqConfig


class TestParameterSerialization:
    def test_empty_parameters_omits_key(self):
        cfg = PowerSeqConfig(rails=[PowerRail("A", seq_type="output")])
        assert "parameters" not in cfg.to_dict()

    def test_old_config_round_trip_byte_identical(self):
        d = {
            "module_name": "PWRSEQ_TOP",
            "clock_freq_mhz": 100.0,
            "pulse_period_ns": 100.0,
            "pulses": ["Pulse_1us"],
            "rails": [{"name": "A", "seq_type": "Output", "depends_on_hi": ["__HIGH__"]}],
        }
        cfg = PowerSeqConfig.from_dict(d)
        assert cfg.parameters == []
        # 重新序列化不得冒出 parameters 鍵
        assert "parameters" not in cfg.to_dict()

    def test_parameters_round_trip_preserves_order(self):
        cfg = PowerSeqConfig(
            rails=[PowerRail("A", seq_type="output")],
            parameters=[Parameter("NUM_CPU", 4), Parameter("NUM_MEM", 2)],
        )
        d = cfg.to_dict()
        assert d["parameters"] == [
            {"name": "NUM_CPU", "value": 4},
            {"name": "NUM_MEM", "value": 2},
        ]
        back = PowerSeqConfig.from_dict(d)
        assert [(p.name, p.value) for p in back.parameters] == [("NUM_CPU", 4), ("NUM_MEM", 2)]


class TestVectorFormulaWidth:
    def _vector_dict(self) -> dict:
        return {
            "parameters": [{"name": "NUM_CPU", "value": 2}],
            "rails": [
                {
                    "name": "V",
                    "seq_type": "Output",
                    "width_expr": "NUM_CPU*2",
                    "bits": [{}, {}, {}, {}],
                }
            ],
        }

    def test_formula_width_expands_via_parameters(self):
        cfg = PowerSeqConfig.from_dict(self._vector_dict())
        vrails = [r for r in cfg.rails if r.group_base == "V"]
        assert [r.name for r in vrails] == ["V[0]", "V[1]", "V[2]", "V[3]"]
        # 公式字串本身保留在每個 bit 上
        assert all(r.width_expr == "NUM_CPU*2" for r in vrails)

    def test_formula_width_round_trip_keeps_symbolic_form(self):
        cfg = PowerSeqConfig.from_dict(self._vector_dict())
        d = cfg.to_dict()
        grp = next(x for x in d["rails"] if x.get("name") == "V")
        assert grp["width_expr"] == "NUM_CPU*2"
        cfg2 = PowerSeqConfig.from_dict(d)
        assert len([r for r in cfg2.rails if r.group_base == "V"]) == 4
