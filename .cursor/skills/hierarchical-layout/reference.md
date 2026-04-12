# Hierarchical Layout Algorithm Reference

Complete pseudocode, formulas, and implementation notes for the Sugiyama
framework and SPX co-optimization.

---

## Phase 1: Layer Assignment

### Longest-Path Layering

Assigns each vertex to the longest path distance from any source. Simple and
fast; tends to produce tall, narrow layouts.

```python
def longest_path_layering(adj: dict[str, list[str]]) -> dict[str, int]:
    """Assign layers by longest path from sources. O(V + E)."""
    in_degree = {v: 0 for v in adj}
    for v in adj:
        for u in adj[v]:
            in_degree[u] = in_degree.get(u, 0) + 1

    sources = [v for v, d in in_degree.items() if d == 0]
    layer = {}
    queue = [(s, 0) for s in sources]

    while queue:
        v, lv = queue.pop(0)
        if v in layer:
            layer[v] = max(layer[v], lv)
        else:
            layer[v] = lv
        for u in adj.get(v, []):
            queue.append((u, lv + 1))

    return layer
```

### Topological Sort (prerequisite)

```python
def topological_sort(adj: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm. Returns vertices in topological order."""
    in_deg = {v: 0 for v in adj}
    for v in adj:
        for u in adj[v]:
            in_deg[u] = in_deg.get(u, 0) + 1

    queue = [v for v, d in in_deg.items() if d == 0]
    result = []
    while queue:
        v = queue.pop(0)
        result.append(v)
        for u in adj.get(v, []):
            in_deg[u] -= 1
            if in_deg[u] == 0:
                queue.append(u)
    return result
```

### Dummy Vertex Insertion

When an edge (u, v) spans multiple layers (layer[v] - layer[u] > 1), insert
dummy vertices so every edge connects adjacent layers.

```python
def insert_dummies(
    adj: dict[str, list[str]],
    layer: dict[str, int],
) -> tuple[dict[str, list[str]], dict[str, int], set[str]]:
    """Insert dummy vertices for long edges. Returns (new_adj, new_layer, dummy_set)."""
    new_adj = {v: [] for v in adj}
    new_layer = dict(layer)
    dummies = set()
    dummy_id = 0

    for u in adj:
        for v in adj[u]:
            span = layer[v] - layer[u]
            if span <= 1:
                new_adj[u].append(v)
            else:
                prev = u
                for k in range(1, span):
                    d = f"__dummy_{dummy_id}"
                    dummy_id += 1
                    dummies.add(d)
                    new_layer[d] = layer[u] + k
                    new_adj[prev] = new_adj.get(prev, []) + [d]
                    new_adj[d] = []
                    prev = d
                new_adj[prev].append(v)

    return new_adj, new_layer, dummies
```

**Important:** after coordinate assignment, remove dummy vertices and replace
with edge waypoints (bend points) at the dummy positions.

---

## Phase 2: Crossing Minimization

### Counting Crossings Between Two Layers

Two edges (u1, v1) and (u2, v2) between layer L_i and L_{i+1} cross if and
only if the relative order of u1, u2 in L_i is opposite to the relative order
of v1, v2 in L_{i+1}.

```python
def count_crossings(
    upper_order: list[str],
    lower_order: list[str],
    edges: list[tuple[str, str]],
) -> int:
    """Count edge crossings between two adjacent layers."""
    upper_pos = {v: i for i, v in enumerate(upper_order)}
    lower_pos = {v: i for i, v in enumerate(lower_order)}

    relevant = [(upper_pos[u], lower_pos[v]) for u, v in edges
                if u in upper_pos and v in lower_pos]
    relevant.sort()

    crossings = 0
    for i in range(len(relevant)):
        for j in range(i + 1, len(relevant)):
            if relevant[i][1] > relevant[j][1]:
                crossings += 1
    return crossings
```

### Barycenter Heuristic

For each vertex v in the free layer, compute the average position of its
neighbors in the fixed layer, then sort by this value.

```python
def barycenter_ordering(
    free_layer: list[str],
    fixed_layer: list[str],
    edges: list[tuple[str, str]],
    free_is_lower: bool = True,
) -> list[str]:
    """Reorder free_layer to minimize crossings with fixed_layer."""
    fixed_pos = {v: i for i, v in enumerate(fixed_layer)}

    bary = {}
    for v in free_layer:
        if free_is_lower:
            neighbors = [u for u, w in edges if w == v and u in fixed_pos]
        else:
            neighbors = [w for u, w in edges if u == v and w in fixed_pos]

        if neighbors:
            bary[v] = sum(fixed_pos[n] for n in neighbors) / len(neighbors)
        else:
            bary[v] = free_layer.index(v)

    return sorted(free_layer, key=lambda v: bary[v])
```

