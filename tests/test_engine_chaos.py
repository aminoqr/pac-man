"""Milestone 4 acceptance: determinism end-to-end and chaos fuzzing.

TESTING_PLAYBOOK.md §7.2: same config + same scripted input tape =>
identical final state across two runs -- the one test that transitively
guards the no-wall-clock / no-global-RNG / tick-purity contracts.
§7.4: thousands of seeded random-input ticks (with pauses and cheat
toggles thrown in) asserting the standing invariants: no exception,
monotonic score (subject VI.6), lives within bounds, everyone on a
walkable tile. Plus the engine-boot half of the hostile-config sweep
(the loader half lives in test_config.py).
"""

from random import Random

from pacman.config.loader import LevelConfig
from pacman.game.session import GameSession, SessionStatus
from pacman.maze.adapter import Direction
from tests.engine_helpers import make_test_config

Fingerprint = tuple[
    int, int, int, tuple[int, int], str,
    tuple[tuple[int, int, str], ...],
]


def _run_scripted(ticks: int, tape_seed: int) -> list[Fingerprint]:
    """Drive a session with a seeded input tape; return per-tick states."""
    session = GameSession(make_test_config())
    tape_rng = Random(tape_seed)
    directions = list(Direction)
    trace: list[Fingerprint] = []
    for _ in range(ticks):
        if tape_rng.random() < 0.4:
            session.state.buffer_input(tape_rng.choice(directions))
        session.tick()
        trace.append((
            session.state.tick_count,
            session.score,
            session.lives,
            session.state.player_cell,
            session.status.name,
            tuple(
                (ghost.cell[0], ghost.cell[1], ghost.mode.name)
                for ghost in session.state.ghosts
            ),
        ))
    return trace


def test_same_config_and_tape_replay_byte_identically() -> None:
    assert _run_scripted(600, tape_seed=99) == _run_scripted(
        600, tape_seed=99,
    )


def test_fuzz_ten_thousand_ticks_holds_all_invariants() -> None:
    """Every tick exercises a LIVE engine: a finished session (random
    play dies fast) is replaced by a fresh one mid-stream, so the fuzz
    also covers many full session lifecycles."""
    session = GameSession(make_test_config())
    fuzz = Random(1234)
    directions = list(Direction)
    granted_lives = 0
    last_score = 0
    sessions_finished = 0
    for _ in range(10_000):
        if session.status is not SessionStatus.RUNNING:
            sessions_finished += 1
            session = GameSession(make_test_config())
            granted_lives = 0
            last_score = 0  # score monotonicity is per session
        roll = fuzz.random()
        if roll < 0.30:
            session.state.buffer_input(fuzz.choice(directions))
        elif roll < 0.31:
            session.state.toggle_pause()
        elif roll < 0.315:
            session.state.cheats.invincible = fuzz.random() < 0.5
        elif roll < 0.32:
            session.state.cheats.ghosts_frozen = fuzz.random() < 0.5
        elif roll < 0.325:
            session.state.cheats.speed_boost = fuzz.random() < 0.5
        elif roll < 0.327:
            session.state.add_life()
            granted_lives += 1
        session.tick()

        state = session.state
        assert state.score >= last_score  # subject VI.6: never decreases
        last_score = state.score
        assert 0 <= state.lives <= 3 + granted_lives
        assert state.adapter.is_walkable(*state.player_cell)
        for ghost in state.ghosts:
            assert state.adapter.is_walkable(*ghost.cell)
    # The stream really cycled through whole games, not one dead one.
    assert sessions_finished >= 1


def test_hostile_config_values_boot_and_run_cleanly() -> None:
    """Engine-boot half of the playbook §7.4 sweep: adversarial (but
    loader-shaped) configs must produce a running or cleanly-dead
    session, never a traceback. Tiny sizes ride the adapter's clamp."""
    hostile_configs = [
        make_test_config(lives=0),
        make_test_config(level=[LevelConfig(1, 1)]),
        make_test_config(level_max_time=1),
        make_test_config(
            points_per_pacgum=0, points_per_super_pacgum=0,
            points_per_ghost=0,
        ),
        make_test_config(level=[LevelConfig(1, 1)] * 25, lives=1),
    ]
    for config in hostile_configs:
        session = GameSession(config)
        for _ in range(50):
            session.state.buffer_input(Direction.EAST)
            session.tick()
        assert session.status in (
            SessionStatus.RUNNING, SessionStatus.GAME_OVER,
        )
