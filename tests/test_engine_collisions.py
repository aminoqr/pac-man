"""Milestone 4.2: the tile-swap anomaly and the full collision matrix.

TESTING_PLAYBOOK.md §5.4 (S1-S4 canonical swap scenarios plus the
adversarial mutation check) and §6 (X1-X10 cross product). Scenario
geometry lives on CORRIDOR_1x5 -- five cells (0,0)..(4,0) where every
head-on, follow, and meet is hand-traceable -- except S3's long form,
which runs on the RING_3x3 loop where the player legitimately enters
the ghost's vacated tile every single tick without ever crossing it.

Frightened ghosts move at 50% (even ticks only), so frightened
scenarios pre-set ``tick_count = 1`` to make the scripted contact
happen on an even tick.
"""

from pacman.ai.ghost import Ghost, GhostMode, GhostPersonality
from pacman.game.engine import GameStatus, update_game_state
from pacman.maze.adapter import Direction
from tests.engine_helpers import make_state, make_test_config
from tests.mazes import CORRIDOR_1x5, RING_3x3

CORRIDOR_SPAWNS = [(0, 0), (4, 0), (0, 0), (4, 0)]


def corridor_ghost(
    cell: tuple[int, int],
    direction: Direction,
    mode: GhostMode = GhostMode.CHASE,
    personality: GhostPersonality = GhostPersonality.BLINKY,
    home: tuple[int, int] = (4, 0),
) -> Ghost:
    """One scripted ghost on the corridor fixture."""
    return Ghost(personality, cell, direction, home, mode=mode)


def test_s1_head_on_swap_with_hostile_ghost_costs_a_life() -> None:
    """S1 + the X1/X2 outcome block + the pellet-preservation rider."""
    ghost = corridor_ghost((2, 0), Direction.WEST)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost],
        pacgums={(3, 0), (0, 0)}, ghost_spawns=CORRIDOR_SPAWNS,
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.lives == 2  # life -1
    assert state.status is GameStatus.RUNNING
    assert state.player_cell == (1, 0)  # back at the center spawn
    assert state.player_direction is Direction.WEST  # start facing
    # Ghosts reset: a fresh four-pack on the spawn corners, SCATTER.
    assert len(state.ghosts) == 4
    assert [g.cell for g in state.ghosts] == [
        (4, 0), (0, 0), (4, 0), (0, 0),  # arcade corner assignment
    ]
    assert all(g.mode is GhostMode.SCATTER for g in state.ghosts)
    assert not state.wave.frightened_active  # wave clock restarted
    assert state.score == 0  # X1: score unchanged
    assert state.pacgum_cells == {(3, 0), (0, 0)}  # pellets preserved


def test_s2_head_on_swap_with_frightened_ghost_is_a_meal() -> None:
    config = make_test_config(points_per_ghost=150)
    ghost = corridor_ghost((2, 0), Direction.WEST, GhostMode.FRIGHTENED)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost],
        pacgums={(0, 0)}, config=config,
    )
    state.player_direction = Direction.EAST
    state.tick_count = 1  # contact lands on an even (frightened) tick
    update_game_state(state)
    assert ghost.mode is GhostMode.EATEN
    assert state.score == 150  # exactly the configured Z
    assert state.lives == 3
    assert state.player_cell == (2, 0)  # player keeps moving


def test_s3_following_a_fleeing_ghost_never_collides() -> None:
    """Same direction, equal speed: the player enters the ghost's old
    tile every tick -- one equality only, which must never fire."""
    ghost = corridor_ghost((2, 0), Direction.EAST)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST
    for _ in range(2):  # until the wall forces the ghost to turn
        update_game_state(state)
        assert state.lives == 3
    assert state.player_cell == (3, 0)
    assert ghost.cell == (4, 0)


def test_s3_long_form_ring_chase_ten_plus_ticks_no_contact() -> None:
    """The §5.2 phantom-death proof, sustained: chasing one tile behind
    around the ring exchanges tiles one-sidedly EVERY tick for 12
    ticks; a one-sided predicate would kill the player on tick 1."""
    ghost = corridor_ghost((1, 0), Direction.EAST, home=(0, 0))
    state = make_state(RING_3x3, player=(0, 0), ghosts=[ghost])
    state.player_direction = Direction.EAST
    clockwise = [
        Direction.EAST, Direction.EAST, Direction.SOUTH, Direction.SOUTH,
        Direction.WEST, Direction.WEST, Direction.NORTH, Direction.NORTH,
    ]
    for tick in range(12):
        state.buffer_input(clockwise[tick % 8])
        previous_ghost_cell = ghost.cell
        update_game_state(state)
        assert state.lives == 3, f"phantom death at tick {tick}"
        # The exchange really is happening (the scenario has teeth):
        assert state.player_cell == previous_ghost_cell


def test_s4_meeting_co_located_still_collides() -> None:
    """Case 2 support must not have broken plain case 1."""
    ghost = corridor_ghost((3, 0), Direction.WEST)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS,
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.lives == 2


def test_mutation_check_co_location_alone_misses_the_swap() -> None:
    """Playbook §5.4 adversarial check: on S1's exact geometry, the
    naive co-location predicate sees nothing (proven on the real
    post-move positions via an invincible dry run), while the engine
    detects the swap and charges a life. The swap rows have teeth."""
    # Dry run: identical geometry, invincible, so positions survive.
    ghost = corridor_ghost((2, 0), Direction.WEST)
    dry = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
    )
    dry.player_direction = Direction.EAST
    dry.cheats.invincible = True
    update_game_state(dry)
    naive_collision = dry.player_cell == ghost.cell
    assert not naive_collision  # the 1980 bug: case 1 is blind here
    # Real run: the full predicate catches it.
    ghost2 = corridor_ghost((2, 0), Direction.WEST)
    real = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost2], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS,
    )
    real.player_direction = Direction.EAST
    update_game_state(real)
    assert real.lives == 2


