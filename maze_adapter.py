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

from enum import Enum


class Direction(Enum):
    """Canonical direction enumeration shared by the whole project.

    Each member must carry (see REFERENCE.md §1.4):
        * the grid delta ``(dx, dy)`` -- remember y grows DOWNWARD,
          so North is (0, -1);
        * the wall bit used for O(1) legality tests (N=1, E=2, S=4, W=8);
        * its opposite (needed by the ghosts' no-reverse rule);
        * the letter used by the wheel's ``shortest_path`` strings (NESW).
    """

    pass


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
    """

    def __init__(self, width: int, height: int, seed: int) -> None:
        """Store the requested parameters; generation happens in load_wheel_maze.

        Clamp/validate width and height BEFORE ever calling the wheel:
        the generator prints a warning and skips the '42' logo when the
        maze is too small (roughly < 14 cells per side).
        """
        pass

    def load_wheel_maze(self) -> None:
        """Call the wheel's ``MazeGenerator`` and capture its output.

        Required call shape (subject V.4): ``perfect=False`` ALWAYS -- the
        braiding pass it triggers removes every dead end, which is what
        makes the maze Pac-Man-playable (REFERENCE.md §1.6).

        Seeding semantics discovered during inspection: seed > 0 gives a
        reproducible maze (level 1 must use the configured seed, e.g. 42);
        seed == 0 means fully random (later levels).

        Must wrap ANY failure in :class:`MazeAdapterError` and validate the
        received grid (dimensions match, every value in [0, 15]).
        """
        pass

    def is_walkable(self, x: int, y: int) -> bool:
        """Return True if the cell exists and is not a solid block.

        A cell is solid when its value is 15 (the "42" logo) -- sealed on
        all four sides. Out-of-bounds coordinates are never walkable.
        """
        pass

    def get_valid_moves(self, x: int, y: int) -> list[Direction]:
        """Enumerate the directions with no blocking wall from (x, y).

        Core predicate (REFERENCE.md §1.3): moving in direction ``d`` is
        legal iff ``grid[y][x] & d.wall_bit == 0``. The border cells always
        carry their outward wall bits, so this test alone also acts as the
        bounding box of the maze -- no separate bounds check is needed for
        movement.
        """
        pass

    def neighbors(self, x: int, y: int) -> list[tuple[int, int]]:
        """Return the coordinates reachable in one step from (x, y).

        This is the ONE primitive the pathfinding module (Milestone 3)
        builds on -- BFS/DFS/A* must depend on this method, not on the
        grid's storage format.
        """
        pass

    def corners(self) -> list[tuple[int, int]]:
        """Return the 4 walkable corner cells (ghost spawns / super-pacgums).

        Subject VI.1: super-pacgums sit in the 4 corners and one ghost
        spawns in each corner. If a literal corner is not walkable, the
        nearest walkable cell to it should be chosen -- document whichever
        policy you implement.
        """
        pass

    def center(self) -> tuple[int, int]:
        """Return the player spawn cell at (or nearest to) the maze center.

        Beware: the exact center may fall inside the solid "42" logo block,
        so this must locate the nearest WALKABLE cell to the geometric
        center. Also used for respawn after losing a life (subject VI.2).
        """
        pass

    def reference_path_length(self) -> int:
        """Return the length of the wheel's own entry->exit shortest path.

        The generator exposes ``shortest_path`` as an 'NESW' string; its
        length is a ready-made oracle for validating our BFS and A* in
        Milestone 3 (equal lengths, not necessarily equal paths). May be
        ``False`` when the wheel found no path -- convert that case into
        :class:`MazeAdapterError` instead of leaking a bool.
        """
        pass
