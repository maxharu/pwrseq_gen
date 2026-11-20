"""
從 PowerSeqConfig 產生 firmware C（power.c 風格）
- pwrcell_t 結構、power_var 初始化、條件式、pwrcell_handle
- 輸入：oemgpio_DI_Get(MACRO)；輸出依賴：power_var.<sig>.<hi|lo|force>.condition
"""
from __future__ import annotations

import os
from datetime import datetime

from core.cond_ir import CondVisitor, resolve_condition
from core.config_models import PowerRail, PowerSeqConfig, eval_width, pulse_suffix
from core.group_logic import c_intra_expr
from core.naming import internal_sig, safe_name


def _gpio_macro(name: str) -> str:
    return safe_name(name).upper()


def _c_member(rail: PowerRail) -> str:
    """rail 在 C 結構裡的引用名（甲案）：群組 bit → 陣列索引 `base[i]`；非群組 → 成員名。

    C 把 vector 收合成 `pwrcell_t base[N]`，所以 init / handle / 條件賦值、以及條件式裡引用
    另一個 bit 的 `.condition`，一律走索引而非舊的 `base_i` 成員名。宣告那一行（含 N）另外處理。
    """
    if rail.group_base is not None:
        return f"{internal_sig(rail.group_base)}[{rail.bit_index}]"
    return internal_sig(rail.name)


def _filename_to_c_names(filepath: str) -> tuple[str, str, str]:
    """
    從檔名產生 guard、函式前綴、全域變數名。
    power.c -> (POWER_C, power, power_var)
    x15snw_pseq.c -> (X15SNW_PSEQ_C, x15snw_pseq, x15snw_pseq_var)
    """
    base = os.path.basename(filepath)
    stem = base[:-2] if base.lower().endswith(".c") else base
    stem = safe_name(stem) or "power"
    guard = f"{stem.upper()}_C"
    var_name = f"{stem}_var" if stem != "power" else "power_var"
    return guard, stem, var_name


def _pulse_time_field(pulse_name: str) -> str | None:
    """Pulse_1ms / iPulse_1ms -> t_1ms；High/default/空則 None（呼叫端用常數 1）。"""
    suffix = pulse_suffix(pulse_name)
    return f"t_{suffix}" if suffix else None


def _pulse_time_expr(pulse_name: str, var_name: str, *, isr: bool = False) -> str:
    field = _pulse_time_field(pulse_name)
    if field is None:
        return "1"
    bucket = "time_isr" if isr else "time"
    return f"{var_name}.{bucket}.{field}"


def _collect_used_time_fields(config: PowerSeqConfig, sequenced: list[PowerRail]) -> list[str]:
    """收集 pwrcell_handle 會用到的 time 欄位名（排序、去重）。"""
    seen: set[str] = set()
    order: list[str] = []
    for r in sequenced:
        for pulse in (
            getattr(r, "pulse_hi", "default") or "default",
            getattr(r, "pulse_lo", "default") or "default",
        ):
            field = _pulse_time_field(pulse)
            if field and field not in seen:
                seen.add(field)
                order.append(field)
    # 保留 config.pulses 順序中出現的欄位
    pulse_order = [_pulse_time_field(p) for p in (config.pulses or [])]
    pulse_order = [f for f in pulse_order if f]
    result = [f for f in pulse_order if f in seen]
    for f in order:
        if f not in result:
            result.append(f)
    return result


class _CCond(CondVisitor):
    """把 CondTree 渲染成 firmware C 運算式。

    準位一律讀回 GPIO（output 也是），只有 use=hi/lo/force 才讀 pwrcell 的條件欄位。
    """

    def __init__(self, var_name: str, name_to_rail: dict[str, PowerRail] | None = None):
        self.var_name = var_name
        self.name_to_rail = name_to_rail or {}

    def const(self, value: int) -> str:
        return "1" if value else "0"

    def level(self, name: str) -> str:
        return f"oemgpio_DI_Get({_gpio_macro(name)})"

    def cond(self, name: str, kind: str) -> str:
        # vector bit 的 .condition 要走陣列索引（base[i]），與結構宣告一致
        rail = self.name_to_rail.get(name)
        member = _c_member(rail) if rail is not None else internal_sig(name)
        return f"{self.var_name}.{member}.{kind}.condition"

    def invert(self, operand: str) -> str:
        return f"!{operand}"

    def group(self, op: str, items: list[str], inv: bool) -> str:
        expr = c_intra_expr(items, op)
        return f"!({expr})" if inv else expr

    def any_group(self, groups: list[str]) -> str:
        return " | ".join(groups)

    def take_ref(self, node):
        raise NotImplementedError("dim-vector take 尚未接線（階段F：C 後端）")


