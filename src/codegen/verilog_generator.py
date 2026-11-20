"""
從 PowerSeqConfig 產生 Verilog
依需求表：seq_type: output (輸出) | input (輸入)
- iPulse_Hi/Lo/Force 由 IO 輸入
- 埠命名：oXXX / iXXX（無底線）
- 無 Lo 依賴時 iLo 接 1'b0
"""
import os

from core.cond_ir import CondVisitor, Const, resolve_condition
from core.config_models import DEFAULT_PULSE, PowerRail, PowerSeqConfig, pulse_verilog_name
from core.constants import DEP_HIGH, DEP_LOW
from core.group_logic import verilog_intra_expr
from core.naming import internal_sig, safe_name
from core.take_expr import take_expr

# 維度 vector 的 generate-for genvar 名（1 維用 row、2 維加 col）。
GV_ROW = "gv_row"
GV_COL = "gv_col"


def _filename_to_module_and_guard(filepath: str) -> tuple[str, str]:
    """
    從檔名產生 module name 與 ifndef guard。
    - module name: 檔名（不含 .v），轉為 Verilog 合法識別子
    - guard: 大寫 + _V 後綴，例如 my_pwrseq.v → MY_PWRSEQ_V
    """
    base = os.path.basename(filepath)
    name = base
    if name.lower().endswith(".v"):
        name = name[:-2]
    name = safe_name(name)
    if not name:
        return "PWRSEQ_TOP", "PWRSEQ_TOP_V"
    return name, f"{name.upper()}_V"


def _aligned_hash_params(param_rows: list[list[tuple[str, int]]]) -> list[str]:
    """Format #(.NAME(val), ...) with numeric values column-aligned across instances."""
    if not param_rows:
        return []
    n = len(param_rows[0])
    widths = [max(len(str(row[i][1])) for row in param_rows) for i in range(n)]
    blocks: list[str] = []
    for row in param_rows:
        parts = [
            f".{name}({str(val).rjust(widths[i])})"
            for i, (name, val) in enumerate(row)
        ]
        blocks.append("#(" + ", ".join(parts) + ")")
    return blocks


def _topological_sort(rails: list) -> list:
    """依依賴關係做拓撲排序"""
    name_to_rail = {r.name: r for r in rails}
    result = []
    visited = set()

    def visit(name: str):
        if name in visited:
            return
        visited.add(name)
        rail = name_to_rail.get(name)
        if rail:
            deps = (
                rail.get_depends_on_hi_flat()
                + rail.get_depends_on_lo_flat()
                + rail.get_depends_on_force_flat()
            )
            for dep in deps:
                if dep not in (DEP_HIGH, DEP_LOW) and dep in name_to_rail:
                    visit(dep)
            result.append(rail)

    for r in rails:
        visit(r.name)
    return result


def _port_name(name: str, prefix: str) -> str:
    """依需求表：oXXX / iXXX（無底線）"""
    return prefix + safe_name(name)


def _is_group_head(rail: PowerRail) -> bool:
    """非群組，或群組的 bit 0；Verilog 收合輸出只在 head 處進行（其餘 bit 跳過）。"""
    return rail.group_base is None or rail.bit_index == 0


def _group_sig(rail: PowerRail) -> str:
    """群組 rail 的 Verilog 代表訊號名（取 base，不帶 [i]）；非群組用節點名。"""
    return internal_sig(rail.group_base if rail.group_base is not None else rail.name)


def _group_port(rail: PowerRail, prefix: str) -> str:
    """群組 rail 的 port 名（取 base）；非群組用節點名。"""
    return _port_name(rail.group_base if rail.group_base is not None else rail.name, prefix)


def _width_msb(width_expr) -> str:
    """寬度 MSB 片段：整數 k → `k-1`；公式 → `(EXPR)-1`（保留符號形式，不求值）。"""
    expr = str(width_expr).strip()
    try:
        return str(int(expr) - 1)
    except ValueError:
        return f"({expr})-1"


def _width_param(width_expr):
    """.WIDTH() 的值：整數 → int（沿用數值對齊）；公式 → `(EXPR)` 字串。"""
    expr = str(width_expr).strip()
    try:
        return int(expr)
    except ValueError:
        return f"({expr})"


def _width_prefix(rail: PowerRail) -> str:
    """群組 rail → `[k-1:0] `（整數）或 `[(EXPR)-1:0] `（公式）；非群組 → ``。"""
    if rail.group_base is None:
        return ""
    return f"[{_width_msb(rail.width_expr)}:0] "


