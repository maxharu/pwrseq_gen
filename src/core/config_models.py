"""
Power Sequence Configuration Data Models
依需求表：seq_type: output (輸出) | input (輸入)
"""
from dataclasses import InitVar, dataclass, field, fields

from core.naming import safe_name
from core.param_expr import eval_width
from core.timing_models import InputWaveSpec, TimingScenario, norm_hscale

DEFAULT_PULSE = "Pulse_1us"


def normalize_pulse_name(name: str) -> str:
    """UI / config 用的 pulse 名稱（無 i 前綴；舊版 iPulse_* 載入時正規化）。"""
    if not name or name == "default":
        return DEFAULT_PULSE
    if name == "High":
        return "High"
    s = safe_name(name)
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


def pulse_suffix(name: str) -> str | None:
    """`Pulse_1ms` / `iPulse_1ms` → `1ms`；High / default / 空 → None（不做 pulse 閘控）。"""
    if not name or name in ("default", "High"):
        return None
    s = normalize_pulse_name(name)
    if s.startswith("Pulse_"):
        s = s[len("Pulse_"):]
    return s or None


def parse_pulse_period(name: str) -> tuple[int, str] | None:
    """`Pulse_2ms` → `(2, 'ms')`；High / default 或解不出數字 → None。

    各後端都走這裡，名稱才不會「Verilog 認得、Draw.io 不認得」——`Pulse-1us` 這種
    含 `.`/`-`/空白的寫法會先被 `normalize_pulse_name` 正規化掉。
    """
    s = pulse_suffix(name)
    if s is None:
        return None
    for unit in ("us", "ms"):
        if s.endswith(unit):
            try:
                return int(s[: -len(unit)]), unit
            except ValueError:
                return None
    return None


def _normalize_pulse_list(pulses: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in pulses or [DEFAULT_PULSE]:
        n = normalize_pulse_name(p)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out or [DEFAULT_PULSE]


def _bit_name(base: str, index: int) -> str:
    """vector 第 i 個 bit 的 canonical 節點名（base[i]）。"""
    return f"{base}[{index}]"


class _Unset:
    """InitVar 哨兵：區分「呼叫端沒給該條件欄位」與「明確傳 None」。

    PowerRail 的條件欄位改委派給 cond 後，建構子仍要原封不動吃這些 kwargs。沒給時
    維持 ConditionConfig 自己的預設（空 list/dict）；明確傳 None 時照舊存 None，才能
    和過去 dataclass 欄位的行為逐一對齊。"""

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()


@dataclass
class ConditionConfig:
    """Verilog depends_on_{hi,lo,force}_* 條件資料與其存取器（A1 身份/條件分層）。

    從 PowerRail 原封搬出：只收 Verilog 條件相關欄位；input-wave 的 hi_groups/... 屬
    時序模擬激勵，留在 PowerRail 節點層。PowerRail 以 @property / 方法委派這裡的全部
    欄位與存取器，使 cond_ir / 五後端 / excel / widgets 呼叫端零改動。"""
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
        from core.group_logic import normalize_intra_op

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


# ConditionConfig 的欄位名（委派用）；委派迴圈與退化測試都以此為準。
_COND_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(ConditionConfig))


