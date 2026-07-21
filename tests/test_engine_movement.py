"""Milestone 4.1: the buffered-turn matrix and consumption coupling.

TESTING_PLAYBOOK.md §3.1 (rows P1-P8 plus the two scripted follow-ups)
and §3.2 (rows C1-C4 plus anti-double-consumption). All geometry is
hand-verified on the fixture mazes; the validator test at the top is
the playbook §1.2 requirement that every hand-built fixture pass the
§2.3 mirror-consistency check -- a wall typo would otherwise poison
every scenario below.
"""

import pytest

from pacman.ai.ghost import Ghost, GhostMode, GhostPersonality
from pacman.game.engine import GameStatus, update_game_state
from pacman.maze.adapter import Direction
from tests.engine_helpers import make_state, make_test_config
from tests.mazes import (
    CORRIDOR_1x5,
    PLAZA_3x3,
    PLUS_3x3,
    POCKET_4x1,
    RING_3x3,
    TEE_3x3,
)

ALL_FIXTURES = [
    ("PLAZA_3x3", PLAZA_3x3),
    ("CORRIDOR_1x5", CORRIDOR_1x5),
    ("RING_3x3", RING_3x3),
    ("PLUS_3x3", PLUS_3x3),
    ("POCKET_4x1", POCKET_4x1),
    ("TEE_3x3", TEE_3x3),
]


@pytest.mark.parametrize("name,grid", ALL_FIXTURES)
def test_fixture_walls_are_mirror_consistent(
    name: str, grid: list[list[int]],
) -> None:
    """Playbook §1.2/§2.3: validate every hand-authored fixture."""
    height, width = len(grid), len(grid[0])
    for y in range(height):
        for x in range(width - 1):
            east = bool(grid[y][x] & Direction.EAST.wall_bit)
            west = bool(grid[y][x + 1] & Direction.WEST.wall_bit)
            assert east == west, f"{name} E/W mismatch at ({x},{y})"
    for y in range(height - 1):
        for x in range(width):
            south = bool(grid[y][x] & Direction.SOUTH.wall_bit)
            north = bool(grid[y + 1][x] & Direction.NORTH.wall_bit)
            assert south == north, f"{name} S/N mismatch at ({x},{y})"
    # Borders must be sealed outward (playbook §2.4 containment).
    for x in range(width):
        assert grid[0][x] & Direction.NORTH.wall_bit, name
        assert grid[height - 1][x] & Direction.SOUTH.wall_bit, name
    for y in range(height):
        assert grid[y][0] & Direction.WEST.wall_bit, name
        assert grid[y][width - 1] & Direction.EAST.wall_bit, name


def test_p1_legal_buffer_turns_while_moving() -> None:
    state = make_state(PLAZA_3x3, player=(1, 1))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.NORTH)
    update_game_state(state)
    assert state.player_cell == (1, 0)
    assert state.player_direction is Direction.NORTH
    assert state.buffered_direction is None


def test_p2_buffering_the_current_direction_does_not_stutter() -> None:
    state = make_state(PLAZA_3x3, player=(1, 1))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.EAST)
    update_game_state(state)
    assert state.player_cell == (2, 1)
    assert state.player_direction is Direction.EAST


def test_p3_corner_turn_when_current_is_blocked() -> None:
    # TEE center: South is walled, East is open.
    state = make_state(TEE_3x3, player=(1, 1))
    state.player_direction = Direction.SOUTH
    state.buffer_input(Direction.EAST)
    update_game_state(state)
    assert state.player_cell == (2, 1)
    assert state.player_direction is Direction.EAST


def test_p4_illegal_buffer_is_retained_while_cruising() -> None:
    state = make_state(CORRIDOR_1x5, player=(1, 0))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.NORTH)  # illegal in the tube
    update_game_state(state)
    assert state.player_cell == (2, 0)
    assert state.player_direction is Direction.EAST
    assert state.buffered_direction is Direction.NORTH  # retained


def test_p5_both_illegal_stops_and_retains_buffer() -> None:
    # TEE arm tip (1,0): only South is open.
    state = make_state(TEE_3x3, player=(1, 0))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.WEST)
    update_game_state(state)
    assert state.player_cell == (1, 0)  # stopped
    assert state.buffered_direction is Direction.WEST  # retained


