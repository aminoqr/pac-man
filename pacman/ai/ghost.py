"""Ghost data model and mode/personality enums (PLAN.md Milestone 2.1).

All four ghosts run the identical decision algorithm; the only thing that
differs between them is the target-tile formula their personality selects
(REFERENCE.md §4.1, §4.7 -- see targeting.py). This module owns per-ghost
mutable state plus the transitions the TESTING_PLAYBOOK.md §4.1 matrix
pins on individual ghosts (frightened entry, eaten bookkeeping). The
global clock that drives SCATTER<->CHASE waves lives in wave.py; the
shared movement rule lives in intersection.py. Nothing here touches the
maze or the game loop, so every transition is unit-testable in isolation.
"""

from dataclasses import dataclass
from enum import Enum, auto

from pacman.maze.adapter import Direction

Cell = tuple[int, int]


class GhostMode(Enum):
    """Global/per-ghost behavior modes (REFERENCE.md §4.2-§4.3).

    SCATTER and CHASE alternate on the wave timer; FRIGHTENED is an
    overlay triggered by a super-pacgum that PAUSES (not consumes) the
    wave timer; EATEN sends a ghost back to its home corner where it
    waits before rejoining the current global mode (subject VI.3).
    """

    SCATTER = auto()
    CHASE = auto()
    FRIGHTENED = auto()
    EATEN = auto()


class GhostPersonality(Enum):
    """Which chase-target formula a ghost uses (REFERENCE.md §4.4)."""

    BLINKY = auto()
    PINKY = auto()
    INKY = auto()
    CLYDE = auto()


@dataclass
class Ghost:
    """One ghost's mutable AI state.

    ``home_corner`` is the EATEN destination and respawn point (the
    ghost's actual spawn cell). ``scatter_target`` is a point *outside*
    the maze beyond that corner: aiming a wall-blind ghost at an
    unreachable outside tile makes it patrol a wide loop hugging the
    outer walls during SCATTER instead of jittering on the corner it is
    already standing on (the classic arcade behaviour, REFERENCE.md
    §4.4). It defaults to ``None`` (fall back to ``home_corner``) so
    hand-built test ghosts need not supply one; ``create_ghosts`` sets
    the real outside targets for gameplay. ``respawn_ticks_remaining``
    is ``None`` except while EATEN and parked at ``home_corner`` waiting
    to rejoin play; see ``tick_eaten_state``.
    """

    personality: GhostPersonality
    cell: Cell
    direction: Direction
    home_corner: Cell
    scatter_target: Cell | None = None
    mode: GhostMode = GhostMode.SCATTER
    respawn_ticks_remaining: int | None = None
    # Ticks travelled from ``cell`` toward the next tile along
    # ``direction``, out of ``move_span``. Ghost position is continuous
    # for the same reason the player's is: the UI draws exactly where the
    # ghost is instead of trailing a whole move period behind the
    # collision that already happened -- a ghost must never look a tile
    # away from the player it just caught. 0 means "on a tile center",
    # the only place the AI re-decides. ``move_span`` is the interval the
    # current tile is being crossed over, kept so a reversal can mirror
    # the travel exactly; the engine maintains it.
    move_ticks: int = 0
    move_span: int = 1

    def reverse(self) -> None:
        """Flip facing, keeping the sub-tile position exact.

        Reversing mid-tile re-anchors onto the tile being entered and
        mirrors the remaining travel, so the ghost pivots where it
        actually is rather than snapping to the tile it left.
        """
        if self.move_ticks > 0:
            self.cell = (
                self.cell[0] + self.direction.dx,
                self.cell[1] + self.direction.dy,
            )
            self.move_ticks = self.move_span - self.move_ticks
        self.direction = self.direction.opposite

    def enter_frightened(self) -> None:
        """Become frightened and reverse, unless EATEN.

        TESTING_PLAYBOOK.md G10: an eaten ghost is NOT re-frightened by
        a later super-pacgum. Reversal-on-entry is REFERENCE.md §4.2's
        rule; the wave-clock side of the trigger is
        ``wave.trigger_frightened``, which calls this on every ghost.
        """
        if self.mode is GhostMode.EATEN:
            return
        self.mode = GhostMode.FRIGHTENED
        self.reverse()

    def enter_eaten(self) -> None:
        """Caught by the player while frightened (TESTING_PLAYBOOK.md G7).

        The caller is responsible for only invoking this on a frightened
        ghost (edibility is collision logic, Milestone 4) and for any
        scoring side effects.
        """
        self.mode = GhostMode.EATEN
        self.respawn_ticks_remaining = None

    def tick_eaten_state(
        self, wave_mode: GhostMode, respawn_delay_ticks: int,
    ) -> None:
        """Advance EATEN bookkeeping one tick (TESTING_PLAYBOOK.md G8/G9).

        Call once per tick while EATEN; movement toward
        ``home_corner`` itself is the caller's job via
        ``intersection.choose_eaten_exit`` -- the true shortest-path
        hop home wired in by Milestone 3 (targeting.py still reports
        ``home_corner`` as the EATEN target). On arrival the respawn
        countdown starts; it
        decrements on each subsequent call, and when it hits zero the
        ghost rejoins ``wave_mode`` -- whatever SCATTER/CHASE phase the
        wave clock is in *now*, not the mode it left (G9). Pinned
        policy: a respawning ghost is never frightened, even if the
        frightened overlay is still running at that moment (documented
        choice, same spirit as the Pinky-quirk decision in
        REFERENCE.md §4.4).
        """
        if self.mode is not GhostMode.EATEN:
            return
        if self.respawn_ticks_remaining is None:
            if self.cell == self.home_corner:
                self.respawn_ticks_remaining = respawn_delay_ticks
            return
        if self.respawn_ticks_remaining > 0:
            self.respawn_ticks_remaining -= 1
        if self.respawn_ticks_remaining == 0:
            self.mode = wave_mode
            self.respawn_ticks_remaining = None


