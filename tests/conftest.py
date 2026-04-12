"""Pytest fixtures for Power Sequence Generator tests."""
import json
import os

import pytest

# Add project root to path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_models import PowerSeqConfig, PowerRail


@pytest.fixture
def sample_config_dict():
    """Sample config matching debug.json structure."""
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
