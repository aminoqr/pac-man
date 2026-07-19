# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Commit Guidelines
- Never add "Co-Authored-By" or any AI attribution lines to git metadata.
- Every commit must belong solely to the primary user profile in .gitconfig.

## Architectural & Project Rules
- **Rule Enforcement:** Every architectural choice, file structure, and logic implementation MUST strictly adhere to the guidelines and criteria specified in `subject.pdf` located in the root directory.
- **Paradigm Constraint:** All code must strictly follow Object-Oriented Programming (OOP) principles. Game entities must be properly encapsulated into isolated, dedicated classes (e.g., `GameController`, `Player`, `Ghost`, `Board`).
- **Generation Style:** Do not rewrite entire files from scratch. Provide modular methods, single classes, or localized diffs to keep implementations focused and preserve context token limits.
- **Process:** Explain the mathematical formulas or architectural logic briefly *before* outputting the code snippet.

## Project status

This is a 42 school project ("Pacman — Ghosts! More ghosts!", subject v1.5, see `pacman-subject.pdf`).
The repository is currently at the **skeleton stage**: `maze_adapter.py` and `pacman_engine.py` contain
only class/function signatures with docstrings and `pass` bodies — no logic is implemented yet. There is
no package directory, no `Makefile`, no `tests/` directory, and no README yet. Treat the docstrings in
those two files as the design spec to implement against, not as documentation of working code.

The assigned maze generator is now delivered as **`mazegenerator-00001.zip`** (the old loose
`mazegenerator-2.1.0-py3-none-any.whl` at the repo root was removed). The zip contains a wheel with the
same name/version (`mazegenerator-2.1.0-py3-none-any.whl`) but its bundled `METADATA`/README disagrees
with its own code in several places — see "Documented-vs-actual traps" below, verified by extracting and
reading the wheel directly. `requirements.txt` still points at `./mazegenerator-2.1.0-py3-none-any.whl` at
the repo root; that path no longer exists, so **extract the wheel from the zip into the repo root before
`pip install -r requirements.txt` will work** (`unzip mazegenerator-00001.zip`).

Three project documents drive the work; read them before making non-trivial changes:

- **PLAN.md** — the milestone-by-milestone progress tracker (checkboxes = source of truth for what's done).
  Work milestone by milestone in the order it lists: (1) wheel integration & maze parsing, (2) ghost AI
  state machine, (3) BFS/DFS/A* pathfinding, (4) game loop/collisions/scoring, (5) UI/highscores/packaging.
- **REFERENCE.md** — the theory companion (graph model, coordinate/bitmask conventions, ghost AI math,
  pathfinding proofs, wheel-integration rules). This is where the *why* behind every convention lives.
- **TESTING_PLAYBOOK.md** — the test specification. Every table row in it is meant to become one pytest
  case; consult it before writing tests for movement, collisions, or ghost state transitions.

## Commands

No `Makefile` exists yet. PLAN.md §1.1 specifies one must be added with rules `install`, `run`, `debug`
(via `pdb`), `clean`, `lint`, and optional `lint-strict` — build that when implementing Milestone 1. Until
then, use the underlying commands directly:

```bash
# Install deps, including the local wheel referenced in requirements.txt
pip install -r requirements.txt

# Lint (the mandatory rule per subject III.1 / PLAN.md §1.1)
flake8 .
mypy . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

# Strict lint (optional Makefile target)
mypy . --strict

# Tests (once a tests/ dir exists)
pytest
pytest tests/test_some_module.py::test_case_name   # single test
```

The entry point will be `pac-man.py <config.json>` — exactly one CLI argument, the config path (PLAN.md §1.2).

## Architecture

### The wheel boundary (anti-corruption layer)

`mazegenerator-2.1.0-py3-none-any.whl` (now shipped inside `mazegenerator-00001.zip`) is a third-party
maze generator that must be used as-is (it is re-installed unmodified at peer review). **`maze_adapter.py`
is the only file in the codebase allowed to import `mazegenerator`** — every other module, including the
pathfinding and game-state layers, must consume only `MazeAdapter`'s vocabulary (`is_walkable`,
`get_valid_moves`, `neighbors`, `corners`, `center`, `reference_path_length`). If the wheel changes or is
swapped for another group's package, only this file should need to change. All generator failures/oddities
(warnings on too-small mazes, `shortest_path` returning `False` instead of a string, malformed grids) must
be normalized into the single `MazeAdapterError` type — no raw traceback or third-party exception may leak
past this module. Full rules of engagement: REFERENCE.md §5, PLAN.md §1.3.

