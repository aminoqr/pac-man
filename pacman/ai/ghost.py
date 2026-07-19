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

    ``home_corner`` triples as scatter target, EATEN destination, and
    respawn point (PLAN.md §2.3: scatter targets are the spawn corners).
    ``respawn_ticks_remaining`` is ``None`` except while EATEN and
    parked at ``home_corner`` waiting to rejoin play; see
    ``tick_eaten_state``.
    """

    personality: GhostPersonality
    cell: Cell
    direction: Direction
    home_corner: Cell
    mode: GhostMode = GhostMode.SCATTER
    respawn_ticks_remaining: int | None = None

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
        self.direction = self.direction.opposite

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

        Call once per tick while EATEN; movement toward ``home_corner``
        itself is the caller's job via the same shared intersection rule
        as everyone else (targeting.py already returns ``home_corner``
        for EATEN ghosts). On arrival the respawn countdown starts; it
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


def create_ghosts(corners: list[Cell]) -> list[Ghost]:
    """Build the four ghosts on their classic corners (subject VI.1).

    ``corners`` must be in ``MazeAdapter.corners()`` order: top-left,
    top-right, bottom-left, bottom-right. Arcade corner assignment:
    Blinky top-right, Pinky top-left, Inky bottom-right, Clyde
    bottom-left. Initial directions face inward horizontally -- always
    physically open on a wheel maze, whose braided corners keep both
    non-border sides carved.
    """
    top_left, top_right, bottom_left, bottom_right = corners
    return [
        Ghost(GhostPersonality.BLINKY, top_right, Direction.WEST, top_right),
        Ghost(GhostPersonality.PINKY, top_left, Direction.EAST, top_left),
        Ghost(
            GhostPersonality.INKY, bottom_right, Direction.WEST, bottom_right,
        ),
        Ghost(
            GhostPersonality.CLYDE, bottom_left, Direction.EAST, bottom_left,
        ),
    ]


def ghost_moves_on_tick(ghost: Ghost, tick_index: int) -> bool:
    """Whether this ghost advances a tile on the given engine tick.

    Frightened ghosts move at half speed (REFERENCE.md §4.6 gives the
    arcade 50-60%; this project pins 50%): they skip every odd tick.
    All other modes move every tick -- including EATEN, whose returning
    "eyes" are traditionally not slowed.
    """
    if ghost.mode is not GhostMode.FRIGHTENED:
        return True
    return tick_index % 2 == 0
