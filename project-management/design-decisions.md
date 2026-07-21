# Design Decisions

The load-bearing choices, each with the rationale and the alternative
that was rejected. Deeper theory lives in `../REFERENCE.md`.

### D1 — The wheel behind a single anti-corruption layer
`maze/adapter.py` is the **only** module allowed to import
`mazegenerator`. Everything else consumes its vocabulary
(`is_walkable`, `neighbors`, `corners`, …). *Why:* the wheel is
re-installed as-is at peer review and may be swapped for another group's
package; isolating it means only one file changes. *Rejected:* touching
the raw grid throughout — fast to write, catastrophic to maintain.

### D2 — Tick-based, headless engine
Every timer is a tick counter (10 ticks/second), never a wall-clock
read; the engine never imports the graphics library. *Why:* makes pause
trivial and lets the tests drive the whole game deterministically
without a window. *Rejected:* frame-coupled movement (speed depends on
the machine).

### D3 — Ghost AI as three decoupled layers
*When* (wave clock) / *what* (four target formulas) / *how* (one shared
intersection rule) are separate. *Why:* each is unit-testable alone, and
adding a personality never touches movement. Follows `REFERENCE.md` §4.

### D4 — Pathfinding depends on a Protocol, not the maze
BFS/DFS/A\* run against a structural `MazeGraph` Protocol, so the package
imports nothing from maze/game/UI. *Why:* zero coupling; the wheel is
the test oracle, not a dependency.

### D5 — Collision predicate covers the tile-swap case
Contact is `P_t==G_t OR (P_t==G_{t-1} AND G_t==P_{t-1})`, resolved in one
pass after all movement using pre-movement snapshots. *Why:* a
co-location-only check silently reintroduces the 1980 arcade
pass-through bug; a mutation test proves the swap rows have teeth.

### D6 — Player state on `GameState`, ghosts as a `Ghost` class
Player fields (tile, facing, buffer, lives) live on `GameState`; ghosts
are a dedicated class. *Why:* the player is a singleton whose state is
inseparable from the load-bearing per-tick ordering and tile-swap
snapshots, so co-locating it keeps that logic auditable in one place;
ghosts are four independent AI agents, which *is* a class. *Trade-off
noted:* CLAUDE.md lists `Player` as an example entity class — a future
extraction is low-risk but was judged unnecessary churn. (This is the
one deliberate deviation from the "every entity is its own class"
reading, and it is documented rather than hidden.)

### D7 — Adversarial config and highscore files
The config loader and the highscore store **never raise**: bad values
clamp to defaults (logged), bad files degrade to empty/salvaged. *Why:*
the config is swapped at defense and files can be corrupt; "no crash"
is a graded requirement (subject IV, V.3, V.5).

### D8 — Pinned policies where the spec left a choice
Recorded so reviewers see them as decisions, not accidents: Pinky's
legacy "up = up-and-left" overflow quirk is **not** reproduced (straight
up); Clyde's 8-tile check uses straight-line distance (arcade-faithful),
with a wall-aware upgrade available via `distance_map`; the player may
reverse instantly (ghosts may not); out-of-time costs a life and resets
the level; super-pacgums count toward level completion; a respawning
eaten ghost is never re-frightened.

### D12 — MLX graphics via a decoupled shell/driver split
The subject mandates MLX (chapter IV). The graphics layer is the
official 42 MiniLibX Python wrapper (`mlx_CLXV`), and the UI is split in
two: `ui/shell.py` holds the entire screen FSM + input handling as a
platform-neutral `GameShell` driven by abstract `Action` values (no
graphics import); `ui/app.py` is the thin MLX driver that renders the
shell's state and maps MLX keysyms to `Action`s. *Why:* MLX's C event
loop cannot run headless, so putting all UI *logic* behind the shell
keeps it unit-testable without a window (216 tests, no display), the
same anti-corruption discipline used for the maze wheel. MLX has no
shape primitives, so the board is drawn into an off-screen image buffer
(walls cached per level, entities layered on top) and blitted; text uses
`mlx_string_put`. *Note:* an earlier build used pygame under the "MLX or
similar" clause; it was replaced entirely with real MLX once the campus
requirement was confirmed. No `pygame` remains.

### D9 — Zip + launcher for packaging
`make package` builds a self-contained `dist/pacman-42.zip` (source +
wheel + `run.sh`/`run.bat` + instructions). *Why:* pure standard
library, cross-platform, and regenerable on demand at peer review.
*Rejected as the primary path:* PyInstaller — heavier, OS-specific
binary; can be added later for an itch.io drop.

### D10 — `(x, y)` with `y` downward, walls as 4-bit masks
The single most bug-prone convention, pinned project-wide and tested on
non-square mazes so the `grid[x][y]` vs `grid[y][x]` swap can't hide.

### D11 — Path-based ghost movement on braided mazes
Ghosts navigate CHASE/SCATTER by **true shortest path**
(`choose_target_exit`, A\* next-hop) rather than the wall-blind greedy
straight-line rule. *Why:* the greedy myopia is arcade-faithful on
hand-designed boards, but this project's mazes come from the braided
wheel generator, which is full of micro-loops. On those, a greedy ghost
gets trapped orbiting a wall while straight-line distance never improves
— it visibly "spins in one place," especially during the corner-facing
scatter phase. True graph distance (the Milestone 3 upgrade
`REFERENCE.md` §3.7 explicitly anticipates for exactly this) has no such
local minima, so ghosts roam and hunt properly. The four personalities
are preserved — they still pursue distinct *target tiles* (Blinky the
player, Pinky 4-ahead, Inky the flank, Clyde pursue-or-flee); only the
*how* of reaching the target changed. The greedy `choose_exit` is kept
as the documented classic primitive, its unit tests, and the
total-safety fallback when a target is unreachable. *Trade-off:*
path-optimal ghosts are marginally less "escapable" than the arcade's
deliberately-fallible ones, which is why frightened flight stays a
seeded random walk — the player always has an out.
