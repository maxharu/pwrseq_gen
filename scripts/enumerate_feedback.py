"""Enumerate all cross-row feedback paths in power.json (src_row > tgt_row)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config_models import PowerSeqConfig
from drawio_export import CONST_DEPS, _build_and_catalog, _departing_and_index

cfg = PowerSeqConfig.from_dict(json.load(open(ROOT / "output" / "power.json", encoding="utf-8")))
outputs = [r for r in cfg.rails if r.seq_type != "input"]
output_to_row = {r.name: i for i, r in enumerate(outputs)}
name_to_rail = {r.name: r for r in cfg.rails}
valid = {r.name for r in cfg.rails}
_, and_idx_map = _build_and_catalog(outputs)


def resolve_src_row(d: str, use: str) -> tuple[int | None, str, str]:
    """Return (src_row, category_hint, effective_source)."""
    base_row = output_to_row.get(d)
    if base_row is None:
        return None, "?", d
    # use=hi/lo on upstream rail: logic comes from that rail's hi/lo output
    if use in ("hi", "lo"):
        return base_row, "via_use", d
    return base_row, "self", d


paths: list[dict] = []

for tgt in outputs:
    tgt_row = output_to_row[tgt.name]
    for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
        for gi, group in enumerate(groups):
            for ii, d in enumerate(group):
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "input":
                    continue
                inv = tgt.get_hi_inv(gi, ii, d) if hl == "hi" else tgt.get_lo_inv(gi, ii, d)
                use = tgt.get_hi_use(gi, ii, d) if hl == "hi" else tgt.get_lo_use(gi, ii, d)
                src_row, _, eff = resolve_src_row(d, use)
                if src_row is None or src_row <= tgt_row:
                    continue
                if len(group) >= 2:
                    tgt_kind = f"AND#{and_idx_map.get((tgt.name, hl, gi), '?')}"
                    src_and = _departing_and_index(d, use, idx_map=and_idx_map, name_to_rail=name_to_rail)
                    if src_and is not None:
                        cat = "AND Output"
                        detail = f"AND#{src_and} output"
                    elif d == "RSMRST_N":
                        cat = "RSMRST_N"
                        detail = "RSMRST_N cell (no src AND)"
                    else:
                        cat = "Cell output"
                        detail = f"{d} cell"
                else:
                    tgt_kind = "L_Deb" if hl == "lo" else "H_Deb"
                    src_and = _departing_and_index(d, use, idx_map=and_idx_map, name_to_rail=name_to_rail)
                    if inv and d == "RSMRST_N":
                        cat = "RSMRST_N NOT"
                        detail = "NOT(RSMRST_N)"
                    elif inv and d == "PCH_PWROK":
                        cat = "PCH_PWROK"
                        detail = "NOT(PCH_PWROK)"
                    elif d == "RSMRST_N":
                        cat = "RSMRST_N"
                        detail = "RSMRST_N cell"
                    elif src_and is not None:
                        cat = "AND Output"
                        detail = f"AND#{src_and} output"
                    else:
                        cat = "Cell output"
                        detail = f"{d} cell"
                paths.append({
                    "cat": cat,
                    "src_rail": d,
                    "eff": eff,
                    "use": use,
                    "inv": inv,
                    "tgt": tgt.name,
                    "hl": hl,
                    "gi": gi,
                    "tgt_kind": tgt_kind,
                    "detail": detail,
                    "src_row": src_row,
                    "tgt_row": tgt_row,
                })

# Also: use=lo/hi where dep rail is upstream but logic resolves to lower row?
# e.g. PCH_P1V25A_EN lo uses PCH_P0V85A_EN with use=lo -> lo logic on row 0, not row 7
# Re-resolve effective source row for use=hi/lo pointing to upstream rail's logic chain
for p in paths:
    d, use = p["src_rail"], p["use"]
    if use == "lo":
        src_r = name_to_rail[d]
        lo_groups = src_r.get_lo_groups()
        if lo_groups and len(lo_groups[0]) == 1 and lo_groups[0][0] in output_to_row:
            inner = lo_groups[0][0]
            if name_to_rail[inner].seq_type == "output":
                inner_row = output_to_row[inner]
                if inner_row > p["tgt_row"]:
                    p["resolved_from"] = inner
                    p["resolved_row"] = inner_row

print(f"Total cross-row feedback (src_row > tgt_row): {len(paths)}\n")

from collections import Counter
cats = Counter(p["cat"] for p in paths)
for c, n in sorted(cats.items()):
    print(f"  {c}: {n}")

# User buckets
def user_bucket(p):
    if p["cat"] == "RSMRST_N NOT":
        return "RSMRST_N NOT"
    if p["cat"] == "PCH_PWROK":
        return "PCH_PWROK"
    if p["cat"] == "AND Output":
        return "AND Output"
    if p["src_rail"] == "RSMRST_N" or p.get("resolved_from") == "RSMRST_N":
        return "RSMRST_N"
    return p["cat"]

print("\n=== By user-style bucket ===")
ub = Counter(user_bucket(p) for p in paths)
for c, n in sorted(ub.items()):
    print(f"  {c}: {n}")

print("\n=== Detail ===")
for i, p in enumerate(sorted(paths, key=lambda x: (user_bucket(x), x["tgt_row"], x["tgt"])), 1):
    inv_s = " inv" if p["inv"] else ""
    print(
        f"{i:2}. [{user_bucket(p)}] {p['detail']} "
        f"({p['src_rail']} use={p['use']}{inv_s}, row {p['src_row']}) "
        f"-> {p['tgt']}/{p['hl']} {p['tgt_kind']} (row {p['tgt_row']})"
    )

# Separate: cross-row where dep uses hi/lo but effective source is different rail
print("\n=== use=hi/lo resolved to different row ===")
extra = []
for tgt in outputs:
    tgt_row = output_to_row[tgt.name]
    for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
        for gi, group in enumerate(groups):
            for ii, d in enumerate(group):
                if d not in valid or d in CONST_DEPS:
                    continue
                if name_to_rail[d].seq_type == "input":
                    continue
                use = tgt.get_hi_use(gi, ii, d) if hl == "hi" else tgt.get_lo_use(gi, ii, d)
                if use not in ("hi", "lo"):
                    continue
                dep_row = output_to_row.get(d)
                # effective logic row = same as dep for hi/lo output on that rail
                eff_row = dep_row
                if eff_row is None or eff_row <= tgt_row:
                    continue
                inv = tgt.get_hi_inv(gi, ii, d) if hl == "hi" else tgt.get_lo_inv(gi, ii, d)
                if len(group) >= 2:
                    kind = f"AND#{and_idx_map.get((tgt.name, hl, gi), '?')}"
                else:
                    kind = "Deb"
                # Check if already in paths
                key = (d, use, tgt.name, hl, gi, ii)
                if not any(
                    p["src_rail"] == d and p["use"] == use and p["tgt"] == tgt.name
                    and p["hl"] == hl and p["gi"] == gi
                    for p in paths
                ):
                    extra.append(key)

print(f"extra not in main list: {len(extra)}")