@dataclass
class PowerRail:
    """
    單一 Sequence 節點
    seq_type: "output" | "input"

    條件欄位（depends_on_{hi,lo,force}_*）已抽到 cond: ConditionConfig；本類別以
    @property 委派全部條件屬性與 get_* 存取器，建構子仍吃原本的條件 kwargs（經 InitVar
    路由進 cond），故 cond_ir / 五後端 / excel / widgets 等呼叫端完全不需改動。
    """
    name: str
    seq_type: str = "output"
    # 條件欄位改由 cond 保存；宣告成 InitVar 讓建構子維持原簽名，__post_init__ 路由進 cond。
    depends_on: InitVar = _UNSET
    depends_on_hi: InitVar = _UNSET
    depends_on_lo: InitVar = _UNSET
    depends_on_hi_inv: InitVar = _UNSET
    depends_on_lo_inv: InitVar = _UNSET
    depends_on_hi_use: InitVar = _UNSET
    depends_on_lo_use: InitVar = _UNSET
    depends_on_hi_inv_groups: InitVar = _UNSET
    depends_on_lo_inv_groups: InitVar = _UNSET
    depends_on_hi_use_groups: InitVar = _UNSET
    depends_on_lo_use_groups: InitVar = _UNSET
    depends_on_hi_groups: InitVar = _UNSET
    depends_on_lo_groups: InitVar = _UNSET
    depends_on_hi_group_inv: InitVar = _UNSET
    depends_on_lo_group_inv: InitVar = _UNSET
    depends_on_hi_intra_op: InitVar = _UNSET
    depends_on_lo_intra_op: InitVar = _UNSET
    depends_on_force: InitVar = _UNSET
    depends_on_force_inv: InitVar = _UNSET
    depends_on_force_use: InitVar = _UNSET
    depends_on_force_inv_groups: InitVar = _UNSET
    depends_on_force_use_groups: InitVar = _UNSET
    depends_on_force_groups: InitVar = _UNSET
    depends_on_force_group_inv: InitVar = _UNSET
    depends_on_force_intra_op: InitVar = _UNSET
    cond: ConditionConfig = field(default_factory=ConditionConfig)
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
    # vector 群組 metadata（扁平 rails + 群組 metadata）；非 vector 時用這組預設值，
    # 讓序列化與五後端行為與 A2 之前完全一致（group_base=None → to_dict 不收合）。
    group_base: str | None = None  # 所屬 vector 的 base 名；None=單一節點
    bit_index: int = 0  # 在群組內的 bit 位置
    width_expr: str = "1"  # 群組寬度字串（整數期 "2"；公式期如 "NUM_CPU*2"）
    dim_params: list[str] = field(default_factory=list)  # 所選 0~2 維名（row=dim_params[0]、col=dim_params[1]），供 take/slice 認得幾何

    def __post_init__(
        self,
        depends_on,
        depends_on_hi,
        depends_on_lo,
        depends_on_hi_inv,
        depends_on_lo_inv,
        depends_on_hi_use,
        depends_on_lo_use,
        depends_on_hi_inv_groups,
        depends_on_lo_inv_groups,
        depends_on_hi_use_groups,
        depends_on_lo_use_groups,
        depends_on_hi_groups,
        depends_on_lo_groups,
        depends_on_hi_group_inv,
        depends_on_lo_group_inv,
        depends_on_hi_intra_op,
        depends_on_lo_intra_op,
        depends_on_force,
        depends_on_force_inv,
        depends_on_force_use,
        depends_on_force_inv_groups,
        depends_on_force_use_groups,
        depends_on_force_groups,
        depends_on_force_group_inv,
        depends_on_force_intra_op,
    ) -> None:
        """把建構子收到的條件 kwargs 路由進 self.cond；未給（_UNSET）者保留 cond 預設。"""
        for name in _COND_FIELDS:
            value = locals()[name]
            if value is not _UNSET:
                setattr(self.cond, name, value)

    @property
    def has_pseqcell(self) -> bool:
        """是否有 PSEQCELL（非 input）"""
        return self.seq_type != "input"

    # --- 條件存取器委派：cond_ir / 後端以 getattr(rail, "get_<kind>_*") 取用，簽名需一致 ---
    def get_hi_groups(self) -> list[list[str]]:
        return self.cond.get_hi_groups()

    def get_lo_groups(self) -> list[list[str]]:
        return self.cond.get_lo_groups()

    def get_force_groups(self) -> list[list[str]]:
        return self.cond.get_force_groups()

    def get_hi_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        return self.cond.get_hi_inv(group_idx, item_idx, name)

    def get_lo_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        return self.cond.get_lo_inv(group_idx, item_idx, name)

    def get_hi_use(self, group_idx: int, item_idx: int, name: str) -> str:
        return self.cond.get_hi_use(group_idx, item_idx, name)

    def get_lo_use(self, group_idx: int, item_idx: int, name: str) -> str:
        return self.cond.get_lo_use(group_idx, item_idx, name)

    def get_force_inv(self, group_idx: int, item_idx: int, name: str) -> bool:
        return self.cond.get_force_inv(group_idx, item_idx, name)

    def get_force_use(self, group_idx: int, item_idx: int, name: str) -> str:
        return self.cond.get_force_use(group_idx, item_idx, name)

    def get_hi_group_inv(self, group_idx: int) -> bool:
        return self.cond.get_hi_group_inv(group_idx)

    def get_lo_group_inv(self, group_idx: int) -> bool:
        return self.cond.get_lo_group_inv(group_idx)

    def get_force_group_inv(self, group_idx: int) -> bool:
        return self.cond.get_force_group_inv(group_idx)

    def get_hi_intra_op(self, group_idx: int) -> str:
        return self.cond.get_hi_intra_op(group_idx)

    def get_lo_intra_op(self, group_idx: int) -> str:
        return self.cond.get_lo_intra_op(group_idx)

    def get_force_intra_op(self, group_idx: int) -> str:
        return self.cond.get_force_intra_op(group_idx)

    def get_depends_on_hi_flat(self) -> list[str]:
        return self.cond.get_depends_on_hi_flat()

    def get_depends_on_lo_flat(self) -> list[str]:
        return self.cond.get_depends_on_lo_flat()

    def get_depends_on_force_flat(self) -> list[str]:
        return self.cond.get_depends_on_force_flat()


