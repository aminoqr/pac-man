"""BFS, DFS and A* over the implicit maze graph (PLAN.md Milestone 3).

Shared vocabulary for all three searches (REFERENCE.md §3.6):

    * a *path* is the full cell sequence ``[start, ..., goal]``; its
      length in MOVES is ``SearchResult.step_count`` = len(path) - 1,
      which is what the wheel's 'NESW' ``shortest_path`` string counts
      -- keep the two straight when comparing against the oracle
      (TESTING_PLAYBOOK.md §7.1);
    * ``expanded`` counts vertices genuinely processed (dequeued or
      popped non-stale), the standard currency for comparing search
      effort -- it backs both the Milestone 3 benchmark and the
      "A* never expands more nodes than BFS" acceptance criterion.

Determinism: no randomness anywhere; exploration order is fixed by the
order ``MazeGraph.neighbors`` returns (the adapter yields N, E, S, W)
plus, for A*, a monotonic push counter breaking heap ties.
"""

from collections import deque
from dataclasses import dataclass
from heapq import heappop, heappush

from pacman.pathfinding.graph import Cell, MazeGraph, manhattan_distance


@dataclass(frozen=True)
class SearchResult:
    """Outcome of one search query.

    ``path`` is None when the goal is unreachable from the start;
    ``expanded`` still reports the effort spent discovering that (the
    search flooded the whole connected component before giving up).
    """

    path: list[Cell] | None
    expanded: int

    @property
    def found(self) -> bool:
        """Whether the goal was reached."""
        return self.path is not None

    @property
    def step_count(self) -> int:
        """Number of moves on the path -- the oracle-comparable length.

        Raises ValueError on a failed search: silently returning a
        sentinel here would let a length comparison "pass" against
        garbage (check ``found`` first).
        """
        if self.path is None:
            raise ValueError("no path was found; check .found first")
        return len(self.path) - 1


def _reconstruct(parent: dict[Cell, Cell | None], goal: Cell) -> list[Cell]:
    """Walk parent pointers goal -> start, then reverse (REFERENCE.md §3.2).

    The parent map is a tree rooted at the start (every vertex is
    parented exactly once, at discovery), so the walk terminates at the
    root's ``None`` and the result never revisits a vertex.
    """
    path = [goal]
    cursor = parent[goal]
    while cursor is not None:
        path.append(cursor)
        cursor = parent[cursor]
    path.reverse()
    return path


def bfs_path(graph: MazeGraph, start: Cell, goal: Cell) -> SearchResult:
    """Shortest path by breadth-first search (REFERENCE.md §3.2).

    FIFO queue + visited-at-enqueue + parent map. The queue holds at
    most two consecutive BFS depths at any moment, so vertices leave
    it in non-decreasing distance order -- the FIRST dequeue of
    ``goal`` therefore carries a provably minimal path (BFS is
    Dijkstra with all weights 1). Goal test at DEQUEUE time, matching
    the reference pseudocode; ``expanded`` counts dequeues. O(V + E)
    time, O(V) space.
    """
    queue: deque[Cell] = deque([start])
    visited = {start}
    parent: dict[Cell, Cell | None] = {start: None}
    expanded = 0
    while queue:
        cell = queue.popleft()
        expanded += 1
        if cell == goal:
            return SearchResult(_reconstruct(parent, cell), expanded)
        for neighbor in graph.neighbors(*cell):
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = cell
                queue.append(neighbor)
    return SearchResult(None, expanded)


def dfs_path(graph: MazeGraph, start: Cell, goal: Cell) -> SearchResult:
    """A legal path by depth-first search -- NOT shortest (REFERENCE.md §3.3).

    Identical skeleton to :func:`bfs_path` with the FIFO queue swapped
    for a LIFO stack (explicit, not recursion: a long snake corridor
    would hit Python's recursion limit). That one swap destroys the
    distance-ordering invariant: DFS plunges down one corridor and may
    report a wildly circuitous route -- tests pin a 3x3 plaza where it
    returns 6 moves for a 2-move query. On a braided, cycle-rich maze
    (REFERENCE.md §1.6) its paths are generally far from optimal, so
    keep it for existence/structure questions (:func:`reachable_cells`)
    and never for distances. Same O(V + E) cost as BFS.
    """
    stack = [start]
    visited = {start}
    parent: dict[Cell, Cell | None] = {start: None}
    expanded = 0
    while stack:
        cell = stack.pop()
        expanded += 1
        if cell == goal:
            return SearchResult(_reconstruct(parent, cell), expanded)
        for neighbor in graph.neighbors(*cell):
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = cell
                stack.append(neighbor)
    return SearchResult(None, expanded)


