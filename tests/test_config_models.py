"""Tests for config_models.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from config_models import PowerSeqConfig, PowerRail


class TestPowerRail:
    """PowerRail 單元測試"""

    def test_has_pseqcell_output(self):
        r = PowerRail(name="X", seq_type="output")
        assert r.has_pseqcell is True

    def test_has_pseqcell_input(self):
        r = PowerRail(name="X", seq_type="input")
        assert r.has_pseqcell is False

    def test_get_hi_groups_from_depends_on_hi(self):
        r = PowerRail(name="X", depends_on_hi=["A", "B"])
        assert r.get_hi_groups() == [["A", "B"]]

    def test_get_hi_groups_from_groups(self):
        r = PowerRail(
            name="X",
            depends_on_hi_groups=[["A"], ["B", "C"]],
        )
        assert r.get_hi_groups() == [["A"], ["B", "C"]]

    def test_get_lo_groups_empty(self):
        r = PowerRail(name="X", depends_on_lo=[])
        assert r.get_lo_groups() == []

    def test_get_depends_on_hi_flat(self):
        r = PowerRail(name="X", depends_on_hi_groups=[["A"], ["B"]])
        assert r.get_depends_on_hi_flat() == ["A", "B"]

    def test_get_depends_on_lo_flat(self):
        r = PowerRail(name="X", depends_on_lo=["C"])
        assert r.get_depends_on_lo_flat() == ["C"]


class TestPowerSeqConfig:
    """PowerSeqConfig 單元測試"""

    def test_from_dict_empty(self):
        cfg = PowerSeqConfig.from_dict({})
        assert cfg.rails == []
        assert cfg.module_name == "PWRSEQ_TOP"
        assert cfg.pulses == ["Pulse_1us"]

    def test_from_dict_with_rails(self):
        d = {
            "module_name": "MY_MOD",
            "rails": [
                {"name": "A", "seq_type": "Output", "depends_on_hi": ["__HIGH__"]},
                {"name": "B", "seq_type": "Input"},
            ],
        }
        cfg = PowerSeqConfig.from_dict(d)
        assert cfg.module_name == "MY_MOD"
        assert len(cfg.rails) == 2
        assert cfg.rails[0].name == "A"
        assert cfg.rails[0].seq_type == "output"
        assert cfg.rails[0].depends_on_hi == ["__HIGH__"]
        assert cfg.rails[1].name == "B"
        assert cfg.rails[1].seq_type == "input"

    def test_from_dict_legacy_seq_type(self):
        """舊版 signal/external/power_rail 相容"""
        d = {"rails": [{"name": "X", "seq_type": "signal"}]}
        cfg = PowerSeqConfig.from_dict(d)
        assert cfg.rails[0].seq_type == "output"

        d2 = {"rails": [{"name": "Y", "seq_type": "external"}]}
        cfg2 = PowerSeqConfig.from_dict(d2)
        assert cfg2.rails[0].seq_type == "input"

    def test_from_dict_uses_depends_on(self):
        """depends_on 作為 depends_on_hi 後備"""
        d = {"rails": [{"name": "X", "depends_on": ["A", "B"]}]}
        cfg = PowerSeqConfig.from_dict(d)
        assert cfg.rails[0].depends_on_hi == ["A", "B"]

    def test_to_dict_roundtrip(self, sample_config_dict):
        cfg = PowerSeqConfig.from_dict(sample_config_dict)
        out = cfg.to_dict()
        assert "module_name" in out
        assert "rails" in out
        assert len(out["rails"]) == len(sample_config_dict["rails"])
        # Roundtrip
        cfg2 = PowerSeqConfig.from_dict(out)
        assert cfg2.module_name == cfg.module_name
        assert len(cfg2.rails) == len(cfg.rails)

    def test_to_dict_omits_legacy_fields(self):
        cfg = PowerSeqConfig.from_dict(
            {
                "rails": [
                    {"name": "IN", "seq_type": "Input", "deb_enable": True},
                    {
                        "name": "OUT",
                        "seq_type": "Output",
                        "depends_on_hi": ["IN"],
                        "depends_on_hi_inv": {"IN": True},
                        "cycle_hi": 3,
                    },
                ]
            }
        )
        out = cfg.to_dict()
        inp = out["rails"][0]
        assert "depends_on" not in inp
        assert "depends_on_hi" not in inp
        assert "cycle_hi" not in inp
        assert inp["deb_enable"] is True
        outp = out["rails"][1]
        assert "depends_on" not in outp
        assert "depends_on_hi" not in outp
        assert outp["depends_on_hi_groups"] == [["IN"]]
        assert outp["depends_on_hi_inv_groups"] == [[True]]

    def test_from_dict_pulses(self):
        d = {"pulses": ["iPulse_1us", "iPulse_1ms"], "rails": []}
        cfg = PowerSeqConfig.from_dict(d)
        assert cfg.pulses == ["Pulse_1us", "Pulse_1ms"]

    def test_migrate_legacy_wavedrom_inputs_to_rails(self):
        cfg = PowerSeqConfig.from_dict(
            {
                "rails": [
                    {"name": "EKEY", "seq_type": "Input", "deb_enable": True},
                ],
                "wavedrom_scenario": {
                    "steps": 50,
                    "inputs": {
                        "EKEY": {
                            "hi_mode": "custom",
                            "lo_mode": "constant_0",
                            "hi_wave": "01",
                        }
                    },
                },
            }
        )
        ekey = cfg.rails[0]
        assert ekey.hi_mode == "custom"
        assert ekey.hi_wave == "01"
        out = cfg.to_dict()
        assert out["wavedrom_scenario"] == {"steps": 50}
        assert out["rails"][0]["hi_mode"] == "custom"
        assert out["rails"][0]["hi_wave"] == "01"
        assert "inputs" not in out.get("wavedrom_scenario", {})
