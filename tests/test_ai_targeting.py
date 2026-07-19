"""Milestone 2.3 unit tests: the four target formulas + mode dispatch.

The fixed-point table comes straight from TESTING_PLAYBOOK.md §4.2:
freeze one configuration -- player P=(10, 10), Blinky B=(4, 10) -- and
hand-compute every expected target, first facing East, then facing North
(the row that catches a sign-flipped y-axis).
"""

import pytest

from pacman.ai.ghost import Cell, Ghost, GhostMode, GhostPersonality
from pacman.ai.targeting import (
    blinky_target,
    clyde_target,
    inky_target,
    pinky_target,
    target_tile,
)
from pacman.maze.adapter import Direction

PLAYER = (10, 10)
BLINKY_AT = (4, 10)
CLYDE_CORNER = (0, 14)


def make_ghost(
    personality: GhostPersonality,
    mode: GhostMode,
    cell: Cell = (0, 0),
    home: Cell = (0, 0),
) -> Ghost:
    """Minimal ghost for dispatch tests; direction is irrelevant here."""
    return Ghost(personality, cell, Direction.EAST, home, mode)


# --- The fixed-point table, facing East ---------------------------------

def test_blinky_targets_the_players_exact_tile() -> None:
    assert blinky_target(PLAYER) == (10, 10)


def test_pinky_targets_four_tiles_ahead_facing_east() -> None:
    assert pinky_target(PLAYER, Direction.EAST) == (14, 10)


def test_inky_reflects_blinky_through_the_two_ahead_pivot() -> None:
    # pivot = (12, 10); target = B + 2*(pivot - B) = (20, 10)
    assert inky_target(PLAYER, Direction.EAST, BLINKY_AT) == (20, 10)


def test_clyde_farther_than_eight_tiles_pursues() -> None:
    # distance 17.0 > 8
    assert clyde_target((27, 10), PLAYER, CLYDE_CORNER) == PLAYER


def test_clyde_inside_eight_tiles_retreats_to_his_corner() -> None:
    # distance sqrt(20) ~ 4.47 <= 8
    assert clyde_target((6, 12), PLAYER, CLYDE_CORNER) == CLYDE_CORNER


def test_clyde_at_exactly_eight_tiles_retreats() -> None:
    """Pin the boundary: strictly farther than 8 chases; exactly 8
    flees."""
    assert clyde_target((18, 10), PLAYER, CLYDE_CORNER) == CLYDE_CORNER


# --- The same table facing North (the y-axis sentinel rows) -------------

def test_pinky_facing_north_goes_straight_up_no_legacy_quirk() -> None:
    """Pinned policy: the up-and-left overflow quirk is NOT reproduced.

    y DECREASES upward, so the target is (10, 6); a sign-flipped delta
    table would produce (10, 14) and this row catches it
    (TESTING_PLAYBOOK.md §4.2).
    """
    assert pinky_target(PLAYER, Direction.NORTH) == (10, 6)


def test_inky_facing_north() -> None:
    # pivot = (10, 8); target = (2*10 - 4, 2*8 - 10) = (16, 6)
    assert inky_target(PLAYER, Direction.NORTH, BLINKY_AT) == (16, 6)


def test_targets_beyond_the_maze_are_never_clamped() -> None:
    """REFERENCE.md §4.4: targets are compared against, never traveled
    to. Inky's (20, 10) lies outside a 15x15 maze and must come back
    untouched -- no clamping, no validation, no exception."""
    assert inky_target(PLAYER, Direction.EAST, BLINKY_AT) == (20, 10)
    far_pinky = pinky_target((0, 0), Direction.NORTH)
    assert far_pinky == (0, -4)


# --- Mode dispatch (target_tile) ----------------------------------------

def test_target_tile_scatter_is_the_home_corner() -> None:
    ghost = make_ghost(
        GhostPersonality.BLINKY, GhostMode.SCATTER, home=(14, 0),
    )
    assert target_tile(ghost, PLAYER, Direction.EAST, BLINKY_AT) == (14, 0)


def test_target_tile_eaten_is_the_home_corner() -> None:
    ghost = make_ghost(
        GhostPersonality.PINKY, GhostMode.EATEN, home=(0, 0),
    )
    assert target_tile(ghost, PLAYER, Direction.EAST, BLINKY_AT) == (0, 0)


@pytest.mark.parametrize("personality,expected", [
    (GhostPersonality.BLINKY, (10, 10)),
    (GhostPersonality.PINKY, (14, 10)),
    (GhostPersonality.INKY, (20, 10)),
])
def test_target_tile_chase_dispatches_each_personality(
    personality: GhostPersonality, expected: Cell,
) -> None:
    ghost = make_ghost(personality, GhostMode.CHASE)
    result = target_tile(ghost, PLAYER, Direction.EAST, BLINKY_AT)
    assert result == expected


def test_target_tile_chase_clyde_uses_his_own_cell_and_corner() -> None:
    far = make_ghost(
        GhostPersonality.CLYDE, GhostMode.CHASE,
        cell=(27, 10), home=CLYDE_CORNER,
    )
    assert target_tile(far, PLAYER, Direction.EAST, BLINKY_AT) == PLAYER

    near = make_ghost(
        GhostPersonality.CLYDE, GhostMode.CHASE,
        cell=(6, 12), home=CLYDE_CORNER,
    )
    result = target_tile(near, PLAYER, Direction.EAST, BLINKY_AT)
    assert result == CLYDE_CORNER


def test_target_tile_frightened_raises() -> None:
    """Frightened movement is a seeded-random walk with no target; asking
    for one is a programming error and must fail loudly."""
    ghost = make_ghost(GhostPersonality.BLINKY, GhostMode.FRIGHTENED)
    with pytest.raises(ValueError):
        target_tile(ghost, PLAYER, Direction.EAST, BLINKY_AT)
