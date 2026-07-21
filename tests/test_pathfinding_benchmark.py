"""Milestone 3 benchmark: expanded-node counts, BFS vs A* (PLAN.md).

Concrete evidence of why the heuristic matters (REFERENCE.md §3.4),
measured on the deterministic 51x51 seed-42 wheel maze (2601 cells):

    corner -> corner  path 102 moves   BFS 2575 expanded   A* 377 (15%)
    center -> corner  path  56 moves   BFS 2577 expanded   A* 511 (20%)

BFS floods essentially the whole maze regardless of where the goal is;
Manhattan guidance prunes ~80-85% of that work at identical path
quality. The asserts below re-measure on every run (the wheel is
reproducible for a fixed seed) and pin the qualitative facts -- equal
lengths, strictly fewer A* expansions, and at least a 2x reduction --
rather than the raw counts, so a future wheel swap degrades this test
gracefully instead of misleadingly. Run with ``pytest -s`` to see the
fresh numbers.
"""

from pacman.maze.adapter import MazeAdapter
from pacman.pathfinding.search import astar_path, bfs_path

BENCH_SIZE = 51
BENCH_SEED = 42


def test_astar_beats_bfs_expansion_counts_on_a_large_maze() -> None:
    adapter = MazeAdapter(BENCH_SIZE, BENCH_SIZE, BENCH_SEED)
    adapter.load_wheel_maze()
    far_corner = (BENCH_SIZE - 1, BENCH_SIZE - 1)
    queries = (
        ("corner -> corner", (0, 0), far_corner),
        ("center -> corner", adapter.center(), far_corner),
    )
    for label, start, goal in queries:
        bfs = bfs_path(adapter, start, goal)
        astar = astar_path(adapter, start, goal)
        assert bfs.found and astar.found, label
        assert bfs.step_count == astar.step_count, label
        assert astar.expanded < bfs.expanded, label
        assert astar.expanded <= bfs.expanded // 2, (
            f"{label}: heuristic pruned less than half "
            f"({astar.expanded} vs {bfs.expanded})"
        )
        print(
            f"{label}: path {bfs.step_count} moves, "
            f"BFS expanded {bfs.expanded}, A* {astar.expanded} "
            f"({100 * astar.expanded // bfs.expanded}%)"
        )
