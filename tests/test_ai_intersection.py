"""Milestone 2.4 unit tests: the shared intersection decision rule.

TESTING_PLAYBOOK.md §4.3 (greedy scoring, tie-breaking, no-reverse,
dead-end escape hatch) and §4.4 F1/F2 (seeded frightened wandering).
All scenarios run on the PLUS_3x3 junction / POCKET_4x1 dead-end
fixtures, where every squared distance below was computed by hand.
"""

from random import Random

from pacman.ai.intersection import (
    TIE_BREAK_ORDER,
    choose_exit,
    choose_frightened_exit,
    choose_target_exit,
    legal_exits,
)
from pacman.maze.adapter import MazeAdapter, Direction
from pacman.pathfinding.search import bfs_path
from tests.mazes import PLUS_3x3, POCKET_4x1, RING_3x3, make_adapter

CENTER = (1, 1)


def test_tie_break_order_is_up_left_down_right() -> None:
    assert TIE_BREAK_ORDER == (
        Direction.NORTH,
        Direction.WEST,
        Direction.SOUTH,
        Direction.EAST,
    )


def test_legal_exits_exclude_the_reverse() -> None:
    adapter = make_adapter(PLUS_3x3)
    # Heading East at the junction: West is the forbidden reverse.
    exits = legal_exits(adapter, CENTER, Direction.EAST)
    assert exits == [Direction.NORTH, Direction.SOUTH, Direction.EAST]


def test_greedy_picks_the_distance_minimizing_exit() -> None:
    adapter = make_adapter(PLUS_3x3)
    # Target sitting exactly on each candidate arm makes that arm the
    # unique minimum (d² = 0).
    assert choose_exit(
        adapter, CENTER, Direction.EAST, (1, 0),
    ) is Direction.NORTH
    assert choose_exit(
        adapter, CENTER, Direction.EAST, (2, 1),
    ) is Direction.EAST
    assert choose_exit(
        adapter, CENTER, Direction.EAST, (1, 2),
    ) is Direction.SOUTH


def test_reverse_is_never_chosen_even_when_optimal() -> None:
    """Playbook I3/I4: the no-reverse rule dominates the scoring."""
    adapter = make_adapter(PLUS_3x3)
    # Target sits exactly on the reverse tile (0, 1): West would score
    # d² = 0 but is excluded; North/South tie at d² = 2 -> Up wins.
    choice = choose_exit(adapter, CENTER, Direction.EAST, (0, 1))
    assert choice is not Direction.WEST
    assert choice is Direction.NORTH


def test_tie_break_up_beats_left() -> None:
    adapter = make_adapter(PLUS_3x3)
    # Heading North (reverse South): exits N, W, E. Target (0, 0):
    # N->(1,0) d²=1, W->(0,1) d²=1 tie; E->(2,1) d²=5.
    choice = choose_exit(adapter, CENTER, Direction.NORTH, (0, 0))
    assert choice is Direction.NORTH


def test_tie_break_left_beats_down() -> None:
    adapter = make_adapter(PLUS_3x3)
    # Heading South (reverse North): exits W, S, E. Target (0, 2):
    # W->(0,1) d²=1, S->(1,2) d²=1 tie; E->(2,1) d²=5.
    choice = choose_exit(adapter, CENTER, Direction.SOUTH, (0, 2))
    assert choice is Direction.WEST


def test_tie_break_down_beats_right() -> None:
    adapter = make_adapter(PLUS_3x3)
    # Heading East (reverse West): exits N, S, E. Target (2, 2):
    # S->(1,2) d²=1, E->(2,1) d²=1 tie; N->(1,0) d²=5.
    choice = choose_exit(adapter, CENTER, Direction.EAST, (2, 2))
    assert choice is Direction.SOUTH


def test_dead_end_allows_the_reversal() -> None:
    """Playbook I5: the escape hatch when only the reverse is open."""
    adapter = make_adapter(POCKET_4x1)
    # Pinned at the closed west end heading West: the only physical
    # exit is East -- the reverse -- and it must be allowed.
    assert legal_exits(
        adapter, (0, 0), Direction.WEST,
    ) == [Direction.EAST]
    assert choose_exit(
        adapter, (0, 0), Direction.WEST, (3, 0),
    ) is Direction.EAST
    assert choose_frightened_exit(
        adapter, (0, 0), Direction.WEST, Random(1),
    ) is Direction.EAST