def _make_cond_property(field_name: str) -> property:
    """產生把 rail.<field_name> 讀寫轉接到 rail.cond.<field_name> 的 property。"""

    def getter(self: PowerRail):
        return getattr(self.cond, field_name)

    def setter(self: PowerRail, value) -> None:
        setattr(self.cond, field_name, value)

    return property(getter, setter)


# 把每個條件欄位委派到 cond（覆蓋 InitVar 留下的類別屬性哨兵）。
for _cond_field in _COND_FIELDS:
    setattr(PowerRail, _cond_field, _make_cond_property(_cond_field))
del _cond_field


@dataclass
class VectorNode:
    """vector 作者層模型：一個 base 展開成 N 個獨立 PowerRail（canonical 名 base[i]）。

    只保存身份（base/seq_type）、寬度（width_expr 字串）與每 bit 的條件（ConditionConfig）；
    物理參數（pulse/deb/cycle）全 bit 共用，由上層填進 elaborate 出來的 rail。elaborate() 是
    Elaboration/Builder：width_expr → N（eval_width）→ N 個 PowerRail，每個帶群組 metadata。
    config 的持久化走 PowerSeqConfig.to_dict/from_dict（扁平 rails + 群組 metadata），不經此類別。
    """
    base: str
    seq_type: str = "output"
    width_expr: str = "1"
    bit_conds: list[ConditionConfig] = field(default_factory=list)

    def elaborate(self) -> list[PowerRail]:
        """展開成 N 個 PowerRail（base[0]..base[N-1]），每個帶群組 metadata 與自己的條件。"""
        n = eval_width(self.width_expr)
        rails: list[PowerRail] = []
        for i in range(n):
            cond = self.bit_conds[i] if i < len(self.bit_conds) else ConditionConfig()
            rail = PowerRail(name=_bit_name(self.base, i), seq_type=self.seq_type)
            rail.cond = cond
            rail.group_base = self.base
            rail.bit_index = i
            rail.width_expr = self.width_expr
            rails.append(rail)
        return rails


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
        from core.group_logic import normalize_intra_op

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
        from core.group_logic import normalize_intra_op

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


