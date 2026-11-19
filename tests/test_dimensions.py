"""階段B：全域維度（dimensions）模型與驗證測試。

涵蓋：
  1. to_dict/from_dict round-trip；空維度不輸出該鍵（既有 config byte 不變）。
  2. from_dict 型別正規化與最多 2 個上限。
  3. validator：個數 0~2、名稱需存在於 parameters、不重複。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from codegen.verilog_generator import generate_verilog
from core.config_edit import set_group_metadata, vector_shape_label, width_expr_from_dims
from core.config_models import Parameter, PowerRail, PowerSeqConfig
from core.validator import check_dimensions, validate


def _config(dims: list[str]) -> PowerSeqConfig:
    return PowerSeqConfig(
        parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)],
        dimensions=dims,
    )


class TestRoundTrip:
    def test_dimensions_round_trip(self):
        cfg = _config(["NUM_CPU", "NUM_CPU_MEM"])
        d = cfg.to_dict()
        assert d["dimensions"] == ["NUM_CPU", "NUM_CPU_MEM"]
        back = PowerSeqConfig.from_dict(d)
        assert back.dimensions == ["NUM_CPU", "NUM_CPU_MEM"]

    def test_empty_dimensions_omits_key(self):
        cfg = _config([])
        assert "dimensions" not in cfg.to_dict()

    def test_from_dict_without_key(self):
        cfg = PowerSeqConfig.from_dict({"module_name": "X", "rails": []})
        assert cfg.dimensions == []

    def test_from_dict_caps_at_two(self):
        cfg = PowerSeqConfig.from_dict({
            "parameters": [{"name": "A", "value": 1}, {"name": "B", "value": 2},
                           {"name": "C", "value": 3}],
            "dimensions": ["A", "B", "C"],
            "rails": [],
        })
        assert cfg.dimensions == ["A", "B"]

    def test_from_dict_drops_non_string(self):
        cfg = PowerSeqConfig.from_dict({
            "parameters": [{"name": "A", "value": 1}],
            "dimensions": ["A", 3, None, ""],
            "rails": [],
        })
        assert cfg.dimensions == ["A"]


class TestValidation:
    def test_valid_dimensions_pass(self):
        assert check_dimensions(_config(["NUM_CPU", "NUM_CPU_MEM"])) == []

    def test_zero_dimensions_pass(self):
        assert check_dimensions(_config([])) == []

    def test_unknown_dimension_rejected(self):
        errs = check_dimensions(_config(["NUM_CPU", "GHOST"]))
        assert any("GHOST" in e for e in errs)

    def test_duplicate_dimension_rejected(self):
        errs = check_dimensions(_config(["NUM_CPU", "NUM_CPU"]))
        assert any("duplicate" in e.lower() for e in errs)

    def test_too_many_dimensions_rejected(self):
        cfg = PowerSeqConfig(
            parameters=[Parameter("A", 1), Parameter("B", 2), Parameter("C", 3)],
            dimensions=["A", "B", "C"],
        )
        errs = check_dimensions(cfg)
        assert any("at most 2" in e for e in errs)

    def test_validate_surfaces_dimension_error(self):
        ok, errors = validate(_config(["GHOST"]))
        assert not ok
        assert any("GHOST" in e for e in errors)


class TestWidthExprFromDims:
    def test_zero_dims_scalar(self):
        assert width_expr_from_dims([]) == "1"
        assert width_expr_from_dims(None) == "1"

    def test_one_dim(self):
        assert width_expr_from_dims(["NUM_CPU"]) == "NUM_CPU"

    def test_two_dims(self):
        assert width_expr_from_dims(["NUM_CPU", "NUM_CPU_MEM"]) == "NUM_CPU*NUM_CPU_MEM"

    def test_drops_empty_and_caps_two(self):
        assert width_expr_from_dims(["A", "", "B", "C"]) == "A*B"


def _dim_rails(base: str, width_expr: str, n: int, dims: list[str]) -> list[PowerRail]:
    rails = [
        PowerRail(f"{base}[{i}]", seq_type="output") for i in range(n)
    ]
    set_group_metadata(rails, base, width_expr, dims)
    return rails


class TestDimParamsModel:
    def test_set_group_metadata_stores_dims(self):
        rails = _dim_rails("V", "NUM_CPU*NUM_CPU_MEM", 4, ["NUM_CPU", "NUM_CPU_MEM"])
        assert all(r.dim_params == ["NUM_CPU", "NUM_CPU_MEM"] for r in rails)

    def test_scalar_clears_dims(self):
        rails = [PowerRail("S", seq_type="output", dim_params=["X"])]
        set_group_metadata(rails, None, "NUM_CPU")
        assert rails[0].dim_params == []

    def test_round_trip_dim_params(self):
        cfg = PowerSeqConfig(
            parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)],
            rails=_dim_rails("V", "NUM_CPU*NUM_CPU_MEM", 16, ["NUM_CPU", "NUM_CPU_MEM"]),
        )
        back = PowerSeqConfig.from_dict(cfg.to_dict())
        heads = [r for r in back.rails if r.group_base == "V"]
        assert len(heads) == 16  # 2 * 8
        assert heads[0].dim_params == ["NUM_CPU", "NUM_CPU_MEM"]

    def test_empty_dim_params_omitted(self):
        cfg = PowerSeqConfig(
            parameters=[Parameter("NUM_CPU", 2)],
            rails=_dim_rails("V", "NUM_CPU", 2, []),
        )
        group = next(r for r in cfg.to_dict()["rails"] if r.get("name") == "V")
        assert "dim_params" not in group


class TestVectorShapeLabel:
    _params = [Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)]

    def test_two_dim_shows_row_col(self):
        node = _dim_rails("V", "NUM_CPU*NUM_CPU_MEM", 16, ["NUM_CPU", "NUM_CPU_MEM"])
        assert vector_shape_label(node, self._params) == "2\u00d78"

    def test_one_dim_shows_total(self):
        node = _dim_rails("V", "NUM_CPU", 2, ["NUM_CPU"])
        assert vector_shape_label(node, self._params) == "\u00d72"

    def test_no_dims_shows_total(self):
        node = _dim_rails("V", "8", 8, [])
        assert vector_shape_label(node, self._params) == "\u00d78"

    def test_product_mismatch_falls_back(self):
        # dim_params 的乘積 (2*8=16) ≠ 實際 bit 數 (4) → 退回 ×N
        node = _dim_rails("V", "NUM_CPU*NUM_CPU_MEM", 4, ["NUM_CPU", "NUM_CPU_MEM"])
        assert vector_shape_label(node, self._params) == "\u00d74"


class TestTwoDimVerilogDeclaration:
    def _config(self, width_expr: str, n: int) -> PowerSeqConfig:
        return PowerSeqConfig(
            module_name="PWRSEQ_TOP",
            parameters=[Parameter("NUM_CPU", 2), Parameter("NUM_CPU_MEM", 8)],
            rails=_dim_rails("V", width_expr, n, ["NUM_CPU", "NUM_CPU_MEM"][: width_expr.count("*") + 1]),
        )

    def test_two_dim_bus_width(self):
        v = generate_verilog(self._config("NUM_CPU*NUM_CPU_MEM", 16))
        assert "[(NUM_CPU*NUM_CPU_MEM)-1:0]" in v

    def test_one_dim_bus_width(self):
        v = generate_verilog(self._config("NUM_CPU", 2))
        assert "[(NUM_CPU)-1:0]" in v
