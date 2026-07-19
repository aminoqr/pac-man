"""Unit + characterization tests for pacman.maze.adapter (Milestone 1.3).

Two kinds of test live here (TESTING_PLAYBOOK.md §1):
    * hand-built micro-mazes (fixtures below) for behavioral assertions
      about wall bits, walkability, and the corner/center fallback policy;
    * live calls into the installed `mazegenerator` wheel to characterize
      facts CLAUDE.md's trap list already documents from reading the
      source -- pinning them here means a future wheel swap fails loudly
      in this suite instead of silently in the game.
"""

import pytest

from pacman.maze.adapter import (
    MIN_MAZE_HEIGHT,
    MIN_MAZE_WIDTH,
    Direction,
    MazeAdapter,
    MazeAdapterError,
)
from tests.mazes import PLAZA_3x3, RING_3x3, make_adapter


# --- Direction enum -----------------------------------------------------

def test_direction_deltas_and_wall_bits() -> None:
    assert Direction.NORTH.dx == 0 and Direction.NORTH.dy == -1
    assert Direction.EAST.dx == 1 and Direction.EAST.dy == 0
    assert Direction.SOUTH.dx == 0 and Direction.SOUTH.dy == 1
    assert Direction.WEST.dx == -1 and Direction.WEST.dy == 0

    assert Direction.NORTH.wall_bit == 1
    assert Direction.EAST.wall_bit == 2
    assert Direction.SOUTH.wall_bit == 4
    assert Direction.WEST.wall_bit == 8


def test_direction_opposites() -> None:
    assert Direction.NORTH.opposite is Direction.SOUTH
    assert Direction.SOUTH.opposite is Direction.NORTH
    assert Direction.EAST.opposite is Direction.WEST
    assert Direction.WEST.opposite is Direction.EAST


def test_direction_letters_match_wheel_alphabet() -> None:
    assert {d.letter for d in Direction} == {"N", "E", "S", "W"}


# --- The exhaustive bit-mapping matrix (TESTING_PLAYBOOK.md §2.2) ------

@pytest.mark.parametrize("cell,expected_open", [
    (0, {"N", "E", "S", "W"}),
    (1, {"E", "S", "W"}),
    (2, {"N", "S", "W"}),
    (3, {"S", "W"}),
    (4, {"N", "E", "W"}),
    (5, {"E", "W"}),
    (6, {"N", "W"}),
    (7, {"W"}),
    (8, {"N", "E", "S"}),
    (9, {"E", "S"}),
    (10, {"N", "S"}),
    (11, {"S"}),
    (12, {"N", "E"}),
    (13, {"E"}),
    (14, {"N"}),
    (15, set()),
])
def test_get_valid_moves_exhaustive_bit_mapping(
    cell: int, expected_open: set[str],
) -> None:
    grid = [[cell]]
    adapter = make_adapter(grid)

    moves = adapter.get_valid_moves(0, 0)

    assert {d.letter for d in moves} == expected_open


# --- Walkability / sealed-cell isolation --------------------------------

def test_is_walkable_false_for_sealed_cell_and_out_of_bounds() -> None:
    adapter = make_adapter(RING_3x3)

    assert adapter.is_walkable(1, 1) is False  # sealed center
    assert adapter.is_walkable(0, 0) is True
    assert adapter.is_walkable(-1, 0) is False
    assert adapter.is_walkable(3, 0) is False


def test_neighbors_never_returns_a_sealed_cell() -> None:
    adapter = make_adapter(RING_3x3)

    for y in range(3):
        for x in range(3):
            if not adapter.is_walkable(x, y):
                continue
            for nx, ny in adapter.neighbors(x, y):
                assert (nx, ny) != (1, 1)


def test_methods_raise_before_load_wheel_maze() -> None:
    adapter = MazeAdapter(15, 15, seed=1)

    with pytest.raises(MazeAdapterError):
        adapter.is_walkable(0, 0)
    with pytest.raises(MazeAdapterError):
        adapter.corners()
    with pytest.raises(MazeAdapterError):
        adapter.center()
    with pytest.raises(MazeAdapterError):
        adapter.reference_path_length()


