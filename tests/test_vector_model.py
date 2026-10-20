"""A2 vector 模型 + 序列化測試。

守住三件事：
  1. VectorNode.elaborate() 展開成 base[i] 並帶正確的群組 metadata。
  2. 含 vector 的 config 經 to_dict→from_dict 收合/展開後 round-trip 相等。
  3. 無 vector 的既有存檔（templates/demo_json.json）載入後 to_dict 不變——
     加了群組 metadata 不能改到舊檔的序列化。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.config_models import (
    ConditionConfig,
    PowerRail,
    PowerSeqConfig,
    VectorNode,
    eval_width,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_JSON = os.path.join(ROOT, "templates", "demo_json.json")


def test_eval_width_integer_string():
    assert eval_width("2") == 2
    assert eval_width(" 4 ") == 4


class TestVectorNodeElaborate:
    def test_names_and_metadata(self):
        vn = VectorNode(base="FOO", seq_type="output", width_expr="3")
        rails = vn.elaborate()
        assert [r.name for r in rails] == ["FOO[0]", "FOO[1]", "FOO[2]"]
        assert all(r.group_base == "FOO" for r in rails)
        assert [r.bit_index for r in rails] == [0, 1, 2]
        assert all(r.width_expr == "3" for r in rails)

    def test_per_bit_conditions_are_independent(self):
        bit0 = ConditionConfig(depends_on_hi_groups=[["EN"]])
        bit1 = ConditionConfig(depends_on_lo_groups=[["EN"]])
        vn = VectorNode(base="FOO", width_expr="2", bit_conds=[bit0, bit1])
        rails = vn.elaborate()
        assert rails[0].get_hi_groups() == [["EN"]]
        assert rails[0].get_lo_groups() == []
        assert rails[1].get_hi_groups() == []
        assert rails[1].get_lo_groups() == [["EN"]]
        # 條件物件不共用
        assert rails[0].cond is not rails[1].cond


class TestVectorRoundTrip:
    def _vector_config(self) -> PowerSeqConfig:
        bit0 = ConditionConfig(depends_on_hi_groups=[["EN"]])
        bit1 = ConditionConfig(
            depends_on_hi_groups=[["EN"]],
            depends_on_lo_groups=[["EN"]],
        )
        vn = VectorNode(base="VOUT", seq_type="output", width_expr="2", bit_conds=[bit0, bit1])
        rails = [PowerRail(name="EN", seq_type="input", deb_enable=True)] + vn.elaborate()
        return PowerSeqConfig(rails=rails)

    def test_to_dict_collapses_group_to_one_entry(self):
        d = self._vector_config().to_dict()
        names = [r["name"] for r in d["rails"]]
        assert names == ["EN", "VOUT"]  # 群組收合成一筆
        vout = d["rails"][1]
        assert vout["width_expr"] == "2"
        assert len(vout["bits"]) == 2
        # 共用物理在頂層，逐 bit 條件在 bits
        assert "cycle_hi" in vout
        assert vout["bits"][0] == {"depends_on_hi_groups": [["EN"]]}
        assert "depends_on_lo_groups" in vout["bits"][1]

    def test_round_trip_equal_and_expands(self):
        cfg = self._vector_config()
        d1 = cfg.to_dict()
        cfg2 = PowerSeqConfig.from_dict(d1)
        d2 = cfg2.to_dict()
        assert d1 == d2
        # from_dict 展開回扁平 rails
        assert [r.name for r in cfg2.rails] == ["EN", "VOUT[0]", "VOUT[1]"]
        vout = [r for r in cfg2.rails if r.group_base == "VOUT"]
        assert [r.bit_index for r in vout] == [0, 1]
        assert vout[0].get_hi_groups() == [["EN"]]
        assert vout[1].get_lo_groups() == [["EN"]]


def test_legacy_json_to_dict_unchanged():
    """無群組 metadata 的舊檔載入後 to_dict 必須與原檔邏輯一致（byte/dict 不變）。"""
    with open(DEMO_JSON, encoding="utf-8") as f:
        data = json.load(f)
    cfg = PowerSeqConfig.from_dict(data)
    assert cfg.to_dict() == data
