"""Milestone 2.2 unit tests: global mode transitions G1-G10.

Each test is one row of TESTING_PLAYBOOK.md §4.1. Wave tables use
``ticks_per_second=1`` so the classic 7/20/5-second schedule reads as
7/20/5 ticks and every countdown is hand-checkable.
"""

import pytest

from pacman.ai.ghost import (
    Ghost,
    GhostMode,
    GhostPersonality,
    create_ghosts,
    mode_speed_multiplier,
)
from pacman.ai.wave import (
    WaveController,
    WaveEvent,
    apply_wave_tick,
    classic_wave_table,
    trigger_frightened,
)
from pacman.maze.adapter import Direction


def two_ghosts() -> list[Ghost]:
    """A minimal pack: cells/corners are irrelevant to the wave clock."""
    return [
        Ghost(GhostPersonality.BLINKY, (5, 5), Direction.EAST, (9, 0)),
        Ghost(GhostPersonality.PINKY, (3, 3), Direction.NORTH, (0, 0)),
    ]


def test_classic_wave_table_shape() -> None:
    table = classic_wave_table(60)
    assert len(table) == 8
    assert table[0] == (GhostMode.SCATTER, 7 * 60)
    assert table[1] == (GhostMode.CHASE, 20 * 60)
    assert table[-1] == (GhostMode.CHASE, None)


def test_wave_table_validation_rejects_bad_tables() -> None:
    with pytest.raises(ValueError):
        WaveController([])
    with pytest.raises(ValueError):
        WaveController([(GhostMode.FRIGHTENED, None)])
    with pytest.raises(ValueError):
        WaveController([(GhostMode.SCATTER, 5), (GhostMode.CHASE, 3)])
    with pytest.raises(ValueError):
        WaveController([(GhostMode.SCATTER, 0), (GhostMode.CHASE, None)])


def test_g1_scatter_expiry_flips_to_chase_and_reverses_all() -> None:
    wave = WaveController(classic_wave_table(1))  # scatter lasts 7 ticks
    ghosts = two_ghosts()
    for _ in range(6):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE
    assert all(g.mode is GhostMode.SCATTER for g in ghosts)

    assert apply_wave_tick(wave, ghosts) is WaveEvent.MODE_FLIP
    assert wave.wave_mode is GhostMode.CHASE
    assert all(g.mode is GhostMode.CHASE for g in ghosts)
    # the mandatory side effect: every ghost reversed (G1)
    assert ghosts[0].direction is Direction.WEST
    assert ghosts[1].direction is Direction.SOUTH


def test_g2_chase_expiry_flips_back_to_scatter_and_reverses() -> None:
    wave = WaveController(classic_wave_table(1))
    ghosts = two_ghosts()
    for _ in range(7 + 20):
        apply_wave_tick(wave, ghosts)
    assert wave.wave_mode is GhostMode.SCATTER
    assert all(g.mode is GhostMode.SCATTER for g in ghosts)
    # two reversals cancel out: directions are back to the originals
    assert ghosts[0].direction is Direction.EAST
    assert ghosts[1].direction is Direction.NORTH


def test_g3_g4_super_pacgum_frightens_reverses_and_pauses() -> None:
    wave = WaveController(classic_wave_table(1))
    ghosts = two_ghosts()

    trigger_frightened(wave, ghosts, duration_ticks=6)

    assert wave.frightened_active
    assert wave.current_mode is GhostMode.FRIGHTENED
    assert wave.wave_mode is GhostMode.SCATTER  # paused, not consumed
    assert all(g.mode is GhostMode.FRIGHTENED for g in ghosts)
    # reversal on entry (G3/G4)
    assert ghosts[0].direction is Direction.WEST
    assert ghosts[1].direction is Direction.SOUTH


def test_g5_second_super_pacgum_restarts_the_countdown_at_full() -> None:
    wave = WaveController(classic_wave_table(1))
    ghosts = two_ghosts()
    trigger_frightened(wave, ghosts, duration_ticks=6)
    for _ in range(3):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE

    trigger_frightened(wave, ghosts, duration_ticks=6)  # restart at full

    for _ in range(5):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE
    assert apply_wave_tick(wave, ghosts) is WaveEvent.FRIGHTENED_ENDED


