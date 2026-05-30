"""
WaveDrom 時序模擬：依使用者定義的 input 波形 + output 依賴/cycle 推算各 rail 邏輯值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from config_models import PowerSeqConfig, PowerRail

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"


@dataclass
class InputWaveSpec:
    """單一 input 於匯出對話框的 hi/lo 設定（僅供模擬，不寫入 PowerRail）。"""

    hi_mode: str = "depends"  # constant_0 | constant_1 | custom | depends
    hi_wave: str = "0"
    hi_groups: list[list[str]] = field(default_factory=list)
    hi_inv_groups: list[list[bool]] = field(default_factory=list)
    hi_use_groups: list[list[str]] = field(default_factory=list)
    lo_mode: str = "constant_0"
    lo_wave: str = "0"
    lo_groups: list[list[str]] = field(default_factory=list)
    lo_inv_groups: list[list[bool]] = field(default_factory=list)
    lo_use_groups: list[list[str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> InputWaveSpec:
        return cls(
            hi_mode=d.get("hi_mode", "depends"),
            hi_wave=d.get("hi_wave", "0"),
            hi_groups=d.get("hi_groups") or [],
            hi_inv_groups=d.get("hi_inv_groups") or [],
            hi_use_groups=d.get("hi_use_groups") or [],
            lo_mode=d.get("lo_mode", "constant_0"),
            lo_wave=d.get("lo_wave", "0"),
            lo_groups=d.get("lo_groups") or [],
            lo_inv_groups=d.get("lo_inv_groups") or [],
            lo_use_groups=d.get("lo_use_groups") or [],
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
        if self.lo_groups:
            d["lo_groups"] = self.lo_groups
        if self.lo_inv_groups:
            d["lo_inv_groups"] = self.lo_inv_groups
        if self.lo_use_groups:
            d["lo_use_groups"] = self.lo_use_groups
        return d


@dataclass
class WaveDromScenario:
    steps: int = 200
    inputs: dict[str, InputWaveSpec] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> WaveDromScenario:
        inputs = {}
        for name, spec in (d.get("inputs") or {}).items():
            inputs[name] = InputWaveSpec.from_dict(spec) if isinstance(spec, dict) else InputWaveSpec()
        return cls(
            steps=int(d.get("steps", 200)),
            inputs=inputs,
        )

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
        }


@dataclass
class SimResult:
    steps: int
    pulse_active: list[set[str]]  # per step which pulses tick
    raw_inputs: dict[str, list[int]]
    output_hi_cond: dict[str, list[int]]
    output_lo_cond: dict[str, list[int]]
    output_values: dict[str, list[int]]
    output_states: dict[str, list[str]]


def _safe_name(name: str) -> str:
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


def _internal_sig(name: str) -> str:
    return _safe_name(name).lower()


def _pulse_scale_units(pulse_name: str) -> int:
    """相對於 1us 的倍率（用於判斷第幾步該 pulse tick）。"""
    if not pulse_name or pulse_name in ("default", "High"):
        return 1
    s = pulse_name.replace("iPulse_", "").lower()
    if s.endswith("us"):
        try:
            return max(1, int(s[:-2]))
        except ValueError:
            return 1
    if s.endswith("ms"):
        try:
            return max(1, int(s[:-2]) * 1000)
        except ValueError:
            return 1000
    return 1


def expand_wave_pattern(pattern: str, length: int) -> list[int]:
    """將 WaveDrom wave 字串展開為 length 個 0/1。支援 0/1/.| 與重複數字。"""
    if length <= 0:
        return []
    mode = pattern.strip()
    if not mode:
        return [0] * length

    if mode in ("constant_0", "0"):
        return [0] * length
    if mode in ("constant_1", "1"):
        return [1] * length

    out: list[int] = []
    prev = 0
    i = 0
    while len(out) < length and i < len(mode):
        ch = mode[i]
        if ch in "01":
            prev = int(ch)
            out.append(prev)
            i += 1
        elif ch == ".":
            out.append(prev)
            i += 1
        elif ch == "|":
            out.append(prev)
            i += 1
        elif ch.isdigit():
            j = i
            while j < len(mode) and mode[j].isdigit():
                j += 1
            repeat = int(mode[i:j])
            fill = prev if ch == "." else prev
            if i > 0 and mode[i - 1] in "01":
                fill = int(mode[i - 1])
            for _ in range(repeat):
                if len(out) >= length:
                    break
                out.append(fill)
            i = j
        else:
            i += 1
    while len(out) < length:
        out.append(prev)
    return out[:length]


def _get_inv_use(
    gi: int,
    ii: int,
    dep: str,
    inv_groups: list[list[bool]],
    use_groups: list[list[str]],
) -> tuple[bool, str]:
    inv = False
    use = "self"
    try:
        inv = bool(inv_groups[gi][ii])
    except IndexError:
        pass
    try:
        use = use_groups[gi][ii]
    except IndexError:
        pass
    if dep in (DEP_HIGH, DEP_LOW):
        use = "self"
    return inv, use


def _eval_spec_groups(
    groups: list[list[str]],
    inv_groups: list[list[bool]],
    use_groups: list[list[str]],
    kind: str,
    name_to_rail: dict[str, PowerRail],
    raw: dict[str, int],
    out_hi: dict[str, int],
    out_lo: dict[str, int],
    out_val: dict[str, int],
) -> int:
    """評估 input 的 hi/lo 訊號條件（group 內 AND、groups 間 OR）。"""
    if not groups:
        return 0
    group_results = []
    for gi, group in enumerate(groups):
        if not group:
            continue
        terms = []
        for ii, d in enumerate(group):
            inv, use = _get_inv_use(gi, ii, d, inv_groups, use_groups)
            dep = name_to_rail.get(d)
            if dep and dep.seq_type == "output":
                sig = _internal_sig(d)
                fallback = out_val.get(sig, 0)
                if use == "hi":
                    v = out_hi.get(sig, fallback)
                elif use == "lo":
                    v = out_lo.get(sig, fallback)
                else:
                    v = fallback
                if inv:
                    v = 1 - v
            else:
                v = _eval_dep(
                    d, name_to_rail, raw, out_hi, out_lo, out_val,
                    inv, use,
                )
            terms.append(v)
        if terms:
            group_results.append(1 if all(terms) else 0)
    return 1 if any(group_results) else 0


def _input_inst_hi_lo(
    spec: InputWaveSpec,
    step: int,
    wave_bits: list[int],
    name_to_rail: dict[str, PowerRail],
    raw: dict[str, int],
    out_hi: dict[str, int],
    out_lo: dict[str, int],
    out_val: dict[str, int],
) -> tuple[int, int]:
    """當步 hi/lo 條件是否成立（供下一格延遲用）。"""
    if spec.hi_mode == "depends" and spec.hi_groups:
        hi = _eval_spec_groups(
            spec.hi_groups, spec.hi_inv_groups, spec.hi_use_groups, "hi",
            name_to_rail, raw, out_hi, out_lo, out_val,
        )
    elif spec.hi_mode == "constant_1":
        hi = 1
    elif spec.hi_mode == "constant_0":
        hi = 0
    elif spec.hi_mode == "custom":
        hi = wave_bits[step] if step < len(wave_bits) else 0
    else:
        hi = 0

    lo = 0
    if spec.lo_mode == "depends" and spec.lo_groups:
        lo = _eval_spec_groups(
            spec.lo_groups, spec.lo_inv_groups, spec.lo_use_groups, "lo",
            name_to_rail, raw, out_hi, out_lo, out_val,
        )
    return hi, lo


def _input_gpio_delayed(
    spec: InputWaveSpec,
    prev_hi: int,
    prev_lo: int,
    instant_hi: int,
    instant_lo: int,
) -> int:
    """常數/自訂 wave 即時；訊號條件在上一格成立後本格才切換。"""
    if spec.hi_mode in ("constant_0", "constant_1", "custom"):
        v = instant_hi
    elif spec.hi_mode == "depends" and spec.hi_groups:
        v = 1 if prev_hi else 0
    else:
        v = 0
    if spec.lo_mode == "depends" and spec.lo_groups and prev_lo:
        return 0
    return v


def _eval_dep(
    dep_name: str,
    name_to_rail: dict[str, PowerRail],
    raw: dict[str, int],
    out_hi: dict[str, int],
    out_lo: dict[str, int],
    out_val: dict[str, int],
    inverted: bool,
    use_mode: str,
) -> int:
    if dep_name == DEP_HIGH:
        v = 0 if inverted else 1
        return v
    if dep_name == DEP_LOW:
        v = 1 if inverted else 0
        return v

    dep = name_to_rail.get(dep_name)
    if not dep or dep.seq_type == "input":
        v = raw.get(dep_name, 0)
    else:
        sig = _internal_sig(dep_name)
        if use_mode == "hi":
            v = out_hi.get(sig, 0)
        elif use_mode == "lo":
            v = out_lo.get(sig, 0)
        elif use_mode == "force":
            v = 0
        else:
            v = out_val.get(sig, 0)
    if inverted:
        return 1 - v
    return v


def _eval_groups(
    groups: list[list[str]],
    rail: PowerRail,
    kind: str,
    name_to_rail: dict[str, PowerRail],
    raw: dict[str, int],
    out_hi: dict[str, int],
    out_lo: dict[str, int],
    out_val: dict[str, int],
) -> int:
    if not groups:
        return 1 if kind == "hi" else 0

    get_inv = {"hi": rail.get_hi_inv, "lo": rail.get_lo_inv, "force": rail.get_force_inv}[kind]
    get_use = {"hi": rail.get_hi_use, "lo": rail.get_lo_use, "force": rail.get_force_use}[kind]

    group_results = []
    for gi, group in enumerate(groups):
        terms = []
        for ii, d in enumerate(group):
            use = get_use(gi, ii, d)
            inv = get_inv(gi, ii, d)
            if use == "self" and name_to_rail.get(d) and name_to_rail[d].seq_type == "output":
                # Align with c_generator: self on output → .hi/.lo.condition
                sig = _internal_sig(d)
                if kind == "hi":
                    v = out_hi.get(sig, 0)
                elif kind == "lo":
                    v = out_lo.get(sig, 0)
                else:
                    v = out_val.get(sig, 0)
                if inv:
                    v = 1 - v
            else:
                v = _eval_dep(
                    d, name_to_rail, raw, out_hi, out_lo, out_val,
                    inv, use,
                )
            terms.append(v)
        group_results.append(1 if all(terms) else 0)
    return 1 if any(group_results) else 0


def _finest_pulse_scale(pulses: list[str]) -> int:
    if not pulses:
        return 1
    return min(max(1, _pulse_scale_units(p)) for p in pulses)


def _pulses_active_at_step(step: int, pulses: list[str]) -> set[str]:
    """每步以最細 pulse 為時間格，較慢 pulse 依比例 tick。"""
    active: set[str] = set()
    base_scale = _finest_pulse_scale(pulses)
    for p in pulses or ["iPulse_1us"]:
        scale = max(1, _pulse_scale_units(p))
        rel = max(1, scale // base_scale)
        if step % rel == 0:
            active.add(p)
    return active or {"iPulse_1us"}


class _OutputFsm:
    """WaveDrom output：不模擬 cycle/pulse；上一格條件成立 → 本格切換。

    低→高：僅看 prev_hi。高→低：僅看 prev_lo，且上一格 hi/lo 不可同時成立（避免抖盪）。
    """

    def __init__(self, rail: PowerRail):
        self._rail = rail
        self.output = 1 if rail.init else 0
        self.prev_hi = 0
        self.prev_lo = 0

    def tick(self, hi_cond: int, lo_cond: int, force_cond: int) -> int:
        if force_cond:
            self.output = 1 if self._rail.force_val else 0
            self.prev_hi = 0
            self.prev_lo = 0
            return self.output

        if self.output == 0 and self.prev_hi:
            self.output = 1
        elif self.output == 1 and self.prev_lo and not (self.prev_hi and self.prev_lo):
            self.output = 0

        self.prev_hi = hi_cond
        self.prev_lo = lo_cond
        return self.output


def default_scenario_for_config(config: PowerSeqConfig) -> WaveDromScenario:
    """為所有 input 建立預設 scenario（PG 類預設延遲拉高）。"""
    inputs = {}
    for r in config.rails:
        if r.seq_type != "input":
            continue
        inputs[r.name] = InputWaveSpec(
            hi_mode="depends",
            lo_mode="constant_0",
        )
    return WaveDromScenario(steps=200, inputs=inputs)


def simulate(config: PowerSeqConfig, scenario: WaveDromScenario) -> SimResult:
    """執行離散 pulse 模擬，回傳各軌跡。"""
    steps = max(10, scenario.steps)
    pulses = list(config.pulses or ["iPulse_1us"])

    name_to_rail = {r.name: r for r in config.rails}
    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs = [r for r in config.rails if r.has_pseqcell]

    pulse_active = [_pulses_active_at_step(t, pulses) for t in range(steps)]

    input_specs: dict[str, InputWaveSpec] = {}
    input_waves: dict[str, list[int]] = {}
    for r in inputs:
        spec = scenario.inputs.get(r.name) or InputWaveSpec()
        input_specs[r.name] = spec
        if spec.hi_mode == "custom":
            input_waves[r.name] = expand_wave_pattern(spec.hi_wave, steps)
        else:
            input_waves[r.name] = [0] * steps

    raw_inputs: dict[str, list[int]] = {r.name: [] for r in inputs}
    input_prev_hi: dict[str, int] = {r.name: 0 for r in inputs}
    input_prev_lo: dict[str, int] = {r.name: 0 for r in inputs}

    fsms = {_internal_sig(r.name): _OutputFsm(r) for r in outputs}

    out_hi: dict[str, list[int]] = {s: [] for s in fsms}
    out_lo: dict[str, list[int]] = {s: [] for s in fsms}
    out_val: dict[str, list[int]] = {s: [] for s in fsms}
    out_state: dict[str, list[str]] = {s: [] for s in fsms}

    out_val_prev: dict[str, int] = {
        _internal_sig(r.name): 1 if r.init else 0 for r in outputs
    }

    for t in range(steps):
        raw_t: dict[str, int] = {}
        hi_t: dict[str, int] = {}
        lo_t: dict[str, int] = {}

        for rail in config.rails:
            if rail.seq_type != "input":
                continue
            spec = input_specs[rail.name]
            inst_hi, inst_lo = _input_inst_hi_lo(
                spec, t, input_waves[rail.name], name_to_rail,
                raw_t, hi_t, lo_t, out_val_prev,
            )
            if spec.hi_mode in ("constant_0", "constant_1", "custom"):
                raw_t[rail.name] = _input_gpio_delayed(
                    spec, 0, 0, inst_hi, inst_lo,
                )
            else:
                raw_t[rail.name] = (
                    raw_inputs[rail.name][-1] if raw_inputs[rail.name] else 0
                )

        force_t: dict[str, int] = {}
        for rail in outputs:
            sig = _internal_sig(rail.name)
            hi_t[sig] = _eval_groups(
                rail.get_hi_groups(), rail, "hi", name_to_rail,
                raw_t, hi_t, lo_t, out_val_prev,
            )
            lo_t[sig] = _eval_groups(
                rail.get_lo_groups(), rail, "lo", name_to_rail,
                raw_t, hi_t, lo_t, out_val_prev,
            )
            force_t[sig] = _eval_groups(
                rail.get_force_groups(), rail, "force", name_to_rail,
                raw_t, hi_t, lo_t, out_val_prev,
            )
            out_hi[sig].append(hi_t[sig])
            out_lo[sig].append(lo_t[sig])

        for rail in outputs:
            sig = _internal_sig(rail.name)
            v = fsms[sig].tick(hi_t[sig], lo_t[sig], force_t[sig])
            out_val[sig].append(v)
            out_state[sig].append("high" if v else "low")
            out_val_prev[sig] = v

        for rail in config.rails:
            if rail.seq_type != "input":
                continue
            spec = input_specs[rail.name]
            inst_hi, inst_lo = _input_inst_hi_lo(
                spec, t, input_waves[rail.name], name_to_rail,
                raw_t, hi_t, lo_t, out_val_prev,
            )
            if spec.hi_mode in ("constant_0", "constant_1", "custom"):
                gpio = raw_t[rail.name]
            else:
                gpio = _input_gpio_delayed(
                    spec,
                    input_prev_hi[rail.name],
                    input_prev_lo[rail.name],
                    inst_hi,
                    inst_lo,
                )
                raw_t[rail.name] = gpio
            raw_inputs[rail.name].append(gpio)
            input_prev_hi[rail.name] = inst_hi
            input_prev_lo[rail.name] = inst_lo

    return SimResult(
        steps=steps,
        pulse_active=pulse_active,
        raw_inputs=raw_inputs,
        output_hi_cond=out_hi,
        output_lo_cond=out_lo,
        output_values=out_val,
        output_states=out_state,
    )


def _bits_runs(bits: list[int]) -> list[tuple[int, int]]:
    if not bits:
        return []
    runs: list[tuple[int, int]] = []
    cur = bits[0]
    run = 1
    for b in bits[1:]:
        if b == cur:
            run += 1
        else:
            runs.append((cur, run))
            cur = b
            run = 1
    runs.append((cur, run))
    return runs


def _dot_encode(bits: list[int]) -> str:
    """WaveDrom ``0``/``1`` with ``.`` hold (e.g. ``0.1.``)."""
    if not bits:
        return "0"
    prev = bits[0]
    out = str(prev)
    for b in bits[1:]:
        if b == prev:
            out += "."
        else:
            out += str(b)
            prev = b
    return out


def values_to_wave(bits: list[int]) -> str:
    """Encode 0/1 bits for WaveJSON export (WaveDrom editor semantics).

    Each wave character is one time step; ``.`` holds the previous level.
    Do not use ``{level}{count}`` (e.g. ``1200``): ``2``–``9`` are bus/data symbols.
    """
    if not bits:
        return "0"
    runs = _bits_runs(bits)
    if len(runs) == 1:
        level, count = runs[0]
        ch = str(level)
        if count == 1:
            return ch
        if count == 2:
            return ch + ch
        # Flat run: bookend level, dots between (e.g. 200 highs -> "1" + "."*198 + "1").
        return ch + "." * (count - 2) + ch
    return _dot_encode(bits)


def expand_binary_wave(wave: str, length: int) -> list[int]:
    """Expand exported 0/1/. wave to per-step bits (WaveDrom hold semantics)."""
    if length <= 0:
        return []
    out: list[int] = []
    prev = 0
    i = 0
    while len(out) < length and i < len(wave):
        ch = wave[i]
        if ch == "0":
            prev = 0
            out.append(0)
            i += 1
        elif ch == "1":
            prev = 1
            out.append(1)
            i += 1
        elif ch == ".":
            out.append(prev)
            i += 1
        else:
            return expand_wave_pattern(wave, length)
    while len(out) < length:
        out.append(prev)
    return out[:length]
