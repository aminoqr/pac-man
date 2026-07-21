"""Isolated adapter layer around the ``mazegenerator`` wheel.

This module is the ONLY place in the codebase allowed to import from the
``mazegenerator`` package (see REFERENCE.md §5.5, the anti-corruption layer).
Everything else in the game consumes the vocabulary defined here.

Why a strict boundary?
    * Subject V.4: the wheel must be used AS-IS and will be re-installed at
      peer review -- our loader adapts to their interface, never the reverse.
      If evaluators swap in another group's package, only this file changes.
    * The wheel's documented API and its observed behavior disagree in spots
      (tuple order of ``maze_entry``/``maze_exit``, default sizes). This
      module resolves those ambiguities ONCE, backed by characterization
      tests, so the rest of the game never has to think about them.

Read-only contract:
    The adapter treats the generator as a sealed black box. It calls the
    public constructor/properties, validates and copies what it receives,
    and never mutates generator state or reaches into ``_private`` members.

Wall encoding reminder (full details in REFERENCE.md §1.3):
    Each cell of the raw maze is an int in [0, 15]; bit 0 = North wall,
    bit 1 = East, bit 2 = South, bit 3 = West. Value 15 (all walls) marks
    the isolated "42"-logo blocks and must be treated as non-walkable.
"""

import logging
from enum import Enum

from mazegenerator import MazeGenerator

logger = logging.getLogger(__name__)

# Verified against the shipped wheel source (CLAUDE.md's trap list): the
# "42" logo is 7 cells wide x 5 cells tall and its insertion is skipped
# (silently, no exception) whenever width < 14 or height < 10 -- these
# thresholds are asymmetric, not a flat "14 per side".
MIN_MAZE_WIDTH = 14
MIN_MAZE_HEIGHT = 10


class Direction(Enum):
    """Canonical direction enumeration shared by the whole project.

    Each member carries (see REFERENCE.md §1.4):
        * the grid delta ``(dx, dy)`` -- remember y grows DOWNWARD,
          so North is (0, -1);
        * the wall bit used for O(1) legality tests (N=1, E=2, S=4, W=8);
        * its opposite (needed by the ghosts' no-reverse rule);
        * the letter used by the wheel's ``shortest_path`` strings (NESW).

    Declared North/East/South/West so member order matches the bit order
    (1, 2, 4, 8 = 2**0..2**3), per REFERENCE.md §1.4.
    """

    NORTH = (0, -1, 1, "N")
    EAST = (1, 0, 2, "E")
    SOUTH = (0, 1, 4, "S")
    WEST = (-1, 0, 8, "W")

    def __init__(self, dx: int, dy: int, wall_bit: int, letter: str) -> None:
        self.dx = dx
        self.dy = dy
        self.wall_bit = wall_bit
        self.letter = letter

    @property
    def opposite(self) -> "Direction":
        """The reverse direction (needed by the ghosts' no-reverse rule)."""
        return _OPPOSITES[self]


_OPPOSITES: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}


class MazeAdapterError(Exception):
    """Single catchable error type for every generator failure.

    Any exception, warning condition, or malformed output coming from the
    wheel (e.g. ``shortest_path`` being ``False`` instead of a string) must
    be converted into this type here, so callers never need to know what
    can go wrong inside the third-party package. Subject III.1: no raw
    tracebacks may ever reach the player.
    """

    pass


