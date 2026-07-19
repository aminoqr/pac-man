# 42 Pacman — Project Plan & Progress Tracker

> Subject: **"Pacman — Ghosts! More ghosts!"** (v1.5) · Python 3.10+ · flake8 + mypy clean · MLX-like graphics
> Companion study guide: [REFERENCE.md](REFERENCE.md) (theory) · [CLAUDE.md](CLAUDE.md) (current, wheel-verified facts)
>
> How to use this file: work milestone by milestone. Tick a box only when the
> acceptance criteria at the end of each milestone pass. Every milestone leaves
> the repository in a runnable, lintable state.

---

## Milestone 1 — Environment Setup, `.whl` Integration, and Grid/Maze Parsing

*Goal: a repository skeleton that installs cleanly, loads a config, generates a
maze through the provided wheel, and can print/parse that maze correctly.*

### 1.1 Repository & tooling

- [*] Create the project layout: a package directory (e.g. `pacman/`) with submodules planned for `config`, `maze`, `entities`, `ai`, `pathfinding`, `game`, `ui`, `highscore`, plus a `tests/` directory and a `project-management/` directory (required by Chapter VIII).
- [*] Write the `Makefile` with the mandatory rules: `install`, `run`, `debug` (via `pdb`), `clean`, `lint` (`flake8 .` and `mypy . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs`), and optional `lint-strict` (`mypy . --strict`).
- [*] Create a virtual environment; `make install` installs the wheel plus dev tools (`flake8`, `mypy`, `pytest`). The wheel now ships inside `mazegenerator-00001.zip` (the old loose `mazegenerator-2.1.0-py3-none-any.whl` is gone), and `requirements.txt` still points at that old path — extract the zip into the repo root (`unzip mazegenerator-00001.zip`) before `make install`/`pip install -r requirements.txt` will work.
- [*] Add `.gitignore` covering `__pycache__/`, `.mypy_cache/`, `.venv/`, editor artifacts.
- [*] Confirm every function you write from now on carries type hints and a PEP 257 docstring (subject III.1 makes this graded, not optional).

### 1.2 Configuration loader (subject V.1–V.3)

- [*] Entry point `pac-man.py` accepts **exactly one** CLI argument (the JSON config path); wrong arg count prints a clean usage message — never a traceback.
- [*] Implement a JSON-with-comments reader: strip lines starting with `#` (optionally also `//` and `/* */`) before parsing.
- [*] Define the config schema with robust defaults: `highscore_filename`, `level` (array of `{width, height}`), `lives: 3`, `pacgum: 42`, `points_per_pacgum: 10`, `points_per_super_pacgum: 50`, `points_per_ghost: 200`, `seed: 42`, `level_max_time: 90`.
- [*] Faulty-config policy: missing/invalid values clamp to safe defaults with a logged message; unknown keys are silently ignored; the game always continues. (The config **will be swapped during the defense** — treat this as an adversarial input.)
- [*] Unit tests: valid config, missing file, invalid JSON, wrong types, out-of-range values, unknown keys.

### 1.3 Wheel integration & maze parsing (subject V.4)

- [*] Inspect the wheel *as a consumer* (see REFERENCE.md §5): list its contents, read `METADATA`, and probe the public API in a REPL — do **not** modify or vendor its code; it will be re-installed at peer review. CLAUDE.md already has this extraction done plus a documented-vs-actual trap list from reading the source directly — start there and confirm with your own REPL/test pass rather than re-investigating blind.
- [*] Wall-bit encoding is confirmed unchanged (bit 0 = North, bit 1 = East, bit 2 = South, bit 3 = West). The coordinate order returned by `maze_entry` / `maze_exit` is now source-verified as `(x, y)` — the README's claimed `(row, col)` is wrong (see CLAUDE.md's trap list, itself pointing back to REFERENCE.md §5.4's methodology). Still write the confirming test; just don't treat the order as an open question.
- [*] Write a **maze adapter** class: it calls `MazeGenerator(size=(w, h), perfect=False, entry_cell=..., exit_cell=..., seed=...)`, catches any generator failure cleanly, and converts the raw wall-encoded `list[list[int]]` into your own internal grid model (never let the rest of the game touch the wheel directly).
- [*] Clamp configured level width/height against the verified, *asymmetric* minimum for the "42" logo insert: width ≥ 14 **and** height ≥ 10 independently (not a flat "≥14 per side") — do this clamping (§1.2) before ever calling the generator.
- [*] Implement the core spatial query: `can_move(cell, direction) -> bool` using bitmask tests, and `neighbors(cell) -> list[cell]`.
- [*] Treat cells with value `15` (all four walls — the "42" logo blocks) as solid, non-walkable tiles.
- [*] Build a debug ASCII renderer for the maze (walls, walkable cells, the 42 block) — this is your primary debugging tool for everything that follows.
- [*] Entity placement pass: pacgums in most corridors, super-pacgums in the 4 corners, 4 ghosts one per corner, player at the maze center (subject VI.1).

