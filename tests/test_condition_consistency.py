"""Cross-consistency between the four condition backends.

Verilog / C / Draw.io / the simulator each re-implement the same dependency
semantics. Nothing in the code forces them to agree, so this module states the
semantics once as an oracle and checks every backend against it.

The semantics live in `core.cond_ir`; this module reads them back through a
visitor as a *leaf* tuple and compares every backend against it:

    ("const", 0|1)              __LOW__ / __HIGH__
    ("level", name)             that node's actual level
    ("cond", name, hi|lo|force) that node's condition signal

`tests/test_cond_ir.py` checks `core.cond_ir` against hand-written expectations,
so a wrong IR cannot quietly make every backend agree here. Group assembly
(intra_op -> group_inv -> OR-join) is shared via `core.group_logic` and is not
re-checked here.

Every backend now matches the oracle exactly, so each sweep asserts an empty
disagreement set. Earlier versions carried KNOWN_* allow-lists for legitimate
divergences; the last one went away when the simulator learned Force.

Scope: this checks *leaf* rendering only. Gate topology (which Draw.io derives
from group shape in `drawio_geometry`) is not covered here -- see doc/FUTURE.md.
"""
import json
import os

import pytest

from codegen.c_generator import _CCond
from codegen.verilog_generator import _VerilogCond
from core.cond_ir import CondVisitor, resolve_dep, resolve_item
from core.config_models import PowerRail, PowerSeqConfig
from core.constants import DEP_HIGH, DEP_LOW
from core.naming import internal_sig, safe_name
from drawio.drawio_cell_export import _DrawioCond
from timing.timing_sim import _SimCond

TEMPLATES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
)
C_VAR = "power_var"

FIXTURE_RAILS = [
    PowerRail(name="IN_PLAIN", seq_type="input", deb_enable=False),
    PowerRail(name="IN_DEB", seq_type="input", deb_enable=True),
    PowerRail(name="OUT_CELL", seq_type="output", depends_on_hi=[DEP_HIGH]),
]
DEPS = [DEP_HIGH, DEP_LOW, "IN_PLAIN", "IN_DEB", "OUT_CELL"]
USES = ["self", "hi", "lo", "force"]


def _name_to_rail(rails):
    return {r.name: r for r in rails}


class _LeafTuple(CondVisitor):
    """Flatten a cond_ir leaf into the tuple form the _want_* helpers expect."""

    def const(self, value):
        return ("const", value)

    def level(self, name):
        return ("level", name)

    def cond(self, name, kind):
        return ("cond", name, kind)

    def invert(self, operand):
        raise AssertionError("resolve_dep never wraps a leaf in Not")

    def group(self, op, items):
        raise AssertionError("resolve_dep never returns a group")

    def any_group(self, groups):
        raise AssertionError("resolve_dep never returns a group join")


def _spec_leaf(dep, use, name_to_rail):
    """Documented semantics (F-DEP-07, timing-sim-behavior.mdc §2)."""
    return resolve_dep(dep, use, name_to_rail).accept(_LeafTuple())


def _want_verilog(leaf, name_to_rail, inv):
    if leaf[0] == "const":
        return "1'b1" if leaf[1] ^ inv else "1'b0"
    if leaf[0] == "cond":
        base = f"{internal_sig(leaf[1])}_{leaf[2]}"
    else:
        rail = name_to_rail.get(leaf[1])
        if rail is not None and rail.seq_type == "output":
            base = internal_sig(leaf[1])
        elif rail is not None and rail.deb_enable:
            base = f"{internal_sig(leaf[1])}_deb"
        else:
            base = "i" + safe_name(leaf[1])
    return f"(~{base})" if inv else base


def _want_c(leaf, inv):
    if leaf[0] == "const":
        return "1" if leaf[1] ^ inv else "0"
    if leaf[0] == "cond":
        base = f"{C_VAR}.{internal_sig(leaf[1])}.{leaf[2]}.condition"
    else:
        base = f"oemgpio_DI_Get({safe_name(leaf[1]).upper()})"
    return f"!{base}" if inv else base


def _want_drawio(leaf, inv):
    """Constants need no gate input, and Force is not drawn at all."""
    if leaf[0] == "const" or leaf == ("cond", leaf[1], "force"):
        return None
    base = f"{internal_sig(leaf[1])}_{leaf[2]}" if leaf[0] == "cond" else leaf[1]
    return f"~{base}" if inv else base


