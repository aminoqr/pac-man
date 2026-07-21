"""Core game-state management for 42 Pacman.

This module owns the mutable world state (player, ghosts, pellets, score,
lives, timers) and advances it in fixed simulation ticks. It knows NOTHING
about rendering or the wheel: maze topology arrives exclusively through the
``MazeAdapter`` interface (maze_adapter.py), and drawing is someone else's
job -- the engine must stay testable headless (no window, no clock).

Coordinate system (identical everywhere in the project; REFERENCE.md §1.2):

        x ->   0   1   2   3        * positions are (x, y) tuples
      y                             * arrays are indexed grid[y][x]
      |  0   [ ] [ ] [ ] [ ]        * y INCREASES DOWNWARD:
      v  1   [ ] [ ] [ ] [ ]            North / up    = (0, -1)
         2   [ ] [ ] [ ] [ ]            South / down  = (0, +1)

    The #1 classic bug is mixing grid[x][y] with grid[y][x]; it stays
    invisible on square mazes and explodes on rectangular ones. Test with
    a non-square maze early.

4-bit wall encoding (REFERENCE.md §1.3):

    bit 0 (value 1) = North wall    bit 2 (value 4) = South wall
    bit 1 (value 2) = East wall     bit 3 (value 8) = West wall

    A cell value is an int in [0, 15]. Example: 9 = 8 + 1 = West + North.
    Movement legality is a single bitwise test: direction d is open iff
    (cell & d.wall_bit) == 0. Value 15 = sealed cell = the "42" logo,
    never walkable.

Time model (REFERENCE.md §2.1): one call to ``update_game_state`` advances
exactly ONE tick of fixed duration. All speeds and timers are expressed in
ticks, never wall-clock seconds, so pause is trivial and tests are
deterministic.
"""

from dataclasses import dataclass
from enum import Enum, auto
from random import Random

from pacman.ai.ghost import (
    Cell,
    Ghost,
    GhostMode,
    GhostPersonality,
    create_ghosts,
    ghost_moves_on_tick,
)
from pacman.ai.intersection import (
    choose_eaten_exit,
    choose_frightened_exit,
    choose_target_exit,
)
from pacman.ai.targeting import target_tile
from pacman.ai.wave import (
    WaveController,
    apply_wave_tick,
    classic_wave_table,
    trigger_frightened,
)
from pacman.config.loader import Config
from pacman.maze.adapter import Direction, MazeAdapter
from pacman.pathfinding.search import reachable_cells

# One engine tick is one movement quantum: every entity displaces at
# most ONE tile per update_game_state call, the exact condition under
# which the tile-swap collision predicate is exhaustive
# (TESTING_PLAYBOOK.md §5.3, "unequal speeds caveat"). This is also the
# movement speed in tiles/second: every timer below scales with it, so
# changing it re-times movement WITHOUT altering any wall-clock duration
# (level time, frightened, respawn all stay the same number of seconds).
# It also sets turn responsiveness: the player only changes direction at
# a tile center, i.e. once per tick, so this many turns/second. 10 gives
# a ~100 ms turn window -- nimble -- while the ghosts are slowed to a
# fraction of it (``GameState.ghost_speed``) so the pace is not frantic,
# and the UI's per-entity motion smoothing keeps everything gliding.
ENGINE_TICKS_PER_SECOND = 10

# Frightened overlay length (REFERENCE.md §4.6 classic ~6 s) and the
# eaten ghost's parked-at-home delay (subject VI.3: 5-10 s).
FRIGHTENED_DURATION_TICKS = 6 * ENGINE_TICKS_PER_SECOND
RESPAWN_DELAY_TICKS = 5 * ENGINE_TICKS_PER_SECOND

# The arcade start facing; also restored on every respawn.
PLAYER_START_DIRECTION = Direction.WEST


class GameStatus(Enum):
    """Lifecycle of one level run (the macro FSM node, REFERENCE.md §2.8).

    RUNNING ticks; LEVEL_WON is raised the tick the last pellet is
    eaten (playbook C4); GAME_OVER the tick lives reach zero (X9).
    Both end states freeze the engine -- the session layer decides
    what happens next (next level / victory / game-over screen).
    """

    RUNNING = auto()
    LEVEL_WON = auto()
    GAME_OVER = auto()