_C_BANNER_INNER = 56  # power.c：// 與結尾 // 之間固定 56 字元


def _c_banner_sep() -> str:
    """//********************************************************//"""
    return f"//{'*' * _C_BANNER_INNER}//"


def _c_banner_text(text: str = "") -> str:
    """//     power.c                                            //（左對齊，非置中）"""
    return f"//{text.ljust(_C_BANNER_INNER)}//"


def _c_banner_title_block(title: str) -> list[str]:
    """Include File / Global Veriables Declare 等三行區塊。"""
    return [_c_banner_sep(), _c_banner_text(title), _c_banner_sep()]


def _c_assign_zero(lhs: str, width: int) -> str:
    """單行賦值 0，= 欄對齊（對齊 power.c Init）。"""
    return f"    {lhs.ljust(width)} = 0;"


_C_HANDLER_BEGIN = (
    "    // Power cell handlers begin ////////////////////////////////////////////////////"
)
_C_HANDLER_END = (
    "    // Power cell handlers end //////////////////////////////////////////////////////"
)


def _c_time_init_lines(var_name: str, time_fields: list[str]) -> list[str]:
    """Init 內 time 清零：每個 pulse 先 time_isr 再 time（交錯）；= 對齊。"""
    if not time_fields:
        return []
    pairs = []
    for f in time_fields:
        pairs.append(f"{var_name}.time_isr.{f}")
        pairs.append(f"{var_name}.time.{f}")
    w = max(len(s) for s in pairs)
    out: list[str] = []
    for f in time_fields:
        out.append(_c_assign_zero(f"{var_name}.time_isr.{f}", w))
        out.append(_c_assign_zero(f"{var_name}.time.{f}", w))
    return out


def _c_time_clear_lines(var_name: str, time_fields: list[str]) -> list[str]:
    """mainLoop 結尾 time.* 清零（簡單賦值，不強制 = 欄對齊）。"""
    return [f"    {var_name}.time.{f} = 0;" for f in time_fields]


def _c_banner_doc_block(title: str, body_lines: list[str]) -> list[str]:
    """power_Init() 註解區：標題、空行、內文各行間空行、結尾 ***。"""
    out = [_c_banner_sep(), _c_banner_text(title), _c_banner_text("")]
    for line in body_lines:
        out.append(_c_banner_text(line))
        out.append(_c_banner_text(""))
    out.pop()  # 最後一則 body 後不要空行，改接 ***
    out.append(_c_banner_sep())
    return out


