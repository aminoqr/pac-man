# Timeline

Milestones were executed in dependency order; each left the repository
runnable and lint-clean before the next began.

| # | Milestone | Key deliverables | Exit gate |
|---|---|---|---|
| 0 | Design & scaffolding | `PLAN.md`, `REFERENCE.md`, `TESTING_PLAYBOOK.md`, package skeleton, `Makefile`, `.gitignore`, config schema | Repo installs; lint clean |
| 1 | Wheel integration & maze parsing | `maze/adapter.py` (anti-corruption layer), `Direction` enum, bitmask queries, ASCII renderer, entity placement | Reproducible seed-42 maze; malformed config still boots |
| 2 | Ghost AI & state machine | `ai/ghost.py`, `ai/wave.py`, `ai/targeting.py`, `ai/intersection.py` — 4 personalities, wave clock, frightened/eaten | Personalities differ deterministically; mode-flip reversal tested |
| 3 | Classical pathfinding | `pathfinding/graph.py|search.py|debug.py` — BFS/DFS/A\*, distance map, reachability | Wheel-oracle agreement over ~150 seeds; A\* ≤ BFS expansions |
| 4 | Game loop, collisions, scoring | `game/engine.py` tick pipeline, `game/session.py` progression, `ui/app.py` playable loop | Full level winnable; tile-swap + co-location collisions; 10k-tick fuzz |
| 5 | UI, highscores, packaging, docs | `highscore/store.py`, UI screen FSM, `packaging/make_package.py`, `README.md`, this directory | `make lint` **and** `make lint-strict` clean; 216 tests green; fresh-clone dry run |

**Test growth by milestone (cumulative):** M1 ≈ 65 → M2 ≈ 108 → M3 ≈ 133
→ M4 ≈ 188 → M5 = 216 (incl. the MLX migration).

**Environment note (M4/M5):** the dev machine lacked `make` and
`python3-venv`; both were installed, and `poppler-utils` was added to
read the subject PDF. The bootstrap is captured in
[blocking-points.md](blocking-points.md).
