"""Pytest fixtures for Power Sequence Generator tests."""
import pytest

# 強制非互動式後端：headless 環境下渲染 PNG 不需要 Tk 視窗，
# 避免某些測試先 import tkinter 後 matplotlib 自動選 TkAgg 而失敗。
try:
    import matplotlib
    matplotlib.use("Agg")
except Exception:
    pass

# src/ 由 pyproject.toml 的 [tool.pytest.ini_options] pythonpath 加入 sys.path
from config_models import PowerSeqConfig, PowerRail


@pytest.fixture
def sample_config_dict():
    """Sample config for round-trip tests."""
    return {
        "module_name": "PWRSEQ_TOP",
        "clock_freq_mhz": 100.0,
        "pulse_period_ns": 100.0,
        "pulses": ["iPulse_1us", "iPulse_1ms"],
        "rails": [
            {
                "name": "SIG_1",
                "seq_type": "Input",
                "depends_on_hi": [],
                "depends_on_lo": [],
                "deb_enable": True,
            },
            {
                "name": "SIG_2",
                "seq_type": "Output",
                "depends_on_hi": ["SIG_1"],
                "depends_on_lo": ["SIG_3"],
                "depends_on_hi_inv": {"SIG_1": True},
            },
            {
                "name": "SIG_3",
                "seq_type": "Output",
                "depends_on_hi": ["SIG_2"],
                "depends_on_lo": ["__LOW__"],
            },
        ],
    }


@pytest.fixture
def minimal_config():
    """Minimal valid config - single output with __HIGH__."""
    return PowerSeqConfig(
        rails=[
            PowerRail(name="OUT1", seq_type="output", depends_on_hi=["__HIGH__"]),
        ]
    )
