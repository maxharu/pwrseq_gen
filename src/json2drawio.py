"""CLI: Convert Power Sequence JSON config to Draw.io XML."""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_models import PowerSeqConfig
from drawio_export import generate_drawio


def convert(json_path: str, xml_path: str, optimize: bool) -> None:
    with open(json_path, "r", encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))
    xml = generate_drawio(cfg, optimize_layout=optimize)
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml)


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
    parser.add_argument(
        "--optimize", action="store_true",
        help="Enable layout optimization (topological sort + channel assignment + crossing reduction)",
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
            convert(path, out, args.optimize)
            print(f"[OK] {path} -> {out}")
            ok += 1
        except Exception as e:
            print(f"[ERROR] {path}: {e}", file=sys.stderr)

    print(f"\nDone: {ok}/{len(files)} converted")
    sys.exit(0 if ok == len(files) else 1)


if __name__ == "__main__":
    main()
