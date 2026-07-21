"""Shared scaffolding for the Milestone 4 engine test suites.

``make_state`` places a fully scripted ``GameState`` on a hand-built
fixture maze: the caller controls player spawn, ghosts, and the pellet
layer exactly (default: empty -- a bare stage), so every playbook
matrix row can set up its precise geometry. ``make_test_config``
builds a valid Config without touching the filesystem, with the
score/timer knobs overridable per test.
"""

from random import Random

from pacman.ai.ghost import Cell, Ghost, GhostMode
from pacman.config.loader import Config, LevelConfig
from pacman.game.engine import GameState, LevelData
from tests.mazes import make_adapter


def ghost_mode(ghost: Ghost) -> GhostMode:
    """Return a ghost's mode as a plain GhostMode.

    Reading through a function widens mypy's literal narrowing, so a
    test can assert successive *distinct* modes on the same ghost
    (e.g. EATEN then, after a tick, SCATTER) under ``mypy --strict``'s
    strict-equality without a false "non-overlapping identity" error.
    """
    return ghost.mode


def make_test_config(
    points_per_pacgum: int = 10,
    points_per_super_pacgum: int = 50,
    points_per_ghost: int = 200,
    lives: int = 3,
    level_max_time: int = 90,
    seed: int = 42,
    level: list[LevelConfig] | None = None,
    highscore_filename: str = "highscores.json",
) -> Config:
    """A valid in-memory Config with per-test overridable knobs."""
    return Config(
        highscore_filename=highscore_filename,
        level=level if level is not None else [LevelConfig(15, 15)],
        lives=lives,
        pacgum=42,
        points_per_pacgum=points_per_pacgum,
        points_per_super_pacgum=points_per_super_pacgum,
        points_per_ghost=points_per_ghost,
        seed=seed,
        level_max_time=level_max_time,
    )


def make_state(
    grid: list[list[int]],
    player: Cell,
    ghosts: list[Ghost] | None = None,
    pacgums: set[Cell] | None = None,
    supers: set[Cell] | None = None,
    ghost_spawns: list[Cell] | None = None,
    config: Config | None = None,
    rng_seed: int = 1,
) -> GameState:
    """A scripted GameState on a hand-authored fixture grid.

    Defaults to an empty stage: no ghosts, no pellets -- each test adds
    exactly the entities its scenario needs. ``ghost_spawns`` (four
    cells, default four copies of the player spawn) only matters to
    the life-loss reset, which recreates the full four-ghost pack on
    them. The RNG is seeded so frightened wandering inside a scenario
    is reproducible (playbook §1.1).
    """
    adapter = make_adapter(grid)
    spawns = ghost_spawns if ghost_spawns is not None else [player] * 4
    level_data = LevelData(
        player_spawn=player,
        ghost_spawns=spawns,
        pacgum_cells=pacgums if pacgums is not None else set(),
        super_pacgum_cells=supers if supers is not None else set(),
    )
    resolved_config = config if config is not None else make_test_config()
    state = GameState(
        adapter=adapter,
        level_data=level_data,
        config=resolved_config,
        lives=resolved_config.lives,
        score=0,
        rng=Random(rng_seed),
    )
    state.ghosts = ghosts if ghosts is not None else []
    return state
