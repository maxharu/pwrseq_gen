"""
Power Sequence Configuration Data Models
依需求表：seq_type: output (輸出) | input (輸入)
"""
from dataclasses import dataclass, field

DEFAULT_PULSE = "Pulse_1us"


def _pulse_safe_name(name: str) -> str:
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


def normalize_pulse_name(name: str) -> str:
    """UI / config 用的 pulse 名稱（無 i 前綴；舊版 iPulse_* 載入時正規化）。"""
    if not name or name == "default":
        return DEFAULT_PULSE
    if name == "High":
        return "High"
    s = _pulse_safe_name(name)
    if s.startswith("iPulse_"):
        return s[1:]
    return s


def pulse_verilog_name(name: str) -> str:
    """Verilog 訊號名（i 前綴）。"""
    if not name or name == "default":
        return "iPulse_1us"
    if name == "High":
        return "1'b1"
    return "i" + normalize_pulse_name(name)


def _normalize_pulse_list(pulses: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in pulses or [DEFAULT_PULSE]:
        n = normalize_pulse_name(p)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out or [DEFAULT_PULSE]


@dataclass
class PowerRail:
    """
    單一 Sequence 節點
    seq_type: "output" | "input"
    """
    name: str
    seq_type: str = "output"
    depends_on: list[str] = field(default_factory=list)  # 舊版相容，對應 depends_on_hi
    depends_on_hi: list[str] = field(default_factory=list)  # iHi 依賴
    depends_on_lo: list[str] = field(default_factory=list)  # iLo 依賴（空則 wLo=1）
    depends_on_hi_inv: dict[str, bool] = field(default_factory=dict)  # dep_name -> 是否反相 (flat fallback)
    depends_on_lo_inv: dict[str, bool] = field(default_factory=dict)
    depends_on_hi_use: dict[str, str] = field(default_factory=dict)  # dep_name -> "self"|"hi"|"lo" (flat fallback)
    depends_on_lo_use: dict[str, str] = field(default_factory=dict)
    depends_on_hi_inv_groups: list[list[bool]] = field(default_factory=list)  # per-group per-item inv
    depends_on_lo_inv_groups: list[list[bool]] = field(default_factory=list)
    depends_on_hi_use_groups: list[list[str]] = field(default_factory=list)  # per-group per-item use
    depends_on_lo_use_groups: list[list[str]] = field(default_factory=list)
    depends_on_hi_groups: list[list[str]] = field(default_factory=list)  # F-DEP-08: group 內 &，group 間 |
    depends_on_lo_groups: list[list[str]] = field(default_factory=list)
    depends_on_hi_group_inv: list[bool] = field(default_factory=list)  # 反相整組結果
    depends_on_lo_group_inv: list[bool] = field(default_factory=list)
    depends_on_hi_intra_op: list[str] = field(default_factory=list)  # group 內 and|or|xor
    depends_on_lo_intra_op: list[str] = field(default_factory=list)
    # iForce 依賴（與 Hi/Lo 同款結構）：空則 wForce=top iForce port
    depends_on_force: list[str] = field(default_factory=list)
    depends_on_force_inv: dict[str, bool] = field(default_factory=dict)
    depends_on_force_use: dict[str, str] = field(default_factory=dict)
    depends_on_force_inv_groups: list[list[bool]] = field(default_factory=list)
    depends_on_force_use_groups: list[list[str]] = field(default_factory=list)
    depends_on_force_groups: list[list[str]] = field(default_factory=list)
    depends_on_force_group_inv: list[bool] = field(default_factory=list)
    depends_on_force_intra_op: list[str] = field(default_factory=list)
    pulse_hi: str = DEFAULT_PULSE  # Hi 週期使用的 pulse（單一訊號）
    pulse_lo: str = DEFAULT_PULSE  # Lo 週期使用的 pulse
    pulse_force: str = DEFAULT_PULSE  # Force 使用的 pulse
    deb_enable: bool = True  # input 專用：是否啟用 Debounce
    deb_init: int = 0  # DEB INIT
    deb_cycle_hi: int = 2  # DEB CYCLE_HI
    deb_cycle_lo: int = 2  # DEB CYCLE_LO
    deb_cycle_sync: int = 2  # DEB CYCLE_SYNC
    deb_pulse: str = DEFAULT_PULSE  # DEB iPulse_Sample
    # 時序模擬激勵（僅 input；非 Verilog depends_on）
    hi_mode: str = "depends"
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
    cycle_hi: int = 8
    cycle_lo: int = 4
    cycle_force: int = 2
    init: int = 0
    force_val: int = 0

    @property
    def has_pseqcell(self) -> bool:
        """是否有 PSEQCELL（非 input）"""
        return self.seq_type != "input"

    def get_hi_groups(self) -> list[list[str]]:
        """取得 Hi 依賴分組，無 groups 時回傳單一 group"""
        if self.depends_on_hi_groups:
            return self.depends_on_hi_groups
        return [self.depends_on_hi] if self.depends_on_hi else []

    def get_lo_groups(self) -> list[list[str]]:
        """取得 Lo 依賴分組，無 groups 時回傳單一 group"""
        if self.depends_on_lo_groups:
            return self.depends_on_lo_groups
        return [self.depends_on_lo] if self.depends_on_lo else []

    def get_force_groups(self) -> list[list[str]]:
        """取得 Force 依賴分組，無 groups 時回傳單一 group"""
        if self.depends_on_force_groups:
            return self.depends_on_force_groups
        return [self.depends_on_force] if self.depends_on_force else []

    def get_hi_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        if self.depends_on_hi_inv_groups:
            try:
                return self.depends_on_hi_inv_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_hi_inv.get(name, False)

    def get_lo_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        if self.depends_on_lo_inv_groups:
            try:
                return self.depends_on_lo_inv_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_lo_inv.get(name, False)

    def get_hi_use(self, group_idx: int, item_idx: int, name: str) -> str:
        if self.depends_on_hi_use_groups:
            try:
                return self.depends_on_hi_use_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_hi_use.get(name, "self")

    def get_lo_use(self, group_idx: int, item_idx: int, name: str) -> str:
        if self.depends_on_lo_use_groups:
            try:
                return self.depends_on_lo_use_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_lo_use.get(name, "self")

    def get_force_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        if self.depends_on_force_inv_groups:
            try:
                return self.depends_on_force_inv_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_force_inv.get(name, False)

    def get_force_use(self, group_idx: int, item_idx: int, name: str) -> str:
        if self.depends_on_force_use_groups:
            try:
                return self.depends_on_force_use_groups[group_idx][item_idx]
            except IndexError:
                pass
        return self.depends_on_force_use.get(name, "self")

    def get_hi_group_inv(self, group_idx: int) -> bool:
        try:
            return bool(self.depends_on_hi_group_inv[group_idx])
        except IndexError:
            return False

    def get_lo_group_inv(self, group_idx: int) -> bool:
        try:
            return bool(self.depends_on_lo_group_inv[group_idx])
        except IndexError:
            return False

    def get_force_group_inv(self, group_idx: int) -> bool:
        try:
            return bool(self.depends_on_force_group_inv[group_idx])
        except IndexError:
            return False

    def _get_intra_op(self, kind: str, group_idx: int) -> str:
        from group_logic import normalize_intra_op

        attr = f"depends_on_{kind}_intra_op"
        ops = getattr(self, attr, [])
        try:
            return normalize_intra_op(ops[group_idx])
        except IndexError:
            return "and"

    def get_hi_intra_op(self, group_idx: int) -> str:
        return self._get_intra_op("hi", group_idx)

    def get_lo_intra_op(self, group_idx: int) -> str:
        return self._get_intra_op("lo", group_idx)

    def get_force_intra_op(self, group_idx: int) -> str:
        return self._get_intra_op("force", group_idx)

    def get_depends_on_hi_flat(self) -> list[str]:
        """取得 Hi 依賴扁平列表（供驗證、拓撲用）"""
        groups = self.get_hi_groups()
        return [d for g in groups for d in g]

    def get_depends_on_lo_flat(self) -> list[str]:
        """取得 Lo 依賴扁平列表（供驗證、拓撲用）"""
        groups = self.get_lo_groups()
        return [d for g in groups for d in g]

    def get_depends_on_force_flat(self) -> list[str]:
        """取得 Force 依賴扁平列表（供驗證用）"""
        groups = self.get_force_groups()
        return [d for g in groups for d in g]


_INPUT_WAVE_RAIL_KEYS = frozenset({
    "hi_mode", "lo_mode", "hi_wave", "lo_wave",
    "hi_groups", "lo_groups", "hi_inv_groups", "lo_inv_groups",
    "hi_use_groups", "lo_use_groups",
    "hi_group_inv", "lo_group_inv", "hi_intra_op", "lo_intra_op",
})


def _rail_dict_has_input_wave(r: dict) -> bool:
    return any(k in r for k in _INPUT_WAVE_RAIL_KEYS)


def input_wave_to_dict(rail: PowerRail) -> dict:
    """Input 節點 Timing 欄位序列化（與 InputWaveSpec.to_dict 規則一致）。"""
    if rail.seq_type != "input":
        return {}
    d: dict = {"hi_mode": rail.hi_mode, "lo_mode": rail.lo_mode}
    if rail.hi_mode == "custom":
        d["hi_wave"] = rail.hi_wave
    if rail.lo_mode == "custom":
        d["lo_wave"] = rail.lo_wave
    if rail.hi_groups:
        d["hi_groups"] = rail.hi_groups
    if rail.hi_inv_groups:
        d["hi_inv_groups"] = rail.hi_inv_groups
    if rail.hi_use_groups:
        d["hi_use_groups"] = rail.hi_use_groups
    if any(rail.hi_group_inv):
        d["hi_group_inv"] = rail.hi_group_inv
    if rail.hi_intra_op:
        from group_logic import normalize_intra_op

        normed = [normalize_intra_op(o) for o in rail.hi_intra_op]
        if any(o != "and" for o in normed):
            d["hi_intra_op"] = normed
    if rail.lo_groups:
        d["lo_groups"] = rail.lo_groups
    if rail.lo_inv_groups:
        d["lo_inv_groups"] = rail.lo_inv_groups
    if rail.lo_use_groups:
        d["lo_use_groups"] = rail.lo_use_groups
    if any(rail.lo_group_inv):
        d["lo_group_inv"] = rail.lo_group_inv
    if rail.lo_intra_op:
        from group_logic import normalize_intra_op

        normed = [normalize_intra_op(o) for o in rail.lo_intra_op]
        if any(o != "and" for o in normed):
            d["lo_intra_op"] = normed
    return d


def apply_input_wave_dict(rail: PowerRail, data: dict) -> None:
    """將 Timing input 設定寫入 PowerRail（僅 input 語意）。"""
    rail.hi_mode = data.get("hi_mode", "depends")
    rail.hi_wave = data.get("hi_wave", "0")
    rail.hi_groups = data.get("hi_groups") or []
    rail.hi_inv_groups = data.get("hi_inv_groups") or []
    rail.hi_use_groups = data.get("hi_use_groups") or []
    rail.hi_group_inv = data.get("hi_group_inv") or []
    rail.hi_intra_op = data.get("hi_intra_op") or []
    rail.lo_mode = data.get("lo_mode", "constant_0")
    rail.lo_wave = data.get("lo_wave", "0")
    rail.lo_groups = data.get("lo_groups") or []
    rail.lo_inv_groups = data.get("lo_inv_groups") or []
    rail.lo_use_groups = data.get("lo_use_groups") or []
    rail.lo_group_inv = data.get("lo_group_inv") or []
    rail.lo_intra_op = data.get("lo_intra_op") or []


def _timing_globals_from_dict(wd: dict | None) -> dict | None:
    """僅保留 steps / hscale（不含 inputs）。"""
    if not wd:
        return None
    out: dict = {}
    if "steps" in wd:
        out["steps"] = wd["steps"]
    hscale = wd.get("hscale", wd.get("cond_step_delay"))
    if hscale is not None and int(hscale) != 1:
        out["hscale"] = int(hscale)
    return out or None


def rail_input_wave_spec(rail: PowerRail):
    """PowerRail → InputWaveSpec（input 節點 Timing 設定）。"""
    from timing_sim import InputWaveSpec

    return InputWaveSpec(
        hi_mode=rail.hi_mode,
        hi_wave=rail.hi_wave,
        hi_groups=rail.hi_groups,
        hi_inv_groups=rail.hi_inv_groups,
        hi_use_groups=rail.hi_use_groups,
        hi_group_inv=rail.hi_group_inv,
        hi_intra_op=rail.hi_intra_op,
        lo_mode=rail.lo_mode,
        lo_wave=rail.lo_wave,
        lo_groups=rail.lo_groups,
        lo_inv_groups=rail.lo_inv_groups,
        lo_use_groups=rail.lo_use_groups,
        lo_group_inv=rail.lo_group_inv,
        lo_intra_op=rail.lo_intra_op,
    )


def build_timing_scenario(config: "PowerSeqConfig"):
    """由 config（rails + 全域 timing_scenario）組出 TimingScenario。"""
    from timing_sim import TimingScenario, _norm_hscale

    wd = config.timing_scenario or {}
    steps = int(wd.get("steps", 50))
    hscale = _norm_hscale(int(wd.get("hscale", wd.get("cond_step_delay", 1))))
    inputs = {
        r.name: rail_input_wave_spec(r)
        for r in config.rails
        if r.seq_type == "input"
    }
    return TimingScenario(steps=steps, hscale=hscale, inputs=inputs)


def _normalize_rail_after_load(rail: PowerRail) -> None:
    """載入後：groups 與扁平欄位互相同步（執行期用）。"""
    for kind in ("hi", "lo", "force"):
        groups_attr = f"depends_on_{kind}_groups"
        flat_attr = f"depends_on_{kind}"
        inv_g_attr = f"depends_on_{kind}_inv_groups"
        use_g_attr = f"depends_on_{kind}_use_groups"
        inv_attr = f"depends_on_{kind}_inv"
        use_attr = f"depends_on_{kind}_use"
        groups = getattr(rail, groups_attr)
        flat = getattr(rail, flat_attr)
        if not groups and flat:
            setattr(rail, groups_attr, [list(flat)])
            inv_flat = getattr(rail, inv_attr)
            use_flat = getattr(rail, use_attr)
            if flat and not getattr(rail, inv_g_attr):
                setattr(
                    rail,
                    inv_g_attr,
                    [[bool(inv_flat.get(n, False)) for n in flat]],
                )
            if flat and not getattr(rail, use_g_attr):
                setattr(
                    rail,
                    use_g_attr,
                    [[str(use_flat.get(n, "self")) for n in flat]],
                )
        elif groups:
            setattr(rail, flat_attr, [n for g in groups for n in g])
    rail.depends_on = list(rail.depends_on_hi)


def _cond_kind_to_dict(rail: PowerRail, kind: str) -> dict:
    groups_fn = getattr(rail, f"get_{kind}_groups")
    groups = groups_fn()
    if not groups or not any(groups):
        return {}
    out: dict = {f"depends_on_{kind}_groups": groups}
    inv_g = getattr(rail, f"depends_on_{kind}_inv_groups")
    use_g = getattr(rail, f"depends_on_{kind}_use_groups")
    g_inv = getattr(rail, f"depends_on_{kind}_group_inv")
    intra = getattr(rail, f"depends_on_{kind}_intra_op")
    if inv_g:
        out[f"depends_on_{kind}_inv_groups"] = inv_g
    if use_g:
        out[f"depends_on_{kind}_use_groups"] = use_g
    if any(g_inv):
        out[f"depends_on_{kind}_group_inv"] = g_inv
    if intra:
        from group_logic import normalize_intra_op

        normed = [normalize_intra_op(o) for o in intra]
        if any(o != "and" for o in normed) or len(normed) == len(groups):
            out[f"depends_on_{kind}_intra_op"] = normed[: len(groups)]
    return out


def _rail_to_dict(rail: PowerRail) -> dict:
    seq_label = "Output" if rail.seq_type == "output" else "Input"
    d: dict = {"name": rail.name, "seq_type": seq_label}
    if rail.seq_type == "input":
        d["deb_enable"] = rail.deb_enable
        if rail.deb_enable:
            d["deb_init"] = rail.deb_init
            d["deb_cycle_hi"] = rail.deb_cycle_hi
            d["deb_cycle_lo"] = rail.deb_cycle_lo
            d["deb_cycle_sync"] = rail.deb_cycle_sync
            d["deb_pulse"] = rail.deb_pulse
        elif rail.deb_init:
            d["deb_init"] = rail.deb_init
        d.update(input_wave_to_dict(rail))
        return d
    d.update(
        {
            "cycle_hi": rail.cycle_hi,
            "cycle_lo": rail.cycle_lo,
            "cycle_force": rail.cycle_force,
            "init": rail.init,
            "force_val": rail.force_val,
            "pulse_hi": rail.pulse_hi,
            "pulse_lo": rail.pulse_lo,
            "pulse_force": rail.pulse_force,
        }
    )
    for kind in ("hi", "lo", "force"):
        d.update(_cond_kind_to_dict(rail, kind))
    return d


@dataclass
class PowerSeqConfig:
    """完整 Power Sequence 規格"""
    rails: list[PowerRail] = field(default_factory=list)
    module_name: str = "PWRSEQ_TOP"
    clock_freq_mhz: float = 100.0
    pulse_period_ns: float = 100.0
    pulses: list[str] = field(default_factory=lambda: [DEFAULT_PULSE])  # Pulse 來源列表，每個為單一訊號（無 _Hi/_Lo/_Force）
    timing_scenario: dict | None = None  # 可選：Timing 匯出設定（見 timing_sim.TimingScenario）

    def rename_rail(self, old_name: str, new_name: str) -> bool:
        """重新命名一個 rail，並把所有其他 rail 的依賴 / inv / use 欄位中的舊名替換為新名。
        回傳是否實際完成（找不到 old 或 new==old 時回傳 False）。"""
        if not new_name or new_name == old_name:
            return False
        target = next((r for r in self.rails if r.name == old_name), None)
        if target is None:
            return False
        target.name = new_name
        for r in self.rails:
            r.depends_on = [new_name if n == old_name else n for n in r.depends_on]
            r.depends_on_hi = [new_name if n == old_name else n for n in r.depends_on_hi]
            r.depends_on_lo = [new_name if n == old_name else n for n in r.depends_on_lo]
            r.depends_on_force = [new_name if n == old_name else n for n in r.depends_on_force]
            r.depends_on_hi_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_hi_groups]
            r.depends_on_lo_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_lo_groups]
            r.depends_on_force_groups = [[new_name if n == old_name else n for n in g] for g in r.depends_on_force_groups]
            r.depends_on_hi_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_inv.items()}
            r.depends_on_lo_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_inv.items()}
            r.depends_on_force_inv = {new_name if k == old_name else k: v for k, v in r.depends_on_force_inv.items()}
            r.depends_on_hi_use = {new_name if k == old_name else k: v for k, v in r.depends_on_hi_use.items()}
            r.depends_on_lo_use = {new_name if k == old_name else k: v for k, v in r.depends_on_lo_use.items()}
            r.depends_on_force_use = {new_name if k == old_name else k: v for k, v in r.depends_on_force_use.items()}
            if r.seq_type == "input":
                for attr in ("hi_groups", "lo_groups"):
                    groups = getattr(r, attr)
                    setattr(
                        r,
                        attr,
                        [[new_name if n == old_name else n for n in g] for g in groups],
                    )
        return True

    def to_dict(self) -> dict:
        """轉換為可序列化的 dict（僅現行欄位；不含 depends_on 等舊版冗餘）。"""
        d = {
            "module_name": self.module_name,
            "clock_freq_mhz": self.clock_freq_mhz,
            "pulse_period_ns": self.pulse_period_ns,
            "pulses": self.pulses,
            "rails": [_rail_to_dict(r) for r in self.rails],
        }
        wd = _timing_globals_from_dict(self.timing_scenario)
        if wd:
            d["timing_scenario"] = wd
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PowerSeqConfig":
        """從 dict 建立"""
        wd_raw = d.get("timing_scenario") or {}
        legacy_inputs = (
            wd_raw.get("inputs") if isinstance(wd_raw.get("inputs"), dict) else {}
        )
        rails = []
        for r in d.get("rails", []):
            st = r.get("seq_type", "output")
            # 正規化為小寫，舊版相容
            st_lower = str(st).lower() if st else "output"
            if st_lower in ("power_rail", "signal", "output"):
                seq_type = "output"
            elif st_lower in ("external", "input"):
                seq_type = "input"
            else:
                seq_type = "output"
            dep_hi = r.get("depends_on_hi", r.get("depends_on", []))
            dep_lo = r.get("depends_on_lo", [])
            rail = PowerRail(
                name=r["name"],
                seq_type=seq_type,
                depends_on=dep_hi,
                depends_on_hi=dep_hi,
                depends_on_lo=dep_lo,
                depends_on_hi_inv=r.get("depends_on_hi_inv", {}),
                depends_on_lo_inv=r.get("depends_on_lo_inv", {}),
                depends_on_hi_use=r.get("depends_on_hi_use", {}),
                depends_on_lo_use=r.get("depends_on_lo_use", {}),
                depends_on_hi_inv_groups=r.get("depends_on_hi_inv_groups") or [],
                depends_on_lo_inv_groups=r.get("depends_on_lo_inv_groups") or [],
                depends_on_hi_use_groups=r.get("depends_on_hi_use_groups") or [],
                depends_on_lo_use_groups=r.get("depends_on_lo_use_groups") or [],
                depends_on_hi_groups=r.get("depends_on_hi_groups") or [],
                depends_on_lo_groups=r.get("depends_on_lo_groups") or [],
                depends_on_hi_group_inv=r.get("depends_on_hi_group_inv") or [],
                depends_on_lo_group_inv=r.get("depends_on_lo_group_inv") or [],
                depends_on_hi_intra_op=r.get("depends_on_hi_intra_op") or [],
                depends_on_lo_intra_op=r.get("depends_on_lo_intra_op") or [],
                depends_on_force=r.get("depends_on_force", []),
                depends_on_force_inv=r.get("depends_on_force_inv", {}),
                depends_on_force_use=r.get("depends_on_force_use", {}),
                depends_on_force_inv_groups=r.get("depends_on_force_inv_groups") or [],
                depends_on_force_use_groups=r.get("depends_on_force_use_groups") or [],
                depends_on_force_groups=r.get("depends_on_force_groups") or [],
                depends_on_force_group_inv=r.get("depends_on_force_group_inv") or [],
                depends_on_force_intra_op=r.get("depends_on_force_intra_op") or [],
                pulse_hi=normalize_pulse_name(r.get("pulse_hi", DEFAULT_PULSE)),
                pulse_lo=normalize_pulse_name(r.get("pulse_lo", DEFAULT_PULSE)),
                pulse_force=normalize_pulse_name(r.get("pulse_force", DEFAULT_PULSE)),
                deb_enable=r.get("deb_enable", False),
                deb_init=r.get("deb_init", 0),
                deb_cycle_hi=r.get("deb_cycle_hi", 2),
                deb_cycle_lo=r.get("deb_cycle_lo", 2),
                deb_cycle_sync=r.get("deb_cycle_sync", 2),
                deb_pulse=normalize_pulse_name(r.get("deb_pulse", DEFAULT_PULSE)),
                cycle_hi=r.get("cycle_hi", 8),
                cycle_lo=r.get("cycle_lo", 4),
                cycle_force=r.get("cycle_force", 2),
                init=r.get("init", 0),
                force_val=r.get("force_val", 0),
                hi_mode=r.get("hi_mode", "depends"),
                hi_wave=r.get("hi_wave", "0"),
                hi_groups=r.get("hi_groups") or [],
                hi_inv_groups=r.get("hi_inv_groups") or [],
                hi_use_groups=r.get("hi_use_groups") or [],
                hi_group_inv=r.get("hi_group_inv") or [],
                hi_intra_op=r.get("hi_intra_op") or [],
                lo_mode=r.get("lo_mode", "constant_0"),
                lo_wave=r.get("lo_wave", "0"),
                lo_groups=r.get("lo_groups") or [],
                lo_inv_groups=r.get("lo_inv_groups") or [],
                lo_use_groups=r.get("lo_use_groups") or [],
                lo_group_inv=r.get("lo_group_inv") or [],
                lo_intra_op=r.get("lo_intra_op") or [],
            )
            _normalize_rail_after_load(rail)
            if seq_type == "input" and not _rail_dict_has_input_wave(r):
                legacy = legacy_inputs.get(rail.name)
                if isinstance(legacy, dict):
                    apply_input_wave_dict(rail, legacy)
            rails.append(rail)
        timing_scenario = _timing_globals_from_dict(wd_raw)
        if timing_scenario is None and legacy_inputs:
            timing_scenario = {"steps": int(wd_raw.get("steps", 50))}
        return cls(
            rails=rails,
            module_name=d.get("module_name", "PWRSEQ_TOP"),
            clock_freq_mhz=d.get("clock_freq_mhz", 100.0),
            pulse_period_ns=d.get("pulse_period_ns", 100.0),
            pulses=_normalize_pulse_list(d.get("pulses")),
            timing_scenario=timing_scenario,
        )
