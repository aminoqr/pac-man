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