### Milestone 1 acceptance criteria

- [*] `make install && make run config.json` opens (or textually prints) a generated maze with no traceback under any malformed config.
- [*] `make lint` passes with zero errors.
- [*] Level 1's maze is reproducible with fixed seed 42; a corrupted config still boots the game with defaults.

---

## Milestone 2 — Core Ghost AI & State Machine

*Goal: four ghosts with distinct, deterministic personalities driven by a
global Scatter/Chase/Frightened state machine. Study REFERENCE.md §4 first.*

### 2.1 Foundations

- [*] Define a `Direction` enumeration carrying `(dx, dy)`, the matching wall bit, and its opposite (used both for movement and the no-reverse rule).
- [*] Give every ghost: a current cell, a current direction, a home corner (its scatter target and respawn point), and a state (`SCATTER`, `CHASE`, `FRIGHTENED`, `EATEN`).

### 2.2 Global mode state machine

- [*] Implement the global Scatter/Chase timer as a wave table (classic pattern: 7 s scatter, 20 s chase, 7 s scatter, 20 s chase, 5 s scatter, 20 s chase, 5 s scatter, then chase forever — tune per level).
- [*] On every Scatter <-> Chase transition, force all ghosts to reverse direction (the classic "mode-change reversal" signal).
- [*] Frightened mode: triggered by a super-pacgum, runs on its own countdown, *pauses* (does not consume) the scatter/chase wave timer; ghosts reverse on entry and move slower.
- [*] Eaten state: an eaten ghost returns to its home corner (path-find or teleport-after-delay), waits ~5–10 s, then rejoins the current global mode (subject VI.3).

### 2.3 Per-ghost targeting (the four personalities)

