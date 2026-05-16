"""
從 PowerSeqConfig 產生 Verilog
依需求表：seq_type: output (輸出) | input (輸入)
- iPulse_Hi/Lo/Force 由 IO 輸入
- 埠命名：oXXX / iXXX（無底線）
- 無 Lo 依賴時 iLo 接 1'b0
"""
import os
from config_models import PowerSeqConfig, PowerRail


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
    name = _verilog_safe_name(name)
    if not name:
        return "PWRSEQ_TOP", "PWRSEQ_TOP_V"
    return name, f"{name.upper()}_V"


def _verilog_safe_name(name: str) -> str:
    """將名稱轉為 Verilog 合法識別子"""
    return name.replace(".", "_").replace("-", "_").replace(" ", "_")


def _internal_sig(name: str) -> str:
    """內部訊號名稱：全小寫，供 wire/assign 使用"""
    return _verilog_safe_name(name).lower()


def _get_successors(config: PowerSeqConfig) -> dict[str, list[str]]:
    """取得每個節點的後繼（依賴它的節點，不含 external），排除 __HIGH__/__LOW__"""
    succ = {r.name: [] for r in config.rails}
    for r in config.rails:
        deps = (
            r.get_depends_on_hi_flat()
            + r.get_depends_on_lo_flat()
            + r.get_depends_on_force_flat()
        )
        for dep in deps:
            if dep not in (DEP_HIGH, DEP_LOW) and dep in succ:
                succ[dep].append(r.name)
    return succ


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


DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"


def _port_name(name: str, prefix: str) -> str:
    """依需求表：oXXX / iXXX（無底線）"""
    return prefix + _verilog_safe_name(name)


def _pulse_signal(pulse_name: str) -> str:
    """取得 pulse 的 Verilog 訊號名稱。每個 pulse 為單一訊號，無 _Hi/_Lo/_Force 後綴。"""
    if pulse_name == "default" or not pulse_name:
        return "iPulse_1us"
    if pulse_name == "High":
        return "1'b1"
    return _verilog_safe_name(pulse_name)


def _get_input_signal(dep_name: str, name_to_rail: dict[str, PowerRail]) -> str:
    """取得 input 節點的訊號名稱（有 Debounce 時回傳 xxx_deb）"""
    dep = name_to_rail.get(dep_name)
    if not dep:
        return _port_name(dep_name, "i")
    if dep.seq_type == "input" and getattr(dep, "deb_enable", False):
        return f"{_internal_sig(dep_name)}_deb"
    return _port_name(dep_name, "i")


def _dep_expr(
    dep_name: str,
    name_to_rail: dict[str, PowerRail],
    inverted: bool = False,
    use_mode: str = "self",
) -> str:
    """
    取得依賴項的條件表示式
    - __HIGH__: 1'b1
    - __LOW__: 1'b0
    - output: wOut (輸出) / wHi (iHi) / wLo (iLo) / wForce (iForce) 依 use_mode
    - input: iXXX 或 xxx_deb（有 Debounce 時）
    - use_mode: "self"=節點本身, "hi"=該節點iHi, "lo"=該節點iLo, "force"=該節點iForce (F-DEP-07)
    - inverted: True 時回傳 ~expr
    """
    if dep_name == DEP_HIGH:
        return "1'b0" if inverted else "1'b1"
    if dep_name == DEP_LOW:
        return "1'b1" if inverted else "1'b0"
    dep = name_to_rail.get(dep_name)
    if not dep:
        base = _port_name(dep_name, "i")  # input
    else:
        if dep.seq_type == "output":
            s = _internal_sig(dep_name)
            if use_mode == "hi" and dep.has_pseqcell:
                base = f"{s}_hi"
            elif use_mode == "lo" and dep.has_pseqcell:
                base = f"{s}_lo"
            elif use_mode == "force" and dep.has_pseqcell:
                base = f"{s}_force"
            else:
                base = s
        else:  # input
            base = _get_input_signal(dep_name, name_to_rail)
    return f"(~{base})" if inverted else base