def _pulse_signal(pulse_name: str) -> str:
    """取得 pulse 的 Verilog 訊號名稱。config 存 Pulse_*，輸出 iPulse_*。"""
    return pulse_verilog_name(pulse_name)


def _get_input_signal(dep_name: str, name_to_rail: dict[str, PowerRail]) -> str:
    """取得 input 節點的訊號名稱（有 Debounce 時回傳 xxx_deb）"""
    dep = name_to_rail.get(dep_name)
    if not dep:
        return _port_name(dep_name, "i")
    if dep.seq_type == "input" and getattr(dep, "deb_enable", False):
        return f"{internal_sig(dep_name)}_deb"
    return _port_name(dep_name, "i")


# 完全沒有該 kind 的 group 時，assign 行尾註明預設值的由來
_NO_CONDITION_NOTES = {
    "hi": "// No Hi condition",
    "lo": "// No Lo condition (F-DEP-06)",
    "force": "// No Force condition",
}


class _VerilogCond(CondVisitor):
    """把 CondTree 渲染成 Verilog 運算式。

    - 常數：1'b1 / 1'b0（反相已由 cond_ir 摺掉）
    - 條件訊號：xxx_hi / xxx_lo / xxx_force（F-DEP-07）
    - 準位：output 為內部線 xxx，input 為 iXXX 或 xxx_deb（有 Debounce 時）
    """

    def __init__(self, name_to_rail: dict[str, PowerRail]):
        self.name_to_rail = name_to_rail

    def const(self, value: int) -> str:
        return "1'b1" if value else "1'b0"

    def level(self, name: str) -> str:
        dep = self.name_to_rail.get(name)
        # 被參照的是某 vector 的一個 bit：收合後是 bus，葉節點要走 bus 索引 `<bus>[i]`
        if dep is not None and dep.group_base is not None:
            idx = f"[{dep.bit_index}]"
            if dep.seq_type == "output":
                return f"{_group_sig(dep)}{idx}"
            if dep.seq_type == "input" and getattr(dep, "deb_enable", False):
                return f"{_group_sig(dep)}_deb{idx}"
            return f"{_group_port(dep, 'i')}{idx}"
        if dep is not None and dep.seq_type == "output":
            return internal_sig(name)
        return _get_input_signal(name, self.name_to_rail)

    def cond(self, name: str, kind: str) -> str:
        dep = self.name_to_rail.get(name)
        if dep is not None and dep.group_base is not None:
            return f"{_group_sig(dep)}_{kind}[{dep.bit_index}]"
        return f"{internal_sig(name)}_{kind}"

    def invert(self, operand: str) -> str:
        return f"(~{operand})"

    def group(self, op: str, items: list[str], inv: bool) -> str:
        expr = verilog_intra_expr(items, op)
        return f"!{expr}" if inv else expr

    def any_group(self, groups: list[str]) -> str:
        return " | ".join(groups)

    def take_ref(self, node) -> str:
        base = internal_sig(node.base)
        bus = base if node.use == "level" else f"{base}_{node.use}"
        return take_expr(bus, node.ref_ndim, node.row, node.col,
                         col_size=node.col_size, gv_row=GV_ROW, gv_col=GV_COL)


def _sep() -> str:
    return "////////////////////////////////////////////////////////////////////////////////"


def _section(title: str) -> list[str]:
    return [_sep(), f"// {title:<74} //", _sep()]


def _emit_dim_vector_cond(lines: list[str], head: PowerRail, s: str,
                          renderer: "_VerilogCond", name_to_rail: dict) -> None:
    """維度 vector 的條件走 generate-for：head 一份符號條件（含 take）套整條 bus。

    1 維：for(gv_row<P1) assign s_kind[gv_row]；2 維：巢狀 for，LHS flat = gv_row*P2+gv_col。"""
    dims = head.dim_params
    p1 = dims[0]
    two_d = len(dims) >= 2
    lines.append("    generate")
    lines.append(f"    for ({GV_ROW}=0; {GV_ROW}<{p1}; {GV_ROW}={GV_ROW}+1) begin : g_{s}")
    if two_d:
        p2 = dims[1]
        lines.append(
            f"        for ({GV_COL}=0; {GV_COL}<{p2}; {GV_COL}={GV_COL}+1) begin : g_{s}_c")
        indent = "            "
        lhs_idx = f"{GV_ROW}*{p2} + {GV_COL}"
    else:
        indent = "        "
        lhs_idx = GV_ROW
    for kind, no_cond_note in _NO_CONDITION_NOTES.items():
        tree = resolve_condition(head, kind, name_to_rail)
        expr = tree.accept(renderer)
        note = f"  {no_cond_note}" if isinstance(tree, Const) else ""
        lines.append(f"{indent}assign {s}_{kind}[{lhs_idx}] = {expr};{note}")
    if two_d:
        lines.append("        end")
    lines.append("    end")
    lines.append("    endgenerate")
    lines.append("")


