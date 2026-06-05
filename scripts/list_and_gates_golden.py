#!/usr/bin/env python3
"""List AND gates top-to-bottom (config order) and output feedback deps."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config_models import PowerSeqConfig

CONST = {"__HIGH__", "__LOW__"}


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "src/reference/golden.json"
    cfg = PowerSeqConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    name_to = {r.name: r for r in cfg.rails}
    outputs = [r for r in cfg.rails if r.seq_type == "output"]

    idx = 0
    feedback_by_and: list[tuple[int, str, str, str, str, str]] = []
    for tgt in outputs:
        for hl, groups in [("hi", tgt.get_hi_groups()), ("lo", tgt.get_lo_groups())]:
            for gi, group in enumerate(groups):
                if len(group) < 2:
                    continue
                idx += 1
                out_deps = []
                for ii, d in enumerate(group):
                    if d in CONST or d not in name_to or name_to[d].seq_type == "input":
                        continue
                    use = tgt.get_hi_use(gi, ii, d) if hl == "hi" else tgt.get_lo_use(gi, ii, d)
                    path = "power_cell" if use in ("hi", "lo") else "and_or"
                    out_deps.append((d, use, path))
                    feedback_by_and.append((idx, tgt.name, hl, gi, d, path))
                mark = " <-- output回授" if out_deps else ""
                print(f"AND #{idx:2d}  {tgt.name}.{hl}[{gi}]  deps={group}{mark}")
                for d, use, path in out_deps:
                    print(f"         <- {d} use={use} [{path}]")

    print()
    print(f"AND 總數: {idx}")
    print(f"output 回授埠總數: {len(feedback_by_and)}")


if __name__ == "__main__":
    main()
