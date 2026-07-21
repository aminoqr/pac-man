"""Milestone 3 unit tests on hand-authored micro-mazes.

Every expected number below was computed by hand on the
TESTING_PLAYBOOK.md §1.2 fixtures (see tests/mazes.py): the open
PLAZA_3x3 (where true distance == Manhattan distance, since there are
no interior walls), the RING_3x3 with its sealed center (unreachable
goals, forced detours), the PLUS_3x3 junction, and the non-square
POCKET_4x1 corridor. Wheel-generated mazes are property-tested
separately in test_pathfinding_oracle.py.
"""

import pytest

from pacman.pathfinding.debug import render_path_ascii
from pacman.pathfinding.graph import manhattan_distance
from pacman.pathfinding.search import (
    astar_path,
    bfs_path,
    dfs_path,
    distance_map,
    reachable_cells,
)
from tests.mazes import (
    PLAZA_3x3,
    PLUS_3x3,
    POCKET_4x1,
    RING_3x3,
    assert_legal_path,
    make_adapter,
)

PLAZA_CELLS = [(x, y) for x in range(3) for y in range(3)]


def test_manhattan_distance_basics() -> None:
    assert manhattan_distance((0, 0), (0, 0)) == 0
    assert manhattan_distance((0, 0), (3, 4)) == 7
    assert manhattan_distance((3, 4), (0, 0)) == 7  # symmetric
    assert manhattan_distance((-2, 1), (1, -1)) == 5  # off-grid targets


def test_bfs_and_astar_are_exact_on_the_open_plaza() -> None:
    """On a wall-less grid, true distance IS Manhattan distance.

    That makes every one of the 81 plaza queries an independent
    shortest-path oracle (REFERENCE.md §3.5 point 1), and checks the
    A*-never-expands-more-than-BFS guarantee on tiny inputs too.
    """
    adapter = make_adapter(PLAZA_3x3)
    for start in PLAZA_CELLS:
        for goal in PLAZA_CELLS:
            expected = manhattan_distance(start, goal)
            bfs = bfs_path(adapter, start, goal)
            astar = astar_path(adapter, start, goal)
            assert bfs.path is not None and astar.path is not None
            assert bfs.step_count == expected, (start, goal)
            assert astar.step_count == expected, (start, goal)
            assert_legal_path(adapter, bfs.path, start, goal)
            assert_legal_path(adapter, astar.path, start, goal)
            assert astar.expanded <= bfs.expanded, (start, goal)