- [*] **Blinky (red)** — chase target = Pac-Man's current tile (pure pursuit).
- [*] **Pinky (pink)** — chase target = 4 tiles ahead of Pac-Man's facing direction (the ambusher; optionally reproduce the legacy "up = up-and-left" overflow quirk, documented in REFERENCE.md §4.4 — pinned policy: NOT reproduced, straight up).
- [*] **Inky (cyan)** — chase target = the vector from Blinky to the point 2 tiles ahead of Pac-Man, doubled (the flanker; depends on Blinky's position).
- [*] **Clyde (orange)** — chase target = Pac-Man's tile when farther than 8 tiles away, else his own scatter corner (the coward).
- [*] Scatter targets = the four maze corners, matching each ghost's spawn corner in this project.

### 2.4 The intersection decision rule

- [*] Movement contract: a ghost only re-decides at tile centers; between tiles it is committed to its direction.
- [*] At each tile: enumerate legal exits (no wall, not the reverse of current direction), pick the exit whose next tile minimizes straight-line distance to the target tile; break ties with the fixed priority Up > Left > Down > Right.
- [*] Frightened movement: choose a pseudo-random legal direction at each intersection (still no reversing).
- [*] Cover the degenerate case: if the only legal move is the reverse (dead end — rare here since the braided maze removes dead ends, but the 42-block pocket edges can surprise you), allow the reversal.

### Milestone 2 acceptance criteria

- [*] With the player standing still, each ghost visibly behaves differently (Blinky homes in, Pinky overshoots ahead, Inky flanks, Clyde oscillates) — verified headlessly in tests/test_ai_personalities.py (deterministic sim on the seed-42 maze); on-screen confirmation rides on Milestone 4's loop.
- [*] Mode switches are visible (all ghosts flip direction) and frightened ghosts scatter randomly and are eatable — reversal + seeded wandering + EATEN transition asserted in tests; collision-based eating is Milestone 4.
- [*] Unit tests for: target-tile computation per ghost, the intersection chooser (including tie-breaking), and wave-timer transitions.

---

## Milestone 3 — Classical Pathfinding (BFS, DFS, A*)

*Goal: a standalone `pathfinding` module, understood deeply, validated against
the wheel's own solver. Study REFERENCE.md §3 first.*

- [ ] Formalize the maze as an unweighted graph interface: `neighbors(node)` built on the Milestone 1 adapter (no copies of the grid inside the algorithms).
- [ ] Implement **BFS** with a FIFO queue, a visited set, and a parent map; reconstruct the path by walking parents backwards. Verify it returns *shortest* paths.
- [ ] Implement **DFS** (iterative, explicit stack) and demonstrate on a real maze why its path is legal but generally *not* shortest — keep it as an educational/utility variant (e.g. connectivity checks).
- [ ] Implement **A\*** with a priority queue on `f(n) = g(n) + h(n)` and Manhattan distance as `h`; include the closed set and the decrease-key-by-reinsertion idiom.
- [ ] Property tests: on many random seeds, `len(bfs_path) == len(astar_path)`, and both match the length of the wheel's `shortest_path` string (entry -> exit) — the wheel is your oracle.
- [ ] Benchmark BFS vs A* on a large maze (e.g. 51x51) and record expanded-node counts — concrete evidence of why the heuristic matters.
- [ ] Wire pathfinding into gameplay where useful: e.g. the EATEN ghost returning home, or a smarter distance metric (true path distance instead of straight-line) for Clyde's 8-tile rule.
- [ ] Optional debug overlay: render the current path of a selected ghost on the maze.

### Milestone 3 acceptance criteria

- [ ] All three algorithms pass tests on hand-crafted micro-mazes *and* wheel-generated mazes across many seeds.
- [ ] A* with Manhattan heuristic never expands more nodes than BFS on the same query.
- [ ] `make lint` still clean; the module has zero dependencies on game/UI code.

---

## Milestone 4 — Game Loop, Collision Detection, and Scoring

*Goal: a complete, winnable, losable game obeying the subject's rules
(VI.2, VI.4–VI.7).*

### 4.1 The loop

- [ ] Fixed-timestep game loop: input -> update (player, ghosts, timers) -> collisions -> render; game speed independent of rendering speed.
- [ ] Player movement: 4 directions via arrows/WASD, wall-checked with the Milestone 1 bitmask query, movement quantized to the grid; buffer the last input so turns feel responsive at intersections.
- [ ] Level timer (`level_max_time`, default 90 s) counting down in the HUD; define and implement your out-of-time policy (e.g. lose a life / restart level).
- [ ] Pause / resume mid-game (subject VI.7).

### 4.2 Collision detection

- [ ] Player vs pacgum / super-pacgum: consume on tile entry, update counters.
- [ ] Player vs ghost — handle **both** collision cases: same-tile overlap *and* the tile-swap (pass-through) case where two entities exchange tiles in one tick (see REFERENCE.md §2.7).
- [ ] Ghost not edible -> player loses a life and respawns at the maze center; ghosts reset. Ghost edible -> ghost enters EATEN, points awarded.
- [ ] Game over when lives reach 0.

### 4.3 Scoring & progression

- [ ] Score events, all read from config: pacgum `+X`, super-pacgum `+Y`, edible ghost `+Z`. Score never decreases (subject VI.6).
- [ ] Level is won when all pacgums are eaten; game has **at least 10 levels**; level 1 uses fixed seed 42, subsequent levels use random seeds (subject VI.1, VI.7).
- [ ] Score and remaining lives persist across levels; game is won when all levels are completed.
- [ ] Cheat mode (subject VI.5), activation documented for reviewers: invincibility, level skip, ghost freeze, extra lives, speed boost.

### Milestone 4 acceptance criteria

- [ ] A full session is playable start-to-finish: win a level, lose lives, game over, and full-game victory all reachable (use cheat mode to verify quickly).
- [ ] No crash under key-mashing, pausing at odd moments, or config edge values (0 lives, 1x1 level array entries, etc.).
- [ ] Tests for the scoring rules and the two collision cases.

---

## Milestone 5 — UI, Highscores, Packaging, and Project Management

*Goal: everything the defense checks beyond gameplay (subject V.5, VI.8,
VII–IX).*

### 5.1 User interface (subject VI.8)

- [ ] Main menu: Start Game, View Highscores (top 10 with names), Instructions, Exit.
- [ ] In-game HUD, always visible: score, lives, level, remaining time.
- [ ] Pause menu: resume / return to main menu.
- [ ] Game-over and Victory screens: final score + name entry (max 10 chars, alphanumeric and spaces only) -> back to main menu.

### 5.2 Highscore system (subject V.5)

- [ ] Persistent storage (e.g. JSON file), loaded at game start, saved at game end.
- [ ] Keep top 10 `(name, score)` entries; validate names and non-negative integer scores.
- [ ] Robust to a missing or corrupted file (start from an empty table, never crash).

### 5.3 Packaging & deployment (subject VII)

- [ ] Packaging script/spec at the repository root producing an installable, fully functional build (e.g. via PyInstaller or a zip + launcher).
- [ ] Publish as a free unlisted/private build on itch.io (or similar); include minimal in-package instructions (controls, options, configuration).
- [ ] Be able to regenerate the package on demand (asked at peer review).

### 5.4 Documentation & project management (subject VIII–IX)

- [ ] `README.md` with the mandatory first line (*"This project has been created as part of the 42 curriculum by <login>…"*, italicized) and sections: Description, Instructions, Resources (incl. how AI was used and for what), Configuration, Highscore, Maze Generation, Implementation, General Software Architecture, Project Management — in English.
- [ ] `project-management/` directory: timeline, progress tracking vs plan (this file is evidence!), design decisions, risk analysis, acceptance test plan, blocking points.
- [ ] Final pass: `make lint` and `make lint-strict` clean, docstrings everywhere, test suite green, and a dry-run of the defense (fresh clone -> `make install` -> `make run`).

### Milestone 5 acceptance criteria

- [ ] A stranger can clone, install, play, and read their way to understanding the project without asking you anything.
- [ ] The deployed platform build launches and is fully functional.
