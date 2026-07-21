# Acceptance Test Plan

"Done" is defined per subject requirement and verified by an automated
test (207 pytest cases) plus the manual defense dry-run below. The test
specification is `../TESTING_PLAYBOOK.md`; each matrix row maps to a
case.

## Automated coverage → requirement

| Subject req. | Verified by |
|---|---|
| V.1 exactly one CLI arg, no traceback | `pac-man.py` arg check; manual dry-run |
| V.2/V.3 JSON-with-comments, robust defaults, adversarial config | `test_config.py` (15), `test_engine_chaos.py` hostile-config sweep |
| V.4 wheel used as-is, failures handled | `test_maze_adapter.py` (47), single `MazeAdapterError` type |
| V.5 highscores: persist, top-10, validate, robust to bad files | `test_highscore.py` (13) |
| VI.1 level layout (corners, center, pellets) | `test_engine_parse_grid_map.py` (3) |
| VI.2 player: move, lives, respawn, win/lose | `test_engine_movement.py` (22), `test_engine_collisions.py` (13) |
| VI.3 ghosts: autonomous, chase/flee, respawn | `test_ai_*` (43), `test_ai_eaten.py` (5) |
| VI.4 pac-gums / super-pac-gums | `test_engine_movement.py` C1–C4 |
| VI.5 cheat mode (all five) | `test_engine_progression.py`, `test_ui_smoke.py` |
| VI.6 scoring, never decreases | `test_engine_progression.py`, fuzz monotonicity |
| VI.7 ≥10 levels, seeds, carry score/lives, pause, win/lose→name | `test_engine_progression.py` (15), `test_ui_smoke.py` (5) |
| VI.8 menus, HUD, pause menu, game-over/victory + name entry | `test_ui_smoke.py` (5) |
| VII packaging, regenerable | `test_packaging.py` (2), `make package` |
| Both collision cases (tile-swap) | `test_engine_collisions.py` S1–S4 + mutation check |
| Full level winnable by play | `test_engine_integration.py` (auto-pilot eat-out) |
| Determinism / no hidden RNG | `test_engine_chaos.py` replay test |
| III.1 lint + docstrings + types | `make lint`, `make lint-strict`, both clean |

## Manual defense dry-run (checklist)

1. Fresh clone → `make install` → `make run config.json` opens the game.
2. Play: eat pellets (score rises), a super-pacgum turns ghosts blue,
   eat one (score += Z), get caught (lose a life, respawn), lose all
   lives → **game over → name entry → highscore saved → main menu**.
3. Use `F5` to skip to **victory**; confirm name entry + highscore.
4. Pause with `P`/`Esc`; confirm the sim freezes and "Return to Main
   Menu" works.
5. Main menu: View Highscores shows the saved entries; Instructions
   renders; Exit quits.
6. Swap in a broken `config.json` (missing keys, wrong types, 0 lives,
   1×1 level) → still boots with defaults, no traceback.
7. `make lint` **and** `make lint-strict` → zero errors; `make test` →
   all green; `make package` → `dist/pacman-42.zip` regenerates.