def test_g6_pause_resume_is_tick_exact_with_no_exit_reversal() -> None:
    """The subtle row: scatter runs 3 of its 7 ticks, frightened runs 6,
    and afterwards scatter must have exactly 4 ticks left. No reversal
    on frightened exit (classic behavior)."""
    wave = WaveController(classic_wave_table(1))
    ghosts = two_ghosts()
    for _ in range(3):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE

    trigger_frightened(wave, ghosts, duration_ticks=6)
    directions_during = [g.direction for g in ghosts]
    for _ in range(5):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE

    assert apply_wave_tick(wave, ghosts) is WaveEvent.FRIGHTENED_ENDED
    assert all(g.mode is GhostMode.SCATTER for g in ghosts)
    # G6: NO reversal when frightened expires
    assert [g.direction for g in ghosts] == directions_during

    # the wave resumed from its pause point: exactly 4 ticks remain
    for _ in range(3):
        assert apply_wave_tick(wave, ghosts) is WaveEvent.NONE
    assert apply_wave_tick(wave, ghosts) is WaveEvent.MODE_FLIP
    assert wave.wave_mode is GhostMode.CHASE


def test_g7_eating_one_ghost_leaves_the_others_frightened() -> None:
    wave = WaveController(classic_wave_table(1))
    ghosts = two_ghosts()
    trigger_frightened(wave, ghosts, duration_ticks=6)

    ghosts[0].enter_eaten()

    assert ghosts[0].mode is GhostMode.EATEN
    assert ghosts[1].mode is GhostMode.FRIGHTENED


def test_g8_eaten_ghost_waits_at_home_then_rejoins() -> None:
    ghost = two_ghosts()[0]
    ghost.enter_eaten()

    # still traveling: not at home, nothing happens
    ghost.tick_eaten_state(GhostMode.SCATTER, respawn_delay_ticks=3)
    assert ghost.respawn_ticks_remaining is None

    # arrival at the home corner starts the countdown
    ghost.cell = ghost.home_corner
    ghost.tick_eaten_state(GhostMode.SCATTER, respawn_delay_ticks=3)
    assert ghost.respawn_ticks_remaining == 3

    for _ in range(2):
        ghost.tick_eaten_state(GhostMode.SCATTER, respawn_delay_ticks=3)
        assert ghost.mode is GhostMode.EATEN

    ghost.tick_eaten_state(GhostMode.SCATTER, respawn_delay_ticks=3)
    assert ghost.mode is GhostMode.SCATTER
    assert ghost.respawn_ticks_remaining is None


def test_g9_eaten_ghost_rejoins_the_mode_active_now() -> None:
    """Eaten during frightened/scatter, but the wave flipped to chase
    while it traveled home: it must rejoin CHASE, not what it left."""
    ghost = two_ghosts()[0]
    ghost.enter_eaten()
    ghost.cell = ghost.home_corner
    ghost.tick_eaten_state(GhostMode.CHASE, respawn_delay_ticks=1)
    ghost.tick_eaten_state(GhostMode.CHASE, respawn_delay_ticks=1)
    assert ghost.mode is GhostMode.CHASE


def test_g10_super_pacgum_does_not_refrighten_an_eaten_ghost() -> None:
    ghost = two_ghosts()[0]
    ghost.enter_eaten()
    direction_before = ghost.direction

    ghost.enter_frightened()

    assert ghost.mode is GhostMode.EATEN
    assert ghost.direction is direction_before  # not even a reversal


def test_frightened_ghosts_move_at_half_speed() -> None:
    """Playbook F3 (state-level half): frightened covers half the ground."""
    frightened = two_ghosts()[0]
    frightened.mode = GhostMode.FRIGHTENED
    normal = two_ghosts()[1]

    assert mode_speed_multiplier(frightened) == 0.5
    assert mode_speed_multiplier(normal) == 1.0
    assert (
        mode_speed_multiplier(frightened)
        == mode_speed_multiplier(normal) * 0.5
    )


def test_create_ghosts_classic_corner_assignment() -> None:
    corners = [(0, 0), (14, 0), (0, 14), (14, 14)]  # TL, TR, BL, BR
    ghosts = create_ghosts(corners)

    by_personality = {g.personality: g for g in ghosts}
    assert by_personality[GhostPersonality.BLINKY].home_corner == (14, 0)
    assert by_personality[GhostPersonality.PINKY].home_corner == (0, 0)
    assert by_personality[GhostPersonality.INKY].home_corner == (14, 14)
    assert by_personality[GhostPersonality.CLYDE].home_corner == (0, 14)
    assert all(g.cell == g.home_corner for g in ghosts)
    assert all(g.mode is GhostMode.SCATTER for g in ghosts)
