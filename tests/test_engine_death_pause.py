"""The death pause that lets the dying animation play (Milestone 5 UI).

A fatal hit normally respawns on the same tick. With
``death_pause_ticks`` set (the UI does; tests default it to 0 so every
other scenario keeps the immediate behaviour), the whole simulation
freezes for that many ticks first -- nothing moves, no timer runs, no
collision resolves -- and the respawn lands on the tick the pause ends.
That is what stops ghosts racing across the screen while Pac-Man dies.
"""

from pacman.ai.ghost import Ghost, GhostMode, GhostPersonality
from pacman.game.engine import GameStatus, update_game_state
from pacman.maze.adapter import Direction
from tests.engine_helpers import make_state, make_test_config
from tests.mazes import CORRIDOR_1x5

CORRIDOR_SPAWNS = [(0, 0), (4, 0), (0, 0), (4, 0)]
PAUSE = 8


def _fatal_state(pause: int, lives: int = 3):  # type: ignore[no-untyped-def]
    """A head-on hit about to happen, with ``pause`` death ticks."""
    ghost = Ghost(GhostPersonality.BLINKY, (2, 0), Direction.WEST, (4, 0),
                  mode=GhostMode.CHASE)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS, config=make_test_config(lives=lives),
    )
    state.death_pause_ticks = pause
    state.player_direction = Direction.EAST
    return state


def test_zero_pause_keeps_the_immediate_respawn() -> None:
    """The default every other test relies on: no pause, respawn now."""
    state = _fatal_state(pause=0)
    update_game_state(state)
    assert state.dying_ticks == 0
    assert state.player_cell == state.level_data.player_spawn


def test_death_pause_defers_the_respawn() -> None:
    state = _fatal_state(PAUSE)
    update_game_state(state)  # the fatal tick
    assert state.lives == 2  # the life is taken immediately
    assert state.dying_ticks == PAUSE  # ...but the pause starts
    assert state.player_cell != state.level_data.player_spawn


def test_simulation_is_frozen_while_dying() -> None:
    """No movement, no timers, no tick advance during the animation."""
    state = _fatal_state(PAUSE)
    update_game_state(state)
    frozen_tick = state.tick_count
    frozen_clock = state.level_ticks_remaining
    where = state.player_cell
    for _ in range(PAUSE - 1):
        update_game_state(state)
    assert state.tick_count == frozen_tick
    assert state.level_ticks_remaining == frozen_clock
    assert state.player_cell == where
    assert state.dying_ticks == 1  # one tick of pause left


def test_respawn_lands_on_the_tick_the_pause_ends() -> None:
    state = _fatal_state(PAUSE)
    update_game_state(state)
    for _ in range(PAUSE):
        update_game_state(state)
    assert state.dying_ticks == 0
    assert state.player_cell == state.level_data.player_spawn
    assert state.status is GameStatus.RUNNING
    # ...and play resumes on the next tick.
    before = state.tick_count
    update_game_state(state)
    assert state.tick_count == before + 1


def test_catch_holds_still_before_the_dying_animation() -> None:
    """Two beats: a caught hold (Pac-Man normal, ghosts on screen), then
    the animation. ``is_caught_hold`` splits the frozen pause so the UI
    can show each beat."""
    ghost = Ghost(GhostPersonality.BLINKY, (2, 0), Direction.WEST, (4, 0),
                  mode=GhostMode.CHASE)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS,
    )
    state.caught_pause_ticks = 5
    state.death_pause_ticks = 15   # 5 hold + 10 animation
    state.player_direction = Direction.EAST
    update_game_state(state)       # the fatal tick
    assert state.death_anim_ticks == 10

    phases = []
    for _ in range(state.death_pause_ticks):
        phases.append(state.is_caught_hold)
        update_game_state(state)
    assert phases[:5] == [True] * 5       # hold first
    assert phases[5:] == [False] * 10     # then the animation
    assert state.dying_ticks == 0
    assert state.player_cell == state.level_data.player_spawn


def test_zero_caught_pause_is_all_animation() -> None:
    """The tests' default: no hold, the whole pause animates (old
    behaviour), so is_caught_hold is never True."""
    state = _fatal_state(PAUSE)  # caught_pause_ticks defaults to 0
    update_game_state(state)
    assert state.death_anim_ticks == PAUSE
    seen_hold = False
    for _ in range(PAUSE):
        seen_hold = seen_hold or state.is_caught_hold
        update_game_state(state)
    assert not seen_hold


def test_last_life_skips_the_pause_and_ends_the_game() -> None:
    """Game over is immediate -- there is nothing to respawn into."""
    state = _fatal_state(PAUSE, lives=1)
    update_game_state(state)
    assert state.status is GameStatus.GAME_OVER
    assert state.dying_ticks == 0


def test_pellets_survive_the_death_pause() -> None:
    """Playbook §6 rider: only entities reset, eaten pacgums stay eaten."""
    state = _fatal_state(PAUSE)
    pellets = set(state.pacgum_cells)
    update_game_state(state)
    for _ in range(PAUSE):
        update_game_state(state)
    assert state.pacgum_cells == pellets


# -- Eating a ghost: the arcade's beat on the catch ---------------------

def _catch_state(pause: int):  # type: ignore[no-untyped-def]
    """A frightened ghost about to be eaten, with ``pause`` eat ticks."""
    ghost = Ghost(GhostPersonality.BLINKY, (2, 0), Direction.WEST, (4, 0),
                  mode=GhostMode.FRIGHTENED)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS,
        config=make_test_config(points_per_ghost=200),
    )
    state.eat_pause_ticks = pause
    state.player_direction = Direction.EAST
    return state


def test_zero_eat_pause_keeps_play_uninterrupted() -> None:
    """The default the rest of the suite relies on."""
    state = _catch_state(pause=0)
    update_game_state(state)
    assert state.score == 200
    assert state.eaten_ticks == 0


def test_eating_a_ghost_freezes_play_and_records_the_value() -> None:
    state = _catch_state(PAUSE)
    update_game_state(state)
    assert state.score == 200  # scored immediately
    assert state.eaten_ticks == PAUSE
    assert state.last_eat_score == 200  # what the UI shows...
    assert state.last_eat_cell == (1, 0)  # ...and where

    frozen = state.tick_count
    for _ in range(PAUSE - 1):
        update_game_state(state)
    assert state.tick_count == frozen  # nothing moved


def test_play_resumes_where_it_left_off_after_the_catch() -> None:
    """Unlike a death, nothing is sent back to spawn."""
    state = _catch_state(PAUSE)
    update_game_state(state)
    where = state.player_cell
    for _ in range(PAUSE):
        update_game_state(state)
    assert state.eaten_ticks == 0
    assert state.player_cell == where  # no respawn
    before = state.tick_count
    update_game_state(state)
    assert state.tick_count == before + 1
