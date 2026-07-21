"""Milestone 4.1/4.3: timers, pause, cheats, and level progression.

The out-of-time policy (pinned: lose a life, full entity+timer reset),
pause as a no-op tick, the five subject VI.5 cheats, and the session
layer: a >=10-level plan, fixed seed for level 1 with drawn seeds
after, score/lives carried across levels, VICTORY after the last one.
Session tests run on real wheel mazes; timer/cheat mechanics run on
scripted corridor stages.
"""

from pacman.ai.ghost import Ghost, GhostMode, GhostPersonality
from pacman.config.loader import LevelConfig
from pacman.game.engine import (
    ENGINE_TICKS_PER_SECOND,
    GameStatus,
    update_game_state,
)
from pacman.game.session import (
    MINIMUM_LEVELS,
    GameSession,
    SessionStatus,
    build_level_plan,
)
from pacman.maze.adapter import Direction
from tests.engine_helpers import ghost_mode, make_state, make_test_config
from tests.mazes import CORRIDOR_1x5


def test_level_timer_expiry_costs_a_life_and_resets() -> None:
    """Pinned out-of-time policy: like a ghost hit -- life lost,
    entities and countdown reset, pellets kept."""
    config = make_test_config(level_max_time=1)
    state = make_state(CORRIDOR_1x5, player=(1, 0), config=config)
    state.player_direction = Direction.EAST
    for _ in range(ENGINE_TICKS_PER_SECOND - 1):
        update_game_state(state)
    assert state.lives == 3  # one tick left on the clock
    update_game_state(state)  # the countdown hits zero
    assert state.lives == 2
    assert state.player_cell == (1, 0)  # respawned
    assert state.level_ticks_remaining == ENGINE_TICKS_PER_SECOND


def test_timer_expiry_on_the_last_life_is_game_over() -> None:
    config = make_test_config(level_max_time=1, lives=1)
    state = make_state(CORRIDOR_1x5, player=(1, 0), config=config)
    for _ in range(ENGINE_TICKS_PER_SECOND):
        update_game_state(state)
    assert state.status is GameStatus.GAME_OVER
    assert state.lives == 0


def test_seconds_remaining_rounds_up_for_the_hud() -> None:
    config = make_test_config(level_max_time=2)
    state = make_state(CORRIDOR_1x5, player=(1, 0), config=config)
    assert state.seconds_remaining == 2  # full: 2 seconds' worth of ticks
    update_game_state(state)
    # One tick gone; a fraction of a second remains, so it rounds up to 2.
    assert state.seconds_remaining == 2
    # Consume down to exactly one second's worth of ticks left.
    while state.level_ticks_remaining > ENGINE_TICKS_PER_SECOND:
        update_game_state(state)
    assert state.seconds_remaining == 1


def test_pause_freezes_every_clock_and_resume_continues() -> None:
    ghost = Ghost(
        GhostPersonality.BLINKY, (4, 0), Direction.WEST, (4, 0),
        mode=GhostMode.CHASE,
    )
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST
    state.toggle_pause()
    for _ in range(5):
        update_game_state(state)
    assert state.tick_count == 0  # nothing ticked
    assert state.player_cell == (1, 0)
    assert ghost.cell == (4, 0)
    assert state.level_ticks_remaining == 90 * ENGINE_TICKS_PER_SECOND
    state.toggle_pause()
    update_game_state(state)
    assert state.tick_count == 1
    assert state.player_cell == (2, 0)


def test_eaten_ghost_full_cycle_home_wait_rejoin() -> None:
    """Subject VI.3 through the real pipeline: eyes travel home via the
    A* hop, park for the respawn delay, then rejoin the wave mode."""
    eyes = Ghost(
        GhostPersonality.BLINKY, (0, 0), Direction.EAST, (4, 0),
        mode=GhostMode.EATEN,
    )
    state = make_state(CORRIDOR_1x5, player=(0, 0), ghosts=[eyes])
    for _ in range(4):
        update_game_state(state)
    assert eyes.cell == (4, 0)  # 4 hops home, never slowed
    assert ghost_mode(eyes) is GhostMode.EATEN
    # Tick 5 arms the countdown; it reaches zero 50 ticks later, so
    # the rejoin lands exactly on tick 55 -- EATEN through tick 54.
    for _ in range(5 * ENGINE_TICKS_PER_SECOND):
        update_game_state(state)
    assert ghost_mode(eyes) is GhostMode.EATEN  # tick 54: still parked
    update_game_state(state)
    assert ghost_mode(eyes) is GhostMode.SCATTER  # the wave clock phase 0
    assert eyes.cell == (3, 0)  # rejoined and moving again already