class MazeAdapter:
    """Read-only facade over one generated maze.

    Owns the raw ``list[list[int]]`` grid received from the wheel and
    answers the graph-interface queries the game actually needs
    (REFERENCE.md §1.5): walkability, legal moves, neighbor enumeration,
    plus the placement anchors required by subject VI.1 (corners, center).

    Coordinate convention (project-wide, non-negotiable):
        * A position is an ``(x, y)`` tuple: x = column, y = row.
        * The raw grid is row-major and indexed ``grid[y][x]``.
        * ``y`` increases downward; ``grid[0]`` is the TOP row.

    Two-step construction: build the adapter, then call
    ``load_wheel_maze()`` before using any other method. Every query
    method raises :class:`MazeAdapterError` if called first.
    """

    def __init__(self, width: int, height: int, seed: int) -> None:
        """Clamp width/height to the wheel's playable minimum and store them.

        Clamped here (not in the config loader, PLAN.md §1.2) because the
        minimum is a `mazegenerator` implementation detail (the "42" logo
        insertion), not a general config-validation concern.
        """
        clamped_width = max(width, MIN_MAZE_WIDTH)
        clamped_height = max(height, MIN_MAZE_HEIGHT)
        if clamped_width != width or clamped_height != height:
            logger.warning(
                "Requested maze size %dx%d is below the wheel's playable "
                "minimum (%dx%d); clamped to %dx%d.",
                width, height, MIN_MAZE_WIDTH, MIN_MAZE_HEIGHT,
                clamped_width, clamped_height,
            )
        self.width = clamped_width
        self.height = clamped_height
        self.seed = seed
        self._grid: list[list[int]] | None = None
        self._shortest_path: str | bool = False

    def load_wheel_maze(self) -> None:
        """Call the wheel's ``MazeGenerator`` and capture its output.

        Required call shape (subject V.4): ``perfect=False`` ALWAYS -- the
        braiding pass it triggers removes every dead end, which is what
        makes the maze Pac-Man-playable (REFERENCE.md §1.6). Entry/exit are
        left at the wheel's own defaults (top-left / bottom-right corner);
        this project doesn't need custom placement.

        Seeding semantics verified from the wheel source: seed > 0 gives a
        reproducible maze (level 1 must use the configured seed, e.g. 42);
        seed == 0 means fully random (later levels).

        Wraps ANY failure in :class:`MazeAdapterError` and validates the
        received grid (dimensions match, every value in [0, 15]) -- the
        wheel is a sealed black box, so a bare ``except Exception`` here is
        deliberate, not sloppy (REFERENCE.md §5.2).
        """
        try:
            generator = MazeGenerator(
                size=(self.width, self.height),
                perfect=False,
                seed=self.seed,
            )
        except Exception as exc:
            raise MazeAdapterError(
                f"mazegenerator failed to generate a {self.width}x"
                f"{self.height} maze (seed={self.seed}): {exc}"
            ) from exc

        grid = generator.maze
        self._validate_grid(grid)
        self._grid = grid
        self._shortest_path = generator.shortest_path

    def _validate_grid(self, grid: object) -> None:
        """Raise MazeAdapterError if the wheel's grid isn't well-formed."""
        if not isinstance(grid, list) or len(grid) != self.height:
            actual = (
                len(grid) if isinstance(grid, list) else type(grid).__name__
            )
            raise MazeAdapterError(
                f"wheel returned {actual} rows, expected {self.height}"
            )
        for y, row in enumerate(grid):
            if not isinstance(row, list) or len(row) != self.width:
                raise MazeAdapterError(f"wheel returned a malformed row {y}")
            for cell in row:
                if not isinstance(cell, int) or not (0 <= cell <= 15):
                    raise MazeAdapterError(
                        f"wheel returned an out-of-range cell value: {cell!r}"
                    )

    def _require_loaded(self) -> list[list[int]]:
        """Return the grid, raising if load_wheel_maze() hasn't run yet."""
        if self._grid is None:
            raise MazeAdapterError(
                "load_wheel_maze() must be called before querying the maze"
            )
        return self._grid

    def is_walkable(self, x: int, y: int) -> bool:
        """Return True if the cell exists and is not a solid block.

        A cell is solid when its value is 15 (the "42" logo) -- sealed on
        all four sides. Out-of-bounds coordinates are never walkable.
        """
        grid = self._require_loaded()
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return grid[y][x] != 15

    def get_valid_moves(self, x: int, y: int) -> list[Direction]:
        """Enumerate the directions with no blocking wall from (x, y).

        Core predicate (REFERENCE.md §1.3): moving in direction ``d`` is
        legal iff ``grid[y][x] & d.wall_bit == 0``. The border cells always
        carry their outward wall bits, so this test alone also acts as the
        bounding box of the maze -- no separate bounds check is needed for
        movement (an out-of-range (x, y) simply yields no legal moves).
        """
        grid = self._require_loaded()
        if not (0 <= x < self.width and 0 <= y < self.height):
            return []
        cell = grid[y][x]
        return [d for d in Direction if cell & d.wall_bit == 0]

    def neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        """Return the coordinates reachable in one step from (x, y).

        This is the ONE primitive the pathfinding module (Milestone 3)
        builds on -- BFS/DFS/A* must depend on this method, not on the
        grid's storage format.
        """
        return [
            (x + d.dx, y + d.dy) for d in self.get_valid_moves(x, y)
        ]

    def _nearest_walkable(self, x: int, y: int) -> tuple[int, int]:
        """Return (x, y) if walkable, else the nearest walkable cell.

        Searches expanding square rings (Chebyshev distance) around the
        point, scanning each ring top-to-bottom/left-to-right for a
        deterministic result. Geometric proximity, not graph distance --
        this only matters for the rare case where a literal corner/center
        lands on a sealed "42"-logo cell.
        """
        if self.is_walkable(x, y):
            return (x, y)
        max_radius = max(self.width, self.height)
        for radius in range(1, max_radius):
            y_lo, y_hi = max(0, y - radius), min(self.height, y + radius + 1)
            x_lo, x_hi = max(0, x - radius), min(self.width, x + radius + 1)
            for ny in range(y_lo, y_hi):
                for nx in range(x_lo, x_hi):
                    if max(abs(nx - x), abs(ny - y)) != radius:
                        continue
                    if self.is_walkable(nx, ny):
                        return (nx, ny)
        raise MazeAdapterError("maze has no walkable cell at all")

    def nearest_walkable(self, x: int, y: int) -> tuple[int, int]:
        """Public: the walkable cell nearest to (x, y), coords clamped first.

        Ghost target tiles are deliberately un-clamped and may lie
        outside the maze (a scatter point beyond a corner, Pinky's
        4-ahead phantom). Path-based navigation needs a real in-maze
        anchor, so the coordinates are first clamped into bounds and
        then resolved to the nearest walkable cell (Chebyshev), keeping
        the search cheap for far-outside points.
        """
        clamped_x = min(max(x, 0), self.width - 1)
        clamped_y = min(max(y, 0), self.height - 1)
        return self._nearest_walkable(clamped_x, clamped_y)

    def corners(self) -> list[tuple[int, int]]:
        """Return the 4 walkable corner cells (ghost spawns / super-pacgums).

        Subject VI.1: super-pacgums sit in the 4 corners and one ghost
        spawns in each corner. Policy for an unwalkable literal corner
        (sealed "42"-logo cell): substitute the nearest walkable cell by
        geometric (Chebyshev) proximity, per ``_nearest_walkable``.
        """
        self._require_loaded()
        literal_corners = [
            (0, 0),
            (self.width - 1, 0),
            (0, self.height - 1),
            (self.width - 1, self.height - 1),
        ]
        return [self._nearest_walkable(x, y) for x, y in literal_corners]

    def center(self) -> tuple[int, int]:
        """Return the player spawn cell at (or nearest to) the maze center.

        Beware: the exact center may fall inside the solid "42" logo block,
        so this must locate the nearest WALKABLE cell to the geometric
        center. Also used for respawn after losing a life (subject VI.2).
        """
        self._require_loaded()
        return self._nearest_walkable(self.width // 2, self.height // 2)

    def reference_path_length(self) -> int:
        """Return the length of the wheel's own entry->exit shortest path.

        The generator exposes ``shortest_path`` as an 'NESW' string; its
        length is a ready-made oracle for validating our BFS and A* in
        Milestone 3 (equal lengths, not necessarily equal paths). May be
        ``False`` when the wheel found no path -- converted here into
        :class:`MazeAdapterError` instead of leaking a bool.
        """
        self._require_loaded()
        if not isinstance(self._shortest_path, str):
            raise MazeAdapterError(
                "wheel reported no entry->exit path (shortest_path=False)"
            )
        return len(self._shortest_path)

    def render_ascii(self) -> str:
        """Render the maze as ASCII: '#' walls, '.' walkable, solid block "42".

        The primary debugging tool for everything built on top of this
        adapter (PLAN.md Milestone 1.3). Draws a (2*height+1) x (2*width+1)
        character canvas: cell centers on odd rows/columns, walls on the
        even rows/columns between them.
        """
        grid = self._require_loaded()
        canvas = [
            [" "] * (2 * self.width + 1) for _ in range(2 * self.height + 1)
        ]

        for y in range(self.height):
            for x in range(self.width):
                cell = grid[y][x]
                cy, cx = 2 * y + 1, 2 * x + 1
                canvas[cy][cx] = "#" if cell == 15 else "."
                for d in Direction:
                    if cell & d.wall_bit:
                        canvas[cy + d.dy][cx + d.dx] = "#"

        for ry in range(0, 2 * self.height + 1, 2):
            for rx in range(0, 2 * self.width + 1, 2):
                canvas[ry][rx] = "#"

        return "\n".join("".join(row) for row in canvas)