def _sim_actual(dep, use, inv, name_to_rail, bit):
    """Drive `bit` into whichever channel the leaf should read, then evaluate."""
    leaf = _spec_leaf(dep, use, name_to_rail)
    raw, out_hi, out_lo, out_force, out_val = {}, {}, {}, {}, {}
    if leaf[0] == "level":
        rail = name_to_rail.get(leaf[1])
        if rail is not None and rail.seq_type == "output":
            out_val[internal_sig(leaf[1])] = bit
        else:
            raw[leaf[1]] = bit
    elif leaf[0] == "cond":
        channel = {"hi": out_hi, "lo": out_lo, "force": out_force}[leaf[2]]
        channel[internal_sig(leaf[1])] = bit
    evaluator = _SimCond(name_to_rail, raw, out_hi, out_lo, out_force, out_val)
    return resolve_item(dep, inv, use, name_to_rail).accept(evaluator)


def _disagreements(backend, deps, uses, name_to_rail):
    """Return the (dep, use) pairs where `backend` departs from the oracle."""
    bad = set()
    for dep in deps:
        for use in uses:
            leaf = _spec_leaf(dep, use, name_to_rail)
            for inv in (False, True):
                if backend == "verilog":
                    item = resolve_item(dep, inv, use, name_to_rail)
                    ok = item.accept(_VerilogCond(name_to_rail)) == _want_verilog(
                        leaf, name_to_rail, inv
                    )
                elif backend == "c":
                    item = resolve_item(dep, inv, use, name_to_rail)
                    ok = item.accept(_CCond(C_VAR)) == _want_c(leaf, inv)
                elif backend == "drawio":
                    item = resolve_item(dep, inv, use, name_to_rail)
                    term = item.accept(_DrawioCond(set(name_to_rail)))
                    ok = (term.text if term else None) == _want_drawio(leaf, inv)
                else:
                    ok = all(
                        _sim_actual(dep, use, inv, name_to_rail, bit)
                        == ((leaf[1] if leaf[0] == "const" else bit) ^ inv)
                        for bit in (0, 1)
                    )
                if not ok:
                    bad.add((dep, use))
    return bad


def _sweep(backend):
    return _disagreements(backend, DEPS, USES, _name_to_rail(FIXTURE_RAILS))


def test_verilog_matches_spec():
    assert _sweep("verilog") == set()


def test_c_matches_spec():
    assert _sweep("c") == set()


def test_drawio_matches_spec():
    assert _sweep("drawio") == set()


def test_simulator_matches_spec():
    assert _sweep("sim") == set()


def _load(path):
    if path.endswith(".xlsm"):
        pytest.importorskip("openpyxl")
        from excel.excel_import import load_powerseq_from_excel

        return load_powerseq_from_excel(path)
    with open(path, encoding="utf-8") as f:
        return PowerSeqConfig.from_dict(json.load(f))


@pytest.mark.parametrize(
    "filename", ["demo_json.json", "multi-group.xlsm", "x15dot-f.xlsm"]
)
def test_real_configs_only_hit_known_divergences(filename):
    """Same check against shipped configs, so realistic shapes are covered too."""
    path = os.path.join(TEMPLATES, filename)
    if not os.path.isfile(path):
        pytest.skip(f"templates/{filename} missing")
    config = _load(path)
    name_to_rail = _name_to_rail(config.rails)

    for rail in config.rails:
        if not rail.has_pseqcell:
            continue
        for kind in ("hi", "lo", "force"):
            groups = getattr(rail, f"get_{kind}_groups")()
            get_use = getattr(rail, f"get_{kind}_use")
            for gi, group in enumerate(groups):
                for ii, dep in enumerate(group):
                    use = get_use(gi, ii, dep)
                    where = f"{rail.name}.{kind}[{gi}][{ii}] dep={dep} use={use}"
                    dep_rail = name_to_rail.get(dep)
                    is_input = dep_rail is not None and dep_rail.seq_type == "input"

                    for backend in ("verilog", "c", "drawio", "sim"):
                        bad = _disagreements(backend, [dep], [use], name_to_rail)
                        if not bad:
                            continue
                        if backend == "sim" and use == "force" and not is_input:
                            continue
                        pytest.fail(f"{backend} diverges at {where}")