@dataclass
class CheatFlags:
    """Toggleable evaluation cheats (subject VI.5), all off by default.

    ``invincible``: hostile contact is ignored entirely -- the player
    passes through (pinned X6 policy: the ghost survives); frightened
    ghosts remain edible. ``ghosts_frozen``: no ghost moves at all.
    ``speed_boost``: hostile ghosts step only on even ticks, making the
    player effectively twice as fast -- boosting the player's own
    displacement instead would exceed 1 tile/tick and break the
    tile-swap predicate (playbook §5.3). Extra lives and level skip
    are actions, not flags: ``GameState.add_life`` / session
    ``skip_level``.
    """

    invincible: bool = False
    ghosts_frozen: bool = False
    speed_boost: bool = False


class GameState:
    """All mutable state for one running level; advanced by
    :func:`update_game_state`.

    Owns the player (tile, facing, buffered input, lives), the four
    ghosts plus their wave clock, the pellet layer (two sets, kept
    separate from wall data -- different lifetimes), score, the level
    countdown, the seeded RNG behind frightened wandering, cheat
    flags, and pause. Previous-tick positions are NOT stored here:
    the tile-swap predicate needs per-update-call snapshots
    (playbook §5.3), so ``update_game_state`` takes them as locals
    before anything moves.
    """

    def __init__(
        self,
        adapter: MazeAdapter,
        level_data: "LevelData",
        config: Config,
        lives: int,
        score: int,
        rng: Random,
        ghost_speed: float = 1.0,
    ) -> None:
        """Assemble a fresh level run carrying ``lives``/``score`` over.

        A state created with no lives is born GAME_OVER (the config
        may adversarially say ``lives: 0`` -- subject V.3) rather than
        ticking a dead player.

        ``ghost_speed`` is the fraction of the player's speed at which
        SCATTER/CHASE ghosts move (1.0 = every tick, the default kept by
        the whole test suite; the UI sets it lower so the nimble player
        can outmanoeuvre them -- the classic arcade balance). EATEN eyes
        and FRIGHTENED ghosts keep their own cadences.
        """
        self.adapter = adapter
        self.level_data = level_data
        self.config = config
        self.ghost_speed = ghost_speed
        self.player_cell: Cell = level_data.player_spawn
        self.player_direction = PLAYER_START_DIRECTION
        self.buffered_direction: Direction | None = None
        self.lives = lives
        self.score = score
        self.ghosts = create_ghosts(level_data.ghost_spawns)
        self.wave = WaveController(
            classic_wave_table(ENGINE_TICKS_PER_SECOND)
        )
        self.pacgum_cells = set(level_data.pacgum_cells)
        self.super_pacgum_cells = set(level_data.super_pacgum_cells)
        self.rng = rng
        self.cheats = CheatFlags()
        self.paused = False
        self.tick_count = 0
        self.level_ticks_remaining = (
            config.level_max_time * ENGINE_TICKS_PER_SECOND
        )
        self.status = (
            GameStatus.RUNNING if lives > 0 else GameStatus.GAME_OVER
        )

    def buffer_input(self, direction: Direction) -> None:
        """Record the latest requested direction (REFERENCE.md §2.3).

        One slot, not a queue: a newer press overwrites an unfired
        older one (playbook §3.1 buffer-overwrite rule). The buffer
        persists across ticks until it becomes legal at a tile center
        or is overwritten.
        """
        self.buffered_direction = direction

    def toggle_pause(self) -> None:
        """Flip pause (subject VI.7). A paused tick is a no-op tick."""
        self.paused = not self.paused

    def add_life(self) -> None:
        """Cheat: grant one extra life (subject VI.5)."""
        self.lives += 1

    @property
    def seconds_remaining(self) -> int:
        """Level countdown in whole seconds, rounded up, for the HUD."""
        ticks = max(self.level_ticks_remaining, 0)
        return -(-ticks // ENGINE_TICKS_PER_SECOND)


@dataclass
class LevelData:
    """Static per-level layout derived once from a generated maze."""

    player_spawn: tuple[int, int]
    ghost_spawns: list[tuple[int, int]]
    pacgum_cells: set[tuple[int, int]]
    super_pacgum_cells: set[tuple[int, int]]


def parse_grid_map(adapter: MazeAdapter) -> LevelData:
    """Derive the engine's static level data from a loaded MazeAdapter.

    Entity placement (subject VI.1): super-pacgums sit in the 4 corners
    (also the 4 ghost spawns, per this project's design); the player spawns
    at the maze center; every other walkable cell reachable from the
    player spawn gets a pacgum ("most corridors"). Reachability is
    delegated to ``pathfinding.reachable_cells`` (the Milestone 3 DFS
    utility), which itself only walks ``adapter.neighbors()`` --
    wall-consistency and cell-value validation already happened inside
    MazeAdapter.load_wheel_maze(), so this function only ever consumes
    the MazeAdapter vocabulary, never a raw grid (REFERENCE.md §5.5).
    """
    player_spawn = adapter.center()
    ghost_spawns = adapter.corners()
    super_pacgum_cells = set(ghost_spawns)
    reachable = reachable_cells(adapter, player_spawn)
    pacgum_cells = reachable - super_pacgum_cells
    return LevelData(
        player_spawn=player_spawn,
        ghost_spawns=ghost_spawns,
        pacgum_cells=pacgum_cells,
        super_pacgum_cells=super_pacgum_cells,
    )


def create_game_state(
    adapter: MazeAdapter,
    config: Config,
    lives: int,
    score: int,
    rng: Random,
    ghost_speed: float = 1.0,
) -> GameState:
    """Build a ready-to-tick GameState for one loaded maze.

    The one-stop factory the session layer uses per level: placement
    via :func:`parse_grid_map`, then a GameState carrying the running
    ``lives``/``score`` (subject VI.7: both persist across levels) and
    the ``ghost_speed`` balance (default 1.0; the UI passes it down).
    """
    return GameState(
        adapter=adapter,
        level_data=parse_grid_map(adapter),
        config=config,
        lives=lives,
        score=score,
        rng=rng,
        ghost_speed=ghost_speed,
    )


def update_game_state(state: GameState) -> None:
    """Advance the simulation by exactly one fixed tick.

    Canonical order of operations (REFERENCE.md §2 / playbook §5.3 --
    the order is load-bearing):
        1. snapshot previous positions (consumed by step 5);
        2. tick timers: level countdown (timeout = lose a life, the
           pinned out-of-time policy), scatter/chase wave + frightened
           overlay (``apply_wave_tick`` also fires the all-ghost
           mode-change reversal), eaten-ghost respawn bookkeeping.
           Frightened expiring HERE, before movement, is what makes a
           same-tick contact hostile (playbook X8);
        3. move player: buffered direction first, else current, else
           stop -- reversal allowed (pinned P8 policy);
        4. move all ghosts (single pass, mode-dispatched);
        5. resolve collisions once, after ALL movement, using the
           snapshots -- co-location OR tile swap; a death tick ends
           here (the respawned player must not eat the center pellet);
        6. consume pellets on the player's tile; update score; raise
           LEVEL_WON the tick the last pellet disappears (C4).

    Free of rendering and I/O: the whole game is drivable tick-by-tick
    inside pytest. Paused or finished states are no-op ticks.
    """
    if state.status is not GameStatus.RUNNING or state.paused:
        return
    state.tick_count += 1
    prev_player = state.player_cell
    prev_ghost_cells = [ghost.cell for ghost in state.ghosts]

    state.level_ticks_remaining -= 1
    if state.level_ticks_remaining <= 0:
        _lose_life(state)
        return
    apply_wave_tick(state.wave, state.ghosts)
    for ghost in state.ghosts:
        ghost.tick_eaten_state(state.wave.wave_mode, RESPAWN_DELAY_TICKS)

    _move_player(state)
    _move_ghosts(state)

    if _resolve_collisions(state, prev_player, prev_ghost_cells):
        return
    _consume_pellets(state)


def _move_player(state: GameState) -> None:
    """One player step under the buffered-turn policy (REFERENCE.md §2.3).

    At the tile center: fire the buffered direction if legal (clearing
    the buffer), else continue with the current direction, else stop.
    An unfired buffer is RETAINED (playbook P4/P5) so an early press
    still fires at a later tile where it becomes legal. The player may
    reverse instantly (pinned P8 policy -- the no-reverse rule is a
    ghost rule).
    """
    legal = state.adapter.get_valid_moves(*state.player_cell)
    buffered = state.buffered_direction
    if buffered is not None and buffered in legal:
        state.player_direction = buffered
        state.buffered_direction = None
    elif state.player_direction not in legal:
        return
    step = state.player_direction
    state.player_cell = (
        state.player_cell[0] + step.dx,
        state.player_cell[1] + step.dy,
    )


def _ghost_steps_this_tick(state: GameState, ghost: Ghost) -> bool:
    """Whether this ghost advances a tile on the current tick.

    Layered cadence gates: FRIGHTENED ghosts skip odd ticks
    (``ghost_moves_on_tick``, 50% speed); SCATTER/CHASE ghosts move at
    ``state.ghost_speed`` of the player's rate via an evenly-spread
    Bresenham cadence (``int(t*s) > int((t-1)*s)`` -- a no-op at the
    default s=1.0, so every test sees full-speed ghosts); EATEN eyes
    always move (fast return). The speed-boost cheat additionally halves
    every non-EATEN ghost.
    """
    if not ghost_moves_on_tick(ghost, state.tick_count):
        return False
    if ghost.mode in (GhostMode.SCATTER, GhostMode.CHASE):
        t, s = state.tick_count, state.ghost_speed
        if int(t * s) <= int((t - 1) * s):
            return False
    if (
        state.cheats.speed_boost
        and ghost.mode is not GhostMode.EATEN
        and state.tick_count % 2 == 1
    ):
        return False
    return True


def _move_ghosts(state: GameState) -> None:
    """One movement pass over all four ghosts (REFERENCE.md §4.5).

    Blinky's cell is snapshotted before anyone moves so Inky's formula
    is update-order independent. Mode dispatch: EATEN eyes take the
    shortest-path hop home (and park once there, waiting out the
    respawn delay); FRIGHTENED wanders on the state's seeded RNG;
    SCATTER/CHASE run the shared greedy rule against the personality
    target. The wall guard before stepping keeps a sealed-in ghost
    (impossible on a wheel maze, constructible in fixtures) from
    phasing through walls -- the chooser's fallback is a facing, not a
    licence to move.
    """
    if state.cheats.ghosts_frozen:
        return
    # Inky's anchor; falls back to the player's tile if no Blinky is
    # present (scripted test states may field fewer than four ghosts).
    blinky_cell = next(
        (
            ghost.cell
            for ghost in state.ghosts
            if ghost.personality is GhostPersonality.BLINKY
        ),
        state.player_cell,
    )
    for ghost in state.ghosts:
        if not _ghost_steps_this_tick(state, ghost):
            continue
        if ghost.mode is GhostMode.EATEN:
            if ghost.cell == ghost.home_corner:
                continue
            step = choose_eaten_exit(
                state.adapter, ghost.cell, ghost.direction,
                ghost.home_corner,
            )
        elif ghost.mode is GhostMode.FRIGHTENED:
            step = choose_frightened_exit(
                state.adapter, ghost.cell, ghost.direction, state.rng,
            )
        else:
            target = target_tile(
                ghost, state.player_cell, state.player_direction,
                blinky_cell,
            )
            step = choose_target_exit(
                state.adapter, ghost.cell, ghost.direction, target,
            )
        ghost.direction = step
        if step in state.adapter.get_valid_moves(*ghost.cell):
            ghost.cell = (
                ghost.cell[0] + step.dx, ghost.cell[1] + step.dy,
            )


def _resolve_collisions(
    state: GameState,
    prev_player: Cell,
    prev_ghost_cells: list[Cell],
) -> bool:
    """Single post-movement collision pass; True if a life was lost.

    The complete predicate (playbook §5.2), per ghost: co-location
    ``P_t == G_t`` OR the tile swap ``P_t == G_(t-1) and G_t ==
    P_(t-1)`` -- both equalities, so a fleeing ghost merely vacating a
    tile the player enters is NOT a hit. Contacts are collected first,
    then ONE outcome applies (playbook §5.3 no-mutating-mid-pass):
    a hostile contact outranks any number of frightened ones (X7);
    with no hostile hit, every frightened contact ghost is eaten and
    scored. EATEN ghosts are intangible both ways (X5); invincibility
    ignores hostile contact but leaves frightened ghosts edible (X6).
    """
    hostile_hit = False
    frightened_hits = []
    for ghost, prev_cell in zip(state.ghosts, prev_ghost_cells):
        if ghost.mode is GhostMode.EATEN:
            continue
        colocated = ghost.cell == state.player_cell
        swapped = (
            state.player_cell == prev_cell
            and ghost.cell == prev_player
        )
        if not (colocated or swapped):
            continue
        if ghost.mode is GhostMode.FRIGHTENED:
            frightened_hits.append(ghost)
        else:
            hostile_hit = True
    if hostile_hit and not state.cheats.invincible:
        _lose_life(state)
        return True
    for ghost in frightened_hits:
        ghost.enter_eaten()
        state.score += state.config.points_per_ghost
    return False


def _lose_life(state: GameState) -> None:
    """Apply the one-life-lost outcome (subject VI.2, playbook X1/X9).

    Lives hit zero -> GAME_OVER, no respawn. Otherwise reset the
    entities: player back to the center spawn facing the start
    direction with a cleared buffer, ghosts recreated fresh on their
    corners in SCATTER, wave clock restarted from phase 0, level
    countdown refilled. The pellet layer is deliberately untouched
    (playbook §6 regression rider: eaten pacgums stay eaten). Score
    never decreases (subject VI.6): nothing here touches it.
    """
    state.lives -= 1
    if state.lives <= 0:
        state.lives = 0
        state.status = GameStatus.GAME_OVER
        return
    state.player_cell = state.level_data.player_spawn
    state.player_direction = PLAYER_START_DIRECTION
    state.buffered_direction = None
    state.ghosts = create_ghosts(state.level_data.ghost_spawns)
    state.wave = WaveController(
        classic_wave_table(ENGINE_TICKS_PER_SECOND)
    )
    state.level_ticks_remaining = (
        state.config.level_max_time * ENGINE_TICKS_PER_SECOND
    )


def _consume_pellets(state: GameState) -> None:
    """Per-entry pellet consumption + the same-tick win check.

    Set-removal makes consumption once-only by construction (standing
    still on an emptied tile scores nothing -- playbook C3 and the
    anti-double-consumption scenario). A super-pacgum triggers the
    frightened overlay (REFERENCE.md §4.6). The level is won the tick
    the LAST pellet of either kind disappears (pinned policy: supers
    count -- a super-pacgum is a pacgum too), never later (C4). A
    level whose placement had no pellets at all cannot be won
    vacuously -- "all pacgums eaten" presumes there was something to
    eat (only scripted test stages ever hit this; parse_grid_map
    always places pellets).
    """
    cell = state.player_cell
    if cell in state.pacgum_cells:
        state.pacgum_cells.discard(cell)
        state.score += state.config.points_per_pacgum
    elif cell in state.super_pacgum_cells:
        state.super_pacgum_cells.discard(cell)
        state.score += state.config.points_per_super_pacgum
        trigger_frightened(
            state.wave, state.ghosts, FRIGHTENED_DURATION_TICKS,
        )
    level_had_pellets = bool(
        state.level_data.pacgum_cells
        or state.level_data.super_pacgum_cells
    )
    if (
        level_had_pellets
        and not state.pacgum_cells
        and not state.super_pacgum_cells
    ):
        state.status = GameStatus.LEVEL_WON
