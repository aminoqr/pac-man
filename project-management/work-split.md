# Work Split — 42 Pac-Man (for the defense)

Two of us, one project. At the evaluation **both of us must be able to
answer for the whole codebase** — this document does not change that.
What it does is give each of us a *lead half* to own: the part you wrote,
know cold, and drive the discussion on.

The previous split was layered (one person all backend, the other all
frontend). That left each of us weak on the other half at defense. This
revision **interleaves** ownership so **each of us leads both algorithms
and UI** — a coherent diagonal slice across the stack, not a silo.

- **aasylbye** leads **search, targeting & pixels** — classical pathfinding,
  the ghost *what/how* decision layers, the maze adapter, and the MLX
  render path (how frames actually get drawn).
- **dalamrew** leads **ticks, modes & screens** — the game-loop / collision
  engine, the ghost *when* state machine, config & progression, and the
  screen FSM / menus / highscores (how the player navigates the app).

The two halves meet at **three named interfaces** (see
[§4 Shared seams](#4-shared-seams)); knowing your side of each seam is the
most likely thing you'll be asked to defend.

---

## 1. Ownership at a glance

| Layer | Module(s) | Milestone | Lead |
|---|---|---|---|
| Wheel anti-corruption | `pacman/maze/adapter.py` (+ `Direction`) | M1 | **aasylbye** |
| Pathfinding | `pacman/pathfinding/graph.py`, `search.py`, `debug.py` | M3 | **aasylbye** |
| Ghost *what* / *how* | `pacman/ai/targeting.py`, `intersection.py` | M2 | **aasylbye** |
| MLX driver (pixels) | `pacman/ui/app.py` | M5 | **aasylbye** |
| Packaging script | `packaging/make_package.py` | M5 | **aasylbye** |
| Config | `pacman/config/loader.py` | M1 | **dalamrew** |
| Game engine | `pacman/game/engine.py` | M4 | **dalamrew** |
| Session / progression | `pacman/game/session.py` | M4 | **dalamrew** |
| Ghost *when* | `pacman/ai/ghost.py`, `wave.py` | M2 | **dalamrew** |
| Screen FSM + clock | `pacman/ui/shell.py` | M5 | **dalamrew** |
| Pixel font | `pacman/ui/font.py` | M5 | **dalamrew** |
| Highscores | `pacman/highscore/store.py` | M5 | **dalamrew** |
| Entry point + Makefile | `pac-man.py`, `Makefile`, `scripts/` | M0/M5 | **dalamrew** |

Rough balance (source lines, tests excluded): **aasylbye ≈ 2,520**,
**dalamrew ≈ 2,450**. Each half mixes backend algorithms *and* UI so
neither person is only "the frontend person" or only "the engine person"
at the defense.

```
                    ALGORITHMS / SIM                 UI / SHIPPING
                 ┌──────────────────────┐      ┌─────────────────────┐
  aasylbye  →    │ adapter, pathfinding,│      │ app.py (MLX pixels),│
                 │ targeting,           │      │ packaging           │
                 │ intersection         │      │                     │
                 └──────────────────────┘      └─────────────────────┘
  dalamrew  →    │ config, engine,      │      │ shell (screen FSM), │
                 │ session, ghost/wave  │      │ font, highscores,   │
                 │                      │      │ pac-man.py/Makefile │
                 └──────────────────────┘      └─────────────────────┘
```

---

## 2. Part A — aasylbye: Search, targeting & pixels

**Theme:** *how agents find paths and pick turns, and how a frame is
drawn.* Classical graph search + the ghost decision formulas, plus the
entire MLX pixel pipeline.

### Files you own
- `pacman/maze/adapter.py` — the **only** file allowed to
  `import mazegenerator`. The anti-corruption layer + the `Direction`
  enum (dx/dy, wall bit, opposite, NESW letter).
- `pacman/pathfinding/graph.py` — the `MazeGraph` **Protocol** (structural
  typing; pathfinding imports nothing from maze/game/UI).
- `pacman/pathfinding/search.py` — BFS, DFS, A\* (Manhattan heuristic),
  `distance_map`, reachability.
- `pacman/pathfinding/debug.py` — the debug/visualization helpers.
- `pacman/ai/targeting.py` — the four chase/scatter target formulas
  (Blinky / Pinky / Inky / Clyde).
- `pacman/ai/intersection.py` — the shared "how it moves" rule (greedy
  step by true path distance, no-reverse, Up > Left > Down > Right).
- `pacman/ui/app.py` — the **only** importer of `mlx`. Window/image
  buffer, wall rendering, sprite (XPM) rendering, the HUD, all overlays,
  the How-to-Play keyboard page, and the maximize/resize crash fix.
- `packaging/make_package.py` — how the installable build is produced.

### Concepts you must be able to defend
- **The coordinate system & wall bitmask.** `(x, y)` with `y` growing
  *downward*; each cell a 4-bit mask (N=1, E=2, S=4, W=8); movement legal
  iff `(grid[y][x] & bit) == 0`; value 15 = sealed "42" logo block. Be
  ready to explain why the axis order matters and how it's tested on a
  **non-square** maze (`REFERENCE.md` §1, §2.3).
- **The wheel traps you normalized.** Documented-vs-actual tuple order,
  default size, `shortest_path` returning `False` — all funneled into one
  `MazeAdapterError` so no third-party exception leaks past the adapter.
- **BFS / DFS / A\*.** BFS = FIFO + visited + parent (shortest on an
  unweighted graph); DFS = connectivity/structure only, **not** shortest;
  A\* = min-heap on `f = g + Manhattan-h`. Why the Manhattan heuristic is
  admissible here, and why **A\* never expands more nodes than BFS**
  (`REFERENCE.md` §3). All three are cross-validated and checked against
  the wheel's own `shortest_path` as an **oracle** (equal *lengths*, not
  necessarily equal paths) across ~150 seeds.
- **The Protocol boundary.** Pathfinding depends only on
  `MazeGraph.neighbors()` (structural typing), never the raw grid or the
  game — that's why it's a standalone, reusable library.
- **Ghost target formulas (*what*).** Blinky = Pac-Man's tile; Pinky = 4
  ahead; Inky = reflection through Blinky; Clyde = pursue-or-flee at an
  8-tile radius. Targets need not be reachable — they are only *compared
  against* (`REFERENCE.md` §4.4).
- **Intersection rule (*how*).** At tile centers only: legal non-reverse
  exits, score by true path distance via `distance_map`, tie-break
  Up > Left > Down > Right; reverse allowed only on mode flips and dead
  ends.
- **Rendering into an image buffer.** MLX has no shape primitives, so
  everything (walls, sprites, glyphs, keycaps) is composed into one
  off-screen buffer and blitted in a single atomic put — no flicker.
- **The resize/maximize crash fix.** MLX's Vulkan swapchain can't survive
  a window resize; on a `ConfigureNotify` the window is rebuilt at the
  fixed size (debounced, re-entry guarded) so a resize snaps back instead
  of crashing.

### Likely evaluator questions → where to point
- *"Show me the maze can't be walked through a wall."* →
  `adapter.get_valid_moves` / `is_walkable`; `test_maze_adapter.py`.
- *"Prove your A\* is correct / efficient."* → `search.py`;
  `test_pathfinding_oracle.py` (oracle agreement),
  `test_pathfinding_benchmark.py` (A\* ≤ BFS expansions),
  `test_pathfinding_micro.py`.
- *"Why don't all four ghosts aim at the same tile?"* → `targeting.py`
  formulas; `test_ai_targeting.py`, `test_ai_personalities.py`.
- *"How does a ghost actually pick a turn?"* → `intersection.py` +
  `distance_map`; `test_ai_intersection.py`.
- *"Resize the window."* → the `ConfigureNotify` rebuild in `app.py`.
- *"How is a frame drawn without flicker?"* → off-screen buffer compose
  then single blit in `app.py`.

### Tests you own
`test_maze_adapter.py`,
`test_pathfinding_benchmark.py`, `test_pathfinding_micro.py`,
`test_pathfinding_oracle.py`,
`test_ai_targeting.py`, `test_ai_intersection.py`,
`test_ai_personalities.py`,
`test_packaging.py` *(packaging half — coordinate with dalamrew on
`pac-man.py` CLI cases)*.

*(UI pixel path is mostly smoke-tested via dalamrew's `test_ui_smoke.py`,
which drives the shared shell; know that suite even though you don't own
the file.)*

---

## 3. Part B — dalamrew: Ticks, modes & screens

**Theme:** *how the world advances every tick and how the player moves
between screens.* The headless engine + ghost mode clock, plus the
platform-neutral UI shell, menus, and highscores.

### Files you own
- `pacman/config/loader.py` — the adversarial JSON config loader.
- `pacman/game/engine.py` — `GameState` + `update_game_state`: the whole
  tick pipeline (movement, collisions, pellets, scoring).
- `pacman/game/session.py` — `GameSession`: ≥10 levels, seeding, cheats,
  carrying score/lives across levels.
- `pacman/ai/ghost.py` — per-ghost state (tile, direction, home, mode).
- `pacman/ai/wave.py` — the Scatter/Chase wave clock and Frightened/Eaten
  overlays (*when* a ghost behaves).
- `pacman/ui/shell.py` — the platform-neutral screen FSM
  (`MAIN_MENU`/`INSTRUCTIONS`/`HIGHSCORES`/`PLAYING`/`PAUSED`/
  `NAME_ENTRY`), abstract `Action` input model, the fixed-timestep clock,
  and the READY!/interstitial banner queue.
- `pacman/ui/font.py` — the hand-rolled 5×7 bitmap font.
- `pacman/highscore/store.py` — the persistent top-10 table.
- `pac-man.py`, `Makefile`, `scripts/` — the entry point and how the
  project is installed / run / linted / tested.

### Concepts you must be able to defend
- **The canonical per-tick order** (load-bearing): snapshot previous
  positions → tick timers/mode transitions → move player → move ghosts →
  resolve collisions on the snapshots → consume pellets / score /
  win-loss. Why snapshotting is *before* movement and collision is a
  *single pass after* — otherwise the tile-swap check breaks.
- **Two collision cases:** same-tile co-location **and** the tile-swap
  pass-through (`P_t == G_(t-1) AND G_t == P_(t-1)`). Testing only
  co-location reintroduces the 1980 arcade pass-through bug
  (`REFERENCE.md` §2.7, `TESTING_PLAYBOOK.md` §5).
- **Buffered input:** at tile centers, try the buffered direction, else
  keep current, else stop; the buffer persists across ticks.
- **Ghost mode state machine (*when*).** Scatter/Chase wave table;
  Frightened is an overlay that *pauses* (does not reset) the wave timer;
  Eaten returns home then rejoins whatever mode is *now* active; mode
  flips force a direction reverse (`REFERENCE.md` §4.2–§4.3).
- **Determinism:** every timer is a tick counter, never wall-clock; all
  randomness (frightened wander, later-level seeds) goes through one
  seeded RNG owned by the state.
- **The `GameState`-owns-player choice.** Player fields live on
  `GameState`, not a separate `Player` class, so the per-tick order and
  tile-swap snapshot stay in one auditable place; ghosts *are* a class
  because there are four independent instances.
- **The headless/thin-view split.** `shell.py` is a pure state machine
  driven by abstract `Action`s with **zero** graphics-library imports;
  only `app.py` (aasylbye) touches MLX. This is what lets the whole UI —
  the entire screen FSM — be unit-tested without ever opening a window.
- **Fixed-timestep clock:** sim advances in ticks via a time accumulator,
  so behavior is frame-rate independent.
- **Highscores hardened.** Load **never raises**: a missing / unreadable
  / malformed / partially-corrupt file degrades to whatever valid rows
  can be salvaged. Names sanitized to ≤10 alphanumeric-and-space chars.
- **Faulty config & CLI.** Missing/invalid keys clamp to defaults with a
  log; unknown keys ignored; `pac-man.py <config.json>` takes exactly one
  arg and never prints a traceback.

### Likely evaluator questions → where to point
- *"What happens if the config is garbage?"* → clamp + log + always boot;
  `config/loader.py`; `test_config.py`.
- *"Two entities swap tiles in one tick — caught or not?"* → tile-swap
  branch in `engine.py`; `test_engine_collisions.py`.
- *"Prove a mode change lets a ghost reverse."* → `wave.py` (and the
  reverse consumed by aasylbye's `intersection.py`); `test_ai_wave.py`.
- *"Why doesn't the UI import MLX everywhere?"* → `shell.py` is
  graphics-free; only `app.py` imports `mlx`; `test_ui_smoke.py` drives
  the FSM headless.
- *"Corrupt the highscore file."* → salvage logic in `store.py`;
  `test_highscore.py`.
- *"Run it with the wrong number of arguments."* → the single clean catch
  site in `pac-man.py`.

### Tests you own
`test_config.py`,
`test_engine_movement.py`, `test_engine_collisions.py`,
`test_engine_death_pause.py`, `test_engine_chaos.py`,
`test_engine_integration.py`, `test_engine_parse_grid_map.py`,
`test_engine_progression.py`,
`test_ai_wave.py`, `test_ai_eaten.py`,
`test_ui_smoke.py`, `test_ui_interstitials.py`,
`test_highscore.py`.

---

## 4. Shared seams

Three interfaces where the two halves meet. **Each of us owns one side;
know exactly what crosses the line.**

1. **Ghost decision API** — *aasylbye provides → dalamrew consumes.*
   The engine (`dalamrew`) advances ghosts each tick by calling into
   `targeting.py` + `intersection.py` (aasylbye), which in turn call
   `astar_path` / `distance_map` from `pathfinding/search.py` (also
   aasylbye). If asked "how does a ghost pick a turn?", aasylbye explains
   the target formula and exit scoring; dalamrew explains *when* that
   rule runs inside the tick pipeline and how `wave.py` forces a reverse
   on mode change.

2. **Session / State read API** — *dalamrew provides → aasylbye consumes.*
   `ui/app.py` (aasylbye) reads `GameSession` / `GameState` (dalamrew) —
   player/ghost render positions, pellets, score, lives, timers, the
   death/eat pause flags — to draw a frame, and calls `buffer_input` +
   `tick`. `shell.py` (dalamrew) constructs `GameSession(...)` with the
   speed and pause parameters. The engine never calls the UI.

3. **`Direction` enum + adapter vocabulary** — *aasylbye provides →
   both consume.* The engine (dalamrew) uses
   `adapter.get_valid_moves` / `neighbors` for movement and collisions;
   the renderer (aasylbye's `app.py`) draws walls from the same vocabulary
   and orients sprites with `Direction`. One canonical enum, consumed by
   input, AI, *and* rendering.

**Shared, not owned by either:** `tests/engine_helpers.py` and
`tests/mazes.py` (the hand-authored fixture mazes from
`TESTING_PLAYBOOK.md` §1.2). Both suites build on them; change them
together.

---

## 5. What BOTH of us must know (regardless of owner)

The subject can put either of us on the spot for any of these — rehearse
them together. Because the split is interleaved, you already *own* one
side of each topic; still walk the other person's files once before the
defense:

- **OOP / architecture:** why the codebase is layered so each layer
  depends only on those below it; the two boundaries (wheel
  anti-corruption layer; headless engine + thin MLX view).
- **The wheel is used as-is** and re-installed at review — only
  `maze/adapter.py` imports it.
- **"No crash!"** — bad config boots, missing display degrades to a text
  preview, wrong CLI args print a clean message.
- **The mandatory gate:** `flake8` + `mypy` (mandatory flags **and**
  `--strict`) clean; the full `pytest` suite green.
- **Cheat keys** F1–F5 (invincibility, freeze, +1 life, speed, skip) and
  why they exist (peer-review aids, subject VI.5).
- **How AI (Claude Code) was used** — humans authored the design specs
  (`PLAN.md`/`REFERENCE.md`/`TESTING_PLAYBOOK.md`) and steered; the model
  implemented against them; everything was reviewed and gated (README
  "How AI was used").
- **Cross-half flash cards (practice each other):**
  - aasylbye quizzes dalamrew on BFS vs A\* and Pinky's +4 target.
  - dalamrew quizzes aasylbye on the tile-swap predicate and the
    Scatter→Chase reverse.
  - aasylbye quizzes dalamrew on the screen FSM transitions.
  - dalamrew quizzes aasylbye on the off-screen buffer / resize fix.

## 6. Study companions

- `REFERENCE.md` — the theory (coordinate/bitmask conventions, ghost-AI
  math, pathfinding proofs, wheel rules).
- `TESTING_PLAYBOOK.md` — the test spec (every matrix row → one test).
- `PLAN.md` — the milestone tracker.
- `project-management/` — timeline, progress, design decisions, risk
  analysis, acceptance-test plan, blocking points.