def rail_input_wave_spec(rail: PowerRail) -> InputWaveSpec:
    """PowerRail → InputWaveSpec（input 節點 Timing 設定）。"""
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


def build_timing_scenario(config: "PowerSeqConfig") -> TimingScenario:
    """由 config（rails + 全域 timing_scenario）組出 TimingScenario。"""
    wd = config.timing_scenario or {}
    steps = int(wd.get("steps", 50))
    hscale = norm_hscale(int(wd.get("hscale", wd.get("cond_step_delay", 1))))
    inputs = {
        r.name: rail_input_wave_spec(r)
        for r in config.rails
        if r.seq_type == "input"
    }
    return TimingScenario(steps=steps, hscale=hscale, inputs=inputs)


def merge_scenario_for_config(
    loaded: TimingScenario, config: "PowerSeqConfig",
) -> TimingScenario:
    """Keep only input nodes that exist in the current project."""
    defaults = build_timing_scenario(config)
    inputs: dict[str, InputWaveSpec] = {}
    for r in config.rails:
        if r.seq_type != "input":
            continue
        spec = loaded.inputs.get(r.name) or defaults.inputs.get(
            r.name, InputWaveSpec(),
        )
        inputs[r.name] = spec
        apply_input_wave_dict(r, spec.to_dict())
    return TimingScenario(
        steps=loaded.steps,
        inputs=inputs,
        hscale=loaded.hscale,
    )


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
        from core.group_logic import normalize_intra_op

        normed = [normalize_intra_op(o) for o in intra]
        if any(o != "and" for o in normed) or len(normed) == len(groups):
            out[f"depends_on_{kind}_intra_op"] = normed[: len(groups)]
    return out


def _rail_physical_dict(rail: PowerRail) -> dict:
    """節點的共用身份／物理欄位（不含條件）；vector 收合時全 bit 共用這一份。"""
    if rail.seq_type == "input":
        d: dict = {"deb_enable": rail.deb_enable}
        if rail.deb_enable:
            d["deb_init"] = rail.deb_init
            d["deb_cycle_hi"] = rail.deb_cycle_hi
            d["deb_cycle_lo"] = rail.deb_cycle_lo
            d["deb_cycle_sync"] = rail.deb_cycle_sync
            d["deb_pulse"] = rail.deb_pulse
        elif rail.deb_init:
            d["deb_init"] = rail.deb_init
        return d
    return {
        "cycle_hi": rail.cycle_hi,
        "cycle_lo": rail.cycle_lo,
        "cycle_force": rail.cycle_force,
        "init": rail.init,
        "force_val": rail.force_val,
        "pulse_hi": rail.pulse_hi,
        "pulse_lo": rail.pulse_lo,
        "pulse_force": rail.pulse_force,
    }


def _rail_cond_dict(rail: PowerRail) -> dict:
    """節點的逐 bit 條件欄位；vector 收合時每 bit 各存一份。"""
    if rail.seq_type == "input":
        return input_wave_to_dict(rail)
    d: dict = {}
    for kind in ("hi", "lo", "force"):
        d.update(_cond_kind_to_dict(rail, kind))
    return d


def _rail_to_dict(rail: PowerRail) -> dict:
    seq_label = "Output" if rail.seq_type == "output" else "Input"
    d: dict = {"name": rail.name, "seq_type": seq_label}
    d.update(_rail_physical_dict(rail))
    d.update(_rail_cond_dict(rail))
    return d


# from_dict 展開 vector 時，這些鍵是群組 metadata／逐 bit 容器，不屬於共用物理欄位。
_VECTOR_META_KEYS = frozenset({"name", "seq_type", "width_expr", "bits", "dim_params"})


