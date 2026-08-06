# 42 Pacman — Diagnostic & Testing Playbook

> A rigorous, implementation-agnostic test blueprint for the state machine,
> grid movement, collision resolution, and wall-encoding layers.
> Companions: [PLAN.md](PLAN.md) (progress tracker) · [REFERENCE.md](REFERENCE.md) (theory).
> No test code lives here — this is the *specification* your pytest suite
> must satisfy. Every table row below is meant to become exactly one test

**Conventions used throughout (identical to the whole project):**
positions are `(x, y)` tuples; arrays are indexed `grid[y][x]`; the y-axis
points **down** (North = `(0, -1)`); wall bits are N=1 (bit 0), E=2 (bit 1),
S=4 (bit 2), W=8 (bit 3); cell value 15 is a sealed, non-walkable block.

**Contents**

1. [Test Harness Architecture](#1-test-harness-architecture)
2. [The 4-Bit Wall-Encoding Validation Suite](#2-the-4-bit-wall-encoding-validation-suite)
3. [Pac-Man Grid-Movement Test Matrix](#3-pac-man-grid-movement-test-matrix)
4. [Ghost AI State-Machine Test Matrix](#4-ghost-ai-state-machine-test-matrix)
5. [The Tile-Swap Collision Anomaly](#5-the-tile-swap-collision-anomaly)
6. [Full Collision Test Matrix](#6-full-collision-test-matrix)
7. [Integration Scenarios and Oracles](#7-integration-scenarios-and-oracles)

---

## 1. Test Harness Architecture

### 1.1 The three preconditions for testability

None of the matrices below are writable unless the engine honors three
design contracts (already specified in `pacman_engine.py`'s docstrings):

1. **Headless determinism.** `update_game_state` performs zero I/O and zero
   rendering. A test drives the world by calling it N times and asserting on
   state. If any test needs a window or a sleep, the engine layering is wrong.
2. **Tick-based time.** All timers are tick counters. "After 7 seconds" in a
   spec row means "after `7 * TICKS_PER_SECOND` calls", exactly, no clock.
3. **Injected randomness.** Frightened-mode direction picks and any random
   seeds flow from one seeded RNG owned by the state. Same seed ⇒ same game,
   tick for tick. Never call a global unseeded RNG inside the engine.

### 1.2 Fixture mazes: test on grids you built by hand

Generated mazes are for property tests (§2.5, §7); *behavioral* tests must
run on tiny, hand-authored grids where you know every wall by heart.
Recommended fixture set:

| Fixture | Layout | Purpose |
|---|---|---|
| `PLAZA_3x3` | 3x3, no interior walls, border sealed | movement, targeting, tie-breaks |
| `CORRIDOR_1x5` | 1 row, 5 columns, straight tube | tile-swap collision, commitment |
| `RING_3x3` | 3x3 with center cell = 15 | no-reverse rule, orbiting, loop traversal |
| `TEE_3x3` | T-junction (degree-3 intersection) | intersection decision rule |
| `POCKET_4x1` | dead-end pocket | reverse-only escape hatch |

Author each fixture directly as a `list[list[int]]` of wall bytes, then run
the §2.3 consistency validator over it — a typo in a hand-built fixture
otherwise poisons every test built on it.

**Worked fixture (memorize this one).** `PLAZA_3x3` — every border wall set,
no interior walls:

```
        x=0        x=1        x=2
y=0   9 (N+W)    1 (N)      3 (N+E)
y=1   8 (W)      0 (open)   2 (E)
y=2  12 (S+W)    4 (S)      6 (S+E)
```

Row `y=0` is the TOP row, so it carries North bits; row `y=2` is the BOTTOM
row and carries South bits. If your renderer or your intuition disagrees
with this table, stop and fix that before writing any other test.

### 1.3 Test taxonomy used below

- **[U]** unit — one pure function, one assertion cluster.
- **[M]** matrix — a parametrized table; each row is one parametrize case.
- **[P]** property — randomized over many seeds, asserting invariants.
- **[S]** scenario — multi-tick scripted run on a fixture maze.

---

## 2. The 4-Bit Wall-Encoding Validation Suite

### 2.1 The predicate under test

The single load-bearing expression of the entire spatial layer:

```
canMove(x, y, d)  ⇔  (grid[y][x] & bit(d)) == 0
```

with `bit(N)=0x1, bit(E)=0x2, bit(S)=0x4, bit(W)=0x8`, and destination
`(x + dx(d), y + dy(d))` where the deltas are **N=(0,−1), E=(+1,0),
S=(0,+1), W=(−1,0)**.

Two independent things can go wrong, and your tests must be able to tell
them apart:

- **Bit mapping error** — you test the wrong bit (e.g. `& 0x4` for North).
  Symptom: movement blocked/allowed on the wrong *sides*.
- **Delta sign error** — you test the right bit but move the wrong way
  (e.g. North = `y+1` because "up is bigger" intuition). Symptom: the wall
  check passes but the entity lands on the wrong row — the **clipping**
  class of bugs (§2.4).

### 2.2 [M] The exhaustive bit-mapping matrix

Enumerate all 16 possible cell values x 4 directions = 64 rows. This is one
parametrized test, not 64 functions. Expected result is pure arithmetic:

| cell value | & 0x1 (N) | & 0x2 (E) | & 0x4 (S) | & 0x8 (W) | open directions |
|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | N E S W |
| 1 | 1 | 0 | 0 | 0 | E S W |
| 2 | 0 | 2 | 0 | 0 | N S W |
| 3 | 1 | 2 | 0 | 0 | S W |
| 4 | 0 | 0 | 4 | 0 | N E W |
| 5 | 1 | 0 | 4 | 0 | E W |
| 6 | 0 | 2 | 4 | 0 | N W |
| 7 | 1 | 2 | 4 | 0 | W |
| 8 | 0 | 0 | 0 | 8 | N E S |
| 9 | 1 | 0 | 0 | 8 | E S |
| 10 | 0 | 2 | 0 | 8 | N S |
| 11 | 1 | 2 | 0 | 8 | S |
| 12 | 0 | 0 | 4 | 8 | N E |
| 13 | 1 | 0 | 4 | 8 | E |
| 14 | 0 | 2 | 4 | 8 | N |
| 15 | 1 | 2 | 4 | 8 | *(sealed — also not walkable)* |

Assert both directions of the contract: `get_valid_moves` returns *exactly*
the "open" set (no missing direction, no extra direction). Testing only
"contains" lets a too-permissive implementation pass.

### 2.3 [U/P] The mirror-consistency invariant

Physical walls are stored twice (REFERENCE.md §1.3). For every interior
adjacency the two records must agree:

```
For all x in [0, W-2], y in [0, H-1]:
    (grid[y][x] & 0x2 != 0)  ⇔  (grid[y][x+1] & 0x8 != 0)     # E ↔ W
For all x in [0, W-1], y in [0, H-2]:
    (grid[y][x] & 0x4 != 0)  ⇔  (grid[y+1][x] & 0x1 != 0)     # S ↔ N
```

Run this as [U] on every hand-built fixture (catches fixture typos) and as
[P] over ~100 seeded generator outputs (catches misreading of the wheel).
A useful corollary test: `canMove(a → b)` must equal `canMove(b → a)` for
every adjacent pair — the graph is undirected, and this version exercises
your *predicate* rather than the raw grid.

### 2.4 [M] Boundary containment and the y-axis clipping trap

**The trap, precisely.** Suppose the delta table erroneously encodes
North as `(0, +1)`. Take `PLAZA_3x3`, entity at `(1, 0)` (top edge,
cell value 1 = North wall set). The player presses Up:

- The wall check `grid[0][1] & 0x1 = 1` correctly *blocks* — fine so far.
- But now the entity stands at `(1, 1)` (cell 0, all open) and presses Up:
  check passes, and the buggy delta moves it to `(1, 2)` — it walked
  **down** on screen. Visually this reads as "the sprite clips through the
  south wall of the corridor I expected it to leave northward". The wall
  bits were never wrong; the *coordinate plane orientation* was.

**The Python-specific aggravation.** If instead the bit test is wrong and a
move to `y = -1` slips through, `grid[-1][x]` does **not** raise in Python —
negative indices silently wrap to the *bottom row*. The entity teleports
from the top edge to the bottom edge and the game keeps running, corrupt.
This is why boundary tests must assert on *coordinates*, never merely on
"no exception was raised".

The containment matrix — run each row on `PLAZA_3x3` and assert both the
predicate result and, after an attempted move, the entity's exact position:

| # | Start | Cell value | Attempt | `& bit` result | Expected predicate | Expected position after |
|---|---|---|---|---|---|---|
| B1 | (1, 0) top edge | 1 | North | `1 & 0x1 = 1` | blocked | unchanged (1, 0) |
| B2 | (1, 2) bottom edge | 4 | South | `4 & 0x4 = 4` | blocked | unchanged (1, 2) |
| B3 | (0, 1) left edge | 8 | West | `8 & 0x8 = 8` | blocked | unchanged (0, 1) |
| B4 | (2, 1) right edge | 2 | East | `2 & 0x2 = 2` | blocked | unchanged (2, 1) |
| B5 | (0, 0) corner | 9 | North | `9 & 0x1 = 1` | blocked | unchanged (0, 0) |
| B6 | (0, 0) corner | 9 | West | `9 & 0x8 = 8` | blocked | unchanged (0, 0) |
| B7 | (0, 0) corner | 9 | East | `9 & 0x2 = 0` | **open** | (1, 0) |
| B8 | (0, 0) corner | 9 | South | `9 & 0x4 = 0` | **open** | (0, 1) — *larger* y |
| B9 | (1, 1) center | 0 | North | `0 & 0x1 = 0` | open | (1, 0) — *smaller* y |

Rows **B8 and B9 are the y-axis-orientation sentinels**: they fail under a
sign-flipped delta table even when every bit test is correct. Add the [P]
generalization: from any cell of any generated maze, apply every direction
the predicate declares open, and assert the destination is always inside
`0 ≤ x < W, 0 ≤ y < H` — on a wheel-generated maze the border bits alone
must guarantee this, with no explicit bounds check in the movement path.

### 2.5 [U/P] Sealed-cell (value 15) isolation

- `is_walkable` is false for every value-15 cell and true for all others.
- No value-15 cell is ever returned by `neighbors()` of a walkable cell —
  provable from §2.3 consistency (its neighbors must carry the mirror bits),
  but test it directly anyway: it is the invariant gameplay relies on.
- [P] On generated mazes: the walkable cells form **one connected
  component** (BFS from the entry reaches every non-15 cell). The braided
  generator guarantees it; your parser must not break it.

---

## 3. Pac-Man Grid-Movement Test Matrix

Player movement policy under test (REFERENCE.md §2.3): at a tile center,
try the **buffered** requested direction first; if illegal, continue with
the **current** direction; if that is also illegal, **stop**. Between tile
centers, only the buffer may change.

### 3.1 [M] The buffered-turn decision matrix

`R` = requested (buffered) direction legal? `C` = current direction legal?

| # | R legal | C legal | R == C | Expected outcome | Notes |
|---|---|---|---|---|---|
| P1 | yes | yes | no | turn to R, keep moving | the responsive-turn case |
| P2 | yes | yes | yes | continue (no-op turn) | must not stutter |
| P3 | yes | no | no | turn to R | corner turn at a bend |
| P4 | no | yes | no | continue with C, buffer *retained* | early press before the gap: must still fire at a later tile where R becomes legal |
| P5 | no | no | no | stop; buffer retained | facing a corner pocket |
| P6 | none buffered | yes | — | continue with C | cruise |
| P7 | none buffered | no | — | stop | ran into a wall |
| P8 | yes (reverse of C) | yes | no | turn immediately, even mid-corridor | the player MAY reverse (unlike ghosts); decide and pin your policy — arcade allows instant reversal |

Two scripted [S] follow-ups that matrices can't capture:

- **Buffer persistence** (extends P4): in `TEE_3x3`, press Up two tiles
  before the junction while moving East; assert the turn executes exactly
  at the junction tile center, not before, not never.
- **Buffer overwrite**: press Up then Left before reaching the junction;
  only Left (the latest) fires. The buffer holds one direction, not a queue.

### 3.2 [M] Movement/consumption coupling

On tile *entry* (the tick the logical tile changes), exactly once each:

| # | Tile contains | Expected state change |
|---|---|---|
| C1 | pacgum | pellet removed; `score += X`; remaining count −1 |
| C2 | super-pacgum | pellet removed; `score += Y`; frightened mode triggered (§4.4) |
| C3 | nothing | score unchanged |
| C4 | last pacgum | level-won flag raised the same tick |

Anti-double-consumption [S]: stand still on a (now empty) tile for 10 ticks
— score must not change again. A per-tick (rather than per-entry) consumption
check fails this instantly.

---

## 4. Ghost AI State-Machine Test Matrix

### 4.1 [M] Global mode transitions

`W` = wave timer expiry, `SP` = super-pacgum eaten, `FT` = frightened timer
expiry, `EG` = ghost eaten, `RT` = respawn wait elapsed.

| # | From | Event | To | Mandatory side effects |
|---|---|---|---|---|
| G1 | SCATTER | W | CHASE | **all ghosts reverse direction** |
| G2 | CHASE | W | SCATTER | all ghosts reverse |
| G3 | SCATTER | SP | FRIGHTENED | all reverse; wave timer **paused**, not reset |
| G4 | CHASE | SP | FRIGHTENED | all reverse; wave timer paused |
| G5 | FRIGHTENED | SP | FRIGHTENED | frightened countdown **restarts** at full |
| G6 | FRIGHTENED | FT | previous global mode | wave timer **resumes from pause point**; NO reversal on exit (classic behavior) |
| G7 | FRIGHTENED | EG (that ghost) | EATEN (that ghost only) | `score += Z`; others stay frightened |
| G8 | EATEN | reaches home corner | waiting | respawn countdown starts |
| G9 | EATEN/waiting | RT | current global mode | rejoins whatever mode is now active, not the one it left |
| G10 | EATEN | SP | EATEN | an eaten ghost is NOT re-frightened |

The subtle rows are **G6** (pause/resume arithmetic: run scatter for 3 s,
trigger 6 s of frightened, assert scatter still has 4 s left afterwards —
tick-count exactly) and **G9** (eat a ghost during frightened, let the wave
flip to chase while it travels home; it must rejoin in *chase*).

### 4.2 [M] Per-ghost target formulas — fixed-point table

Freeze one configuration and hand-compute every target. With player
`P = (10, 10)` facing **East** (`û = (1, 0)`) and Blinky at `B = (4, 10)`:

| Ghost | Formula | Expected target |
|---|---|---|
| Blinky | `P` | (10, 10) |
| Pinky | `P + 4û` | (14, 10) |
| Inky | `B + 2((P + 2û) − B)` | pivot (12, 10); `B + 2(8, 0)` = **(20, 10)** |
| Clyde, far (distance 17.0 > 8) | `P` | (10, 10) |
| Clyde at (6, 12) (distance √20 ≈ 4.47 ≤ 8) | scatter corner | its home corner |

Then repeat the whole table with the player facing **North** — now
`û = (0, −1)`, so Pinky = `(10, 6)` (y *decreases*; a sign-flipped delta
table yields (10, 14) and this row catches it). Decide here whether you
reproduce the legacy up-quirk (Pinky = `P + 4·(0,−1) + 4·(−1,0)` = (6, 6));
either choice is valid, but the test must pin the one you documented.

**Out-of-bounds targets are legal**: assert that Inky's (20, 10) on a 15x15
maze raises nothing and is never clamped — targets are compared against,
never traveled to (REFERENCE.md §4.4).

### 4.3 [M] The intersection decision rule

On `TEE_3x3`, ghost arrives at the junction heading East (so West is the
forbidden reverse). Open exits: North, East, South.

| # | Target tile | d² North / East / South | Expected choice | Tests |
|---|---|---|---|---|
| I1 | 2 up, 1 right | 1+4=5 / 4+... — compute per fixture | min-d² exit | basic greedy scoring |
| I2 | equidistant N and S (target straight ahead East, blocked) | tie | **North** | tie-break priority Up first |
| I3 | equidistant W-ish (target directly behind) | reverse would win | best *non-reverse* | no-reverse rule dominates scoring |
| I4 | any | — | never West | reverse excluded even when optimal |
| I5 | `POCKET_4x1` dead end | only reverse legal | reverse allowed | escape hatch |

Also assert the *tie-break order in full*: construct targets making each
pair {Up, Left}, {Left, Down}, {Down, Right} exactly tied and confirm
Up > Left > Down > Right. Use squared distances in the implementation and
the tests — no floats, no epsilon problems.

### 4.4 [M/S] Frightened behavior

| # | Check | Expected |
|---|---|---|
| F1 | direction choice at intersections | drawn from the seeded RNG; same seed ⇒ same wander path (assert two runs identical) |
| F2 | reverse exclusion | still no 180° turns while frightened |
| F3 | speed | frightened ticks-per-tile > normal (slower); resumes on expiry |
| F4 | edibility window | contact resolves as "ghost eaten" only while frightened flag set; one tick after expiry it kills the player |

---

## 5. The Tile-Swap Collision Anomaly

### 5.1 The anomaly, in exact coordinate math

Let positions be sampled at tick boundaries. Player `P`, ghost `G`,
superscript = tick index. On `CORRIDOR_1x5` (cells `(0,0)…(4,0)`):

```
tick t−1 :  P^(t−1) = (1, 0)  moving East  (+1, 0)
            G^(t−1) = (2, 0)  moving West  (−1, 0)

tick t   :  P^t = (1,0) + (1,0) = (2, 0)
            G^t = (2,0) + (−1,0) = (1, 0)
```

Test at every tick `P^t == G^t`? Then:

- tick t−1: `(1,0) ≠ (2,0)` → no collision.
- tick t: `(2,0) ≠ (1,0)` → **no collision.**

The entities exchanged tiles across the same edge in the same tick and the
naive check is blind to it. In continuous reality their sprites crossed at
the shared edge midpoint `x = 1.5` at half-tick time; the discrete sampler
just never looked there. This is a genuine bug in the 1980 arcade original —
players deliberately "passed through" Blinky with it. Your engine must not
inherit it.

### 5.2 The complete predicate

A collision between player and ghost g at tick t is:

```
collide(g, t) ⇔ ( P^t == G_g^t )                                  # case 1: co-location
             ∨ ( P^t == G_g^(t−1)  ∧  G_g^t == P^(t−1) )          # case 2: edge swap
```

Case 2 requires **both** equalities. Testing only `P^t == G^(t−1)`
("player stepped onto the ghost's old tile") is wrong: that situation is
routine and harmless when the ghost moved *away* perpendicular to the
player's approach. Prove it to yourself: player `(1,0) → (2,0)` East while
the ghost leaves `(2,0)` **without** entering `(1,0)` — a following move,
not a crossing. One-sided checks produce phantom deaths every time the
player chases a fleeing frightened ghost, which is exactly when tiles get
exchanged legitimately in one direction only.

### 5.3 What the game loop must guarantee for the predicate to be sound

The predicate consumes four values: `P^(t−1), P^t, G^(t−1), G^t`. That
imposes a strict phase ordering inside one tick (already sketched in
`pacman_engine.py`'s `update_game_state` docstring):

```
1. snapshot:   prev_P ← P;  prev_G[g] ← G[g]  for all g     (BEFORE any movement)
2. move player                                              (may change P)
3. move all ghosts                                          (may change G[g])
4. resolve:    for each g: collide(g) per §5.2, using the snapshots
```

Three loop-ordering bugs this forbids, each worth a dedicated regression
test:

- **Interleaved resolution** (check ghost g right after moving it, before
  moving ghost g+1): a *later* ghost's move can create a case-2 swap with
  the player that is never re-examined. Resolution must be a single pass
  *after all movement*.
- **Snapshot-after-player-moves**: `prev_P` then equals `P^t`, case 2
  degenerates to case 1, and every swap is missed again. The snapshot is
  the *first* thing the tick does.
- **Mutating during resolution**: killing the player mid-pass and
  continuing to test remaining ghosts against a respawned position. Collect
  all contacts first, then apply *one* outcome with a precedence rule
  (a non-edible contact outranks any number of edible ones in the same tick).

**Unequal speeds caveat.** If ghosts and player move on different tick
schedules (frightened ghosts skip ticks), a swap can span the *sub-steps*.
The predicate stays sound if and only if "tick" in §5.2 means one full
`update_game_state` call and snapshots are per-call, not per-sub-move. If
you later adopt fractional per-tick motion (REFERENCE.md §2.2), re-derive:
with per-tick displacement ≤ 1 tile per entity, the edge-swap test on
logical tiles remains exhaustive; displacement > 1 tile per tick would
require segment-intersection tests — keep speeds ≤ 1 tile/tick and you
never need them.

### 5.4 [S] The canonical swap scenarios

All on `CORRIDOR_1x5`, all four must pass with the same engine build:

| # | Setup (tick t−1) | Motion | Expected at tick t |
|---|---|---|---|
| S1 | P=(1,0)→E, normal ghost G=(2,0)→W | head-on swap | collision; player loses life; respawn at center; ghosts reset |
| S2 | P=(1,0)→E, **frightened** ghost G=(2,0)→W | head-on swap | collision; ghost EATEN; `score += Z`; player *keeps moving* |
| S3 | P=(1,0)→E, ghost G=(2,0)→E (fleeing, same direction, equal speed) | follow, no cross | **no collision**, ever, across 10 ticks |
| S4 | P=(1,0)→E, ghost G=(3,0)→W | they meet co-located at (2,0) | collision via case 1 (sanity check that case 2 logic didn't break case 1) |

And the adversarial [S]: S1 but with the collision check deliberately
limited to case 1 in a copied predicate — assert the test *fails*. A test
suite that cannot detect the bug it was written for is decoration; this
"mutation check" proves the swap rows have teeth.

---

## 6. Full Collision Test Matrix

Cross product of contact geometry x ghost state x cheat flags. `Co` =
co-location (case 1), `Sw` = swap (case 2).

| # | Geometry | Ghost state | Cheat | Expected outcome |
|---|---|---|---|---|
| X1 | Co | CHASE/SCATTER | off | life −1; player→center; ghosts→corners; modes reset; score unchanged |
| X2 | Sw | CHASE/SCATTER | off | identical to X1 (geometry must not matter) |
| X3 | Co | FRIGHTENED | off | ghost→EATEN; `score += Z`; player unaffected |
| X4 | Sw | FRIGHTENED | off | identical to X3 |
| X5 | Co/Sw | EATEN | off | **no interaction** — an eaten ghost is intangible both ways |
| X6 | Co/Sw | any hostile | invincibility on | no life lost; define & pin: does the ghost die or pass through? |
| X7 | two ghosts contact player same tick, one hostile one frightened | mixed | off | hostile outcome wins (precedence rule, §5.3); no double-processing |
| X8 | contact on the same tick the frightened timer expires | boundary | off | define the tick-boundary winner (timer decrements *before* collision resolution ⇒ hostile) and test the exact tick |
| X9 | contact on the tick player has 1 life | hostile | off | GAME_OVER state entered, no respawn |
| X10 | ghost–ghost co-location | any | — | no interaction; ghosts pass through each other |

Regression rider for every X-row that resets positions: assert pellet
state is *preserved* across a life-loss reset (only entities reset, the
eaten pacgums stay eaten).

---

## 7. Integration Scenarios and Oracles

### 7.1 The wheel as an oracle (Milestone 3 gate)

For ~50 seeds x several sizes: `len(your_bfs_path) == len(your_astar_path)
== len(wheel.shortest_path)` between the wheel's entry and exit. Lengths,
not paths — multiple optimal paths exist in a braided maze. Skip cleanly
when the wheel reports `False` (and assert your adapter converted it to
`MazeAdapterError` rather than a crash).

### 7.2 Determinism end-to-end [S]

Same config, same seed, same scripted input tape (a list of
(tick, key) pairs) ⇒ byte-identical final state (score, positions, tick
count) across two runs. This one test transitively guards §1.1's three
contracts and will catch any accidental wall-clock or global-RNG leak the
unit tests missed.

### 7.3 Ghost personality smoke test [S]

On a generated 15x15 maze, player parked motionless at center, run 30 s of
chase: Blinky's mean distance to the player must trend to a small constant;
Clyde's distance distribution must be bimodal around the 8-tile shell;
Pinky's most-visited tiles must lie on the player's facing side. Loose,
statistical, but it catches "all four ghosts accidentally share one target"
— a bug the per-formula unit tests cannot see because each formula is
individually correct.

### 7.4 Chaos & robustness [S]

- Random-input fuzz: 10,000 ticks of seeded random key events, assert no
  exception and all invariants (§2.5 connectivity untouched, score
  monotonic non-decreasing per subject VI.6, lives ∈ [0, initial]).
- Hostile config sweep: the defense will swap your config (subject V.3).
  Boot the engine against each file in a `tests/configs/` gallery —
  missing keys, wrong types, negatives, zero-size levels, unknown keys —
  and assert clean defaults every time, tracebacks never.

---

*End of playbook. Suggested build order: §2 (encoding) → §3 (movement) →
§5 (swap collision, while §3 is fresh) → §4 (state machine) → §6 →  §7.
Each section's tests are the acceptance gate for the matching PLAN.md
milestone items*
