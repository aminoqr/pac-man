"""Milestone 4 acceptance: a level is genuinely winnable through play.

Where test_engine_progression shortcuts the win by shrinking the pellet
set, this drives the player tile-by-tile across a real wheel maze until
every last pacgum and super-pacgum is eaten -- proving the win
condition is reachable by movement, not just by fiat. The "player" is a
BFS auto-pilot (ghosts frozen + invincible, so the run is a pure
traversal): each tick it steps toward the nearest remaining pellet.
This is exactly the "use cheat mode to verify quickly" path the
acceptance criterion names, made deterministic and headless.
"""

from pacman.config.loader import LevelConfig
from pacman.game.engine import (
    ENGINE_TICKS_PER_SECOND,
    GameState,
    GameStatus,
)
from pacman.game.session import GameSession, SessionStatus
from pacman.maze.adapter import Direction
from pacman.pathfinding.search import bfs_path, distance_map
from tests.engine_helpers import make_test_config


def _nearest_pellet_first_step(state: GameState) -> Direction | None:
    """Direction of the first hop toward the closest remaining pellet.

    One distance flood from the player picks the nearest pellet; one
    BFS to it yields the first step. Returns None only if no pellet is
    reachable (never on a braided maze -- one connected component).
    """
    pellets = state.pacgum_cells | state.super_pacgum_cells
    distances = distance_map(state.adapter, state.player_cell)
    reachable = [(distances[p], p) for p in pellets if p in distances]
    if not reachable:
        return None
    _, nearest = min(reachable)
    path = bfs_path(state.adapter, state.player_cell, nearest).path
    if path is None or len(path) < 2:
        return None
    dx = path[1][0] - state.player_cell[0]
    dy = path[1][1] - state.player_cell[1]
    return next(d for d in Direction if (d.dx, d.dy) == (dx, dy))


def test_a_full_level_is_winnable_by_eating_every_pellet() -> None:
    """Auto-pilot the player until the level rolls over to the next."""
    config = make_test_config(level=[LevelConfig(14, 10)])
    session = GameSession(config)
    session.state.cheats.ghosts_frozen = True
    session.state.cheats.invincible = True
    total = len(session.state.pacgum_cells) + len(
        session.state.super_pacgum_cells
    )
    assert total > 0

    # Greedy nearest-pellet traversal needs far fewer than this.
    for _ in range(total * 60):
        state = session.state
        if state.level_ticks_remaining < 5 * ENGINE_TICKS_PER_SECOND:
            state.level_ticks_remaining = 90 * ENGINE_TICKS_PER_SECOND
        step = _nearest_pellet_first_step(state)
        if step is not None:
            state.buffer_input(step)
        session.tick()
        if session.level_number > 1 or (
            session.status is not SessionStatus.RUNNING
        ):
            break

    # Rolling over to level 2 proves level 1 was won by eating out.
    assert session.level_number > 1
    assert session.status is SessionStatus.RUNNING
    assert session.state.status is not GameStatus.GAME_OVER
