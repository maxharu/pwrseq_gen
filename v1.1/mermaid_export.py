"""
Export Power Sequence dependency as Mermaid flowchart.
"""
from config_models import PowerSeqConfig, PowerRail

DEP_HIGH = "__HIGH__"
DEP_LOW = "__LOW__"
CONST_DEPS = {DEP_HIGH, DEP_LOW}


def _mermaid_id(name: str) -> str:
    """Mermaid node id: alphanumeric and underscore only."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def generate_mermaid(config: PowerSeqConfig) -> str:
    """
    Generate Mermaid flowchart TB (top-bottom).
    - Nodes: all rails. Inputs in subgraph, outputs with Hi/Lo edges.
    - Hi dependency: solid arrow -->
    - Lo dependency: dotted arrow -.->
    """
    lines = ["flowchart TB"]
    name_to_rail = {r.name: r for r in config.rails}
    valid = set(name_to_rail.keys())

    inputs = [r for r in config.rails if r.seq_type == "input"]
    outputs = [r for r in config.rails if r.seq_type == "output"]

    if inputs:
        lines.append("  subgraph Inputs[Inputs]")
        for r in inputs:
            nid = _mermaid_id(r.name)
            lines.append(f"    {nid}[\"{r.name}\"]")
        lines.append("  end")

    for r in outputs:
        nid = _mermaid_id(r.name)
        lines.append(f"  {nid}[\"{r.name}\"]")

    # Hi edges
    for r in outputs:
        to_id = _mermaid_id(r.name)
        for d in r.get_depends_on_hi_flat():
            if d not in valid or d in CONST_DEPS:
                continue
            from_id = _mermaid_id(d)
            inv = r.depends_on_hi_inv.get(d, False)
            label = "Hi" if not inv else "~Hi"
            lines.append(f"  {from_id} -->|{label}| {to_id}")

    # Lo edges
    for r in outputs:
        to_id = _mermaid_id(r.name)
        for d in r.get_depends_on_lo_flat():
            if d not in valid or d in CONST_DEPS:
                continue
            from_id = _mermaid_id(d)
            inv = r.depends_on_lo_inv.get(d, False)
            label = "Lo" if not inv else "~Lo"
            lines.append(f"  {from_id} -.->|{label}| {to_id}")

    return "\n".join(lines)
