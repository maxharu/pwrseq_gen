# Hierarchical Layout Examples

Real-world examples from the **pwrseq_gen** project showing how each Sugiyama
phase and SPX concept maps to actual Python code.

---

## Example 1: Layer Assignment via Topological Sort

**File:** `src/drawio_export.py` -- `_topological_order_outputs()`

This function assigns an implicit layer order to output nodes using DFS-based
topological sort. Nodes that are depended upon are visited first and placed
earlier in the result list.

```python
def _topological_order_outputs(outputs, name_to_rail):
    out_names = {r.name for r in outputs}
    result = []
    visited = set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        rail = name_to_rail.get(name)
        if rail and rail in outputs:
            for dep in rail.get_depends_on_hi_flat() + rail.get_depends_on_lo_flat():
                if dep not in CONST_DEPS and dep in out_names:
                    visit(dep)
            result.append(rail)

    for r in outputs:
        visit(r.name)
    return result
```

**Mapping to Sugiyama Phase 1:**
- The graph is the dependency DAG among output rails
- "Layer" is the position in the result list (index 0 = topmost row)
- Dependencies are visited recursively before the dependent node

---

## Example 2: Crossing Minimization via Barycenter

**File:** `src/drawio_export.py` -- `_barycenter_order_outputs()`

After topological sort, this function refines the ordering using the barycenter
heuristic to minimize edge crossings between rows.

```python
def _barycenter_order_outputs(outputs, name_to_rail, valid):
    topo = _topological_order_outputs(outputs, name_to_rail)
    if len(topo) <= 2:
        return topo

    out_names = {r.name for r in topo}

    def _deps_of(r):
        return [d for d in r.get_depends_on_hi_flat() + r.get_depends_on_lo_flat()
                if d not in CONST_DEPS and d in valid and d in out_names]

    order = list(topo)
    for _ in range(4):                          # 4 sweeps
        pos = {r.name: i for i, r in enumerate(order)}
        bary = {}
        for r in order:
            deps = _deps_of(r)
            if deps:
                bary[r.name] = sum(pos[d] for d in deps) / len(deps)  # mean position
            else:
                bary[r.name] = float(pos[r.name])

        new_order = sorted(order, key=lambda r: bary[r.name])

        # Verify topological constraints are preserved
        topo_pos = {r.name: i for i, r in enumerate(new_order)}
        violated = False
        for r in new_order:
            for d in _deps_of(r):
                if topo_pos[d] > topo_pos[r.name]:
                    violated = True
                    break
            if violated:
                break
        if violated:
            break                               # revert to previous order
        if [r.name for r in new_order] == [r.name for r in order]:
            break                               # converged
        order = new_order

    return order
```

**Key Sugiyama concepts demonstrated:**
- Barycenter = mean of neighbor positions in the adjacent layer
- Iterative sweeps (4 iterations)
- Constraint checking: if reordering violates topological order, revert
- Convergence detection: stop when order stabilizes

---

## Example 3: Channel Routing (Wire Separation)

**File:** `src/drawio_export.py` -- `_ChannelAllocator`

This class implements channel routing for vertical wire segments, ensuring no
two wires sharing the same y range overlap on the same x coordinate.

```python
class _ChannelAllocator:
    def __init__(self, base_x, step=40):
        self._base_x = base_x
        self._step = step
        self._channels = []  # list of list of (y_min, y_max)

    def allocate(self, y_min, y_max):
        if y_min > y_max:
            y_min, y_max = y_max, y_min
        # Try to fit into an existing channel
        for i, spans in enumerate(self._channels):
            if all(y_max <= s[0] or y_min >= s[1] for s in spans):
                spans.append((y_min, y_max))
                return self._base_x + i * self._step
        # No existing channel fits; create a new one
        self._channels.append([(y_min, y_max)])
        return self._base_x + (len(self._channels) - 1) * self._step
```

**Mapping to layout concepts:**
- This is a 1D interval scheduling / channel assignment problem
- Each "channel" is a vertical x-coordinate track
- Wires with non-overlapping y ranges can share the same track
- Wires with overlapping y ranges get separate tracks (spaced by `step`)
- The allocator greedily assigns the first available channel

**Usage pattern:**

```python
ch_left = _ChannelAllocator(channel_x_left, step=GRID)
# For each wire that needs a vertical segment:
wire_x = ch_left.allocate(y_start, y_end)
# Use wire_x as the x coordinate for waypoints
```

---

## Example 4: Edge Crossing Minimization (Post-processing)

**File:** `src/layout_engine.py` -- `minimize_crossings()`

