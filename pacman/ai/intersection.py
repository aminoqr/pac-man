"""The shared intersection decision rule (Milestone 2.4, REFERENCE.md §4.5).

One rule serves all four ghosts: at a tile, enumerate the legal exits
(no blocking wall, not the reverse of travel), score each candidate next
tile by SQUARED straight-line distance to the target -- integers only,
same ordering as Euclidean, no float epsilon -- take the minimum, and
break ties with the fixed priority Up > Left > Down > Right. Frightened
mode replaces the scoring with a draw from the caller's seeded RNG
(still never reversing). The wall-ignoring myopia is deliberate arcade
design, not a shortcut: path-optimal ghosts are less escapable and less
fun (REFERENCE.md §4.5).

Between tiles a ghost is committed to its direction (REFERENCE.md §1.1,
degree-2 cells are corridors): the engine only calls these functions at
tile centers, which is what makes ghost AI cheap.

Gameplay movement uses the path-based ``choose_target_exit`` instead
(and ``choose_eaten_exit`` for EATEN eyes): the greedy rule's wall-blind
myopia is arcade-faithful on hand-designed boards, but this project's
braided wheel mazes are full of micro-loops that trap a greedy ghost
orbiting a wall forever (it visibly "spins in place"). Navigating by
true graph distance -- the Milestone 3 upgrade REFERENCE.md §3.7
anticipates -- keeps the four personalities (they still pursue distinct
*target tiles*) while making the ghosts actually roam and hunt.
``choose_exit`` remains the documented greedy primitive (still used by
its unit tests and as the total-safety fallback).
"""

from random import Random

from pacman.ai.ghost import Cell
from pacman.maze.adapter import Direction, MazeAdapter
from pacman.pathfinding.search import astar_path, distance_map

# Up > Left > Down > Right (TESTING_PLAYBOOK.md §4.3): fixed so every
# tie resolves identically on every run -- determinism is a feature.
TIE_BREAK_ORDER = (
    Direction.NORTH,
    Direction.WEST,
    Direction.SOUTH,
    Direction.EAST,
)


def legal_exits(
    adapter: MazeAdapter, cell: Cell, current_direction: Direction,
) -> list[Direction]:
    """Open, non-reverse exits from ``cell`` in tie-break priority order.

    Dead-end escape hatch (PLAN.md §2.4 / playbook I5): if the only
    physical exit is the reverse, the reversal is allowed rather than
    trapping the ghost -- rare on a braided maze, but the "42"-block
    pocket edges can produce it. A fully sealed cell yields ``[]``.
    """
    open_moves = adapter.get_valid_moves(*cell)
    exits = [
        direction
        for direction in TIE_BREAK_ORDER
        if direction in open_moves
        and direction is not current_direction.opposite
    ]
    if not exits and current_direction.opposite in open_moves:
        return [current_direction.opposite]
    return exits


def choose_exit(
    adapter: MazeAdapter,
    cell: Cell,
    current_direction: Direction,
    target: Cell,
) -> Direction:
    """Greedy step toward ``target``; ties break Up > Left > Down > Right.

    Because ``legal_exits`` returns candidates in priority order and the
    comparison below is strictly ``<``, the first of any tied set wins.
    Falls back to ``current_direction`` when the cell has no exit at all
    (only a sealed cell no ghost should ever occupy) -- the AI stays
    total because rare crashes are still crashes (REFERENCE.md §4.5).
    """
    exits = legal_exits(adapter, cell, current_direction)
    if not exits:
        return current_direction
    best = exits[0]
    best_d2 = _squared_distance_after(cell, best, target)
    for candidate in exits[1:]:
        d2 = _squared_distance_after(cell, candidate, target)
        if d2 < best_d2:
            best, best_d2 = candidate, d2
    return best


def choose_frightened_exit(
    adapter: MazeAdapter,
    cell: Cell,
    current_direction: Direction,
    rng: Random,
) -> Direction:
    """Seeded pseudo-random legal exit for frightened wandering.

    Playbook F1/F2: the draw comes from the caller's seeded RNG (one RNG
    owned by the game state -- same seed, same wander path) and the
    no-reverse rule still applies, dead-end hatch included.
    """
    exits = legal_exits(adapter, cell, current_direction)
    if not exits:
        return current_direction
    return rng.choice(exits)


