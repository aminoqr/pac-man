"""The maze as a formal unweighted graph (PLAN.md Milestone 3).

Graph model (REFERENCE.md §1.1, §3.1): vertices are the walkable cells
``(x, y)``; an undirected edge joins two cells iff no wall separates
them; every edge has weight 1. The graph stays *implicit*
(REFERENCE.md §1.5): it is never materialized as an adjacency list --
``neighbors`` computes adjacency on demand from the wall bitmasks, and
the algorithms never copy or even see the grid.

This package is deliberately standalone: the searches in search.py run
against ANY object that can enumerate neighbors -- the game's
MazeAdapter, a hand-built fixture, a mock. The Protocol below is that
contract, so the package imports nothing from the maze, game, or UI
layers (Milestone 3 acceptance criteria).
"""

from typing import Protocol

Cell = tuple[int, int]


class MazeGraph(Protocol):
    """Structural interface every search algorithm consumes.

    ``MazeAdapter`` satisfies it out of the box -- its ``neighbors`` is
    the ONE primitive Milestone 3 is allowed to build on (REFERENCE.md
    §5.5, "never the raw grid"). Because this is a typing.Protocol,
    conformance is by shape, not inheritance: zero coupling by
    construction.
    """

    def neighbors(self, x: int, y: int) -> list[Cell]:
        """Cells reachable in one legal step from (x, y)."""
        ...


def manhattan_distance(a: Cell, b: Cell) -> int:
    """The L1 norm |x1-x2| + |y1-y2| -- A*'s heuristic (REFERENCE.md §3.5).

    Admissible: it is the EXACT distance on a wall-less 4-connected
    grid, and walls only ever lengthen real paths, so it never
    overestimates true graph distance. Consistent: one step changes
    each coordinate term by at most 1, so h(n) <= 1 + h(n') across
    every edge. Manhattan dominates Euclidean pointwise (h_E <= h_M by
    the triangle inequality), so A* guided by it never expands more
    vertices -- use this one, never the square root.
    """
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