Always call the generator with `perfect=False` — this triggers the braiding pass that removes dead ends,
which is what makes the maze escapable/playable (REFERENCE.md §1.6). `seed=42` for level 1 (reproducible),
`seed=0` (or a random positive seed) for later levels.

**Verified constructor** (read directly from `mazegenerator/mazegenerator.py` in the current wheel —
trust this over the bundled README):

```python
MazeGenerator(size: tuple[int, int] = (15, 15), perfect: bool = False,
              entry_cell: tuple[int, int] = (0, 0),
              exit_cell: tuple[int, int] = (-1, -1),
              seed: int = 0)
```

`entry_cell`/`exit_cell` are `(x, y)` and get clamped to `(0, 0)` / bottom-right corner respectively if out
of range — so the *unclamped* default `exit_cell=(-1, -1)` silently resolves to `(width-1, height-1)`.
`maze_entry`/`maze_exit` properties also return `(x, y)` (i.e. `(entryx, entryy)`), not `(row, col)`.
`generate(seed=0)` re-rolls the maze in place on the same instance; `seed > 0` reproducible, `seed == 0`
(or omitted) fully random each call.

**Documented-vs-actual traps in this wheel's own `METADATA`** — confirmed by reading the shipped source,
not by guessing; re-verify against whatever `mazegenerator.py` ships next time the wheel is swapped:

1. The README's Quick Start calls `MazeGenerator(width=20, height=20)` — those keyword arguments **do not
   exist** on the real constructor (it only takes `size=(w, h)`); that example would raise `TypeError`.
2. The README states the default size is `(20, 20)`; the actual code default is `size=(15, 15)`.
3. The README's API reference states `exit_cell` defaults to `(0, 0)`; the actual default is `(-1, -1)`,
   which resolves to the bottom-right corner, not the top-left.
4. The README states `maze_entry`/`maze_exit` are `(row, col)`; the actual properties return `(x, y)`
   (column, row) — i.e. the opposite order. Never trust the tuple order without the kind of experiment
   REFERENCE.md §5.4 describes; this wheel is a live example of why.
5. The minimum playable size for the "42" logo insert is **asymmetric**, not a flat "≥14 per side": the
   logo pattern is 7 cells wide x 5 cells tall and `_add_42_to_maze` skips insertion (with a printed
   warning, no exception) whenever `width < 14` **or** `height < 10`. Clamp config values against both
   thresholds independently before calling the generator.
6. Loops are not only introduced by the final braid pass: during initial carving, `_get_neighbors` has a
   1-in-6 chance of opening an extra wall to an already-visited neighbor even before `_braid()` runs (only
   when `perfect=False`). Both mechanisms only ever *remove* wall bits, so the mirror-consistency invariant
   (REFERENCE.md §2.3) still holds — but don't assume every loop in a generated maze came from braiding
   dead ends specifically.

### Coordinate system and wall encoding (non-negotiable, project-wide)

- Positions are `(x, y)` tuples; the raw grid is row-major and indexed `grid[y][x]`.
- `y` increases **downward**: North = `(0, -1)`, South = `(0, +1)`. This is the single most common source
  of bugs in this codebase (invisible on square mazes, explodes on rectangular ones) — always test with a
  non-square maze.
