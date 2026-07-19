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
"""

from random import Random

from pacman.ai.ghost import Cell
from pacman.maze.adapter import Direction, MazeAdapter

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


def _squared_distance_after(
    cell: Cell, direction: Direction, target: Cell,
) -> int:
    """Squared distance from the tile ``direction`` leads to, to target."""
    next_x = cell[0] + direction.dx
    next_y = cell[1] + direction.dy
    return (next_x - target[0]) ** 2 + (next_y - target[1]) ** 2
