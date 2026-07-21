# Progress Tracking

The live tracker is [`../PLAN.md`](../PLAN.md): every checkbox is ticked
only when its milestone's acceptance criteria pass, and each ticked item
carries a note pointing at the code/test that satisfies it. That file is
the primary evidence; this page summarizes status at the M5 close.

## Status at Milestone 5 completion

| Milestone | Status | Verification |
|---|---|---|
| 1 — Environment, wheel, maze parsing | ✅ Done | `test_maze_adapter.py` (47), `test_config.py` (15), `test_engine_parse_grid_map.py` (3) |
| 2 — Ghost AI & state machine | ✅ Done | `test_ai_targeting.py` (16), `test_ai_wave.py` (13), `test_ai_intersection.py` (15, incl. path-based nav), `test_ai_personalities.py` (4) |
| 3 — Pathfinding (BFS/DFS/A\*) | ✅ Done | `test_pathfinding_micro.py` (15), `test_pathfinding_oracle.py` (4), `test_pathfinding_benchmark.py` (1), `test_ai_eaten.py` (5) |
| 4 — Game loop, collisions, scoring | ✅ Done | `test_engine_movement.py` (22), `test_engine_collisions.py` (13), `test_engine_progression.py` (15), `test_engine_chaos.py` (3), `test_engine_integration.py` (1) |
| 5 — UI, highscores, packaging, PM | ✅ Done | `test_highscore.py` (14), `test_ui_smoke.py` (7, shell FSM + keysym map), `test_packaging.py` (2) |

**Totals:** 216 pytest cases, all green. `flake8 .` and
`mypy . --strict` both report zero issues across 47 source files.

## Quality gates (enforced every milestone)

- `make lint` — `flake8 .` + `mypy` with the mandatory flags.
- `make lint-strict` — `flake8 .` + `mypy . --strict`.
- `make test` — the full pytest suite.
- Type hints + PEP 257 docstrings on every function/class (subject
  III.1, graded).

## Deferred to the human (out of scope for code)

- **itch.io publication** (subject VII): requires the author's account.
  `make package` produces the uploadable `dist/pacman-42.zip`; upload
  steps are documented in the bundle's `INSTRUCTIONS.txt` and the root
  README.
