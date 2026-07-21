"""Milestone 3 gameplay wiring: EATEN eyes path home via A* next-hop.

``choose_eaten_exit`` trades the shared greedy rule for the first hop
of a true shortest path (REFERENCE.md §3.6 pins "eaten ghost going
home" as A*'s use case) and is exempt from no-reverse. The corridor
fixture makes the difference stark: greedy runs AWAY from home rather
than reverse; the eyes turn around and arrive. The wheel-maze sim
pins the arrival guarantee -- exactly d(cell, home) hops, because
every re-decision strictly decreases true path distance.
"""

from pacman.ai.intersection import choose_eaten_exit, choose_exit
from pacman.maze.adapter import Direction, MazeAdapter
from pacman.pathfinding.search import bfs_path
from tests.mazes import PLUS_3x3, POCKET_4x1, RING_3x3, make_adapter


def test_eaten_hop_takes_the_direct_arm_home() -> None:
    adapter = make_adapter(PLUS_3x3)
    # From the junction, home one arm east: the hop is East no matter
    # which way the eyes were heading.
    for heading in Direction:
        choice = choose_eaten_exit(adapter, (1, 1), heading, (2, 1))
        assert choice is Direction.EAST, heading


def test_eaten_hop_may_reverse_where_greedy_flees_home() -> None:
    """The wiring's reason to exist, in one corridor.

    At (1, 0) heading East with home at (0, 0): the greedy rule's
    no-reverse forces it East, AWAY from home; the shortest-path hop
    is the reversal, straight home.
    """
    adapter = make_adapter(POCKET_4x1)
    greedy = choose_exit(adapter, (1, 0), Direction.EAST, (0, 0))
    eaten = choose_eaten_exit(adapter, (1, 0), Direction.EAST, (0, 0))
    assert greedy is Direction.EAST
    assert eaten is Direction.WEST


def test_unreachable_home_falls_back_to_the_greedy_rule() -> None:
    """A sealed home cell cannot happen on a braided wheel maze, but
    the chooser stays total: it degrades to choose_exit (which picks
    South here -- the S/E tie at d^2 = 1 breaks by Up>Left>Down>Right).
    """
    adapter = make_adapter(RING_3x3)
    eaten = choose_eaten_exit(adapter, (0, 0), Direction.EAST, (1, 1))
    assert eaten is choose_exit(adapter, (0, 0), Direction.EAST, (1, 1))
    assert eaten is Direction.SOUTH


def test_already_home_falls_back_and_stays_total() -> None:
    # Zero-move path home: degrade to greedy toward the own tile
    # (all three exits tie at d^2 = 1; Up wins).
    adapter = make_adapter(PLUS_3x3)
    choice = choose_eaten_exit(adapter, (1, 1), Direction.EAST, (1, 1))
    assert choice is Direction.NORTH


def test_eyes_arrive_in_exactly_shortest_path_many_hops() -> None:
    """Seed-42 gameplay maze: center -> top-right corner, re-deciding
    every tick like the engine will, arrives in exactly d moves.
    """
    adapter = MazeAdapter(14, 10, 42)
    adapter.load_wheel_maze()
    cell = adapter.center()
    home = adapter.corners()[1]  # top-right, Blinky's corner
    expected = bfs_path(adapter, cell, home).step_count
    direction = Direction.NORTH
    for hop in range(expected):
        assert cell != home, f"arrived early at hop {hop}"
        direction = choose_eaten_exit(adapter, cell, direction, home)
        assert direction in adapter.get_valid_moves(*cell)
        cell = (cell[0] + direction.dx, cell[1] + direction.dy)
    assert cell == home
