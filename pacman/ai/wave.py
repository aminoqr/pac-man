"""Global Scatter/Chase wave clock + Frightened overlay (Milestone 2.2).

REFERENCE.md §4.2: ghost behavior is driven by one global mode switching
on a fixed schedule measured in simulation ticks, never wall-clock time
(REFERENCE.md §2.4). Frightened is an overlay, not a phase: it pauses the
wave timer and resumes it from the exact pause point when it expires
(TESTING_PLAYBOOK.md G3-G6). The two module-level helpers push clock
events onto the ghosts so the engine (Milestone 4) has a one-call API and
the double-reversal mistake (flipping ghosts twice on one event) has no
room to happen.
"""

from enum import Enum, auto
from typing import Iterable

from pacman.ai.ghost import Ghost, GhostMode

DEFAULT_TICKS_PER_SECOND = 60
DEFAULT_FRIGHTENED_TICKS = 6 * DEFAULT_TICKS_PER_SECOND
DEFAULT_RESPAWN_DELAY_TICKS = 5 * DEFAULT_TICKS_PER_SECOND

WavePhase = tuple[GhostMode, int | None]


def classic_wave_table(
    ticks_per_second: int = DEFAULT_TICKS_PER_SECOND,
) -> list[WavePhase]:
    """The classic level-1 wave schedule (REFERENCE.md §4.2).

    7 s scatter, 20 s chase, 7 s scatter, 20 s chase, 5 s scatter,
    20 s chase, 5 s scatter, then chase forever. Tests pass
    ``ticks_per_second=1`` to keep tick counts human-readable; higher
    levels can tune their own tables per PLAN.md §2.2.
    """
    second = ticks_per_second
    return [
        (GhostMode.SCATTER, 7 * second),
        (GhostMode.CHASE, 20 * second),
        (GhostMode.SCATTER, 7 * second),
        (GhostMode.CHASE, 20 * second),
        (GhostMode.SCATTER, 5 * second),
        (GhostMode.CHASE, 20 * second),
        (GhostMode.SCATTER, 5 * second),
        (GhostMode.CHASE, None),
    ]


class WaveEvent(Enum):
    """What one ``WaveController.tick`` produced.

    MODE_FLIP: a scatter<->chase transition fired this tick (callers must
    reverse all wave-mode ghosts -- ``apply_wave_tick`` does).
    FRIGHTENED_ENDED: the frightened countdown just hit zero (ghosts
    resume the wave mode with NO reversal, TESTING_PLAYBOOK.md G6).
    """

    NONE = auto()
    MODE_FLIP = auto()
    FRIGHTENED_ENDED = auto()


