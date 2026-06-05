"""Analyze route_orthogonal success/failure for output/power.json."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")

from config_models import PowerSeqConfig
from drawio_export import GRID, generate_drawio
from drawio_export_options import DrawioExportOptions
from layout_engine import (
    ROUTE_GRID_FALLBACK,
    _anchor_point,
    _astar_orthogonal,
    _astar_orthogonal_with_fallback,
    _bbox,
    _collect_edges,
    _collect_vertices,
    _entry_stub_point,
    _exit_stub_point,
    _parse_style,
    _style_float,
    route_orthogonal,
)


def _edge_label(root: ET.Element, sid: str | None, tid: str | None) -> str:
    parts = []
    for vid, role in ((sid, "src"), (tid, "tgt")):
        if not vid:
            parts.append(f"{role}=?")
            continue
        cell = root.find(f".//mxCell[@id='{vid}']")
        val = (cell.get("value") or "").strip() if cell is not None else ""
        parts.append(f"{role}={val or vid}")
    return " -> ".join(parts)


def analyze_route_orthogonal(root: ET.Element, skip_edge_ids: set[str]) -> dict:
    """Mirror route_orthogonal with per-edge skip reasons."""
    grid = GRID
    vertices = _collect_vertices(root, "1")
    boxes_by_id: dict[str, tuple[float, float, float, float]] = {}
    for v in vertices:
        vid = v.get("id")
        bb = _bbox(v)
        if vid is not None and bb is not None:
            boxes_by_id[vid] = bb

    routed_v: list = []
    routed_h: list = []
    opts = DrawioExportOptions.defaults()
    results: list[dict] = []

    for cell in _collect_edges(root, "1"):
        eid = cell.get("id") or "?"
        sid = cell.get("source")
        tid = cell.get("target")
        label = _edge_label(root, sid, tid)

        if eid in skip_edge_ids:
            results.append({"id": eid, "label": label, "status": "skipped_fixed", "reason": "NOT/fixed edge"})
            continue
        if sid is None or tid is None:
            results.append({"id": eid, "label": label, "status": "skipped", "reason": "missing source/target"})
            continue
        s_box = boxes_by_id.get(sid)
        t_box = boxes_by_id.get(tid)
        if s_box is None or t_box is None:
            results.append({"id": eid, "label": label, "status": "skipped", "reason": "missing bbox"})
            continue

        st = _parse_style(cell.get("style"))
        exit_ax = _style_float(st, "exitX", 1.0)
        exit_ay = _style_float(st, "exitY", 0.5)
        entry_ax = _style_float(st, "entryX", 0.0)
        entry_ay = _style_float(st, "entryY", 0.5)
        if exit_ax < 0.75 or entry_ax > 0.25:
            results.append({
                "id": eid, "label": label, "status": "skipped",
                "reason": f"non-standard anchors exitX={exit_ax} entryX={entry_ax}",
            })
            continue

        ex, ey = _anchor_point(s_box, exit_ax, exit_ay)
        tx, ty = _anchor_point(t_box, entry_ax, entry_ay)
        if ex >= tx - grid:
            results.append({
                "id": eid, "label": label, "status": "skipped",
                "reason": f"target too close (ex={ex:.0f} tx={tx:.0f})",
            })
            continue

        start_stub = _exit_stub_point(ex, ey, exit_ax, tx)
        end_stub = _entry_stub_point(tx, ty, entry_ax, ex)
        obstacles = [b for vid, b in boxes_by_id.items() if vid not in (sid, tid)]

        p40 = _astar_orthogonal(
            start_stub, end_stub, obstacles, grid, routed_v, routed_h,
            source_id=sid, dest_id=tid, overlap_options=opts,
        )
        p20 = None
        if p40 is None:
            p20 = _astar_orthogonal(
                start_stub, end_stub, obstacles, ROUTE_GRID_FALLBACK, routed_v, routed_h,
                source_id=sid, dest_id=tid, overlap_options=opts,
            )
        path = p40 if p40 is not None else p20

        if path is None:
            results.append({
                "id": eid, "label": label, "status": "failed",
                "reason": "A* failed at 40pt and 20pt",
            })
            continue

        grid_used = grid if p40 is not None else ROUTE_GRID_FALLBACK
        full_path = __import__("layout_engine")._collapse_collinear(
            [(ex, ey), start_stub] + path[1:-1] + [end_stub, (tx, ty)]
        )
        for k in range(len(full_path) - 1):
            ax2, ay2 = full_path[k]
            bx2, by2 = full_path[k + 1]
            if abs(ax2 - bx2) < 0.5 and abs(ay2 - by2) >= 0.5:
                routed_v.append((ax2, min(ay2, by2), max(ay2, by2), sid, tid))
            elif abs(ay2 - by2) < 0.5 and abs(ax2 - bx2) >= 0.5:
                routed_h.append((ay2, min(ax2, bx2), max(ax2, bx2), sid, tid))

        results.append({
            "id": eid, "label": label, "status": "ok",
            "reason": f"routed grid={grid_used}",
        })

    return {"results": results}


def main() -> int:
    with open("output/power.json", encoding="utf-8") as f:
        cfg = PowerSeqConfig.from_dict(json.load(f))

    xml = generate_drawio(cfg, options=DrawioExportOptions.defaults())
    root = ET.fromstring(xml)

    # NOT/fixed edges: edgeStyle=none but in skip set — detect by label->NOT pattern
    fixed_not = 0
    rerouted = 0
    still_ortho = 0
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        sty = cell.get("style") or ""
        if "edgeStyle=none" in sty:
            rerouted += 1
        elif "edgeStyle=orthogonalEdgeStyle" in sty:
            still_ortho += 1

    # Re-run analysis on pre-route state: generate XML before route_orthogonal
    # Use exported XML — compare rerouted vs still_ortho after full export
    skip_ids: set[str] = set()
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        sid, tid = cell.get("source"), cell.get("target")
        sv = root.find(f".//mxCell[@id='{sid}']") if sid else None
        tv = root.find(f".//mxCell[@id='{tid}']") if tid else None
        if sv is not None and "inverter_2" in (sv.get("style") or ""):
            pass
        if tv is not None and "inverter_2" in (tv.get("style") or ""):
            sty = cell.get("style") or ""
            if "edgeStyle=none" not in sty and sid:
                # label/O -> NOT often kept with waypoints + skip in route
                tgt_style = tv.get("style") or ""
                if "inverter_2" in tgt_style:
                    eid = cell.get("id")
                    if eid:
                        skip_ids.add(eid)

    # Identify NOT inbound edges (source is label or O, target is NOT)
    for cell in root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        tid = cell.get("target")
        if not tid:
            continue
        tv = root.find(f".//mxCell[@id='{tid}']")
        if tv is not None and "inverter_2" in (tv.get("style") or ""):
            eid = cell.get("id")
            if eid:
                skip_ids.add(eid)
                fixed_not += 1

    # Build fresh graph before route for accurate simulate — call generate internals
    # Instead: parse final XML stats + simulate on a clone before route
    # Simplest accurate path: monkeypatch route_orthogonal return and trace

    # Simulate routing decisions by re-parsing: use xml BEFORE route from partial gen
    # For accurate skip/fail counts, duplicate pre-route graph via second export hook
    from drawio_export import generate_drawio as gd  # noqa

    # Run analysis on XML produced WITHOUT route — inject by reading generate_drawio
    # Actually run route_orthogonal on xml with all skip_ids empty to see pure A* fail
    # NOT edges have waypoints — route skips them in production via skip_edge_ids

    print("=== power.json Draw.io routing report ===")
    print(f"Total edges (final XML): {rerouted + still_ortho}")
    print(f"  edgeStyle=none (A* rerouted): {rerouted}")
    print(f"  edgeStyle=orthogonalEdgeStyle (NOT rerouted): {still_ortho}")
    print(f"  label/O -> NOT (fixed, skip A*): ~{fixed_not}")

    # Full pipeline re-sim: need pre-route root. Call generate_drawio pieces...
    # Quick approach: regenerate and use route_orthogonal with empty skip to see all failures
    pre_xml = xml  # post full export
    pre_root = ET.fromstring(pre_xml)

    # Edges still orthogonal after export = failed/skipped route_orthogonal
    failed_edges = []
    for cell in pre_root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id") or "?"
        sty = cell.get("style") or ""
        if "edgeStyle=orthogonalEdgeStyle" in sty:
            failed_edges.append({
                "id": eid,
                "label": _edge_label(pre_root, cell.get("source"), cell.get("target")),
                "style_snip": sty[:80],
            })

    print(f"\nEdges still on orthogonalEdgeStyle (route_orthogonal did NOT apply): {len(failed_edges)}")
    for e in failed_edges[:25]:
        print(f"  [{e['id']}] {e['label']}")
    if len(failed_edges) > 25:
        print(f"  ... and {len(failed_edges) - 25} more")

    # Deep simulate: rebuild without calling full generate — use exported xml,
    # reset edge styles to orthogonal for non-NOT edges and re-run route
    sim_root = ET.fromstring(xml)
    for cell in sim_root.iter("mxCell"):
        if cell.get("edge") != "1":
            continue
        eid = cell.get("id")
        if eid in skip_ids:
            continue
        sty = cell.get("style") or ""
        if "edgeStyle=none" in sty:
            sty = sty.replace("edgeStyle=none", "edgeStyle=orthogonalEdgeStyle")
            cell.set("style", sty)

    n = route_orthogonal(sim_root, grid=GRID, skip_edge_ids=skip_ids)
    print(f"\nRe-sim route_orthogonal rerouted: {n} (skip NOT edges: {len(skip_ids)})")

    report = analyze_route_orthogonal(sim_root, skip_ids)
    by_status: dict[str, list] = {}
    for r in report["results"]:
        by_status.setdefault(r["status"], []).append(r)

    print("\nPer-edge simulation (after reset to pre-route style):")
    for status in ("ok", "failed", "skipped", "skipped_fixed"):
        items = by_status.get(status, [])
        print(f"  {status}: {len(items)}")
        for r in items:
            if status in ("failed", "skipped"):
                print(f"    [{r['id']}] {r['label']} — {r['reason']}")
            elif status == "ok" and "grid=20" in r.get("reason", ""):
                print(f"    [{r['id']}] {r['label']} — {r['reason']}")

    astar_failed = by_status.get("failed", [])
    non_std = [r for r in by_status.get("skipped", []) if "non-standard" in r["reason"]]
    too_close = [r for r in by_status.get("skipped", []) if "too close" in r["reason"]]

    print("\n=== Summary ===")
    print(f"A* 40pt+20pt both failed: {len(astar_failed)}")
    print(f"Skipped (non-standard direction): {len(non_std)}")
    print(f"Skipped (target too close): {len(too_close)}")
    print(f"Skipped fixed NOT: {len(by_status.get('skipped_fixed', []))}")
    print(f"Successfully routed: {len(by_status.get('ok', []))}")

    return 1 if astar_failed or non_std else 0


if __name__ == "__main__":
    raise SystemExit(main())