def test_sealed_cell_keeps_current_direction() -> None:
    """A value-15 cell has no exits at all; the rule stays total."""
    adapter = make_adapter(PLUS_3x3)
    assert legal_exits(adapter, (0, 0), Direction.EAST) == []
    assert choose_exit(
        adapter, (0, 0), Direction.EAST, CENTER,
    ) is Direction.EAST


def test_frightened_draws_are_reproducible_and_never_reverse() -> None:
    """Playbook F1/F2: same seed => same wander; still no 180° turns."""
    adapter = make_adapter(PLUS_3x3)

    def wander(seed: int) -> list[Direction]:
        rng = Random(seed)
        return [
            choose_frightened_exit(adapter, CENTER, Direction.EAST, rng)
            for _ in range(50)
        ]

    first, second = wander(7), wander(7)
    assert first == second                # F1: same seed, same path
    assert Direction.WEST not in first    # F2: reverse never drawn
    assert len(set(first)) > 1            # and it genuinely varies


# --- Path-based navigation (Milestone 3 upgrade, choose_target_exit) -----

def test_target_exit_steps_toward_the_target_arm() -> None:
    """The reachable arm wins on true path distance."""
    adapter = make_adapter(PLUS_3x3)
    # Heading East (so West is the forbidden reverse), the north arm is
    # the target: North leads straight onto it, the others are farther.
    assert choose_target_exit(
        adapter, CENTER, Direction.EAST, (1, 0),
    ) is Direction.NORTH
    # Heading South, targeting the east arm: East steps onto it.
    assert choose_target_exit(
        adapter, CENTER, Direction.SOUTH, (2, 1),
    ) is Direction.EAST


def test_target_exit_never_reverses_even_toward_the_target() -> None:
    """The arcade's core ghost rule, and what stops the jitter.

    Taking a raw shortest-path hop would double back the instant the
    target sat behind, so a ghost twitched on the spot whenever the
    player moved. The reverse is excluded; the ghost commits to the
    corridor and comes back around.
    """
    adapter = make_adapter(POCKET_4x1)
    # At (1,0) heading East with the target behind at (0,0): West is the
    # reverse, so it keeps going East despite the target being back there.
    assert choose_target_exit(
        adapter, (1, 0), Direction.EAST, (0, 0),
    ) is Direction.EAST


def test_target_exit_beats_greedy_where_a_wall_blocks_the_way() -> None:
    """True path distance, not straight-line: the ring's sealed centre
    means the geometrically-closer exit is the topologically wrong one.
    """
    adapter = make_adapter(RING_3x3)
    # At (1,0) heading East, target (1,2) is straight down past the
    # sealed centre; the only routes are around the ring. East and West
    # are both 3 hops... East is legal and West is the reverse, so it
    # commits East rather than stalling.
    assert choose_target_exit(
        adapter, (1, 0), Direction.EAST, (1, 2),
    ) is Direction.EAST


def test_target_exit_clamps_a_phantom_off_maze_target() -> None:
    """Targets are never clamped by the AI (REFERENCE.md §4.4); the
    path chooser resolves an outside point to the nearest walkable
    anchor and heads there instead of failing."""
    adapter = make_adapter(PLUS_3x3)
    # Far to the north-east of the 3x3 plus: anchor resolves toward the
    # top/right arm, so the first hop is North (tie-break over East).
    step = choose_target_exit(adapter, CENTER, Direction.EAST, (99, -99))
    assert step in (Direction.NORTH, Direction.EAST)


def test_target_exit_falls_back_to_greedy_when_unreachable() -> None:
    """A sealed target has no path; the chooser degrades to the greedy
    rule and stays total."""
    adapter = make_adapter(RING_3x3)
    # (1,1) is the sealed center -- unreachable from the ring.
    greedy = choose_exit(adapter, (0, 0), Direction.EAST, (1, 1))
    assert choose_target_exit(
        adapter, (0, 0), Direction.EAST, (1, 1),
    ) is greedy


def test_target_exit_reaches_a_real_maze_target_in_shortest_path() -> None:
    """Re-deciding every tile like the engine does, a ghost arrives in
    exactly the graph distance -- no orbiting local minima."""
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    start, target = adapter.center(), adapter.corners()[0]
    expected = bfs_path(adapter, start, target).step_count
    cell, direction = start, Direction.NORTH
    for hop in range(expected):
        assert cell != target, f"arrived early at hop {hop}"
        direction = choose_target_exit(adapter, cell, direction, target)
        cell = (cell[0] + direction.dx, cell[1] + direction.dy)
    assert cell == target