def _group_to_dict(group: list[PowerRail]) -> dict:
    """把同群組的 N 個 rail 收合成一筆：base + width_expr + 共用物理 + 每 bit 條件。"""
    head = group[0]
    seq_label = "Output" if head.seq_type == "output" else "Input"
    d: dict = {
        "name": head.group_base,
        "seq_type": seq_label,
        "width_expr": head.width_expr,
    }
    if head.dim_params:
        d["dim_params"] = list(head.dim_params)
    d.update(_rail_physical_dict(head))
    d["bits"] = [_rail_cond_dict(r) for r in group]
    return d


def _collapse_rails_to_dicts(rails: list[PowerRail]) -> list[dict]:
    """序列化 rails：group_base 相同且連續的 rail 收合成一筆，其餘逐筆輸出。"""
    out: list[dict] = []
    i = 0
    n = len(rails)
    while i < n:
        base = rails[i].group_base
        if base is None:
            out.append(_rail_to_dict(rails[i]))
            i += 1
            continue
        group = [rails[i]]
        i += 1
        while i < n and rails[i].group_base == base:
            group.append(rails[i])
            i += 1
        out.append(_group_to_dict(group))
    return out


def _normalize_seq_type(st) -> str:
    """seq_type 正規化為 output/input（舊版 signal/external/power_rail 相容）。"""
    st_lower = str(st).lower() if st else "output"
    if st_lower in ("external", "input"):
        return "input"
    return "output"  # power_rail / signal / output / 未知


