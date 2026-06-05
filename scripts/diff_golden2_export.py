#!/usr/bin/env python3
"""Pixel/layout diff: export (golden.json) vs src/reference/golden2.xml."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config_models import PowerSeqConfig
from drawio_export import generate_drawio
from drawio_golden_diff import diff_golden2_export


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--golden-json",
        type=Path,
        default=ROOT / "src/reference/golden.json",
    )
    p.add_argument(
        "--golden2-xml",
        type=Path,
        default=ROOT / "src/reference/golden2.xml",
    )
    p.add_argument("--tol", type=float, default=0.5, help="position tolerance (pt)")
    p.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit 1 when differences found",
    )
    args = p.parse_args()

    with open(args.golden_json, encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))
    export_xml = generate_drawio(cfg)
    report = diff_golden2_export(
        cfg,
        export_xml,
        str(args.golden2_xml),
        pos_tol=args.tol,
    )
    print(report.format_text(tol=args.tol))
    if args.fail_on_diff and not report.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