# --- Boundary containment / y-axis clipping trap (TESTING_PLAYBOOK §2.4) --

@pytest.mark.parametrize("start,direction,expected_after", [
    ((1, 0), Direction.NORTH, (1, 0)),   # B1: blocked, unchanged
    ((1, 2), Direction.SOUTH, (1, 2)),   # B2: blocked, unchanged
    ((0, 1), Direction.WEST, (0, 1)),    # B3: blocked, unchanged
    ((2, 1), Direction.EAST, (2, 1)),    # B4: blocked, unchanged
    ((0, 0), Direction.NORTH, (0, 0)),   # B5: blocked, unchanged
    ((0, 0), Direction.WEST, (0, 0)),    # B6: blocked, unchanged
    ((0, 0), Direction.EAST, (1, 0)),    # B7: open
    ((0, 0), Direction.SOUTH, (0, 1)),   # B8: open, larger y (sentinel)
    ((1, 1), Direction.NORTH, (1, 0)),   # B9: open, smaller y (sentinel)
])
def test_plaza_3x3_boundary_containment_matrix(
    start: tuple[int, int],
    direction: Direction,
    expected_after: tuple[int, int],
) -> None:
    adapter = make_adapter(PLAZA_3x3)
    x, y = start

    legal = direction in adapter.get_valid_moves(x, y)
    result = (x + direction.dx, y + direction.dy) if legal else (x, y)

    assert result == expected_after


# --- Corner / center resolution ------------------------------------------

def test_corners_and_center_on_plaza_are_the_literal_cells() -> None:
    adapter = make_adapter(PLAZA_3x3)

    assert set(adapter.corners()) == {(0, 0), (2, 0), (0, 2), (2, 2)}
    assert adapter.center() == (1, 1)


def test_center_falls_back_to_nearest_walkable_when_sealed() -> None:
    adapter = make_adapter(RING_3x3)

    # literal center (1, 1) is sealed; all 8 surrounding cells are equally
    # near by Chebyshev distance, so the deterministic row-major ring scan
    # (top-to-bottom, left-to-right) picks (0, 0) first.
    assert adapter.center() == (0, 0)


def test_reference_path_length_raises_when_wheel_reports_no_path() -> None:
    adapter = make_adapter(PLAZA_3x3)
    adapter._shortest_path = False

    with pytest.raises(MazeAdapterError):
        adapter.reference_path_length()


# --- ASCII renderer -------------------------------------------------------

def test_render_ascii_shape_and_sealed_block() -> None:
    adapter = make_adapter(RING_3x3)

    rendered = adapter.render_ascii()
    lines = rendered.splitlines()

    assert len(lines) == 2 * 3 + 1
    assert all(len(line) == 2 * 3 + 1 for line in lines)
    # sealed center cell (grid[1][1] == 15) sits at canvas (3, 3).
    assert lines[3][3] == "#"


# --- Size clamping (Milestone 1.3, verified asymmetric minimum) ---------

@pytest.mark.parametrize("width,height", [
    (5, 5),
    (14, 5),
    (5, 10),
    (1, 1),
])
def test_undersized_requests_are_clamped_to_the_wheel_minimum(
    width: int, height: int,
) -> None:
    adapter = MazeAdapter(width, height, seed=1)

    assert adapter.width >= MIN_MAZE_WIDTH
    assert adapter.height >= MIN_MAZE_HEIGHT


def test_oversized_requests_are_not_clamped() -> None:
    adapter = MazeAdapter(21, 15, seed=1)

    assert (adapter.width, adapter.height) == (21, 15)


