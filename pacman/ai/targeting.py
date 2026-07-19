"""Per-ghost chase-target formulas + mode dispatch (PLAN.md Milestone 2.3).

REFERENCE.md §4.4. Every formula is pure coordinate math with zero maze
dependency -- exactly what makes each personality unit-testable without a
game loop (REFERENCE.md §4.7). TESTING_PLAYBOOK.md §4.2 is the fixed-point
table these functions are tested against.

Two pinned policies (either choice is valid; the tests pin these):
    * Pinky's legacy "up = up-and-left" overflow quirk is NOT reproduced:
      facing North targets straight up, ``P + 4*(0, -1)``.
    * Clyde's 8-tile radius uses straight-line (squared) distance like the
      arcade, not path distance (REFERENCE.md §3.7 describes the
      wall-aware upgrade Milestone 3 unlocks).

Targets are compared against, never traveled to: they may land outside
the maze or inside a wall and MUST NOT be clamped (REFERENCE.md §4.4).
"""

from pacman.ai.ghost import Cell, Ghost, GhostMode, GhostPersonality
from pacman.maze.adapter import Direction

PINKY_LOOKAHEAD_TILES = 4
INKY_PIVOT_TILES = 2
CLYDE_RADIUS_TILES = 8


def blinky_target(player_cell: Cell) -> Cell:
    """Blinky ("Shadow") pursues Pac-Man's exact tile."""
    return player_cell


def pinky_target(player_cell: Cell, player_direction: Direction) -> Cell:
    """Pinky ("Speedy") aims 4 tiles ahead of Pac-Man's mouth."""
    return (
        player_cell[0] + PINKY_LOOKAHEAD_TILES * player_direction.dx,
        player_cell[1] + PINKY_LOOKAHEAD_TILES * player_direction.dy,
    )


def inky_target(
    player_cell: Cell, player_direction: Direction, blinky_cell: Cell,
) -> Cell:
    """Inky ("Bashful") reflects Blinky through the 2-ahead pivot.

    ``T = B + 2 * (pivot - B)`` with ``pivot = P + 2 * u`` -- the only
    two-anchor formula; coupling to Blinky is what creates the emergent
    pincer (REFERENCE.md §4.4).
    """
    pivot_x = player_cell[0] + INKY_PIVOT_TILES * player_direction.dx
    pivot_y = player_cell[1] + INKY_PIVOT_TILES * player_direction.dy
    return (2 * pivot_x - blinky_cell[0], 2 * pivot_y - blinky_cell[1])


def clyde_target(
    clyde_cell: Cell, player_cell: Cell, scatter_corner: Cell,
) -> Cell:
    """Clyde ("Pokey") chases from afar, breaks off inside 8 tiles.

    Strictly farther than 8 tiles -> pursue the player; at exactly 8 or
    closer -> retreat toward his scatter corner. Squared comparison keeps
    it integer-exact (no float epsilon).
    """
    dx = clyde_cell[0] - player_cell[0]
    dy = clyde_cell[1] - player_cell[1]
    if dx * dx + dy * dy > CLYDE_RADIUS_TILES ** 2:
        return player_cell
    return scatter_corner


def chase_target(
    ghost: Ghost,
    player_cell: Cell,
    player_direction: Direction,
    blinky_cell: Cell,
) -> Cell:
    """Dispatch CHASE targeting to the ghost's personality formula.

    ``blinky_cell`` is passed in (rather than looked up) so callers
    snapshot it once per tick -- Inky must see the same Blinky position
    regardless of update order.
    """
    personality = ghost.personality
    if personality is GhostPersonality.BLINKY:
        return blinky_target(player_cell)
    if personality is GhostPersonality.PINKY:
        return pinky_target(player_cell, player_direction)
    if personality is GhostPersonality.INKY:
        return inky_target(player_cell, player_direction, blinky_cell)
    if personality is GhostPersonality.CLYDE:
        return clyde_target(ghost.cell, player_cell, ghost.home_corner)
    raise ValueError(f"unknown personality: {personality!r}")


def target_tile(
    ghost: Ghost,
    player_cell: Cell,
    player_direction: Direction,
    blinky_cell: Cell,
) -> Cell:
    """The ghost's current target tile given its mode (REFERENCE.md §4.1).

    SCATTER and EATEN both target ``home_corner`` (scatter corner ==
    spawn corner == respawn point in this project); CHASE dispatches on
    personality. FRIGHTENED has no target by design -- movement is a
    seeded-random walk (intersection.choose_frightened_exit), so asking
    for one is a programming error and fails loudly.
    """
    if ghost.mode in (GhostMode.SCATTER, GhostMode.EATEN):
        return ghost.home_corner
    if ghost.mode is GhostMode.CHASE:
        return chase_target(ghost, player_cell, player_direction, blinky_cell)
    raise ValueError("frightened ghosts have no target tile")
