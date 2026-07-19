"""Milestone 2 acceptance: distinct, deterministic personalities.

Headless equivalent of PLAN.md's "with the player standing still, each
ghost visibly behaves differently" (the statistical version is
TESTING_PLAYBOOK.md §7.3, once Milestone 4's loop exists). One shared
algorithm + four target formulas driven tick-by-tick on the real
seed-42 level-1 maze, player parked at the center.
"""

from pacman.ai.ghost import Cell, GhostMode, GhostPersonality, create_ghosts
from pacman.ai.intersection import choose_exit
from pacman.ai.targeting import target_tile
from pacman.maze.adapter import Direction, MazeAdapter

Paths = dict[GhostPersonality, list[Cell]]


def run_chase_sim(ticks: int) -> Paths:
    """Drive all four ghosts in pure CHASE against a motionless player.

    One tile per ghost per tick via the shared intersection rule;
    Blinky's cell is snapshotted before anyone moves so Inky's formula
    is update-order independent (see targeting.chase_target).
    """
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    player = adapter.center()

    ghosts = create_ghosts(adapter.corners())
    for ghost in ghosts:
        ghost.mode = GhostMode.CHASE

    blinky = next(
        g for g in ghosts if g.personality is GhostPersonality.BLINKY
    )
    paths: Paths = {g.personality: [] for g in ghosts}
    for _ in range(ticks):
        blinky_cell = blinky.cell
        for ghost in ghosts:
            target = target_tile(ghost, player, Direction.WEST, blinky_cell)
            step = choose_exit(adapter, ghost.cell, ghost.direction, target)
            ghost.direction = step
            ghost.cell = (
                ghost.cell[0] + step.dx, ghost.cell[1] + step.dy,
            )
            paths[ghost.personality].append(ghost.cell)
    return paths


def test_same_seed_gives_identical_runs() -> None:
    """Determinism end-to-end: no hidden RNG or wall-clock anywhere."""
    assert run_chase_sim(120) == run_chase_sim(120)


def test_the_four_personalities_trace_different_paths() -> None:
    """The bug this catches: all four ghosts accidentally sharing one
    target formula -- invisible to per-formula unit tests."""
    paths = list(run_chase_sim(120).values())
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            assert paths[i] != paths[j]


def test_blinky_homes_in_on_the_parked_player() -> None:
    """Pure pursuit must close in on a motionless target.

    Characterized bound: on the seed-42 maze the wall-blind greedy rule
    orbits the sealed "42" block beside the center and bottoms out at
    d² = 5 (~2.2 tiles) without ever landing on the player's tile.
    That myopia is the arcade's deliberate design (REFERENCE.md §4.5);
    actually catching a player relies on the player moving.
    """
    paths = run_chase_sim(120)
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    px, py = adapter.center()

    blinky_path = paths[GhostPersonality.BLINKY]
    start_x, start_y = blinky_path[0]
    start_d2 = (start_x - px) ** 2 + (start_y - py) ** 2
    min_d2 = min(
        (x - px) ** 2 + (y - py) ** 2 for x, y in blinky_path
    )
    assert min_d2 < start_d2
    assert min_d2 <= 5


def test_clyde_keeps_more_distance_than_blinky() -> None:
    """The coward's 8-tile break-off keeps his average distance to the
    player above the pure pursuer's."""
    paths = run_chase_sim(120)
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    px, py = adapter.center()

    def mean_d2(path: list[Cell]) -> float:
        total = sum((x - px) ** 2 + (y - py) ** 2 for x, y in path)
        return total / len(path)

    blinky_mean = mean_d2(paths[GhostPersonality.BLINKY])
    clyde_mean = mean_d2(paths[GhostPersonality.CLYDE])
    assert clyde_mean > blinky_mean