# How far beyond each corner the scatter target sits. Any positive
# margin works (the point only has to be unreachable and "pull" toward
# the corner); a few tiles keeps the patrol loop hugging that quadrant.
SCATTER_MARGIN = 4


def _outside_target(corner: Cell, center: Cell) -> Cell:
    """A point ``SCATTER_MARGIN`` tiles beyond ``corner``, away from center.

    Extrapolating outward from the 4-corner centroid gives an
    off-the-maze tile diagonally past the corner, robust to a corner
    that was nudged inward by ``MazeAdapter`` (a sealed literal corner).
    The greedy rule can never arrive there, so the ghost orbits the
    corner region instead of the corner cell.
    """
    dx = 1 if corner[0] >= center[0] else -1
    dy = 1 if corner[1] >= center[1] else -1
    return (corner[0] + dx * SCATTER_MARGIN, corner[1] + dy * SCATTER_MARGIN)


def create_ghosts(corners: list[Cell]) -> list[Ghost]:
    """Build the four ghosts on their classic corners (subject VI.1).

    ``corners`` must be in ``MazeAdapter.corners()`` order: top-left,
    top-right, bottom-left, bottom-right. Arcade corner assignment:
    Blinky top-right, Pinky top-left, Inky bottom-right, Clyde
    bottom-left. Initial directions face inward horizontally -- always
    physically open on a wheel maze, whose braided corners keep both
    non-border sides carved.

    Each ghost's SCATTER target is set to a tile just *outside* the maze
    beyond its corner (``_outside_target``) so it patrols its quadrant
    rather than jittering on its spawn cell; ``home_corner`` stays the
    real spawn/respawn cell used by EATEN eyes.
    """
    top_left, top_right, bottom_left, bottom_right = corners
    cx = sum(c[0] for c in corners) // len(corners)
    cy = sum(c[1] for c in corners) // len(corners)
    center = (cx, cy)
    return [
        Ghost(
            GhostPersonality.BLINKY, top_right, Direction.WEST, top_right,
            scatter_target=_outside_target(top_right, center),
        ),
        Ghost(
            GhostPersonality.PINKY, top_left, Direction.EAST, top_left,
            scatter_target=_outside_target(top_left, center),
        ),
        Ghost(
            GhostPersonality.INKY, bottom_right, Direction.WEST, bottom_right,
            scatter_target=_outside_target(bottom_right, center),
        ),
        Ghost(
            GhostPersonality.CLYDE, bottom_left, Direction.EAST, bottom_left,
            scatter_target=_outside_target(bottom_left, center),
        ),
    ]


def mode_speed_multiplier(ghost: Ghost) -> float:
    """This ghost's speed as a multiple of its normal rate.

    Frightened ghosts move at half speed (REFERENCE.md §4.6 gives the
    arcade 50-60%; this project pins 50%), so a super-pacgum always makes
    them easier to catch. EATEN "eyes" are traditionally not slowed but
    hurried, returning at double rate. Every other mode runs normally.
    """
    if ghost.mode is GhostMode.FRIGHTENED:
        return 0.5
    if ghost.mode is GhostMode.EATEN:
        return 2.0
    return 1.0