### Median Heuristic

Same as barycenter but uses median instead of mean. More robust against
outliers (vertices with connections to both extremes of the adjacent layer).

```python
def median_ordering(free_layer, fixed_layer, edges, free_is_lower=True):
    fixed_pos = {v: i for i, v in enumerate(fixed_layer)}
    med = {}
    for v in free_layer:
        if free_is_lower:
            neighbors = sorted(fixed_pos[u] for u, w in edges if w == v and u in fixed_pos)
        else:
            neighbors = sorted(fixed_pos[w] for u, w in edges if u == v and w in fixed_pos)
        if neighbors:
            mid = len(neighbors) // 2
            med[v] = neighbors[mid]
        else:
            med[v] = free_layer.index(v)
    return sorted(free_layer, key=lambda v: med[v])
```

### Full Sweep Strategy

```python
def minimize_crossings_sweep(layers, edges, num_sweeps=8):
    """Alternate top-down and bottom-up sweeps."""
    for sweep in range(num_sweeps):
        if sweep % 2 == 0:  # top-down
            for i in range(1, len(layers)):
                layers[i] = barycenter_ordering(
                    layers[i], layers[i - 1], edges, free_is_lower=True)
        else:  # bottom-up
            for i in range(len(layers) - 2, -1, -1):
                layers[i] = barycenter_ordering(
                    layers[i], layers[i + 1], edges, free_is_lower=False)
    return layers
```

### Adjacent Swap Refinement

After barycenter/median ordering, do local swaps to further reduce crossings.

```python
def adjacent_swap(layers, edges, max_iter=20):
    """Swap adjacent vertices in each layer if it reduces crossings."""
    for _ in range(max_iter):
        improved = False
        for layer in layers:
            for i in range(len(layer) - 1):
                before = total_crossings(layers, edges)
                layer[i], layer[i + 1] = layer[i + 1], layer[i]
                after = total_crossings(layers, edges)
                if after < before:
                    improved = True
                else:
                    layer[i], layer[i + 1] = layer[i + 1], layer[i]  # revert
        if not improved:
            break
    return layers
```

---

## Phase 3: Coordinate Assignment

### Simple Grid Assignment

```python
def grid_coordinates(
    layers: list[list[str]],
    node_w: int = 80,
    node_h: int = 40,
    gap_x: int = 80,
    gap_y: int = 80,
    grid: int = 40,
) -> dict[str, tuple[int, int]]:
    coords = {}
    for li, layer in enumerate(layers):
        y = align(li * (node_h + gap_y), grid)
        for vi, v in enumerate(layer):
            x = align(vi * (node_w + gap_x), grid)
            coords[v] = (x, y)
    return coords

def align(v, grid):
    return round(v / grid) * grid
```

### Brandes-Kopf (simplified concept)

1. Compute a "median" alignment for each vertex relative to its upper neighbors
2. Compact horizontally: push vertices as far left as possible without overlap
3. Repeat for 4 combinations: {leftmost/rightmost} x {upper/lower alignment}
4. Take the coordinate assignment with minimum total edge length

This produces balanced layouts where connected vertices are close together.

### Channel Routing for Edges

When multiple edges share the same vertical or horizontal corridor, assign each
to a separate channel to avoid overlapping wire segments.

```python
class ChannelAllocator:
    def __init__(self, base: int, step: int = 40):
        self._base = base
        self._step = step
        self._channels: list[list[tuple[float, float]]] = []

    def allocate(self, span_min: float, span_max: float) -> int:
        if span_min > span_max:
            span_min, span_max = span_max, span_min
        for i, spans in enumerate(self._channels):
            if all(span_max <= s[0] or span_min >= s[1] for s in spans):
                spans.append((span_min, span_max))
                return self._base + i * self._step
        self._channels.append([(span_min, span_max)])
        return self._base + (len(self._channels) - 1) * self._step
```

---

## SPX Co-optimization

### Stress Function