def test_p6_cruises_with_no_buffer() -> None:
    state = make_state(CORRIDOR_1x5, player=(1, 0))
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.player_cell == (2, 0)


def test_p7_stops_at_a_wall_with_no_buffer() -> None:
    state = make_state(CORRIDOR_1x5, player=(4, 0))
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.player_cell == (4, 0)


def test_p8_player_may_reverse_instantly() -> None:
    """Pinned policy: instant reversal is allowed (a ghost-only rule
    forbids it) -- the arcade behaves the same."""
    state = make_state(CORRIDOR_1x5, player=(2, 0))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.WEST)
    update_game_state(state)
    assert state.player_cell == (1, 0)
    assert state.player_direction is Direction.WEST


def test_buffer_persistence_fires_exactly_at_the_junction() -> None:
    """Scripted follow-up to P4: an early Up press on the TEE corridor
    fires exactly at the junction tile center -- not before, not never.
    """
    state = make_state(TEE_3x3, player=(0, 1))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.NORTH)
    update_game_state(state)  # (0,1): North illegal, cruise East
    assert state.player_cell == (1, 1)
    assert state.buffered_direction is Direction.NORTH
    update_game_state(state)  # (1,1): North opens, buffer fires
    assert state.player_cell == (1, 0)
    assert state.player_direction is Direction.NORTH
    assert state.buffered_direction is None


def test_buffer_overwrite_keeps_only_the_latest_press() -> None:
    """The buffer is one slot, not a queue: Up then Left -> only Left."""
    state = make_state(TEE_3x3, player=(0, 1))
    state.player_direction = Direction.EAST
    state.buffer_input(Direction.NORTH)
    state.buffer_input(Direction.EAST)  # overwrites Up
    update_game_state(state)
    update_game_state(state)
    assert state.player_cell == (2, 1)  # cruised past the junction
    assert state.player_direction is Direction.EAST


def test_c1_pacgum_consumed_on_tile_entry() -> None:
    config = make_test_config(points_per_pacgum=7)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0),
        pacgums={(2, 0), (0, 0)}, config=config,
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.player_cell == (2, 0)
    assert state.score == 7  # exactly the configured X
    assert state.pacgum_cells == {(0, 0)}
    assert state.status is GameStatus.RUNNING  # pellets remain


def test_c2_super_pacgum_scores_and_frightens() -> None:
    config = make_test_config(points_per_super_pacgum=31)
    ghost = Ghost(
        GhostPersonality.BLINKY, (4, 0), Direction.WEST, (4, 0),
        mode=GhostMode.SCATTER,
    )
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost],
        pacgums={(0, 0)}, supers={(2, 0)}, config=config,
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.score == 31  # exactly the configured Y
    assert state.super_pacgum_cells == set()
    assert state.wave.frightened_active
    assert ghost.mode is GhostMode.FRIGHTENED
    # Reversal on frightened entry: the ghost moved West this tick,
    # then the super flipped it to face East.
    assert ghost.direction is Direction.EAST


def test_c3_empty_tile_leaves_the_score_alone() -> None:
    state = make_state(CORRIDOR_1x5, player=(1, 0), pacgums={(0, 0)})
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.score == 0


def test_c4_last_pellet_wins_the_level_the_same_tick() -> None:
    state = make_state(CORRIDOR_1x5, player=(1, 0), pacgums={(2, 0)})
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.status is GameStatus.LEVEL_WON
    assert state.tick_count == 1  # the very tick, never later


def test_win_waits_for_super_pacgums_too() -> None:
    """Pinned policy: supers count toward completion -- eating every
    plain pacgum with a super left is not a win."""
    state = make_state(
        CORRIDOR_1x5, player=(1, 0),
        pacgums={(2, 0)}, supers={(4, 0)},
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.status is GameStatus.RUNNING


def test_anti_double_consumption_while_parked() -> None:
    """Playbook §3.2 scenario: sitting on an emptied tile for 10 ticks
    must not score again (per-entry, not per-tick, consumption)."""
    config = make_test_config(points_per_pacgum=7)
    state = make_state(
        CORRIDOR_1x5, player=(3, 0),
        pacgums={(4, 0), (0, 0)}, config=config,
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.player_cell == (4, 0)
    assert state.score == 7
    for _ in range(10):  # blocked by the east wall: parked on the tile
        update_game_state(state)
    assert state.player_cell == (4, 0)
    assert state.score == 7
