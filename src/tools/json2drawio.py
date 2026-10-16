"""CLI: Convert Power Sequence JSON config to Draw.io XML."""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config_models import PowerSeqConfig
from pipeline import export as run_export


def convert(json_path: str, xml_path: str) -> None:
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))
    # 走與 GUI 同一條匯出路徑：validate 由 pipeline 把關，無效設定不會寫出檔案
    result = run_export(cfg, "drawio", xml_path)
    if not result.ok:
        raise ValueError("; ".join(result.errors))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Power Sequence JSON to Draw.io XML",
    )
    parser.add_argument(
        "input", nargs="+",
        help="JSON config file(s); supports wildcards e.g. *.json",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output XML path (only when a single input is given)",
    )
    args = parser.parse_args()

    files: list[str] = []
    for pattern in args.input:
        expanded = glob.glob(pattern)
        if expanded:
            files.extend(expanded)
        else:
            files.append(pattern)

    if args.output and len(files) > 1:
        parser.error("-o/--output can only be used with a single input file")

    ok = 0
    for path in files:
        if not os.path.isfile(path):
            print(f"[SKIP] not found: {path}", file=sys.stderr)
            continue
        out = args.output if args.output else os.path.splitext(path)[0] + ".xml"
        try:
            convert(path, out)
            print(f"[OK] {path} -> {out}")
            ok += 1
        except Exception as e:
            print(f"[ERROR] {path}: {e}", file=sys.stderr)

    print(f"\nDone: {ok}/{len(files)} converted")
    sys.exit(0 if ok == len(files) else 1)


if __name__ == "__main__":
    main()