def test_ghost_freeze_cheat_stops_all_ghosts() -> None:
    session = GameSession(make_test_config())
    session.state.cheats.ghosts_frozen = True
    parked = [ghost.cell for ghost in session.state.ghosts]
    for _ in range(5):
        session.tick()
    assert [ghost.cell for ghost in session.state.ghosts] == parked
    assert session.lives == 3


def test_speed_boost_cheat_halves_hostile_ghosts() -> None:
    ghost = Ghost(
        GhostPersonality.BLINKY, (0, 0), Direction.EAST, (0, 0),
        mode=GhostMode.CHASE,
    )
    state = make_state(
        CORRIDOR_1x5, player=(4, 0), ghosts=[ghost], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST  # parked at the east wall
    state.cheats.speed_boost = True
    state.cheats.invincible = True  # isolate cadence from collisions
    for _ in range(4):
        update_game_state(state)
    assert ghost.cell == (2, 0)  # stepped on ticks 2 and 4 only


def test_add_life_cheat() -> None:
    state = make_state(CORRIDOR_1x5, player=(1, 0), pacgums={(0, 0)})
    state.add_life()
    assert state.lives == 4


def test_level_plan_pads_to_ten_by_cycling() -> None:
    sizes = [
        LevelConfig(14, 10), LevelConfig(15, 15), LevelConfig(16, 12),
    ]
    plan = build_level_plan(make_test_config(level=sizes))
    assert len(plan) == MINIMUM_LEVELS
    assert plan == [sizes[index % 3] for index in range(MINIMUM_LEVELS)]
    # A config already offering more than ten levels keeps them all.
    twelve = [LevelConfig(14, 10)] * 12
    assert len(build_level_plan(make_test_config(level=twelve))) == 12


def test_level_one_maze_is_reproducible_from_the_config_seed() -> None:
    config = make_test_config()
    first = GameSession(config)
    second = GameSession(config)
    assert (
        first.state.adapter.render_ascii()
        == second.state.adapter.render_ascii()
    )


def test_later_levels_differ_but_replay_identically() -> None:
    """Subject VI.1: level 2 is 'random' (differs from level 1) yet the
    same config replays the same game (playbook §7.2)."""
    first = GameSession(make_test_config())
    second = GameSession(make_test_config())
    level_one_maze = first.state.adapter.render_ascii()
    first.advance_level()
    second.advance_level()
    assert first.state.adapter.render_ascii() != level_one_maze
    assert (
        first.state.adapter.render_ascii()
        == second.state.adapter.render_ascii()
    )


def test_winning_a_level_advances_and_carries_score_and_lives() -> None:
    session = GameSession(make_test_config())
    state = session.state
    state.score = 77
    state.lives = 2
    # Shrink the remaining pellets to one adjacent cell and eat it.
    target_direction = state.adapter.get_valid_moves(*state.player_cell)[0]
    target_cell = (
        state.player_cell[0] + target_direction.dx,
        state.player_cell[1] + target_direction.dy,
    )
    state.pacgum_cells = {target_cell}
    state.super_pacgum_cells = set()
    state.buffer_input(target_direction)
    session.tick()
    assert session.level_number == 2
    assert session.status is SessionStatus.RUNNING
    assert session.score == 87  # 77 + the winning pacgum
    assert session.lives == 2


def test_skip_cheat_reaches_victory_and_keeps_score() -> None:
    session = GameSession(make_test_config())
    session.state.score = 123
    for _ in range(MINIMUM_LEVELS):
        session.advance_level()
    assert session.status is SessionStatus.VICTORY
    assert session.score == 123  # final state kept for the score screen


def test_cheat_flags_persist_across_level_changes() -> None:
    session = GameSession(make_test_config())
    session.state.cheats.invincible = True
    session.advance_level()
    assert session.state.cheats.invincible


def test_zero_lives_config_is_born_game_over() -> None:
    session = GameSession(make_test_config(lives=0))
    assert session.status is SessionStatus.GAME_OVER
    session.tick()  # inert, no crash
    assert session.status is SessionStatus.GAME_OVER
