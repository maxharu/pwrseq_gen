#!/usr/bin/env python3
"""Count feedback: AND input pins vs layout trunks (40pt each)."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config_models import PowerSeqConfig
from drawio_export import _build_and_catalog, _count_feedback_trunks

CONST = {"__HIGH__", "__LOW__"}


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "src/reference/golden.json"
    cfg = PowerSeqConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    name_to = {r.name: r for r in cfg.rails}
    outputs = [r for r in cfg.rails if r.seq_type == "output"]
    output_to_row = {r.name: j for j, r in enumerate(outputs)}
    valid = set(name_to)
    trunk_n, trunk_and, trunk_rsmrst = _count_feedback_trunks(
        outputs, output_to_row, name_to, valid
    )
    catalog, _ = _build_and_catalog(outputs)
    print("=== 版面回授幹線（每條 40pt）===")
    print(f"  幹線數: {trunk_n}  (= {trunk_n * 40}pt)")
    print(f"  來源 AND 編號: {sorted(trunk_and)}")
    print(f"  含 RSMRST_N 幹線: {trunk_rsmrst}")
    for i, (rail, hl, gi) in enumerate(catalog, 1):
        if i in trunk_and:
            print(f"    AND #{i} {rail}.{hl}[{gi}]")
    print()

    rows: list[dict] = []
    for tgt in outputs:
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) < 2:
                    continue
                for ii, d in enumerate(group):
                    if d in CONST or d not in name_to:
                        continue
                    if name_to[d].seq_type == "input":
                        continue
                    use = tgt.get_hi_use(gi, ii, d) if hl == "hi" else tgt.get_lo_use(gi, ii, d)
                    inv = tgt.get_hi_inv(gi, ii, d) if hl == "hi" else tgt.get_lo_inv(gi, ii, d)
                    path = "power_cell" if use in ("hi", "lo") else "and_or"
                    rows.append(
                        {
                            "target": tgt.name,
                            "hl": hl,
                            "group": gi,
                            "source": d,
                            "use": use,
                            "inv": inv,
                            "path": path,
                        }
                    )

    unique_sources = {r["source"] for r in rows}
    unique_pairs = {(r["target"], r["source"]) for r in rows}

    print("=== golden.json：回授到 AND 層 input（來源為 output）===")
    print()
    print(f"總條數（每個 AND 輸入埠 1 條）: {len(rows)}")
    print(f"不重複來源 output 數（每一個 output 只算一個名字）: {len(unique_sources)}")
    print(f"不重複 (目標 output, 來源 output) 配對: {len(unique_pairs)}")
    print()
    by_path = Counter(r["path"] for r in rows)
    print("依來源類型（對應 use_mode / 走線）:")
    print(f"  Power Cell 邏輯輸出 (use=hi 或 lo): {by_path['power_cell']}")
    print(f"  該 output 自身 AND/OR (use=self):     {by_path['and_or']}")
    print()
    print("各來源 output 出現在幾個 AND input 埠:")
    for name, c in Counter(r["source"] for r in rows).most_common():
        print(f"  {name}: {c}")
    print()
    print("明細 (目標 AND <- 來源 output):")
    for r in sorted(rows, key=lambda x: (x["target"], x["hl"], x["group"], x["source"])):
        print(
            f"  {r['target']}.{r['hl']}[{r['group']}] <- {r['source']} "
            f"use={r['use']} inv={r['inv']} [{r['path']}]"
        )


if __name__ == "__main__":
    main()