def _sep() -> str:
    return "////////////////////////////////////////////////////////////////////////////////"


def _section(title: str) -> list[str]:
    return [_sep(), f"// {title:<74} //", _sep()]


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
    successors = _get_successors(config)
    sequenced = [r for r in node_order_rails if r.has_pseqcell]
    externals = [r for r in node_order_rails if r.seq_type == "input"]
    inputs_with_deb = [r for r in node_order_rails if r.seq_type == "input" and getattr(r, "deb_enable", False)]

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
    lines.append("//#(")
    lines.append("//    No parameters")
    lines.append("//)")
    lines.extend(_section("Input/Output Port Declare"))
    lines.append("(")
    lines.append("    input  iRst,")
    lines.append("    input  iClk_Core,")
    pulses = getattr(config, "pulses", None) or ["iPulse_1us"]
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
    # Ports 依節點順序 (config.rails)：input 用 iXXX，output 用 oXXX
    for r in config.rails:
        if r.seq_type == "input":
            lines.append(f"    input  {_port_name(r.name, 'i')},")
        else:
            lines.append(f"    output {_port_name(r.name, 'o')},")
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
        if r.has_pseqcell:
            lines.append(f"wire {_internal_sig(r.name)};")
        elif r.seq_type == "input" and getattr(r, "deb_enable", False):
            lines.append(f"wire {_internal_sig(r.name)}_deb;")
    lines.append("")

    if sequenced:
        lines.append("// Condition signals (iHi, iLo, iForce) for PSEQCELL")
        cond_sigs = [_internal_sig(r.name) for r in node_order_rails if r.has_pseqcell]
        w_hi = max(len(s) + 3 for s in cond_sigs)     # "_hi"
        w_lo = max(len(s) + 3 for s in cond_sigs)     # "_lo"
        w_fc = max(len(s) + 6 for s in cond_sigs)     # "_force"
        for s in cond_sigs:
            lines.append(
                f"wire {(s + '_hi').ljust(w_hi)}, "
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
            s = _internal_sig(r.name)
            deb_specs.append({
                "rail": r,
                "u": f"u_deb_{s}",
                "inp": _port_name(r.name, "i"),
                "out": f"{s}_deb",
            })
        w_u = max(len(d["u"]) for d in deb_specs)
        w_inp = max(len(d["inp"]) for d in deb_specs)
        w_out = max(len(d["out"]) for d in deb_specs)
        for d in deb_specs:
            r = d["rail"]
            init = getattr(r, "deb_init", 0)
            cyc_hi = getattr(r, "deb_cycle_hi", 2)
            cyc_lo = getattr(r, "deb_cycle_lo", 2)
            cyc_sync = getattr(r, "deb_cycle_sync", 2)
            pulse_sig = _pulse_signal(getattr(r, "deb_pulse", "iPulse_1us") or "iPulse_1us")
            inst = (
                f"    DEB #(.WIDTH(1), .INIT({init}), .CYCLE_SYNC({cyc_sync}), "
                f".CYCLE_HI({cyc_hi}), .CYCLE_LO({cyc_lo})) "
                f"{d['u'].ljust(w_u)} (.iRst(iRst), .iClk_Core(iClk_Core), "
                f".iPulse_Sample({pulse_sig}), .i({d['inp'].ljust(w_inp)}), "
                f".o({d['out'].ljust(w_out)}));"
            )
            lines.append(inst)
        lines.append("")

    if sequenced:
        # iHi, iLo assignments (F-DEP-08: group 內 &，group 間 |)
        for r in sequenced:
            s = _internal_sig(r.name)
            hi_groups = r.get_hi_groups()
            if hi_groups:
                group_exprs = []
                for gi, group in enumerate(hi_groups):
                    terms = [
                        _dep_expr(
                            d, name_to_rail,
                            r.get_hi_inv(gi, ii, d),
                            r.get_hi_use(gi, ii, d),
                        )
                        for ii, d in enumerate(group)
                    ]
                    group_exprs.append(f"({' & '.join(terms)})")
                lines.append(f"    assign {s}_hi = {' || '.join(group_exprs)};")
            else:
                lines.append(f"    assign {s}_hi = 1'b1;  // No Hi condition")
            lo_groups = r.get_lo_groups()
            if lo_groups:
                group_exprs = []
                for gi, group in enumerate(lo_groups):
                    terms = [
                        _dep_expr(
                            d, name_to_rail,
                            r.get_lo_inv(gi, ii, d),
                            r.get_lo_use(gi, ii, d),
                        )
                        for ii, d in enumerate(group)
                    ]
                    group_exprs.append(f"({' & '.join(terms)})")
                lines.append(f"    assign {s}_lo = {' || '.join(group_exprs)};")
            else:
                lines.append(f"    assign {s}_lo = 1'b0;  // No Lo condition (F-DEP-06)")
            force_groups = r.get_force_groups()
            if force_groups:
                group_exprs = []
                for gi, group in enumerate(force_groups):
                    terms = [
                        _dep_expr(
                            d, name_to_rail,
                            r.get_force_inv(gi, ii, d),
                            r.get_force_use(gi, ii, d),
                        )
                        for ii, d in enumerate(group)
                    ]
                    group_exprs.append(f"({' & '.join(terms)})")
                lines.append(f"    assign {s}_force = {' || '.join(group_exprs)};")
            else:
                lines.append(f"    assign {s}_force = 1'b0;  // No Force condition")
            lines.append("")

        # PSEQCELL instances (per-rail pulse selection)
        # Parameter order: INIT, WIDTH, CYCLE_HI, CYCLE_LO, CYCLE_FORCE, OD
        ps_specs = []
        for r in sequenced:
            s = _internal_sig(r.name)
            ps_specs.append({
                "rail": r,
                "s": s,
                "u": f"u_{s}",
                "hi": f"{s}_hi",
                "lo": f"{s}_lo",
                "force": f"{s}_force",
                "out": s,
            })
        w_u = max(len(p["u"]) for p in ps_specs)
        w_hi = max(len(p["hi"]) for p in ps_specs)
        w_lo = max(len(p["lo"]) for p in ps_specs)
        w_fc = max(len(p["force"]) for p in ps_specs)
        w_out = max(len(p["out"]) for p in ps_specs)
        for p in ps_specs:
            r = p["rail"]
            ph = _pulse_signal(getattr(r, "pulse_hi", "default") or "default")
            pl = _pulse_signal(getattr(r, "pulse_lo", "default") or "default")
            pf = _pulse_signal(getattr(r, "pulse_force", "default") or "default")
            inst = (
                f"    PSEQCELL #(.INIT({r.init}), .WIDTH(1), .CYCLE_HI({r.cycle_hi}), "
                f".CYCLE_LO({r.cycle_lo}), .CYCLE_FORCE({r.cycle_force}), .OD({r.od})) "
                f"{p['u'].ljust(w_u)} (.iRst(iRst), .iClk_Core(iClk_Core), "
                f".iPulse_Hi({ph}), .iPulse_Lo({pl}), .iPulse_Force({pf}), "
                f".iHi({p['hi'].ljust(w_hi)}), .iLo({p['lo'].ljust(w_lo)}), "
                f".iForce({p['force'].ljust(w_fc)}), .o({p['out'].ljust(w_out)}));"
            )
            lines.append(inst)

    lines.append("///// Always Block /////////////////////////////////////////////////////////////")
    lines.append("    // None")
    lines.append("")

    lines.append("///// Continuous Assignment ////////////////////////////////////////////////////")
    out_specs = [
        (_port_name(r.name, "o"), _internal_sig(r.name))
        for r in node_order_rails if r.seq_type != "input"
    ]
    if out_specs:
        w_p = max(len(p) for p, _ in out_specs)
        for p, s in out_specs:
            lines.append(f"    assign {p.ljust(w_p)} = {s};")
    lines.append("")

    lines.append(f"endmodule //{module_name}")
    lines.append(f"`endif  //{define_name}")

    return "\n".join(lines)
