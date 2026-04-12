"""
Power Sequence Configuration Data Models
依需求表：seq_type: output (輸出) | input (輸入)
"""
from dataclasses import dataclass, field


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
    pulse_hi: str = "iPulse_1us"  # Hi 週期使用的 pulse（單一訊號）
    pulse_lo: str = "iPulse_1us"  # Lo 週期使用的 pulse
    pulse_force: str = "iPulse_1us"  # Force 使用的 pulse
    deb_enable: bool = True  # input 專用：是否啟用 Debounce
    deb_init: int = 0  # DEB INIT
    deb_cycle_hi: int = 2  # DEB CYCLE_HI
    deb_cycle_lo: int = 2  # DEB CYCLE_LO
    deb_cycle_sync: int = 2  # DEB CYCLE_SYNC
    deb_pulse: str = "iPulse_1us"  # DEB iPulse_Sample
    cycle_hi: int = 8
    cycle_lo: int = 4
    cycle_force: int = 2
    recover: int = 3  # 2'b11
    init: int = 0
    force_val: int = 0
    cycle_sync: int = 0
    od: int = 0

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

    def get_depends_on_hi_flat(self) -> list[str]:
        """取得 Hi 依賴扁平列表（供驗證、拓撲用）"""
        groups = self.get_hi_groups()
        return [d for g in groups for d in g]

    def get_depends_on_lo_flat(self) -> list[str]:
        """取得 Lo 依賴扁平列表（供驗證、拓撲用）"""
        groups = self.get_lo_groups()
        return [d for g in groups for d in g]


@dataclass
class PowerSeqConfig:
    """完整 Power Sequence 規格"""
    rails: list[PowerRail] = field(default_factory=list)
    module_name: str = "PWRSEQ_TOP"
    clock_freq_mhz: float = 100.0
    pulse_period_ns: float = 100.0
    pulses: list[str] = field(default_factory=lambda: ["iPulse_1us"])  # Pulse 來源列表，每個為單一訊號（無 _Hi/_Lo/_Force）

    def to_dict(self) -> dict:
        """轉換為可序列化的 dict"""
        return {
            "module_name": self.module_name,
            "clock_freq_mhz": self.clock_freq_mhz,
            "pulse_period_ns": self.pulse_period_ns,
            "pulses": self.pulses,
            "rails": [
                {
                    "name": r.name,
                    "seq_type": "Output" if r.seq_type == "output" else "Input",
                    "depends_on": r.depends_on_hi or r.depends_on,
                    "depends_on_hi": r.depends_on_hi,
                    "depends_on_lo": r.depends_on_lo,
                    "depends_on_hi_inv": r.depends_on_hi_inv,
                    "depends_on_lo_inv": r.depends_on_lo_inv,
                    "depends_on_hi_use": r.depends_on_hi_use,
                    "depends_on_lo_use": r.depends_on_lo_use,
                    "depends_on_hi_inv_groups": r.depends_on_hi_inv_groups if r.depends_on_hi_inv_groups else None,
                    "depends_on_lo_inv_groups": r.depends_on_lo_inv_groups if r.depends_on_lo_inv_groups else None,
                    "depends_on_hi_use_groups": r.depends_on_hi_use_groups if r.depends_on_hi_use_groups else None,
                    "depends_on_lo_use_groups": r.depends_on_lo_use_groups if r.depends_on_lo_use_groups else None,
                    "depends_on_hi_groups": r.depends_on_hi_groups if r.depends_on_hi_groups else None,
                    "depends_on_lo_groups": r.depends_on_lo_groups if r.depends_on_lo_groups else None,
                    "pulse_hi": r.pulse_hi,
                    "pulse_lo": r.pulse_lo,
                    "pulse_force": r.pulse_force,
                    "deb_enable": r.deb_enable,
                    "deb_init": r.deb_init,
                    "deb_cycle_hi": r.deb_cycle_hi,
                    "deb_cycle_lo": r.deb_cycle_lo,
                    "deb_cycle_sync": r.deb_cycle_sync,
                    "deb_pulse": r.deb_pulse,
                    "cycle_hi": r.cycle_hi,
                    "cycle_lo": r.cycle_lo,
                    "cycle_force": r.cycle_force,
                    "recover": r.recover,
                    "init": r.init,
                    "force_val": r.force_val,
                    "cycle_sync": r.cycle_sync,
                    "od": r.od,
                }
                for r in self.rails
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PowerSeqConfig":
        """從 dict 建立"""
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
            rails.append(
                PowerRail(
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
                    pulse_hi=r.get("pulse_hi", "iPulse_1us"),
                    pulse_lo=r.get("pulse_lo", "iPulse_1us"),
                    pulse_force=r.get("pulse_force", "iPulse_1us"),
                    deb_enable=r.get("deb_enable", False),
                    deb_init=r.get("deb_init", 0),
                    deb_cycle_hi=r.get("deb_cycle_hi", 2),
                    deb_cycle_lo=r.get("deb_cycle_lo", 2),
                    deb_cycle_sync=r.get("deb_cycle_sync", 2),
                    deb_pulse=r.get("deb_pulse", "iPulse_1us"),
                    cycle_hi=r.get("cycle_hi", 8),
                    cycle_lo=r.get("cycle_lo", 4),
                    cycle_force=r.get("cycle_force", 2),
                    recover=r.get("recover", 3),
                    init=r.get("init", 0),
                    force_val=r.get("force_val", 0),
                    cycle_sync=r.get("cycle_sync", 0),
                    od=r.get("od", 0),
                )
            )
        return cls(
            rails=rails,
            module_name=d.get("module_name", "PWRSEQ_TOP"),
            clock_freq_mhz=d.get("clock_freq_mhz", 100.0),
            pulse_period_ns=d.get("pulse_period_ns", 100.0),
            pulses=d.get("pulses") or ["iPulse_1us"],
        )
