"""Whole-game progression across levels (PLAN.md Milestone 4.3).

The session sits between the entry point / UI and the per-level engine:
it owns the level plan (subject VI.7: at least MINIMUM_LEVELS levels),
builds one ``GameState`` per level, and carries score and remaining
lives across the boundary. Seeding policy (subject VI.1): level 1 uses
the configured seed (reproducible, e.g. 42); every later level's maze
seed is drawn from ONE session RNG seeded with the config seed --
levels visibly differ, yet the same config replays the same game,
which is exactly what the end-to-end determinism test
(TESTING_PLAYBOOK.md §7.2) demands. No wall-clock, no global RNG.
"""

import logging
from enum import Enum, auto
from random import Random

from pacman.config.loader import Config, LevelConfig
from pacman.game.engine import (
    GameState,
    GameStatus,
    create_game_state,
    update_game_state,
)
from pacman.maze.adapter import MazeAdapter, MazeAdapterError

logger = logging.getLogger(__name__)

MINIMUM_LEVELS = 10
_MAX_SEED = 2 ** 31 - 1
_GENERATION_ATTEMPTS = 3


class SessionStatus(Enum):
    """The application-level outcome of a whole game run.

    RUNNING while any level is in play; VICTORY when the last level is
    won (subject VI.7: all levels completed); GAME_OVER when lives run
    out. End states are final -- a new game means a new session.
    """

    RUNNING = auto()
    VICTORY = auto()
    GAME_OVER = auto()


def build_level_plan(config: Config) -> list[LevelConfig]:
    """The full level list, padded to MINIMUM_LEVELS by cycling.

    The config may define any number of levels (its loader guarantees
    at least one); the subject demands at least ten. Cycling the
    configured entries preserves whatever size variety the config
    author intended instead of flatly repeating the last one.
    """
    plan = list(config.level)
    while len(plan) < MINIMUM_LEVELS:
        plan.append(config.level[len(plan) % len(config.level)])
    return plan


class GameSession:
    """One full game: a sequence of levels sharing score and lives.

    The UI drives it with ``buffer_input``-on-the-current-state plus
    one ``tick()`` per simulation step; the session promotes engine
    end states (LEVEL_WON / GAME_OVER) into level advancement or a
    final session status. ``advance_level`` doubles as the level-skip
    cheat (subject VI.5: "immediately win the current level").
    """

    def __init__(
        self,
        config: Config,
        ghost_speed: float = 1.0,
        player_speed: float = 1.0,
        death_pause_ticks: int = 0,
    ) -> None:
        """Build the level plan and enter level 1.

        An adversarial ``lives: 0`` config produces a state that is
        born GAME_OVER; the session mirrors it immediately rather
        than ticking a dead game. ``ghost_speed``/``player_speed``
        (both default 1.0, kept by the tests) are applied to every
        level; the UI passes a lower ``player_speed`` to make Pac-Man
        easier to control, and a lower ``ghost_speed`` for the classic
        nimble-player balance.
        """
        self.config = config
        self.ghost_speed = ghost_speed
        self.player_speed = player_speed
        self.death_pause_ticks = death_pause_ticks
        self._seed_rng = Random(config.seed)
        self.level_plan = build_level_plan(config)
        self.level_index = 0
        self.status = SessionStatus.RUNNING
        self.state: GameState = self._build_state(
            lives=config.lives, score=0,
        )
        if self.state.status is GameStatus.GAME_OVER:
            self.status = SessionStatus.GAME_OVER

    @property
    def level_number(self) -> int:
        """1-based level number for the HUD."""
        return self.level_index + 1

    @property
    def score(self) -> int:
        """The running score (lives in the current level's state)."""
        return self.state.score

    @property
    def lives(self) -> int:
        """Remaining lives (live in the current level's state)."""
        return self.state.lives

    def tick(self) -> None:
        """Advance the game one simulation tick, crossing level ends.

        A LEVEL_WON engine tick rolls straight into the next level (or
        VICTORY after the last); GAME_OVER freezes the session with
        the final state kept around for the score display.
        """
        if self.status is not SessionStatus.RUNNING:
            return
        update_game_state(self.state)
        if self.state.status is GameStatus.GAME_OVER:
            self.status = SessionStatus.GAME_OVER
        elif self.state.status is GameStatus.LEVEL_WON:
            self.advance_level()

    def advance_level(self) -> None:
        """Move to the next level carrying score/lives -- or VICTORY.

        Also the level-skip cheat's entry point. Cheat flags persist
        across the boundary (a reviewer toggling invincibility should
        not lose it at every level change).
        """
        if self.status is not SessionStatus.RUNNING:
            return
        self.level_index += 1
        if self.level_index >= len(self.level_plan):
            self.status = SessionStatus.VICTORY
            return
        carried_cheats = self.state.cheats
        self.state = self._build_state(
            lives=self.state.lives, score=self.state.score,
        )
        self.state.cheats = carried_cheats

    def _build_state(self, lives: int, score: int) -> GameState:
        """Generate the current level's maze and wrap it in a GameState.

        Maze seed: the configured seed for level 1, else drawn from
        the session RNG. A generator failure is retried with freshly
        drawn seeds (robustness outranks level-1 reproducibility in
        the failure case -- subject IV: "no crash!"); if every attempt
        fails, the MazeAdapterError propagates for the entry point's
        single clean catch site.
        """
        level_config = self.level_plan[self.level_index]
        seed = (
            self.config.seed
            if self.level_index == 0
            else self._seed_rng.randint(1, _MAX_SEED)
        )
        adapter: MazeAdapter | None = None
        for attempt in range(_GENERATION_ATTEMPTS):
            try:
                candidate = MazeAdapter(
                    level_config.width, level_config.height, seed,
                )
                candidate.load_wheel_maze()
                adapter = candidate
                break
            except MazeAdapterError as exc:
                logger.warning(
                    "Maze generation failed for level %d (seed=%d): %s",
                    self.level_number, seed, exc,
                )
                if attempt == _GENERATION_ATTEMPTS - 1:
                    raise
                seed = self._seed_rng.randint(1, _MAX_SEED)
        assert adapter is not None  # the loop either set it or raised
        wander_rng = Random(self._seed_rng.randint(0, _MAX_SEED))
        return create_game_state(
            adapter, self.config, lives, score, wander_rng,
            ghost_speed=self.ghost_speed, player_speed=self.player_speed,
            death_pause_ticks=self.death_pause_ticks,
        )