def choose_target_exit(
    adapter: MazeAdapter,
    cell: Cell,
    current_direction: Direction,
    target: Cell,
) -> Direction:
    """Best legal exit toward ``target`` by TRUE path distance.

    The arcade rule with a wall-aware metric. Each candidate is a legal
    exit that is NOT the reverse of travel (``legal_exits``, dead-end
    hatch included); each is scored by the real graph distance from the
    tile it leads to, and the smallest wins, ties broken Up > Left >
    Down > Right. The target may be a phantom tile (outside the maze or
    inside a wall -- targets are never clamped, REFERENCE.md §4.4), so
    it is first resolved to the nearest walkable anchor.

    Three properties this gets right, each one a bug in a simpler rule:

    * **No reversing.** Taking a raw shortest-path hop instead lets a
      ghost double back the instant the player moves, so it jitters on
      the spot; forbidding the reverse is what produces the committed,
      readable arcade pursuit (and is what gives the player any escape).
    * **Never stalls.** Scoring the *exits* rather than pathing to the
      anchor means a ghost sitting on its own target still has to pick
      an exit and keep going -- it circles, as the arcade ghosts do,
      instead of parking or twitching between two tiles.
    * **No wall traps.** Straight-line distance (``choose_exit``) sinks
      into local minima on these braided mazes; graph distance cannot
      (REFERENCE.md §3.7).

    Personalities are untouched -- each ghost still pursues its own
    target tile; only the route-finding is shared.
    """
    exits = legal_exits(adapter, cell, current_direction)
    if not exits:
        return current_direction
    anchor = adapter.nearest_walkable(*target)
    distances = distance_map(adapter, anchor)
    best = exits[0]
    best_distance: int | None = None
    for candidate in exits:
        step_cell = (cell[0] + candidate.dx, cell[1] + candidate.dy)
        reach = distances.get(step_cell)
        if reach is None:  # walled off from the target entirely
            continue
        if best_distance is None or reach < best_distance:
            best, best_distance = candidate, reach
    return best


def choose_eaten_exit(
    adapter: MazeAdapter,
    cell: Cell,
    current_direction: Direction,
    home: Cell,
) -> Direction:
    """First hop of a true shortest path home, for EATEN eyes.

    The Milestone 3 gameplay wiring (PLAN.md): eyes follow
    ``astar_path`` -- REFERENCE.md §3.6 pins "eaten ghost going home"
    as A*'s best use -- instead of the greedy rule, because greedy
    straight-line scoring plus no-reverse can orbit the "42" block
    indefinitely, while the shortest-path hop strictly decreases TRUE
    path distance every re-decision: arrival in exactly d(cell, home)
    moves, guaranteed. Two deliberate rule changes for eyes: they may
    reverse (the hop home can point backward; ``current_direction`` is
    unused on the happy path), and they never wander. Falls back to
    the shared greedy rule -- staying total -- when already home or
    when home is unreachable (a sealed cell; cannot happen on a
    braided wheel maze).
    """
    result = astar_path(adapter, cell, home)
    if result.path is None or len(result.path) < 2:
        return choose_exit(adapter, cell, current_direction, home)
    next_cell = result.path[1]
    return _DELTA_TO_DIRECTION[
        (next_cell[0] - cell[0], next_cell[1] - cell[1])
    ]


def _squared_distance_after(
    cell: Cell, direction: Direction, target: Cell,
) -> int:
    """Squared distance from the tile ``direction`` leads to, to target."""
    next_x = cell[0] + direction.dx
    next_y = cell[1] + direction.dy
    return (next_x - target[0]) ** 2 + (next_y - target[1]) ** 2


# A* returns cells; ghosts speak Directions. Adjacent-hop deltas map
# 1:1 onto the canonical enum (REFERENCE.md §1.4).
_DELTA_TO_DIRECTION: dict[Cell, Direction] = {
    (d.dx, d.dy): d for d in Direction
}