class WaveController:
    """Owns the scatter/chase phase clock and the frightened countdown.

    Purely a clock: it never touches ghosts itself. Its ``tick`` reports
    events; ``apply_wave_tick`` translates them into ghost mode/direction
    changes.
    """

    def __init__(self, wave_table: list[WavePhase] | None = None) -> None:
        """Validate and adopt a wave table (default: classic at 60 tps).

        Table rules, enforced here because a malformed table is a
        programmer error, not player input: non-empty; phases only
        SCATTER or CHASE; every duration a positive tick count except
        the final phase, whose duration must be ``None`` (that mode then
        holds forever, so the clock can never run off the table's end).
        """
        if wave_table is None:
            table = classic_wave_table()
        else:
            table = list(wave_table)
        if not table:
            raise ValueError("wave table must not be empty")
        for mode, _duration in table:
            if mode not in (GhostMode.SCATTER, GhostMode.CHASE):
                raise ValueError("wave phases must be SCATTER or CHASE")
        for _mode, duration in table[:-1]:
            if not isinstance(duration, int) or duration <= 0:
                raise ValueError(
                    "every non-final wave duration must be a positive "
                    "tick count"
                )
        if table[-1][1] is not None:
            raise ValueError(
                "the final wave phase must have duration None "
                "(it holds forever)"
            )
        self._table = table
        self._phase_index = 0
        self._ticks_remaining: int | None = table[0][1]
        self._frightened_ticks = 0

    @property
    def wave_mode(self) -> GhostMode:
        """The SCATTER/CHASE phase per the wave clock, ignoring frightened.

        This is what EATEN ghosts rejoin (G9) and what frightened ghosts
        resume when the overlay expires (G6).
        """
        return self._table[self._phase_index][0]

    @property
    def frightened_active(self) -> bool:
        """True while the frightened countdown is running."""
        return self._frightened_ticks > 0

    @property
    def current_mode(self) -> GhostMode:
        """FRIGHTENED while the overlay runs, else the wave mode."""
        if self.frightened_active:
            return GhostMode.FRIGHTENED
        return self.wave_mode

    def start_frightened(self, duration_ticks: int) -> None:
        """(Re)start the frightened countdown at full.

        TESTING_PLAYBOOK.md G5: a super-pacgum eaten mid-frightened
        restarts the countdown at its full duration, it does not stack.
        The wave clock stays paused throughout (G3/G4).
        """
        if duration_ticks <= 0:
            raise ValueError("frightened duration must be positive")
        self._frightened_ticks = duration_ticks

    def tick(self) -> WaveEvent:
        """Advance the clock exactly one tick and report what happened.

        While frightened is active only its countdown advances -- the
        wave phase timer is frozen at its pause point (G3/G4) and resumes
        untouched afterwards (G6's tick-exact arithmetic). In the final
        (duration ``None``) phase the clock idles forever.
        """
        if self._frightened_ticks > 0:
            self._frightened_ticks -= 1
            if self._frightened_ticks == 0:
                return WaveEvent.FRIGHTENED_ENDED
            return WaveEvent.NONE
        if self._ticks_remaining is None:
            return WaveEvent.NONE
        self._ticks_remaining -= 1
        if self._ticks_remaining > 0:
            return WaveEvent.NONE
        self._phase_index += 1
        self._ticks_remaining = self._table[self._phase_index][1]
        return WaveEvent.MODE_FLIP


def trigger_frightened(
    wave: WaveController,
    ghosts: Iterable[Ghost],
    duration_ticks: int = DEFAULT_FRIGHTENED_TICKS,
) -> None:
    """Super-pacgum eaten: pause the wave and frighten every ghost.

    Each non-EATEN ghost flips to FRIGHTENED and reverses
    (``Ghost.enter_frightened`` -- G3/G4); EATEN ghosts are immune
    (G10). The reversal lives inside the per-ghost transition, so this
    helper must NOT also reverse -- that would double-flip.
    """
    wave.start_frightened(duration_ticks)
    for ghost in ghosts:
        ghost.enter_frightened()


def apply_wave_tick(
    wave: WaveController, ghosts: Iterable[Ghost],
) -> WaveEvent:
    """Tick the wave clock and push its effects onto the ghosts.

    MODE_FLIP: every ghost currently in a wave mode (SCATTER/CHASE)
    adopts the new mode and reverses direction -- the classic
    mode-change reversal signal (G1/G2). EATEN ghosts are exempt:
    returning eyes don't flip; they rejoin via
    ``Ghost.tick_eaten_state``. FRIGHTENED_ENDED: frightened ghosts
    resume the wave mode with NO reversal (G6).
    """
    event = wave.tick()
    if event is WaveEvent.MODE_FLIP:
        for ghost in ghosts:
            if ghost.mode in (GhostMode.SCATTER, GhostMode.CHASE):
                ghost.mode = wave.wave_mode
                ghost.direction = ghost.direction.opposite
    elif event is WaveEvent.FRIGHTENED_ENDED:
        for ghost in ghosts:
            if ghost.mode is GhostMode.FRIGHTENED:
                ghost.mode = wave.wave_mode
    return event