def generate_c(
    config: PowerSeqConfig,
    output_filename: str | None = None,
    *,
    include_file: str = "_user.h",
    var_name: str | None = None,
) -> str:
    """
    產生 power.c 風格韌體 C 原始碼。
    output_filename 決定 #ifndef guard 與函式前綴；未提供時用 power / POWER_C。
    """
    if output_filename:
        guard, prefix, default_var = _filename_to_c_names(output_filename)
    else:
        guard, prefix, default_var = "POWER_C", "power", "power_var"

    var_name = var_name or default_var
    type_name = f"_{var_name}" if var_name.endswith("_var") else f"_{prefix}_var"
    if var_name == "power_var":
        type_name = "_power_var"

    node_order = list(config.rails)
    name_to_rail = {r.name: r for r in node_order}
    sequenced = [r for r in node_order if r.has_pseqcell]
    time_fields = _collect_used_time_fields(config, sequenced)

    year = datetime.now().year
    lines: list[str] = []

    lines.append(_c_banner_sep())
    lines.append(_c_banner_text(f"     {prefix}.c"))
    lines.append(_c_banner_text(""))
    lines.append(_c_banner_text("     Supermicro Computer Confidential"))
    lines.append(_c_banner_text(""))
    lines.append(_c_banner_text(f"     Copyright (c) {year} by Supermicro Computer"))
    lines.append(_c_banner_text("     All rights reserved"))
    lines.append(_c_banner_text(""))
    lines.append(_c_banner_sep())
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.extend(_c_banner_title_block(" Include File"))
    lines.append(f'#include "{include_file}"')
    lines.append("")
    params = getattr(config, "parameters", None) or []
    if params:
        lines.extend(_c_banner_title_block(" Parameter Define"))
        w_pname = max(len(p.name) for p in params)
        for p in params:
            lines.append(f"#define {p.name.ljust(w_pname)} {p.value}")
        lines.append("")
    lines.extend(_c_banner_title_block(" Global Veriables Declare"))
    lines.append("typedef struct")
    lines.append("{")

    # 群組（vector）收合成一行陣列宣告 `pwrcell_t base[N];`（在 bit 0 處），其餘 bit 不再各自宣告。
    decl_names: list[str] = []
    for r in sequenced:
        if r.group_base is not None:
            if r.bit_index != 0:
                continue
            n = eval_width(r.width_expr, config.parameters)
            decl_names.append(f"{internal_sig(r.group_base)}[{n}]")
        else:
            decl_names.append(internal_sig(r.name))
    w_member = max((len(d) for d in decl_names), default=0)
    for d in decl_names:
        lines.append(f"    pwrcell_t {d.ljust(w_member)};")

    if time_fields:
        w_tf = max(len(f) for f in time_fields)
        lines.append("    struct")
        lines.append("    {")
        for f in time_fields:
            lines.append(f"        UINT8 {f.ljust(w_tf)}:1;")
        lines.append("    }time_isr;")
        lines.append("    struct")
        lines.append("    {")
        for f in time_fields:
            lines.append(f"        UINT8 {f.ljust(w_tf)}:1;")
        lines.append("    }time;")

    lines.append(f"}}{type_name};")
    lines.append("")

    # Static initializer
    lines.append(f"{type_name} {var_name} = {{")
    w_init = max((len(_c_member(r)) for r in sequenced), default=0)
    w_chi = max((len(str(r.cycle_hi)) for r in sequenced), default=1)
    w_clo = max((len(str(r.cycle_lo)) for r in sequenced), default=1)
    w_polar = max((len(str(getattr(r, "force_val", 0))) for r in sequenced), default=1)
    for i, r in enumerate(sequenced):
        m = _c_member(r)
        comma = "," if i < len(sequenced) - 1 else ""
        hi_c = str(r.cycle_hi).rjust(w_chi)
        lo_c = str(r.cycle_lo).rjust(w_clo)
        polar = str(getattr(r, "force_val", 0)).rjust(w_polar)
        lines.append(
            f"    .{m.ljust(w_init)} = {{ .hi = {{.cycle = {hi_c}}}, "
            f".lo = {{.cycle = {lo_c}}}, .force = {{.polar = {polar}}} }}{comma}"
        )
    lines.append("};")
    lines.append("")

    # Init function
    lines.extend(_c_banner_doc_block(
        f" {prefix}_Init()",
        [
            " Description: Variable Initialization",
            " Input:     None",
            " Return:    None",
        ],
    ))
    lines.append(f"void {prefix}_Init(void)")
    lines.append("{")
    w_init_call = max((len(_c_member(r)) for r in sequenced), default=0)
    for r in sequenced:
        m = _c_member(r)
        lines.append(f"    pwrcell_Init(&{var_name}.{m.ljust(w_init_call)});")
    if time_fields:
        lines.append("")
        lines.extend(_c_time_init_lines(var_name, time_fields))
    lines.append("}")
    lines.append("")

    # Timer ISRs
    for f in time_fields:
        period = f[2:] if f.startswith("t_") else f
        lines.append(f"void {prefix}_timer_{period}_ISR(void)")
        lines.append("{")
        lines.append(f"    {var_name}.time_isr.{f} = 1;")
        lines.append("}")
        lines.append("")

    # vector 群組（依序、去重）：base → 該群組的 bit rails（按 bit_index）。供 GPIO 表與 handle 迴圈共用。
    vector_groups: list[tuple[str, list[PowerRail]]] = []
    seen_bases: set[str] = set()
    for r in sequenced:
        if r.group_base is not None and r.group_base not in seen_bases:
            seen_bases.add(r.group_base)
            bits = sorted(
                (x for x in sequenced if x.group_base == r.group_base),
                key=lambda x: x.bit_index,
            )
            vector_groups.append((r.group_base, bits))

    # GPIO 參考表（僅在有 vector 時輸出）：把 vector handle 從 N 行收成「表 + for」。
    # 每 bit 用 header 既有的 <MACRO>_PORT（port 指標）/ <MACRO>_BIT（pin 整數），不需改 firmware；
    # typedef 自成一體，無 vector 的檔完全不出現這些。
    if vector_groups:
        lines.extend(_c_banner_title_block(" GPIO Reference Table"))
        lines.append("typedef struct { GPIO_T* port; UINT32 pin; } pwrseq_gpio_ref_t;")
        for base, bits in vector_groups:
            tbl = f"{internal_sig(base)}_gpio"
            n = eval_width(bits[0].width_expr, config.parameters)
            entries = ", ".join(
                f"{{ {_gpio_macro(b.name)}_PORT, {_gpio_macro(b.name)}_BIT }}" for b in bits
            )
            lines.append(f"static const pwrseq_gpio_ref_t {tbl}[{n}] = {{ {entries} }};")
        lines.append("")

    # mainLoop
    lines.append(f"void {prefix}_mainLoop(void)")
    lines.append("{")
    lines.append("UINT32 IRQ = m_oemsys_getIrq();")
    lines.append("")

    for f in time_fields:
        lines.append(f"    if ({var_name}.time_isr.{f})")
        lines.append("    {")
        lines.append("        m_oemsys_IrqDis();")
        lines.append(f"        {var_name}.time_isr.{f} = 0;")
        lines.append("        m_oemsys_setIrq(IRQ);")
        lines.append(f"        {var_name}.time.{f} = 1;")
        lines.append("    }")
        lines.append("")

    lines.append(_C_HANDLER_BEGIN)

    w_cell = max((len(_c_member(r)) for r in sequenced), default=0)
    renderer = _CCond(var_name, name_to_rail)

    for r in sequenced:
        s = _c_member(r)
        hi_expr = resolve_condition(r, "hi", name_to_rail).accept(renderer)
        lo_expr = resolve_condition(r, "lo", name_to_rail).accept(renderer)
        force_expr = resolve_condition(r, "force", name_to_rail).accept(renderer)
        lines.append(f"    {var_name}.{s.ljust(w_cell)}.hi.condition    = {hi_expr};")
        lines.append(f"    {var_name}.{s.ljust(w_cell)}.lo.condition    = {lo_expr};")
        lines.append(f"    {var_name}.{s.ljust(w_cell)}.force.condition = {force_expr};")
        lines.append("")

    # pwrcell_handle：非 vector 逐行（引數對齊，維持原樣）；vector 收成 GPIO 表 + for 迴圈。
    # 迴圈 body 同構、只差 GPIO：time 引數（arg_hi/arg_lo）全 bit 共用，取 bit 0 代表整組。
    scalar_specs = [
        {
            "member": _c_member(r),
            "arg_hi": _pulse_time_expr(getattr(r, "pulse_hi", "default") or "default", var_name),
            "arg_lo": _pulse_time_expr(getattr(r, "pulse_lo", "default") or "default", var_name),
            "gpio": _gpio_macro(r.name),
        }
        for r in sequenced
        if r.group_base is None
    ]
    w_m = max((len(h["member"]) for h in scalar_specs), default=0)
    w_ah = max((len(h["arg_hi"]) for h in scalar_specs), default=0)
    w_al = max((len(h["arg_lo"]) for h in scalar_specs), default=0)
    w_g = max((len(h["gpio"]) for h in scalar_specs), default=0)

    scalar_iter = iter(scalar_specs)
    emitted_bases: set[str] = set()
    for r in sequenced:
        if r.group_base is None:
            h = next(scalar_iter)
            lines.append(
                f"    pwrcell_handle(&{var_name}.{h['member'].ljust(w_m)}, "
                f"{h['arg_hi'].ljust(w_ah)}, {h['arg_lo'].ljust(w_al)}, {h['gpio'].ljust(w_g)});"
            )
        elif r.group_base not in emitted_bases:
            emitted_bases.add(r.group_base)
            base = internal_sig(r.group_base)
            n = eval_width(r.width_expr, config.parameters)
            arg_hi = _pulse_time_expr(getattr(r, "pulse_hi", "default") or "default", var_name)
            arg_lo = _pulse_time_expr(getattr(r, "pulse_lo", "default") or "default", var_name)
            lines.append(f"    for (UINT8 i = 0; i < {n}; i++)")
            lines.append(
                f"        pwrcell_handle(&{var_name}.{base}[i], "
                f"{arg_hi}, {arg_lo}, {base}_gpio[i].port, {base}_gpio[i].pin);"
            )

    lines.append(_C_HANDLER_END)
    lines.append("")
    lines.extend(_c_time_clear_lines(var_name, time_fields))
    lines.append("}")
    lines.append(f"#endif  //{guard}")
    lines.append("")

    return "\n".join(lines)
