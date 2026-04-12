---
name: hierarchical-layout
description: >-
  Implements hierarchical (layered) graph layout using the Sugiyama framework
  and SPX co-optimization for Draw.io diagrams, DAGs, circuit schematics, and
  dependency graphs. Use when the user asks about graph layout, Sugiyama
  algorithm, crossing minimization, layer assignment, coordinate assignment,
  edge routing, Draw.io auto-layout, circuit diagram placement, DAG
  visualization, or multi-criteria layout optimization.
---

# Hierarchical Graph Layout

Apply the **Sugiyama framework** (three-phase layered layout) with **SPX
co-optimization** to produce readable hierarchical graph drawings. This skill
covers the full pipeline from abstract graph to Draw.io XML coordinates.

## When to Use

- Laying out a directed acyclic graph (DAG) or dependency graph
- Generating or improving Draw.io / mxGraph XML layout
- Placing circuit components (gates, cells) with orthogonal edge routing
- Reducing edge crossings in an existing diagram
- Any task mentioning "hierarchical layout", "Sugiyama", or "crossing minimization"

## Sugiyama Three-Phase Pipeline

Every hierarchical layout follows these phases in order. Each phase takes the
output of the previous phase as input.

### Phase 1: Layer Assignment

Assign each vertex to a horizontal layer (rank) so that all edges point in the
same direction (typically top-to-bottom or left-to-right).

**Recommended algorithms (pick one):**

| Algorithm | When to use | Complexity |
|-----------|-------------|------------|
| Longest-path | Simple DAGs, fast | O(V + E) |
| Coffman-Graham | Minimize width given max layer size | O(V + E) |
| Network simplex | Best quality, handles min-edge-length | O(V * E) |

**Key decisions:**
- Direction: top-to-bottom (default) or left-to-right (for signal-flow diagrams)
- Dummy vertices: insert dummy nodes on edges that span multiple layers so every
  edge connects adjacent layers only. Track which vertices are dummies for Phase 3.

**Data structures:**

```python
layer: dict[str, int]       # vertex_id -> layer number
adj: dict[str, list[str]]   # vertex_id -> list of successor ids
```

### Phase 2: Crossing Minimization

Reorder vertices within each layer to minimize edge crossings.

**Recommended algorithms:**

| Algorithm | Description | Iterations |
|-----------|-------------|------------|
| Barycenter | Position = mean of neighbors' positions in adjacent layer | 4-8 sweeps |
| Median | Position = median of neighbors' positions | 4-8 sweeps |
| Adjacent swap | Pairwise swap if it reduces crossings | Until stable |

**Barycenter heuristic (primary recommendation):**

```python
for _ in range(num_sweeps):
    for each layer L (alternating top-down / bottom-up):
        for each vertex v in L:
            neighbors = vertices connected to v in the fixed adjacent layer
            if neighbors:
                bary[v] = mean(position[n] for n in neighbors)
            else:
                bary[v] = current_position[v]
        reorder L by bary values
        if reorder violates constraints (e.g., topological): revert
```

**Constraint preservation:** after reordering, verify that topological
constraints still hold. If violated, revert to the previous ordering for that
sweep.

### Phase 3: Coordinate Assignment

Assign concrete (x, y) coordinates to each vertex.

**Recommended algorithms:**

| Algorithm | Quality | Speed |
|-----------|---------|-------|
| Brandes-Kopf | Good balance, handles dummy vertices well | Fast |
| LP-based | Optimal but slow for large graphs | Slow |
| Simple grid | Uniform spacing, easy to implement | Fastest |

**Simple grid approach (good starting point):**

```python
GRID = 40   # alignment grid
GAP = 80    # minimum spacing between elements

for each layer L:
    y = layer_index * (max_node_height + GAP)
    for each vertex v in L (in crossing-minimized order):
        x = position_index * (max_node_width + GAP)
        coords[v] = (align_to_grid(x), align_to_grid(y))
```

**Channel routing for edges:** when edges share vertical/horizontal corridors,
assign each wire to a separate channel to prevent overlap. See
`_ChannelAllocator` pattern in [examples.md](examples.md).

## SPX Co-optimization

After the Sugiyama pipeline produces an initial layout, apply **Stress-Plus-X**
refinement to simultaneously improve multiple readability criteria.

### Objective Function

```
L = w_s * stress(pos) + w_c * crossings(pos) + w_a * angle_penalty(pos) + w_u * upwardness(pos)
```

| Term | What it measures | Weight guide |
|------|-----------------|--------------|
| stress | Sum of (actual_dist - ideal_dist)^2 for all pairs | 1.0 (baseline) |
| crossings | Number of edge crossings | 5.0-20.0 (high priority) |
| angle_penalty | Deviation of crossing angles from 90 degrees | 0.5-2.0 |
| upwardness | Fraction of edges not pointing in the intended direction | 2.0-10.0 (DAGs) |

### Optimization Strategy

1. Run Sugiyama to get initial positions
2. Compute L with current positions
3. For each iteration:
   - Try small perturbations (swap adjacent nodes, nudge coordinates)
   - Accept if L decreases
   - Simulated annealing: occasionally accept worse solutions early on
4. Stop when no improvement for N iterations

### Weight Selection Guide

| Graph type | w_stress | w_cross | w_angle | w_upward |
|------------|----------|---------|---------|----------|
| DAG / dependency | 1.0 | 10.0 | 1.0 | 5.0 |
| Circuit schematic | 1.0 | 20.0 | 0.5 | 2.0 |
| General undirected | 1.0 | 5.0 | 2.0 | 0.0 |
| Sparse tree-like | 0.5 | 5.0 | 0.0 | 3.0 |

## Draw.io XML Integration

### Setting Vertex Positions

```xml
<mxCell id="v1" vertex="1" parent="1" value="Node" style="...">
  <mxGeometry x="160" y="80" width="80" height="40" as="geometry" />
</mxCell>
```

Set `x` and `y` in `mxGeometry` to the computed coordinates. Align to grid:

```python
def align_to_grid(v, grid=40):
    return round(v / grid) * grid
```

### Setting Edge Waypoints

```xml
<mxCell id="e1" edge="1" source="v1" target="v2" style="edgeStyle=orthogonalEdgeStyle;...">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="200" y="120" />
      <mxPoint x="200" y="200" />
    </Array>
  </mxGeometry>
</mxCell>
```

Insert `mxPoint` elements in the `Array` for each waypoint. For orthogonal
routing, ensure consecutive waypoints differ in only one axis (x or y).

### Orthogonal Edge Routing

For circuit-style diagrams, all edges should be horizontal or vertical segments:

1. Compute source exit point (exitX, exitY) and target entry point (entryX, entryY)
2. Route through channel corridors using `_ChannelAllocator`
3. Insert waypoints at each bend

### Grid Alignment Rules

- Vertex positions: align to GRID (typically 40pt)
- Edge waypoints: align to GRID, except where alignment would misalign with
  connection points (e.g., input label y)
- Minimum element spacing: GAP (typically 80pt)

## Quality Checklist

After layout, verify:

- [ ] No vertex overlaps
- [ ] No edge-vertex overlaps (edges route around components)
- [ ] No overlapping edge segments in the same corridor
- [ ] All edges orthogonal (for circuit/schematic style)
- [ ] Coordinates aligned to grid
- [ ] Edge crossings minimized (compare before/after count)
- [ ] DAG edges point in the intended direction

## Additional Resources

- For algorithm pseudocode and formulas, see [reference.md](reference.md)
- For implementation examples from pwrseq_gen, see [examples.md](examples.md)