This function reduces crossings among vertical wire segments by swapping their
x coordinates. It operates on the final Draw.io XML as a post-processing step.

```python
def minimize_crossings(root, grid=40, max_iterations=20):
    segments = _extract_vertical_segments(root)
    if len(segments) < 2:
        return 0

    initial_crossings = _count_crossings(segments)
    if initial_crossings == 0:
        return 0

    improved_total = 0
    for _ in range(max_iterations):
        improved = False
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                _, pts_i, xi, _, _ = segments[i]
                _, pts_j, xj, _, _ = segments[j]
                if xi == xj:
                    continue

                before = _count_crossings(segments)

                # Try swapping x coordinates
                for pt in pts_i: pt.set("x", str(align(xj, grid)))
                for pt in pts_j: pt.set("x", str(align(xi, grid)))
                # Update segment records
                segments[i] = (*segments[i][:2], float(align(xj, grid)), *segments[i][3:])
                segments[j] = (*segments[j][:2], float(align(xi, grid)), *segments[j][3:])

                after = _count_crossings(segments)
                if after < before:
                    improved = True
                    improved_total += before - after
                else:
                    # Revert
                    for pt in pts_i: pt.set("x", str(int(xi)))
                    for pt in pts_j: pt.set("x", str(int(xj)))
                    segments[i] = (*segments[i][:2], xi, *segments[i][3:])
                    segments[j] = (*segments[j][:2], xj, *segments[j][3:])

        if not improved:
            break
    return improved_total
```

**Mapping to Sugiyama Phase 2 (adjacent swap):**
- Instead of swapping node positions within a layer, this swaps wire x positions
- Same greedy accept-if-better strategy
- Operates on the XML DOM directly (modifies mxPoint x attributes)
- Iterates until no improvement (convergence)

---

## Example 5: Complete Small DAG Layout

A minimal end-to-end example laying out a 4-node DAG from scratch.

```python
# Graph: A -> B, A -> C, B -> D, C -> D
adj = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}

# Phase 1: Layer assignment
layer = longest_path_layering(adj)
# Result: {"A": 0, "B": 1, "C": 1, "D": 2}

# Build layers list
num_layers = max(layer.values()) + 1
layers = [[] for _ in range(num_layers)]
for v, l in layer.items():
    layers[l].append(v)
# layers = [["A"], ["B", "C"], ["D"]]

# No dummy vertices needed (all edges span exactly 1 layer)

# Phase 2: Crossing minimization
edges = [(u, v) for u in adj for v in adj[u]]
layers = minimize_crossings_sweep(layers, edges, num_sweeps=4)
# layers = [["A"], ["B", "C"], ["D"]]  (already optimal)

# Phase 3: Coordinate assignment
GRID, GAP, NODE_W, NODE_H = 40, 80, 80, 40
coords = {}
for li, layer_nodes in enumerate(layers):
    y = li * (NODE_H + GAP)
    total_width = len(layer_nodes) * NODE_W + (len(layer_nodes) - 1) * GAP
    start_x = -total_width // 2  # center the layer
    for vi, v in enumerate(layer_nodes):
        x = start_x + vi * (NODE_W + GAP)
        coords[v] = (align(x, GRID), align(y, GRID))

# Result:
# A: (0, 0)
# B: (-80, 120)
# C: (80, 120)
# D: (0, 240)

# Generate Draw.io XML
for v, (x, y) in coords.items():
    print(f'<mxCell id="{v}" vertex="1" value="{v}">')
    print(f'  <mxGeometry x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" />')
    print(f'</mxCell>')

# Edges: no waypoints needed for this simple layout
for u, v in edges:
    print(f'<mxCell edge="1" source="{u}" target="{v}" '
          f'style="edgeStyle=orthogonalEdgeStyle;" />')
```

---

## Mapping Summary

| Sugiyama Phase | pwrseq_gen Implementation | File |
|----------------|--------------------------|------|
| Phase 1: Layer Assignment | `_topological_order_outputs()` | `drawio_export.py` |
| Phase 2: Crossing Minimization | `_barycenter_order_outputs()` | `drawio_export.py` |
| Phase 2: Adjacent Swap | `minimize_crossings()` | `layout_engine.py` |
| Phase 3: Coordinate Assignment | Column-based layout (`cell_start_x`, `row_y_base`) | `drawio_export.py` |
| Channel Routing | `_ChannelAllocator` | `drawio_export.py` |
| SPX-style co-opt | `optimize_layout` flag combines all three phases | `drawio_export.py` |
| Orthogonal Routing | `_orthogonalize_points()` | `drawio_export.py` |
| Grid Alignment | `_align40()`, `_align10()` | `drawio_export.py` |
