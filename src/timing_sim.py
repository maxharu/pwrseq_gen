"""
時序邏輯模擬：依使用者定義的 input 波形 + output 依賴/cycle 推算各 rail 邏輯值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from config_models import PowerSeqConfig, PowerRail, DEFAULT_PULSE, normalize_pulse_name
from group_logic import eval_intra_op

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


def _norm_hscale(value: int) -> int:
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
            hscale = _norm_hscale(d["hscale"])
        elif "cond_step_delay" in d:
            hscale = _norm_hscale(d["cond_step_delay"])
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
    ui = normalize_pulse_name(pulse_name)
    s = ui[6:] if ui.startswith("Pulse_") else ui.lower()
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


def _expand_wave_tokens(
    s: str, i: int, prev: int, cap: int,
) -> tuple[list[int], int, int]:
    """遞迴展開 wave 表達式，直到字串結束或遇到未配對的 ')'。

    支援：0/1（位元）、./|（延續前一位元）、{n}（量詞，重複前一單位至剛好 n 次）、
    (...)（群組，可巢狀與被量化）、裸數字（沿用舊「重複前一電平」相容行為）。
    回傳 (bits, next_index, prev_level)。cap 用來避免巨量展開。
    """
    out: list[int] = []
    last_unit: list[int] | None = None  # 上一個單位的 bits（供 {n} 重複）
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch == ")":
            break
        if ch in "01":
            prev = int(ch)
            unit = [prev]
            out.extend(unit)
            last_unit = unit
            i += 1
        elif ch in ".|":
            unit = [prev]
            out.extend(unit)
            last_unit = unit
            i += 1
        elif ch == "(":
            sub, ni, prev = _expand_wave_tokens(s, i + 1, prev, cap)
            if ni < n and s[ni] == ")":
                ni += 1
            out.extend(sub)
            last_unit = sub
            i = ni
        elif ch == "{":
            j = i + 1
            while j < n and s[j].isdigit():
                j += 1
            num_str = s[i + 1:j]
            if j < n and s[j] == "}":
                j += 1
            if num_str and last_unit is not None:
                count = int(num_str)
                base = len(out) - len(last_unit)
                if count <= 0:
                    del out[base:]
                    last_unit = None
                else:
                    for _ in range(count - 1):
                        if len(out) >= cap:
                            break
                        out.extend(last_unit)
                    if last_unit:
                        prev = last_unit[-1]
            i = j
        elif ch.isdigit():
            # 舊版裸數字：重複前一電平（向後相容）
            j = i
            while j < n and s[j].isdigit():
                j += 1
            repeat = int(s[i:j])
            for _ in range(repeat):
                if len(out) >= cap:
                    break
                out.append(prev)
            last_unit = [prev] * repeat if repeat > 0 else None
            i = j
        else:
            i += 1
    return out, i, prev


def expand_wave_pattern(pattern: str, length: int) -> list[int]:
    """將 wave 字串展開為 length 個 0/1。

    支援 0/1/./|、量詞 {n} 與群組 (...)（regex 風格），例如 0{29}1、(10){3}。
    不足以 length 時補最後電平、超過則截斷。
    """
    if length <= 0:
        return []
    mode = pattern.strip()
    if mode in ("", "constant_0", "0"):
        return [0] * length
    if mode in ("constant_1", "1"):
        return [1] * length

    bits, _, _ = _expand_wave_tokens(mode, 0, 0, length)
    if not bits:
        return [0] * length
    if len(bits) < length:
        bits = bits + [bits[-1]] * (length - len(bits))
    return bits[:length]


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
    group_inv: list[bool] | None = None,
    intra_op: list[str] | None = None,
) -> int:
    """評估 input 的 hi/lo 訊號條件（group 內 Operation、groups 間 OR）。"""
    if not groups:
        return 0
    group_inv = group_inv or []
    intra_op = intra_op or []
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
            op = intra_op[gi] if gi < len(intra_op) else "and"
            gr = eval_intra_op(op, terms)
            if gi < len(group_inv) and group_inv[gi]:
                gr = 1 - gr
            group_results.append(gr)
    return 1 if any(group_results) else 0


def _input_inst_hi_lo(
    spec: InputWaveSpec,
    step: int,
    hi_wave_bits: list[int],
    lo_wave_bits: list[int],
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
            spec.hi_group_inv, spec.hi_intra_op,
        )
    elif spec.hi_mode == "constant_1":
        hi = 1
    elif spec.hi_mode == "constant_0":
        hi = 0
    elif spec.hi_mode == "custom":
        hi = hi_wave_bits[step] if step < len(hi_wave_bits) else 0
    else:
        hi = 0

    lo = 0
    if spec.lo_mode == "depends" and spec.lo_groups:
        lo = _eval_spec_groups(
            spec.lo_groups, spec.lo_inv_groups, spec.lo_use_groups, "lo",
            name_to_rail, raw, out_hi, out_lo, out_val,
            spec.lo_group_inv, spec.lo_intra_op,
        )
    elif spec.lo_mode == "custom":
        lo = lo_wave_bits[step] if step < len(lo_wave_bits) else 0
    return hi, lo


def _input_permit_hi_c(spec: InputWaveSpec, inst_hi: int) -> int:
    """Hi 用於 hi∧lo permit 衝突（含 constant/custom 的即時 hi）。"""
    if spec.hi_mode == "depends" and spec.hi_groups:
        return 1 if inst_hi else 0
    if spec.hi_mode == "constant_1":
        return 1
    if spec.hi_mode == "custom":
        return 1 if inst_hi else 0
    return 0


def _input_enable_flags(spec: InputWaveSpec) -> tuple[bool, bool]:
    enable_hi = (
        (spec.hi_mode == "depends" and bool(spec.hi_groups))
        or spec.hi_mode == "custom"
    )
    enable_lo = (
        (spec.lo_mode == "depends" and bool(spec.lo_groups))
        or spec.lo_mode == "custom"
    )
    return enable_hi, enable_lo


def _input_apply_armed(spec: InputWaveSpec, fsm: _PermitGpioFsm) -> int:
    """Phase A：套用上一拍 arm 的邊，回傳當拍 GPIO（不評估條件，順序無關）。"""
    enable_hi, enable_lo = _input_enable_flags(spec)
    if spec.hi_mode == "constant_0":
        return 0
    if spec.hi_mode == "constant_1":
        if enable_lo:
            fsm.apply_armed(rise_on_hi=False, fall_on_lo=True)
            return fsm.gpio
        return 1
    if enable_hi or enable_lo:
        fsm.apply_armed(rise_on_hi=enable_hi, fall_on_lo=enable_lo)
    return fsm.gpio


def _input_rearm(
    spec: InputWaveSpec, inst_hi: int, inst_lo: int, fsm: _PermitGpioFsm,
) -> None:
    """Phase B：依當拍條件重新 arm（下一拍才翻轉）。"""
    enable_hi, enable_lo = _input_enable_flags(spec)
    if spec.hi_mode == "constant_0":
        return
    if spec.hi_mode == "constant_1":
        if enable_lo:
            lo_c = 1 if inst_lo else 0
            fsm.rearm(1, lo_c, rise_on_hi=False, fall_on_lo=True)
        return
    if enable_hi or enable_lo:
        hi_c = _input_permit_hi_c(spec, inst_hi)
        lo_c = (1 if inst_lo else 0) if enable_lo else 0
        fsm.rearm(hi_c, lo_c, rise_on_hi=enable_hi, fall_on_lo=enable_lo)


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
    get_group_inv = {"hi": rail.get_hi_group_inv, "lo": rail.get_lo_group_inv,
                     "force": rail.get_force_group_inv}[kind]
    get_intra_op = {"hi": rail.get_hi_intra_op, "lo": rail.get_lo_intra_op,
                    "force": rail.get_force_intra_op}[kind]

    group_results = []
    for gi, group in enumerate(groups):
        terms = []
        for ii, d in enumerate(group):
            use = get_use(gi, ii, d)
            inv = get_inv(gi, ii, d)
            # self on output → 該 rail 實際輸出準位（out_val），對齊 Verilog/C；
            # use=hi/lo/force 才走條件欄位。由 _eval_dep 統一處理。
            v = _eval_dep(
                d, name_to_rail, raw, out_hi, out_lo, out_val,
                inv, use,
            )
            terms.append(v)
        gr = eval_intra_op(get_intra_op(gi), terms)
        if get_group_inv(gi):
            gr = 1 - gr
        group_results.append(gr)
    return 1 if any(group_results) else 0


def _finest_pulse_scale(pulses: list[str]) -> int:
    if not pulses:
        return 1
    return min(max(1, _pulse_scale_units(p)) for p in pulses)


def _pulses_active_at_step(step: int, pulses: list[str]) -> set[str]:
    """每步以最細 pulse 為時間格，較慢 pulse 依比例 tick。"""
    active: set[str] = set()
    base_scale = _finest_pulse_scale(pulses)
    for p in pulses or [DEFAULT_PULSE]:
        scale = max(1, _pulse_scale_units(p))
        rel = max(1, scale // base_scale)
        if step % rel == 0:
            active.add(p)
    return active or {DEFAULT_PULSE}


class _PermitGpioFsm:
    """pwrcell permit rules; armed edge applies at start of next tick (sim step)."""

    def __init__(self, init: int = 0):
        self.gpio = init
        self.hi_permit = 0
        self.lo_permit = 0
        self._armed_hi = 0
        self._armed_lo = 0

    def apply_armed(
        self,
        *,
        rise_on_hi: bool = True,
        fall_on_lo: bool = True,
    ) -> int:
        """套用上一拍 arm 的邊（在 step 開頭、評估條件前）。與條件無關，順序無關。"""
        if rise_on_hi and self.gpio == 0 and self._armed_hi:
            self.gpio = 1
        elif fall_on_lo and self.gpio == 1 and self._armed_lo:
            self.gpio = 0
        return self.gpio

    def rearm(
        self,
        hi_c: int,
        lo_c: int,
        *,
        rise_on_hi: bool = True,
        fall_on_lo: bool = True,
    ) -> None:
        """依當拍條件重新 arm（下一拍才會套用）。"""
        hi_c = 1 if hi_c else 0
        lo_c = 1 if lo_c else 0
        if self.gpio:
            self.hi_permit = 0
            if not (hi_c and lo_c):
                self.lo_permit = 1 if fall_on_lo else 0
            self._armed_lo = 1 if (fall_on_lo and self.lo_permit and lo_c) else 0
            self._armed_hi = 0
        else:
            self.lo_permit = 0
            if not (hi_c and lo_c):
                self.hi_permit = 1 if rise_on_hi else 0
            self._armed_hi = 1 if (rise_on_hi and self.hi_permit and hi_c) else 0
            self._armed_lo = 0

    def tick(
        self,
        hi_c: int,
        lo_c: int,
        *,
        rise_on_hi: bool = True,
        fall_on_lo: bool = True,
    ) -> int:
        self.apply_armed(rise_on_hi=rise_on_hi, fall_on_lo=fall_on_lo)
        self.rearm(hi_c, lo_c, rise_on_hi=rise_on_hi, fall_on_lo=fall_on_lo)
        return self.gpio


class _OutputFsm:
    """Output GPIO — permit FSM + force."""

    def __init__(self, rail: PowerRail):
        self._rail = rail
        self._fsm = _PermitGpioFsm(1 if rail.init else 0)
        self._lo_ticks = 0

    @property
    def output(self) -> int:
        return self._fsm.gpio

    def _reset_pending(self) -> None:
        self._lo_ticks = 0
        self._fsm._armed_hi = 0
        self._fsm._armed_lo = 0

    def _pulse_active(self, pulse_name: str, active_pulses: set[str]) -> bool:
        return (pulse_name or DEFAULT_PULSE) in active_pulses

    def apply_step(self) -> int:
        """Pass A：套用上一拍 arm 的邊，回傳當拍 GPIO。與條件無關 → 順序無關。"""
        self._fsm.apply_armed()
        return self._fsm.gpio

    def commit(
        self,
        hi_cond: int,
        lo_cond: int,
        force_cond: int,
    ) -> int:
        """Pass B：依當拍（已套用邊的）準位評估條件，force 即時覆寫、否則 arm 下一拍。

        rise/fall 對稱：條件成立後下一 T 轉態，不模擬 cycle_hi/cycle_lo（邏輯預覽，非 RTL）。
        """
        if force_cond:
            self._fsm.hi_permit = 0
            self._fsm.lo_permit = 0
            self._reset_pending()
            self._fsm.gpio = 1 if self._rail.force_val else 0
            return self._fsm.gpio

        hi_c = 1 if hi_cond else 0
        lo_c = 1 if lo_cond else 0
        self._lo_ticks = 0
        self._fsm.rearm(hi_c, lo_c)
        return self._fsm.gpio


def _output_cond_predecessors(
    rail: PowerRail,
    name_to_rail: dict[str, PowerRail],
    input_specs: dict[str, InputWaveSpec],
) -> set[str]:
    """Output deps whose hi/lo/force condition must be evaluated before *rail*.

    use=self on an output reads GPIO (cur_val) and does not create an edge.
    Input deps expand to outputs referenced in that input's condition groups.
    """
    preds: set[str] = set()
    for kind in ("hi", "lo", "force"):
        groups = getattr(rail, f"get_{kind}_groups")()
        get_use = getattr(rail, f"get_{kind}_use")
        for gi, group in enumerate(groups or []):
            for ii, dep in enumerate(group):
                dr = name_to_rail.get(dep)
                if not dr:
                    continue
                use = get_use(gi, ii, dep)
                if dr.seq_type == "output":
                    if use in ("hi", "lo", "force"):
                        preds.add(dep)
                elif dr.seq_type == "input":
                    spec = input_specs.get(dep)
                    if spec:
                        for ig in (spec.hi_groups, spec.lo_groups):
                            for grp in ig or []:
                                for d2 in grp:
                                    r2 = name_to_rail.get(d2)
                                    if r2 and r2.seq_type == "output":
                                        preds.add(d2)
    return preds


def _output_hi_predecessors(
    rail: PowerRail,
    name_to_rail: dict[str, PowerRail],
    input_specs: dict[str, InputWaveSpec],
) -> set[str]:
    """Hi-path output deps only (legacy alias; prefer _output_cond_predecessors)."""
    return _output_cond_predecessors(rail, name_to_rail, input_specs)


def _outputs_topo_order(
    outputs: list[PowerRail],
    name_to_rail: dict[str, PowerRail],
    input_specs: dict[str, InputWaveSpec],
) -> list[PowerRail]:
    """Topological order for output condition evaluation (hi/lo/force use edges)."""
    by_name = {r.name: r for r in outputs}
    rail_index = {r.name: i for i, r in enumerate(outputs)}
    preds = {
        r.name: _output_cond_predecessors(r, name_to_rail, input_specs) for r in outputs
    }
    remaining = set(by_name)
    ordered: list[PowerRail] = []
    while remaining:
        ready = sorted(
            (n for n in remaining if not (preds[n] & remaining)),
            key=lambda n: rail_index[n],
        )
        if not ready:
            ready = [min(remaining, key=lambda n: rail_index[n])]
        for n in ready:
            ordered.append(by_name[n])
            remaining.remove(n)
    return ordered


def default_scenario_for_config(config: PowerSeqConfig) -> TimingScenario:
    """為所有 input 建立 scenario（優先使用 rail 上 Timing 欄位）。"""
    from config_models import build_timing_scenario

    return build_timing_scenario(config)


def simulate(config: PowerSeqConfig, scenario: TimingScenario) -> SimResult:
    """執行離散 pulse 模擬，回傳各軌跡。"""
    steps = max(10, scenario.steps)
    pulses = list(config.pulses or [DEFAULT_PULSE])

    name_to_rail = {r.name: r for r in config.rails}
    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs = [r for r in config.rails if r.has_pseqcell]

    pulse_active = [_pulses_active_at_step(t, pulses) for t in range(steps)]

    input_specs: dict[str, InputWaveSpec] = {}
    input_hi_waves: dict[str, list[int]] = {}
    input_lo_waves: dict[str, list[int]] = {}
    for r in inputs:
        spec = scenario.inputs.get(r.name) or InputWaveSpec()
        input_specs[r.name] = spec
        if spec.hi_mode == "custom":
            input_hi_waves[r.name] = expand_wave_pattern(spec.hi_wave, steps)
        else:
            input_hi_waves[r.name] = [0] * steps
        if spec.lo_mode == "custom":
            input_lo_waves[r.name] = expand_wave_pattern(spec.lo_wave, steps)
        else:
            input_lo_waves[r.name] = [0] * steps

    raw_inputs: dict[str, list[int]] = {r.name: [] for r in inputs}
    input_fsms: dict[str, _PermitGpioFsm] = {}
    for r in inputs:
        spec = input_specs[r.name]
        init = 1 if spec.hi_mode == "constant_1" else 0
        input_fsms[r.name] = _PermitGpioFsm(init)

    fsms = {
        _internal_sig(r.name): _OutputFsm(r) for r in outputs
    }

    out_hi: dict[str, list[int]] = {s: [] for s in fsms}
    out_lo: dict[str, list[int]] = {s: [] for s in fsms}
    out_val: dict[str, list[int]] = {s: [] for s in fsms}
    out_state: dict[str, list[str]] = {s: [] for s in fsms}

    out_val_prev: dict[str, int] = {
        _internal_sig(r.name): 1 if r.init else 0 for r in outputs
    }

    _instant_hi_modes = ("constant_0", "constant_1")

    for t in range(steps):
        raw_t: dict[str, int] = {
            r.name: (raw_inputs[r.name][-1] if raw_inputs[r.name] else 0)
            for r in inputs
        }
        hi_t: dict[str, int] = {}
        lo_t: dict[str, int] = {}

        # Phase A：套用上一拍 arm 的邊，更新所有 input 的當拍 GPIO。
        # 僅依各自上一拍的 arm，與條件無關 → 順序無關。
        for rail in inputs:
            raw_t[rail.name] = _input_apply_armed(
                input_specs[rail.name], input_fsms[rail.name],
            )

        # Outputs（兩段式，與 input 的 Phase A/B 同構）：
        # Pass A：先套用所有 output 上一拍 arm 的邊，得到當拍準位 cur_val（與條件無關 → 順序無關）。
        #         如此一來，即使是互為迴路的 self 依賴，Pass B 也讀得到來源的「當拍」準位，
        #         不會慢 1 步（消除拓樸序造成的回授 eval lag）。
        # Pass B1：依條件拓撲序評估所有 hi/lo/force（含 output.lo 等跨節點引用）。
        # Pass B2：再 commit FSM（順序與 B1 相同，僅寫入結果）。
        output_order = _outputs_topo_order(outputs, name_to_rail, input_specs)
        cur_val: dict[str, int] = dict(out_val_prev)
        for rail in outputs:
            sig = _internal_sig(rail.name)
            cur_val[sig] = fsms[sig].apply_step()

        force_t: dict[str, int] = {}
        # 條件圖可能有環（例：PWRGD.lo → RESET，RESET.hi ← PLTRST ← PWRGD）。
        # 迭代直到 hi/lo/force 收斂（通常 2 拍內；最多 len(outputs)+1）。
        for _ in range(len(outputs) + 1):
            changed = False
            for rail in output_order:
                sig = _internal_sig(rail.name)
                new_hi = _eval_groups(
                    rail.get_hi_groups(), rail, "hi", name_to_rail,
                    raw_t, hi_t, lo_t, cur_val,
                )
                new_lo = _eval_groups(
                    rail.get_lo_groups(), rail, "lo", name_to_rail,
                    raw_t, hi_t, lo_t, cur_val,
                )
                new_force = _eval_groups(
                    rail.get_force_groups(), rail, "force", name_to_rail,
                    raw_t, hi_t, lo_t, cur_val,
                )
                if (
                    hi_t.get(sig) != new_hi
                    or lo_t.get(sig) != new_lo
                    or force_t.get(sig) != new_force
                ):
                    changed = True
                hi_t[sig] = new_hi
                lo_t[sig] = new_lo
                force_t[sig] = new_force
            if not changed:
                break

        for rail in output_order:
            sig = _internal_sig(rail.name)
            out_hi[sig].append(hi_t[sig])
            out_lo[sig].append(lo_t[sig])
            v = fsms[sig].commit(hi_t[sig], lo_t[sig], force_t[sig])
            cur_val[sig] = v
            out_val[sig].append(v)
            out_state[sig].append("high" if v else "low")
            out_val_prev[sig] = v

        # Phase B：所有 output 算完後，依當拍（input GPIO + output）重新 arm 每個 input。
        # 此時 raw_t 已是當拍 input 值、out_val_prev 已含當拍 output 值 → 順序無關。
        for rail in inputs:
            spec = input_specs[rail.name]
            inst_hi, inst_lo = _input_inst_hi_lo(
                spec, t, input_hi_waves[rail.name], input_lo_waves[rail.name],
                name_to_rail, raw_t, hi_t, lo_t, out_val_prev,
            )
            _input_rearm(spec, inst_hi, inst_lo, input_fsms[rail.name])

        for rail in inputs:
            raw_inputs[rail.name].append(raw_t[rail.name])

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