def astar_path(graph: MazeGraph, start: Cell, goal: Cell) -> SearchResult:
    """Shortest path by A* on f = g + h, h = Manhattan (REFERENCE.md §3.4).

    The frontier is a min-heap keyed on f(n) = g(n) + h(n). Binary
    heaps have no efficient decrease-key, so improved vertices are
    pushed AGAIN and stale entries are discarded on pop via the closed
    set -- the decrease-key-by-reinsertion idiom. Because h is
    consistent (graph.py), the first genuine pop of any vertex carries
    its optimal g, so closing it immediately is safe and no vertex is
    ever expanded twice.

    Why A* can never expand more vertices than BFS here (the Milestone
    3 acceptance criterion, leaned on by the oracle tests): genuine
    pops occur in non-decreasing f, so every non-goal vertex expanded
    before the goal has f <= C* (the optimal cost); Manhattan h >= 1
    off the goal gives it true distance g = f - h < C*, and BFS must
    dequeue EVERY vertex at distance < C* before it can dequeue the
    goal. A*'s expansions are thus a subset of BFS's on every query.
    """
    heap = [(manhattan_distance(start, goal), 0, start)]
    gscore = {start: 0}
    parent: dict[Cell, Cell | None] = {start: None}
    closed: set[Cell] = set()
    pushes = 1
    expanded = 0
    while heap:
        _, _, cell = heappop(heap)
        if cell in closed:
            continue
        expanded += 1
        if cell == goal:
            return SearchResult(_reconstruct(parent, cell), expanded)
        closed.add(cell)
        for neighbor in graph.neighbors(*cell):
            tentative = gscore[cell] + 1
            known = gscore.get(neighbor)
            if known is None or tentative < known:
                gscore[neighbor] = tentative
                parent[neighbor] = cell
                f = tentative + manhattan_distance(neighbor, goal)
                heappush(heap, (f, pushes, neighbor))
                pushes += 1
    return SearchResult(None, expanded)


def distance_map(graph: MazeGraph, source: Cell) -> dict[Cell, int]:
    """True graph distance from ``source`` to every reachable cell.

    Single-source BFS with no goal (REFERENCE.md §3.7): one O(V) flood
    yields d(source, c) for ALL cells c -- the "flow field" that turns
    per-ghost searches into table lookups, and the exact wall-aware
    metric PLAN.md Milestone 3 suggests for Clyde's 8-tile rule (the
    pinned policy in targeting.py keeps the arcade's straight-line
    check for now). Unreachable cells are simply absent from the map.
    """
    distances = {source: 0}
    queue: deque[Cell] = deque([source])
    while queue:
        cell = queue.popleft()
        for neighbor in graph.neighbors(*cell):
            if neighbor not in distances:
                distances[neighbor] = distances[cell] + 1
                queue.append(neighbor)
    return distances


def reachable_cells(graph: MazeGraph, start: Cell) -> set[Cell]:
    """Every cell connected to ``start`` -- DFS put to its right use.

    REFERENCE.md §3.3: DFS is the tool for existence and structure
    questions (connectivity, components), where its non-shortest paths
    cost nothing. Explicit stack, O(V + E). The engine's
    ``parse_grid_map`` delegates its pellet-reachability pass here
    (PLAN.md Milestone 3 wiring).
    """
    reachable = {start}
    stack = [start]
    while stack:
        cell = stack.pop()
        for neighbor in graph.neighbors(*cell):
            if neighbor not in reachable:
                reachable.add(neighbor)
                stack.append(neighbor)
    return reachable