def _build_rail_from_dict(name: str, seq_type: str, r: dict) -> PowerRail:
    """由單筆 dict 欄位建一個 PowerRail（條件 + 物理），並做載入後正規化。

    單一節點與 vector 的每個 bit 都走這裡：vector bit 的 `r` 是「共用物理 + 該 bit 條件」
    的合併 dict，故建構邏輯只有這一份。"""
    dep_hi = r.get("depends_on_hi", r.get("depends_on", []))
    dep_lo = r.get("depends_on_lo", [])
    rail = PowerRail(
        name=name,
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
    return rail


def _expand_vector_dict(r: dict, seq_type: str, parameters=None) -> list[PowerRail]:
    """vector 收合 dict → N 個 PowerRail（base[i]），帶群組 metadata。

    N 由 eval_width(width_expr, parameters) 算出（width_expr 可為引用 parameter 的公式）；
    但 width_expr 字串本身原樣保留在每個 bit（C9 Verilog 符號寬度要用）。共用物理取自頂層，
    逐 bit 條件取自 bits[i]。
    """
    base = r["name"]
    width_expr = str(r.get("width_expr", "1"))
    n = eval_width(width_expr, parameters)
    bits = r.get("bits") or []
    dim_params = [str(p) for p in (r.get("dim_params") or []) if isinstance(p, str) and p][:2]
    physical = {k: v for k, v in r.items() if k not in _VECTOR_META_KEYS}
    out: list[PowerRail] = []
    for i in range(n):
        bit = bits[i] if i < len(bits) and isinstance(bits[i], dict) else {}
        rail = _build_rail_from_dict(_bit_name(base, i), seq_type, {**physical, **bit})
        rail.group_base = base
        rail.bit_index = i
        rail.width_expr = width_expr
        rail.dim_params = list(dim_params)
        out.append(rail)
    return out


@dataclass
class Parameter:
    """具名整數常數：width 公式可引用，Verilog #(parameter) / C #define 由此產生。"""
    name: str
    value: int


def _parse_parameters(raw) -> list["Parameter"]:
    """parameters 原始清單 → 有序 Parameter list；缺鍵/非 dict 的項目略過。"""
    out: list[Parameter] = []
    for p in raw or []:
        if isinstance(p, dict) and "name" in p:
            out.append(Parameter(name=str(p["name"]), value=int(p.get("value", 0))))
    return out


def _parse_dimensions(raw) -> list[str]:
    """dimensions 原始清單 → 有序名稱 list（最多取前 2 個）；非字串項目略過。

    名稱是否存在於 parameters、是否重複、個數上限等交由 validator 檢查，這裡只做型別正規化。"""
    out: list[str] = []
    for name in raw or []:
        if isinstance(name, str) and name:
            out.append(name)
    return out[:2]


@dataclass
class PowerSeqConfig:
    """完整 Power Sequence 規格"""
    rails: list[PowerRail] = field(default_factory=list)
    module_name: str = "PWRSEQ_TOP"
    clock_freq_mhz: float = 100.0
    pulse_period_ns: float = 100.0
    pulses: list[str] = field(default_factory=lambda: [DEFAULT_PULSE])  # Pulse 來源列表，每個為單一訊號（無 _Hi/_Lo/_Force）
    parameters: list[Parameter] = field(default_factory=list)  # 具名整數常數（width 公式可引用）
    dimensions: list[str] = field(default_factory=list)  # 0~2 個全域維度，指向 parameters 名稱（維度1=row、維度2=col）
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

    def rename_group(self, old_base: str, new_base: str) -> bool:
        """整組 rename：base 改名 → 所有 bit（base[i]→new[i]）與全部條件引用一起更新。

        逐 bit 復用 rename_rail（它已處理 hi/lo/force 的 groups/inv/use 與 input-wave groups、
        legacy depends_on），避免引用更新的規則出現第二份。找不到該群組或新舊同名回 False。"""
        if not new_base or new_base == old_base:
            return False
        bits = sorted(
            (r for r in self.rails if r.group_base == old_base),
            key=lambda r: r.bit_index,
        )
        if not bits:
            return False
        for r in bits:
            self.rename_rail(r.name, _bit_name(new_base, r.bit_index))
            r.group_base = new_base
        return True

    def delete_group(self, base: str) -> int:
        """整組刪除：移除 group_base==base 的所有 bit，回傳刪掉的數量。

        引用這些 bit 的條件保持原樣（成為 dangling dep），與單一節點刪除的既有行為一致，
        由 validator 的 missing-deps 檢查反映。"""
        before = len(self.rails)
        self.rails = [r for r in self.rails if r.group_base != base]
        return before - len(self.rails)

    def move_group(self, base: str, to_index: int) -> bool:
        """整組搬移：把該群組的連續區段移到 to_index（移除該塊後的座標）。"""
        from core.config_edit import group_span, move_group

        span = group_span(self.rails, base)
        if span is None:
            return False
        start, count = span
        return move_group(self.rails, start, count, to_index)

    def to_dict(self) -> dict:
        """轉換為可序列化的 dict（僅現行欄位；不含 depends_on 等舊版冗餘）。

        parameters 為空時不輸出該鍵，確保「無 parameter 的既有 config」round-trip byte 不變。
        """
        d: dict = {
            "module_name": self.module_name,
            "clock_freq_mhz": self.clock_freq_mhz,
            "pulse_period_ns": self.pulse_period_ns,
            "pulses": self.pulses,
        }
        if self.parameters:
            d["parameters"] = [{"name": p.name, "value": p.value} for p in self.parameters]
        if self.dimensions:
            d["dimensions"] = list(self.dimensions)
        d["rails"] = _collapse_rails_to_dicts(self.rails)
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
        parameters = _parse_parameters(d.get("parameters"))
        dimensions = _parse_dimensions(d.get("dimensions"))
        rails = []
        for r in d.get("rails", []):
            seq_type = _normalize_seq_type(r.get("seq_type", "output"))
            if "parametric" in r:
                # 舊版 parametric 收合格式已移除（改用維度+slice 模型）：略過不載入。
                continue
            if "width_expr" in r:
                # vector 收合格式：展開成 N 個 base[i]（N 由 width_expr+parameters 算），共用物理 + 逐 bit 條件。
                rails.extend(_expand_vector_dict(r, seq_type, parameters))
                continue
            rail = _build_rail_from_dict(r["name"], seq_type, r)
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
            parameters=parameters,
            dimensions=dimensions,
            timing_scenario=timing_scenario,
        )
