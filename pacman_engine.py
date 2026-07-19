"""Core game-state management for 42 Pacman.

This module owns the mutable world state (player, ghosts, pellets, score,
lives, timers) and advances it in fixed simulation ticks. It knows NOTHING
about rendering or the wheel: maze topology arrives exclusively through the
``MazeAdapter`` interface (maze_adapter.py), and drawing is someone else's
job -- the engine must stay testable headless (no window, no clock).

Coordinate system (identical everywhere in the project; REFERENCE.md §1.2):

        x ->   0   1   2   3        * positions are (x, y) tuples
      y                             * arrays are indexed grid[y][x]
      |  0   [ ] [ ] [ ] [ ]        * y INCREASES DOWNWARD:
      v  1   [ ] [ ] [ ] [ ]            North / up    = (0, -1)
         2   [ ] [ ] [ ] [ ]            South / down  = (0, +1)

    The #1 classic bug is mixing grid[x][y] with grid[y][x]; it stays
    invisible on square mazes and explodes on rectangular ones. Test with
    a non-square maze early.

4-bit wall encoding (REFERENCE.md §1.3):

    bit 0 (value 1) = North wall    bit 2 (value 4) = South wall
    bit 1 (value 2) = East wall     bit 3 (value 8) = West wall

    A cell value is an int in [0, 15]. Example: 9 = 8 + 1 = West + North.
    Movement legality is a single bitwise test: direction d is open iff
    (cell & d.wall_bit) == 0. Value 15 = sealed cell = the "42" logo,
    never walkable.

Time model (REFERENCE.md §2.1): one call to ``update_game_state`` advances
exactly ONE tick of fixed duration. All speeds and timers are expressed in
ticks, never wall-clock seconds, so pause is trivial and tests are
deterministic.
"""

from enum import Enum, auto


class GhostMode(Enum):
    """Global/per-ghost behavior modes (REFERENCE.md §4.2-§4.3).

    SCATTER and CHASE alternate on the wave timer; FRIGHTENED is an overlay
    triggered by a super-pacgum that PAUSES (not consumes) the wave timer;
    EATEN sends a ghost back to its home corner before it rejoins the
    current global mode.
    """

    SCATTER = auto()
    CHASE = auto()
    FRIGHTENED = auto()
    EATEN = auto()


class GameState:
    """Container for one running level's mutable state.

    Expected contents (define the attributes as you implement):
        * the MazeAdapter for the current level;
        * player: tile (x, y), current direction, buffered input direction
          (REFERENCE.md §2.3), remaining lives;
        * ghosts: per-ghost tile, direction, home corner, mode;
        * previous-tick positions of player and ghosts -- REQUIRED for the
          tile-swap collision test (REFERENCE.md §2.7);
        * pellet layer: set of pacgum cells + set of super-pacgum cells,
          kept SEPARATE from wall data (different lifetimes);
        * score, level index, tick counters for: level time limit,
          scatter/chase wave schedule, frightened countdown, eaten respawns.
    """

    pass


def parse_grid_map(raw_grid: list[list[int]]) -> None:
    """Derive the engine's static level data from a raw wall-encoded grid.

    Input: the wheel's row-major ``list[list[int]]`` (via MazeAdapter),
    each value a 4-bit wall mask per the module docstring above.

    Responsibilities when implemented:
        * classify cells: walkable corridor vs solid (value 15);
        * decide pellet placement -- pacgums in "most corridors"
          (subject VI.1), super-pacgums at the 4 corners;
        * compute spawn anchors: 4 ghost corners + player center;
        * sanity-check the wall consistency invariant (a cell's East bit
          must mirror its right neighbor's West bit) to fail fast on a
          malformed or misparsed grid.

    Fix the return type when you design the structure (e.g. a LevelData
    dataclass); it is left as None only because this is a skeleton.
    """
    pass


def update_game_state(state: GameState) -> None:
    """Advance the simulation by exactly one fixed tick.

    Canonical order of operations (REFERENCE.md §2), to be implemented:
        1. snapshot previous positions (needed by step 5);
        2. tick timers: level countdown, scatter/chase wave, frightened,
           eaten-ghost respawn delays; apply mode transitions -- and force
           the all-ghost direction reversal on every scatter<->chase flip;
        3. move player: at tile centers only, try the buffered input
           direction first, else keep current direction, else stop
           (all wall checks via MazeAdapter.get_valid_moves);
        4. move ghosts: at tile centers run the intersection rule
           (REFERENCE.md §4.5) against each ghost's current target tile;
        5. resolve collisions -- BOTH cases: same-tile overlap AND the
           pass-through swap (player now on ghost's previous tile and
           vice versa);
        6. consume pellets on the player's tile; update score; check
           win (no pacgums left) / life-loss / game-over conditions.

    Must remain free of any rendering or I/O so the whole game can be
    driven tick-by-tick inside pytest.
    """
    pass