```
stress(pos) = sum over all pairs (i, j):
    w_ij * (||pos[i] - pos[j]|| - d_ij)^2

where:
    d_ij = shortest-path distance between i and j in the graph
    w_ij = 1 / d_ij^2  (inverse square weighting)
```

### Crossing Count

Use the inversion-count method for efficiency:

```python
def count_all_crossings(layers, edges):
    total = 0
    for i in range(len(layers) - 1):
        total += count_crossings(layers[i], layers[i + 1], edges)
    return total
```

### Upwardness Penalty

For DAGs, penalize edges that do not point in the intended direction:

```
upwardness(pos) = sum over all edges (u, v):
    max(0, pos[u].y - pos[v].y)   # for top-to-bottom layout
```

For left-to-right layout, replace y with x.

### Crossing Angle Penalty

Penalize small crossing angles (ideally crossings should be near 90 degrees):

```
angle_penalty = sum over all crossing pairs (e1, e2):
    (90 - crossing_angle(e1, e2))^2
```

### Combined Objective

```python
def objective(pos, graph, weights):
    w_s, w_c, w_a, w_u = weights
    return (w_s * stress(pos, graph) +
            w_c * count_all_crossings_from_pos(pos, graph) +
            w_a * angle_penalty(pos, graph) +
            w_u * upwardness_penalty(pos, graph))
```

### Iterative Refinement

```python
def spx_refine(pos, graph, weights, max_iter=100, temp=1.0, cooling=0.95):
    best_obj = objective(pos, graph, weights)
    best_pos = dict(pos)

    for iteration in range(max_iter):
        # Pick a random vertex and try a small perturbation
        v = random.choice(list(pos.keys()))
        dx, dy = random.choice([(GRID, 0), (-GRID, 0), (0, GRID), (0, -GRID)])
        old = pos[v]
        pos[v] = (old[0] + dx, old[1] + dy)

        new_obj = objective(pos, graph, weights)
        delta = new_obj - best_obj

        if delta < 0 or random.random() < math.exp(-delta / temp):
            if new_obj < best_obj:
                best_obj = new_obj
                best_pos = dict(pos)
        else:
            pos[v] = old  # revert

        temp *= cooling

    return best_pos
```

---

## Common Pitfalls

### Cyclic Graphs

Sugiyama requires a DAG. For cyclic graphs:
1. Find a minimal feedback arc set (edges to reverse)
2. Reverse those edges temporarily
3. Run Sugiyama on the resulting DAG
4. Restore original edge directions in the final drawing

```python
def break_cycles_dfs(adj):
    """Reverse edges to make the graph acyclic. Returns reversed edge set."""
    visited = set()
    in_stack = set()
    reversed_edges = set()

    def dfs(v):
        visited.add(v)
        in_stack.add(v)
        for u in adj.get(v, []):
            if u in in_stack:
                reversed_edges.add((v, u))
            elif u not in visited:
                dfs(u)
        in_stack.discard(v)

    for v in adj:
        if v not in visited:
            dfs(v)
    return reversed_edges
```

### Disconnected Components

Layout each connected component separately, then arrange components
side-by-side with a gap between them.

### Performance for Large Graphs

| Vertices | Recommended approach |
|----------|---------------------|
| < 50 | Full Sugiyama + SPX refinement |
| 50-500 | Sugiyama + barycenter (skip SPX) |
| 500-5000 | Sugiyama with median heuristic, limited sweeps |
| > 5000 | Consider force-directed layout instead |

### Dummy Vertex Cleanup

After coordinate assignment, convert dummy vertices back to edge waypoints:

```python
def dummies_to_waypoints(coords, dummies, original_edges):
    """Replace dummy vertex chains with edge waypoints."""
    waypoints = {}  # (src, tgt) -> list of (x, y)
    for src, tgt in original_edges:
        path = trace_dummy_chain(src, tgt, adj, dummies)
        if path:
            waypoints[(src, tgt)] = [coords[d] for d in path if d in dummies]
    return waypoints
```

### Orthogonal Edge Routing

For circuit-style diagrams, ensure all edge segments are horizontal or vertical:

```python
def orthogonalize(points):
    """Insert intermediate points to make all segments axis-aligned."""
    result = [points[0]]
    for i in range(1, len(points)):
        px, py = result[-1]
        nx, ny = points[i]
        if px != nx and py != ny:
            result.append((nx, py))  # horizontal first, then vertical
        result.append((nx, ny))
    return result
```