# --- Live wheel characterization tests ------------------------------------
# These call the real installed `mazegenerator` wheel; they pin the facts
# CLAUDE.md's trap list documents from reading the source, so a future
# wheel swap that changes behavior fails here first.
#
# test_wheel_maze_entry_exit_tuple_order_is_x_y is the one place outside
# pacman/maze/adapter.py that imports `mazegenerator` directly: its whole
# purpose is to pin the third-party wheel's own tuple-order behavior
# (REFERENCE.md §5.3-5.4), independent of whether the adapter chooses to
# surface entry/exit at all -- it verifies a fact about the dependency,
# it doesn't consume the dependency from game code.

def test_wheel_maze_entry_exit_tuple_order_is_x_y() -> None:
    """PLAN.md Milestone 1.3 item 36: confirm empirically that
    maze_entry/maze_exit are (x, y) -- the README's claimed (row, col) is
    wrong (CLAUDE.md's trap list #4). Uses an asymmetric maze (REFERENCE.md
    §5.4's own recipe) so a transposed tuple order would be caught."""
    from mazegenerator import MazeGenerator

    width, height = 9, 5
    generator = MazeGenerator(size=(width, height), perfect=False, seed=1)

    entry_x, entry_y = generator.maze_entry
    assert 0 <= entry_x < width
    assert 0 <= entry_y < height

    exit_x, exit_y = generator.maze_exit
    # default exit_cell=(-1, -1) resolves to the bottom-right corner;
    # if the tuple order were really (row, col) this would instead need
    # (exit_y, exit_x) == (width - 1, height - 1) to hold.
    assert (exit_x, exit_y) == (width - 1, height - 1)


def test_load_wheel_maze_is_reproducible_for_a_positive_seed() -> None:
    first = MazeAdapter(15, 15, seed=42)
    first.load_wheel_maze()
    second = MazeAdapter(15, 15, seed=42)
    second.load_wheel_maze()

    assert first._require_loaded() == second._require_loaded()
    assert first.corners() == second.corners()
    assert first.center() == second.center()
    assert first.reference_path_length() == second.reference_path_length()


def test_wheel_grid_is_row_major_and_north_bit_set_on_top_row() -> None:
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    grid = adapter._require_loaded()

    assert len(grid) == 15 and all(len(row) == 15 for row in grid)
    # every cell in the top row must carry its North wall bit (border).
    assert all(cell & Direction.NORTH.wall_bit for cell in grid[0])


def test_wheel_mirror_consistency_invariant() -> None:
    """TESTING_PLAYBOOK.md §2.3: East/West and South/North bits must mirror
    between adjacent cells on a real generated maze."""
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    grid = adapter._require_loaded()
    width, height = 15, 15

    for y in range(height):
        for x in range(width - 1):
            east = bool(grid[y][x] & Direction.EAST.wall_bit)
            west = bool(grid[y][x + 1] & Direction.WEST.wall_bit)
            assert east == west
    for y in range(height - 1):
        for x in range(width):
            south = bool(grid[y][x] & Direction.SOUTH.wall_bit)
            north = bool(grid[y + 1][x] & Direction.NORTH.wall_bit)
            assert south == north


def test_wheel_walkable_cells_form_one_connected_component() -> None:
    """TESTING_PLAYBOOK.md §2.5: the braided generator guarantees this."""
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()
    width, height = 15, 15

    walkable = {
        (x, y)
        for y in range(height) for x in range(width)
        if adapter.is_walkable(x, y)
    }
    assert walkable  # sanity: not an empty maze

    start = next(iter(walkable))
    reached = {start}
    frontier = [start]
    while frontier:
        cell = frontier.pop()
        for neighbor in adapter.neighbors(*cell):
            if neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)

    assert reached == walkable


def test_reference_path_length_matches_a_real_maze() -> None:
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()

    length = adapter.reference_path_length()

    assert isinstance(length, int)
    assert length > 0


def test_load_wheel_maze_wraps_generator_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pacman.maze.adapter as adapter_module

    class ExplodingGenerator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(adapter_module, "MazeGenerator", ExplodingGenerator)
    adapter = MazeAdapter(15, 15, seed=1)

    with pytest.raises(MazeAdapterError):
        adapter.load_wheel_maze()