def test_x3_co_located_frightened_ghost_is_eaten() -> None:
    ghost = corridor_ghost((3, 0), Direction.WEST, GhostMode.FRIGHTENED)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST
    state.tick_count = 1  # even tick: the frightened ghost steps too
    update_game_state(state)
    assert state.player_cell == (2, 0) and ghost.cell == (2, 0)
    assert ghost.mode is GhostMode.EATEN
    assert state.score == 200
    assert state.lives == 3


def test_x5_eaten_ghosts_are_intangible_both_geometries() -> None:
    # Swap geometry: returning eyes pass through the player.
    eyes = corridor_ghost(
        (2, 0), Direction.WEST, GhostMode.EATEN, home=(0, 0),
    )
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[eyes], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.player_cell == (2, 0) and eyes.cell == (1, 0)  # swapped
    assert state.lives == 3 and state.score == 0
    assert eyes.mode is GhostMode.EATEN
    # Co-location geometry: walking onto eyes parked at home.
    parked = corridor_ghost(
        (2, 0), Direction.WEST, GhostMode.EATEN, home=(2, 0),
    )
    state2 = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[parked], pacgums={(0, 0)},
    )
    state2.player_direction = Direction.EAST
    update_game_state(state2)
    assert state2.player_cell == (2, 0) == parked.cell
    assert state2.lives == 3 and state2.score == 0


def test_x6_invincibility_ignores_hostile_keeps_frightened_edible() -> None:
    """Pinned X6 policy: the player passes through a hostile ghost
    (which survives); frightened ghosts can still be eaten."""
    hostile = corridor_ghost((2, 0), Direction.WEST)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[hostile], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST
    state.cheats.invincible = True
    update_game_state(state)
    assert state.lives == 3 and state.score == 0
    assert state.player_cell == (2, 0)  # passed through
    assert hostile.mode is GhostMode.CHASE  # ghost survives
    # Frightened contact still scores under invincibility.
    tasty = corridor_ghost((2, 0), Direction.WEST, GhostMode.FRIGHTENED)
    state2 = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[tasty], pacgums={(0, 0)},
    )
    state2.player_direction = Direction.EAST
    state2.cheats.invincible = True
    state2.tick_count = 1
    update_game_state(state2)
    assert tasty.mode is GhostMode.EATEN
    assert state2.score == 200


def test_x7_hostile_outranks_frightened_in_the_same_tick() -> None:
    """Precedence rule (§5.3): one outcome only -- the life is lost and
    the frightened ghost is NOT eaten (no double-processing)."""
    hostile = corridor_ghost((2, 0), Direction.WEST)
    tasty = corridor_ghost(
        (2, 0), Direction.WEST, GhostMode.FRIGHTENED,
        personality=GhostPersonality.PINKY,
    )
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[hostile, tasty],
        pacgums={(0, 0)}, ghost_spawns=CORRIDOR_SPAWNS,
    )
    state.player_direction = Direction.EAST
    state.tick_count = 1  # even tick: both ghosts step into the swap
    update_game_state(state)
    assert state.lives == 2  # hostile outcome applied
    assert tasty.mode is GhostMode.FRIGHTENED  # never eaten
    assert state.score == 0  # no Z points awarded


def test_x8_contact_on_the_frightened_expiry_tick_is_hostile() -> None:
    """Timers tick before movement/collision (pipeline step 2), so the
    tick the countdown hits zero the ghost is hostile again.

    Home is (0,0) so the just-un-frightened ghost (now SCATTER) paths
    west toward its corner -- straight into the player advancing east,
    producing the expiry-tick swap the test is about.
    """
    ghost = corridor_ghost(
        (2, 0), Direction.WEST, GhostMode.FRIGHTENED, home=(0, 0),
    )
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        ghost_spawns=CORRIDOR_SPAWNS,
    )
    state.player_direction = Direction.EAST
    state.wave.start_frightened(1)  # expires on the very next tick
    update_game_state(state)
    assert state.lives == 2  # hostile, not a meal
    assert state.score == 0


def test_x9_last_life_contact_is_game_over_without_respawn() -> None:
    ghost = corridor_ghost((2, 0), Direction.WEST)
    state = make_state(
        CORRIDOR_1x5, player=(1, 0), ghosts=[ghost], pacgums={(0, 0)},
        config=make_test_config(lives=1),
    )
    state.player_direction = Direction.EAST
    update_game_state(state)
    assert state.status is GameStatus.GAME_OVER
    assert state.lives == 0
    assert state.player_cell == (2, 0)  # frozen where it happened
    # The end state is inert: further ticks change nothing.
    update_game_state(state)
    assert state.player_cell == (2, 0) and state.tick_count == 1


def test_x10_ghosts_pass_through_each_other() -> None:
    one = corridor_ghost((2, 0), Direction.WEST)
    two = corridor_ghost(
        (2, 0), Direction.WEST, personality=GhostPersonality.PINKY,
    )
    state = make_state(
        CORRIDOR_1x5, player=(4, 0), ghosts=[one, two], pacgums={(0, 0)},
    )
    state.player_direction = Direction.EAST  # parked against the wall
    update_game_state(state)
    # Both CHASE the player (east) and land on the same tile -- ghosts
    # never interact with each other, so they simply overlap.
    assert one.cell == two.cell == (3, 0)  # co-located, no interaction
    assert state.lives == 3
    assert one.mode is GhostMode.CHASE and two.mode is GhostMode.CHASE
