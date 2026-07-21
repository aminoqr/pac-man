"""Shared hand-authored fixture mazes (TESTING_PLAYBOOK.md §1.2).

Behavioral tests run on tiny grids where every wall is known by heart;
wheel-generated mazes are reserved for property/characterization tests.
Each fixture is a raw ``list[list[int]]`` of 4-bit wall bytes (N=1, E=2,
S=4, W=8; 15 = sealed); the mirror-consistency suite in
tests/test_maze_adapter.py is what protects them against typos.
"""

from pacman.maze.adapter import MIN_MAZE_HEIGHT, MIN_MAZE_WIDTH, MazeAdapter

# 3x3, every border wall set, no interior walls -- the worked fixture
# from TESTING_PLAYBOOK.md §1.2 ("memorize this one").
PLAZA_3x3 = [
    [9, 1, 3],
    [8, 0, 2],
    [12, 4, 6],
]

# 3x3 with a sealed (value 15) center and an open ring around it. Every
# ring cell carries the wall bit facing the sealed center, mirroring the
# center's own bits -- exactly how the wheel's "42" blocks are sealed.
RING_3x3 = [
    [9, 5, 3],
    [10, 15, 10],
    [12, 5, 6],
]

# Open junction at the center with four one-cell arms and sealed
# corners. The intersection-rule fixture: a ghost at the center heading
# East sees exactly the playbook §4.3 scenario -- open North/East/South,
# West forbidden as the reverse.
PLUS_3x3 = [
    [15, 11, 15],
    [13, 0, 7],
    [15, 14, 15],
]

# One-row corridor closed at both ends; standing at the west end the
# only physical exit is the reverse -- the dead-end escape-hatch
# fixture (playbook I5).
POCKET_4x1 = [
    [13, 5, 5, 7],
]

# One-row, five-column straight tube -- the tile-swap collision fixture
# (playbook §5.1/§5.4: every S-row scenario is scripted on these five
# cells (0,0)..(4,0)).
CORRIDOR_1x5 = [
    [13, 5, 5, 5, 7],
]

# T-junction: horizontal corridor along y=1 with one arm going North
# from the center -- the degree-3 intersection for the buffered-turn
# scripted tests (playbook §3.1): press Up early while moving East and
# the turn must fire exactly at (1,1), where North first opens.
TEE_3x3 = [
    [15, 11, 15],
    [13, 4, 7],
    [15, 15, 15],
]


def assert_legal_path(
    adapter: MazeAdapter,
    path: list[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
) -> None:
    """Assert ``path`` starts/ends right and every hop is a legal move.

    Shared by the micro, oracle and benchmark pathfinding suites.
    Legality is checked through the same public vocabulary the search
    algorithms consume (``adapter.neighbors``), so a passing path is
    legal by the maze's own definition. The no-revisit assert holds for
    every search here because paths are read off a parent TREE
    (REFERENCE.md §3.2) -- a duplicate would flag real corruption.
    """
    assert path[0] == start
    assert path[-1] == goal
    for cell, following in zip(path, path[1:]):
        assert following in adapter.neighbors(*cell), (
            f"illegal hop {cell} -> {following}"
        )
    assert len(set(path)) == len(path), "path revisits a cell"


def make_adapter(grid: list[list[int]]) -> MazeAdapter:
    """Loaded MazeAdapter over a hand-authored grid, no wheel involved.

    Fixture mazes are smaller than the wheel's playable minimum, so
    width/height are set directly on the instance *after* construction
    to sidestep MazeAdapter's own size clamping -- that clamp is about
    what we ask the wheel to generate, not a limit on hand-built grids.
    """
    adapter = MazeAdapter(MIN_MAZE_WIDTH, MIN_MAZE_HEIGHT, seed=1)
    adapter.width = len(grid[0])
    adapter.height = len(grid)
    adapter._grid = grid
    return adapter
