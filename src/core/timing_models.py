"""Timing 模擬用的資料模型（不依賴 config_models，避免循環 import）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputWaveSpec:
    """單一 input 於匯出對話框的 hi/lo 設定（僅供模擬，不寫入 PowerRail）。"""

    hi_mode: str = "depends"  # constant_0 | constant_1 | custom | depends
    hi_wave: str = "0"
    hi_groups: list[list[str]] = field(default_factory=list)
    hi_inv_groups: list[list[bool]] = field(default_factory=list)
    hi_use_groups: list[list[str]] = field(default_factory=list)
    hi_group_inv: list[bool] = field(default_factory=list)
    hi_intra_op: list[str] = field(default_factory=list)
    lo_mode: str = "constant_0"
    lo_wave: str = "0"
    lo_groups: list[list[str]] = field(default_factory=list)
    lo_inv_groups: list[list[bool]] = field(default_factory=list)
    lo_use_groups: list[list[str]] = field(default_factory=list)
    lo_group_inv: list[bool] = field(default_factory=list)
    lo_intra_op: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> InputWaveSpec:
        return cls(
            hi_mode=d.get("hi_mode", "depends"),
            hi_wave=d.get("hi_wave", "0"),
            hi_groups=d.get("hi_groups") or [],
            hi_inv_groups=d.get("hi_inv_groups") or [],
            hi_use_groups=d.get("hi_use_groups") or [],
            hi_group_inv=d.get("hi_group_inv") or [],
            hi_intra_op=d.get("hi_intra_op") or [],
            lo_mode=d.get("lo_mode", "constant_0"),
            lo_wave=d.get("lo_wave", "0"),
            lo_groups=d.get("lo_groups") or [],
            lo_inv_groups=d.get("lo_inv_groups") or [],
            lo_use_groups=d.get("lo_use_groups") or [],
            lo_group_inv=d.get("lo_group_inv") or [],
            lo_intra_op=d.get("lo_intra_op") or [],
        )

    def to_dict(self) -> dict:
        d = {"hi_mode": self.hi_mode, "lo_mode": self.lo_mode}
        if self.hi_mode == "custom":
            d["hi_wave"] = self.hi_wave
        if self.lo_mode == "custom":
            d["lo_wave"] = self.lo_wave
        if self.hi_groups:
            d["hi_groups"] = self.hi_groups
        if self.hi_inv_groups:
            d["hi_inv_groups"] = self.hi_inv_groups
        if self.hi_use_groups:
            d["hi_use_groups"] = self.hi_use_groups
        if any(self.hi_group_inv):
            d["hi_group_inv"] = self.hi_group_inv
        if self.hi_intra_op:
            d["hi_intra_op"] = self.hi_intra_op
        if self.lo_groups:
            d["lo_groups"] = self.lo_groups
        if self.lo_inv_groups:
            d["lo_inv_groups"] = self.lo_inv_groups
        if self.lo_use_groups:
            d["lo_use_groups"] = self.lo_use_groups
        if any(self.lo_group_inv):
            d["lo_group_inv"] = self.lo_group_inv
        if self.lo_intra_op:
            d["lo_intra_op"] = self.lo_intra_op
        return d


def norm_hscale(value: int) -> int:
    """Timing config.hscale — horizontal pixels per time step (min 1)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(100, n))


@dataclass
class TimingScenario:
    steps: int = 200
    inputs: dict[str, InputWaveSpec] = field(default_factory=dict)
    hscale: int = 1
    cond_step_delay: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> TimingScenario:
        inputs = {}
        for name, spec in (d.get("inputs") or {}).items():
            inputs[name] = InputWaveSpec.from_dict(spec) if isinstance(spec, dict) else InputWaveSpec()
        if "hscale" in d:
            hscale = norm_hscale(d["hscale"])
        elif "cond_step_delay" in d:
            hscale = norm_hscale(d["cond_step_delay"])
        else:
            hscale = 1
        return cls(
            steps=int(d.get("steps", 200)),
            inputs=inputs,
            hscale=hscale,
            cond_step_delay=1,
        )

    def to_dict(self) -> dict:
        d: dict = {
            "steps": self.steps,
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
        }
        if self.hscale != 1:
            d["hscale"] = self.hscale
        return d
