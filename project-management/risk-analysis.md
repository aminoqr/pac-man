# Risk Analysis

Likelihood (L) and Impact (I): Low / Med / High.

| # | Risk | L | I | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | Wheel swapped for another group's package at review | High | High | All wheel use isolated in `maze/adapter.py`; consumers speak only its vocabulary → one file to change | Mitigated |
| R2 | Wheel docs disagree with its code (tuple order, defaults) | High | Med | Behaviour source-verified and characterization-tested; traps documented in `CLAUDE.md` + `REFERENCE.md` §5.4 | Mitigated |
| R3 | Adversarial config at defense crashes the game | High | High | Loader never raises: clamp+log defaults, ignore unknown keys; hostile-config boot sweep in tests | Mitigated |
| R4 | Corrupt/missing highscore file crashes startup | Med | Med | `HighscoreTable.load` salvages valid rows, never raises; tested against corrupt/wrong-shape files | Mitigated |
| R5 | Coordinate axis bug (`grid[x][y]` vs `grid[y][x]`) | Med | High | Single pinned `(x,y)`/y-down convention; tested on non-square mazes | Mitigated |
| R6 | Tile-swap pass-through collision bug | Med | High | Two-case predicate + snapshot ordering; adversarial mutation test proves detection | Mitigated |
| R7 | Non-determinism (hidden RNG / wall-clock) breaks tests & replays | Med | Med | Tick-based engine; one seeded RNG owned by state; end-to-end determinism test (identical input tape → identical final state) | Mitigated |
| R8 | No display at review machine (headless/SSH) | Med | Med | MLX segfaults with no display, so a `DISPLAY`/`WAYLAND_DISPLAY` check gates `mlx_init` and degrades to the textual maze fallback; UI logic tested headlessly via the platform-neutral shell | Mitigated |
| R13 | MLX not built / wrong arch on the review machine | Med | High | Prebuilt Linux-x86_64 mlx wheel vendored (matches 42 machines); `make mlx` / `scripts/build_mlx.sh` rebuilds from source; build deps documented in README | Mitigated |
| R9 | `make lint-strict` not actually clean | Low | Med | Both lint gates run every milestone; `mypy --strict` clean across 46 files | Mitigated |
| R10 | itch.io publication can't be automated | High | Low | Out of code scope; `make package` yields the uploadable build; steps documented | Accepted / documented |
| R11 | Player-state-on-`GameState` flagged as an OOP deviation | Low | Low | Deliberate, documented (design-decisions D6); trivially refactorable if a reviewer insists | Accepted / documented |
| R12 | Level unwinnable (disconnected pellets) | Low | High | Braided maze is one connected component (asserted); a real seed-42 level is auto-played to a full eat-out win in tests | Mitigated |