def test_bfs_returns_the_unique_corridor_path() -> None:
    result = bfs_path(make_adapter(POCKET_4x1), (0, 0), (3, 0))
    assert result.path == [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert result.step_count == 3


def test_shortest_path_detours_around_the_sealed_ring_center() -> None:
    """(1,0) -> (1,2) is Manhattan 2 but costs 4 around the block.

    The gap between geometric and topological closeness in one query
    (REFERENCE.md §3.1) -- and proof the heuristic underestimating
    (h=2 < d=4) still yields the optimal answer (admissibility).
    """
    adapter = make_adapter(RING_3x3)
    bfs = bfs_path(adapter, (1, 0), (1, 2))
    astar = astar_path(adapter, (1, 0), (1, 2))
    assert bfs.step_count == astar.step_count == 4
    assert manhattan_distance((1, 0), (1, 2)) == 2


def test_unreachable_goal_reports_not_found_after_full_flood() -> None:
    adapter = make_adapter(RING_3x3)
    for search in (bfs_path, dfs_path, astar_path):
        result = search(adapter, (0, 0), (1, 1))
        assert not result.found
        assert result.path is None
        # The whole 8-cell ring component was exhausted before giving up.
        assert result.expanded == 8, search.__name__


def test_step_count_on_a_failed_search_fails_loudly() -> None:
    result = bfs_path(make_adapter(RING_3x3), (0, 0), (1, 1))
    with pytest.raises(ValueError):
        result.step_count


def test_start_equals_goal_is_a_zero_move_path() -> None:
    for search in (bfs_path, dfs_path, astar_path):
        result = search(make_adapter(PLAZA_3x3), (1, 1), (1, 1))
        assert result.path == [(1, 1)]
        assert result.step_count == 0
        assert result.expanded == 1, search.__name__


def test_dfs_path_is_legal_but_three_times_longer_than_shortest() -> None:
    """The REFERENCE.md §3.3 negative result, pinned deterministically.

    On the open plaza the LIFO stack (with the adapter's fixed N,E,S,W
    neighbor order) snakes down the west wall and around the south rim,
    reporting 6 moves for a 2-move query. Legal path, wrong length --
    exactly why DFS must never answer distance questions.
    """
    adapter = make_adapter(PLAZA_3x3)
    dfs = dfs_path(adapter, (0, 0), (2, 0))
    assert dfs.path == [
        (0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0),
    ]
    assert_legal_path(adapter, dfs.path, (0, 0), (2, 0))
    assert dfs.step_count == 6
    assert bfs_path(adapter, (0, 0), (2, 0)).step_count == 2


def test_dfs_matches_bfs_where_no_cycle_exists() -> None:
    """On the acyclic corridor the unique path is forced: cycles, not
    the stack itself, are what make DFS suboptimal (REFERENCE.md §1.6).
    """
    adapter = make_adapter(POCKET_4x1)
    dfs = dfs_path(adapter, (0, 0), (3, 0))
    assert dfs.path == bfs_path(adapter, (0, 0), (3, 0)).path


def test_plus_junction_routes_arm_to_arm_through_the_center() -> None:
    adapter = make_adapter(PLUS_3x3)
    for search in (bfs_path, astar_path):
        result = search(adapter, (1, 0), (0, 1))
        assert result.path == [(1, 0), (1, 1), (0, 1)], search.__name__


def test_distance_map_equals_manhattan_on_the_open_plaza() -> None:
    adapter = make_adapter(PLAZA_3x3)
    distances = distance_map(adapter, (0, 0))
    assert distances == {
        cell: manhattan_distance((0, 0), cell) for cell in PLAZA_CELLS
    }


def test_distance_map_walks_the_ring_both_ways() -> None:
    """Hand-computed cycle distances: min(i, 8 - i) along the 8-ring."""
    distances = distance_map(make_adapter(RING_3x3), (0, 0))
    assert distances == {
        (0, 0): 0,
        (1, 0): 1, (0, 1): 1,
        (2, 0): 2, (0, 2): 2,
        (2, 1): 3, (1, 2): 3,
        (2, 2): 4,
    }


def test_reachable_cells_excludes_the_sealed_center() -> None:
    ring = reachable_cells(make_adapter(RING_3x3), (0, 0))
    assert ring == {
        (0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2), (0, 1),
    }
    assert reachable_cells(make_adapter(PLAZA_3x3), (1, 1)) == set(PLAZA_CELLS)
    assert reachable_cells(make_adapter(POCKET_4x1), (2, 0)) == {
        (0, 0), (1, 0), (2, 0), (3, 0),
    }


def test_render_path_ascii_draws_a_connected_line() -> None:
    adapter = make_adapter(POCKET_4x1)
    result = bfs_path(adapter, (0, 0), (3, 0))
    assert result.path is not None
    rendered = render_path_ascii(adapter, result.path)
    assert rendered == "#########\n#S*****G#\n#########"


def test_render_path_ascii_edge_cases() -> None:
    adapter = make_adapter(PLAZA_3x3)
    # Empty path: render untouched.
    assert render_path_ascii(adapter, []) == adapter.render_ascii()
    # Degenerate single-cell path: the start mark wins.
    rendered = render_path_ascii(adapter, [(1, 1)])
    assert rendered.splitlines()[3][3] == "S"