def generate_verilog(config: PowerSeqConfig, output_filename: str | None = None) -> str:
    """
    產生完整 Verilog 模組。
    若提供 output_filename，則依檔名產生 module name 與 `ifndef/`define guard；
    否則使用 config.module_name。
    內部訊號、assign、PSEQCELL 等皆依 config.rails（節點順序）輸出，不依拓撲序。
    """
    # 節點順序 = config.rails（左側列表拖拉順序），用於 port 與整份 Verilog 程式碼順序
    node_order_rails = config.rails
    name_to_rail = {r.name: r for r in config.rails}
    # 群組（vector）在 Verilog 收合成一條 bus，只在 bit 0（head）產生訊號／實例，其餘 bit 跳過。
    sequenced = [r for r in node_order_rails if r.has_pseqcell and _is_group_head(r)]
    inputs_with_deb = [
        r for r in node_order_rails
        if r.seq_type == "input" and getattr(r, "deb_enable", False) and _is_group_head(r)
    ]

    if output_filename:
        module_name, define_name = _filename_to_module_and_guard(output_filename)
    else:
        module_name = config.module_name
        mod_upper = config.module_name.upper().replace(".", "_")
        define_name = f"{mod_upper}_V"

    lines = []
    lines.append("`timescale 1ns / 1ps")
    lines.append(_sep())
    lines.append(f"// Module                : {module_name:<50} //")
    lines.append("// Author                : pwrseq_gen (Auto-generated)                        //")
    lines.append("// Date Simulation Tested:                                                    //")
    lines.append("//                                                                            //")
    lines.append("// Function Description  :                                                    //")
    lines.append("//   Power Sequence. output: oXXX, input: iXXX.                               //")
    lines.append("//   iHi from depends_on (output: out, input: in). iLo default 1'b0.          //")
    lines.append("// Change Log            :                                                    //")
    lines.append("//   Auto-generated.                                                          //")
    lines.append(_sep())
    lines.append(f"`ifndef {define_name}")
    lines.append(f"`define {define_name}")
    lines.append("")

    lines.extend(_section("Define"))
    lines.append("//`define DEFINE_NAME    0")
    lines.append("")

    lines.extend(_section("Library Include"))
    lines.append("//`include \"PSEQCELL.v\"")
    lines.append("")

    lines.extend(_section("Module Declare"))
    lines.append("module " + module_name)
    lines.extend(_section("Parameter Declare"))
    params = getattr(config, "parameters", None) or []
    if params:
        w_name = max(len(p.name) for p in params)
        lines.append("#(")
        for i, p in enumerate(params):
            comma = "," if i < len(params) - 1 else ""
            lines.append(f"    parameter {p.name.ljust(w_name)} = {p.value}{comma}")
        lines.append(")")
    else:
        lines.append("//#(")
        lines.append("//    No parameters")
        lines.append("//)")
    lines.extend(_section("Input/Output Port Declare"))
    lines.append("(")
    lines.append("    input  iRst,")
    lines.append("    input  iClk_Core,")
    pulses = getattr(config, "pulses", None) or [DEFAULT_PULSE]
    need_pulses = sequenced or inputs_with_deb
    if need_pulses and pulses:
        seen = set()
        pulse_sigs = []
        for p in pulses:
            sig = _pulse_signal(p)
            if sig.startswith("1'b") or sig in seen:
                continue
            seen.add(sig)
            pulse_sigs.append(sig)
        if pulse_sigs:
            lines.append("    input  " + ", ".join(pulse_sigs) + ",")
    # Ports 依節點順序 (config.rails)：input 用 iXXX，output 用 oXXX；群組收合成一條 bus。
    for r in config.rails:
        if not _is_group_head(r):
            continue
        wp = _width_prefix(r)
        if r.seq_type == "input":
            lines.append(f"    input  {wp}{_group_port(r, 'i')},")
        else:
            lines.append(f"    output {wp}{_group_port(r, 'o')},")
    if lines[-1].endswith(","):
        lines[-1] = lines[-1].rstrip(",")
    lines.append(");")
    lines.append("")

    lines.extend(_section("Function Include"))
    lines.append("")

    lines.extend(_section("Local Parameter Declare"))
    lines.append("// None")
    lines.append("")

    lines.extend(_section("Internal Signal Declare"))
    for r in node_order_rails:
        if not _is_group_head(r):
            continue
        wp = _width_prefix(r)
        if r.has_pseqcell:
            lines.append(f"wire {wp}{_group_sig(r)};")
        elif r.seq_type == "input" and getattr(r, "deb_enable", False):
            lines.append(f"wire {wp}{_group_sig(r)}_deb;")
    lines.append("")

    if sequenced:
        lines.append("// Condition signals (iHi, iLo, iForce) for PSEQCELL")
        cond_heads = [r for r in node_order_rails if r.has_pseqcell and _is_group_head(r)]
        cond_sigs = [_group_sig(r) for r in cond_heads]
        w_hi = max(len(s) + 3 for s in cond_sigs)     # "_hi"
        w_lo = max(len(s) + 3 for s in cond_sigs)     # "_lo"
        w_fc = max(len(s) + 6 for s in cond_sigs)     # "_force"
        # width 前綴欄對齊：純量（無前綴）補等寬空白，讓 `_hi` 名稱與 vector 行同欄。
        w_wp = max(len(_width_prefix(r)) for r in cond_heads)
        for r in cond_heads:
            s = _group_sig(r)
            wp = _width_prefix(r).ljust(w_wp)
            lines.append(
                f"wire {wp}{(s + '_hi').ljust(w_hi)}, "
                f"{(s + '_lo').ljust(w_lo)}, "
                f"{(s + '_force').ljust(w_fc)};"
            )
        lines.append("")

    lines.extend(_section("Task Define"))
    lines.append("// None")
    lines.append("")

    lines.extend(_section("Design"))
    lines.append("///// Instance /////////////////////////////////////////////////////////////////")

    # DEB instances (input debounce, each on one line)
    if inputs_with_deb:
        deb_specs = []
        for r in inputs_with_deb:
            s = _group_sig(r)
            deb_specs.append({
                "rail": r,
                "u": f"u_deb_{s}",
                "inp": _group_port(r, "i"),
                "out": f"{s}_deb",
                "ps": _pulse_signal(getattr(r, "deb_pulse", DEFAULT_PULSE) or DEFAULT_PULSE),
            })
        w_u = max(len(d["u"]) for d in deb_specs)
        w_inp = max(len(d["inp"]) for d in deb_specs)
        w_out = max(len(d["out"]) for d in deb_specs)
        w_ps = max(len(d["ps"]) for d in deb_specs)
        deb_param_rows = [
            [
                ("WIDTH", _width_param(d["rail"].width_expr)),
                ("INIT", getattr(d["rail"], "deb_init", 0)),
                ("CYCLE_SYNC", getattr(d["rail"], "deb_cycle_sync", 2)),
                ("CYCLE_HI", getattr(d["rail"], "deb_cycle_hi", 2)),
                ("CYCLE_LO", getattr(d["rail"], "deb_cycle_lo", 2)),
            ]
            for d in deb_specs
        ]
        deb_hash = _aligned_hash_params(deb_param_rows)
        for d, params in zip(deb_specs, deb_hash):
            inst = (
                f"    DEB {params} "
                f"{d['u'].ljust(w_u)} (.iRst(iRst), .iClk_Core(iClk_Core), "
                f".iPulse_Sample({d['ps'].ljust(w_ps)}), "
                f".i({d['inp'].ljust(w_inp)}), "
                f".o({d['out'].ljust(w_out)}));"
            )
            lines.append(inst)
        lines.append("")

    if sequenced:
        # iHi, iLo assignments (F-DEP-08: group 內 &，group 間 |)
        # 群組逐 bit 索引展開（每 bit 渲染自己的條件，condition wire/PSEQCELL 仍是整條 bus）；
        # 非群組維持原樣（單一 assign，無索引）。
        renderer = _VerilogCond(name_to_rail)
        dim_vectors = [r for r in sequenced if r.group_base is not None and r.dim_params]
        if dim_vectors:
            lines.append(f"    genvar {GV_ROW};")
            if any(len(r.dim_params) >= 2 for r in dim_vectors):
                lines.append(f"    genvar {GV_COL};")
            lines.append("")
        for r in sequenced:
            s = _group_sig(r)
            if r.group_base is None:
                for kind, no_cond_note in _NO_CONDITION_NOTES.items():
                    tree = resolve_condition(r, kind, name_to_rail)
                    expr = tree.accept(renderer)
                    note = f"  {no_cond_note}" if isinstance(tree, Const) else ""
                    lines.append(f"    assign {s}_{kind} = {expr};{note}")
                lines.append("")
            elif r.dim_params:
                _emit_dim_vector_cond(lines, r, s, renderer, name_to_rail)
            else:
                bits = sorted(
                    (x for x in node_order_rails if x.group_base == r.group_base),
                    key=lambda x: x.bit_index,
                )
                for b in bits:
                    for kind, no_cond_note in _NO_CONDITION_NOTES.items():
                        tree = resolve_condition(b, kind, name_to_rail)
                        expr = tree.accept(renderer)
                        note = f"  {no_cond_note}" if isinstance(tree, Const) else ""
                        lines.append(f"    assign {s}_{kind}[{b.bit_index}] = {expr};{note}")
                    lines.append("")

        # PSEQCELL instances (per-rail pulse selection)
        # Parameter order per src/reference/PSEQCELL.v
        ps_specs = []
        for r in sequenced:
            s = _group_sig(r)
            ps_specs.append({
                "rail": r,
                "s": s,
                "u": f"u_{s}",
                "hi": f"{s}_hi",
                "lo": f"{s}_lo",
                "force": f"{s}_force",
                "out": s,
                "ph": _pulse_signal(getattr(r, "pulse_hi", "default") or "default"),
                "pl": _pulse_signal(getattr(r, "pulse_lo", "default") or "default"),
                "pf": _pulse_signal(getattr(r, "pulse_force", "default") or "default"),
            })
        w_u = max(len(p["u"]) for p in ps_specs)
        w_hi = max(len(p["hi"]) for p in ps_specs)
        w_lo = max(len(p["lo"]) for p in ps_specs)
        w_fc = max(len(p["force"]) for p in ps_specs)
        w_out = max(len(p["out"]) for p in ps_specs)
        w_ph = max(len(p["ph"]) for p in ps_specs)
        w_pl = max(len(p["pl"]) for p in ps_specs)
        w_pf = max(len(p["pf"]) for p in ps_specs)
        ps_param_rows = [
            [
                ("INIT", p["rail"].init),
                ("WIDTH", _width_param(p["rail"].width_expr)),
                ("CYCLE_HI", p["rail"].cycle_hi),
                ("CYCLE_LO", p["rail"].cycle_lo),
                ("CYCLE_FORCE", p["rail"].cycle_force),
                ("FORCE", p["rail"].force_val),
            ]
            for p in ps_specs
        ]
        ps_hash = _aligned_hash_params(ps_param_rows)
        for p, params in zip(ps_specs, ps_hash):
            r = p["rail"]
            inst = (
                f"    PSEQCELL {params} "
                f"{p['u'].ljust(w_u)} (.iRst(iRst), .iClk_Core(iClk_Core), "
                f".iPulse_Hi({p['ph'].ljust(w_ph)}), "
                f".iPulse_Lo({p['pl'].ljust(w_pl)}), "
                f".iPulse_Force({p['pf'].ljust(w_pf)}), "
                f".iHi({p['hi'].ljust(w_hi)}), .iLo({p['lo'].ljust(w_lo)}), "
                f".iForce({p['force'].ljust(w_fc)}), .o({p['out'].ljust(w_out)}));"
            )
            lines.append(inst)

    lines.append("///// Always Block /////////////////////////////////////////////////////////////")
    lines.append("    // None")
    lines.append("")

    lines.append("///// Continuous Assignment ////////////////////////////////////////////////////")
    out_specs = [
        (_group_port(r, "o"), _group_sig(r))
        for r in node_order_rails if r.seq_type != "input" and _is_group_head(r)
    ]
    if out_specs:
        w_p = max(len(p) for p, _ in out_specs)
        for p, s in out_specs:
            lines.append(f"    assign {p.ljust(w_p)} = {s};")
    lines.append("")

    lines.append(f"endmodule //{module_name}")
    lines.append(f"`endif  //{define_name}")

    return "\n".join(lines)