- Each cell is an int in `[0, 15]`, a 4-bit wall mask: bit 0/value 1 = North, bit 1/value 2 = East, bit
  2/value 4 = South, bit 3/value 8 = West. Movement is legal iff `(grid[y][x] & direction.wall_bit) == 0`.
  Value 15 (all walls) marks the sealed "42"-logo blocks — never walkable, never returned by `neighbors()`.
- A single canonical `Direction` enum (in `maze_adapter.py`) must carry, per member: `(dx, dy)`, wall bit,
  opposite direction (needed by the ghost no-reverse rule), and the NESW letter used to decode the wheel's
  `shortest_path` string. Every subsystem (input, ghost AI, pathfinding) should consume this one enum.

Full derivation and worked examples: REFERENCE.md §1, TESTING_PLAYBOOK.md §2.

### Game engine (`pacman_engine.py`)

`GameState`/`update_game_state` own all mutable world state (player, ghosts, pellets, score, lives,
timers) and must stay headless and deterministic:

- **Tick-based, not wall-clock.** Every timer (level countdown, scatter/chase wave, frightened countdown,
  eaten-ghost respawn) is a tick counter, never a real-time read. This is what makes pause trivial and the
  engine unit-testable without a window or a clock (REFERENCE.md §2.1, §2.4).
- **Canonical per-tick order** (see the `update_game_state` docstring and REFERENCE.md §2.7 /
  TESTING_PLAYBOOK.md §5.3 for why the order is load-bearing): snapshot previous positions → tick timers/
  mode transitions → move player → move ghosts → resolve collisions using the snapshots → consume pellets
  / update score / check win-loss. Snapshotting must happen *before* any movement, and collision
  resolution must be a single pass *after* all movement — interleaving either breaks the tile-swap check.
- **Collision has two cases**, both required: same-tile co-location, and the "tile-swap" pass-through
  where player and ghost exchange tiles across one edge in a single tick without ever sharing a tile
  (`P_t == G_(t-1) AND G_t == P_(t-1)`). Testing only co-location silently reintroduces the original 1980
  arcade's pass-through bug.
- **Ghost AI is one shared algorithm, four target formulas.** Global mode (SCATTER/CHASE/FRIGHTENED/EATEN)
  determines *when* to behave; a per-ghost target-tile formula (Blinky = Pac-Man's tile, Pinky = 4 ahead of
  Pac-Man, Inky = reflection through Blinky, Clyde = pursue-or-flee at an 8-tile radius) determines *what*
  it wants; a single shared intersection rule (greedy step toward target, no-reverse except mode-change
  flips and dead ends, tie-break Up > Left > Down > Right) determines *how* it moves. Keep these three
  layers separate — REFERENCE.md §4 has the full math and REFERENCE.md §4.7 explains why this separation
  matters for testability.
- Player input uses a **buffered direction**: at tile centers, try the buffered direction, else keep the
  current direction, else stop; the buffer persists across ticks until it becomes legal or is overwritten.

### Pathfinding (planned, Milestone 3)

A standalone module with zero dependencies on game/UI code, built only against `MazeAdapter.neighbors()`
(never the raw grid). BFS (shortest paths, FIFO+visited+parent), DFS (connectivity/structure only — not
shortest), and A* (min-heap on `f = g + Manhattan-h`) are all validated against each other and against the
wheel's own `shortest_path` string as an oracle (equal lengths, not necessarily equal paths). See
REFERENCE.md §3 for the proofs and PLAN.md's Milestone 3 checklist.

## Testing conventions

TESTING_PLAYBOOK.md §1.2 specifies a fixed set of hand-authored fixture mazes to test movement/collision/
AI logic against (`PLAZA_3x3`, `CORRIDOR_1x5`, `RING_3x3`, `TEE_3x3`, `POCKET_4x1`) — prefer these over
wheel-generated mazes for behavioral tests; reserve generated mazes for property tests (e.g. "BFS and A*
agree on ~50 seeds", "the maze stays one connected component"). Any test involving randomness (frightened
wandering, level seeds) must go through one seeded RNG owned by the state — never a global unseeded RNG —
so runs are reproducible.
