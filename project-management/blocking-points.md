# Blocking Points

Obstacles encountered and how each was resolved. Kept as an honest
record for the defense.

### B1 — Wheel docs contradict the wheel's own code
The bundled `METADATA`/README disagreed with the shipped source in five
places (constructor kwargs, default size, `exit_cell` default,
`maze_entry`/`maze_exit` tuple order, the "42" logo minimum). *Resolved:*
read the wheel source directly, characterization-tested the real
behaviour, and pinned the truth in `CLAUDE.md` + `REFERENCE.md` §5.4. The
adapter now trusts source, not docs.

### B2 — `requirements.txt` points at a path that no longer exists
The loose `mazegenerator-2.1.0-...whl` was replaced by
`mazegenerator-00001.zip`, but `requirements.txt` still referenced the
old path. *Resolved:* the wheel is extracted to the repo root (present
for `make install`), and the packaging bundle ships it so a fresh clone
installs offline.

### B3 — Dev machine missing `make` and `python3-venv`
`make install` failed (`ensurepip` unavailable; `make` not found).
*Resolved:* installed `make` and `python3.12-venv` (and `poppler-utils`
to read the subject PDF). The standard `make install` → `make run` flow
now works end to end; the earlier `get-pip.py` bootstrap is no longer
needed.

### B4 — Fixed-timestep vs. rendering speed
Naively moving per frame ties game speed to frame rate. *Resolved:* the
engine advances in fixed 10 Hz ticks; the UI accumulates real elapsed
time and runs catch-up ticks, so gameplay speed is frame-rate
independent (`REFERENCE.md` §2.1).

### B5 — `mypy --strict` false positives on enum identity in tests
Strict-equality flagged successive `is Screen.X` / `is GhostMode.X`
assertions on the same mutated attribute as "non-overlapping", because
mypy keeps the first literal narrowed across opaque method calls.
*Resolved:* read the value through a tiny typed accessor (`_screen`,
`ghost_mode`) that widens the narrowing — no `# type: ignore` scattered,
and both lint gates stay clean.

### B6 — Vacuous level-win on empty scripted stages
The win check (`no pellets left`) fired immediately on hand-built test
stages that intentionally have no pellets. *Resolved:* the win requires
the level to have *had* pellets at placement time — real levels always
do; only bare test stages were affected.

### B8 — "MLX for Python" and the graphics rewrite
An early build used pygame under the subject's "MLX or similar" clause.
When the requirement was clarified to real MLX, the initial read was
that no Python MLX exists (MLX is a C library; `pip install mlx` is
Apple's unrelated ML framework). That was **wrong**: 42 ships
`mlx_CLXV`, an official MiniLibX with a Python wrapper. *Resolved:*
built its wheel from source (clang + Vulkan + XCB dev libs), vendored it
like the maze wheel, and rewrote the UI against it. The decoupled
shell/driver split (design-decisions D12) kept the change isolated to
`ui/app.py` + a new `ui/shell.py`, and the engine untouched.

### B9 — MLX segfaults with no display
MLX's C layer core-dumps (uncatchable from Python) when it can't reach a
display, so `except` around `mlx_init` wasn't enough for headless
machines. *Resolved:* a cheap `DISPLAY`/`WAYLAND_DISPLAY` env check
gates MLX and routes to the textual fallback instead of crashing.

### B7 — itch.io publication cannot be automated
Publishing needs the author's account (subject VII). *Resolved as
out-of-scope:* `make package` produces the uploadable
`dist/pacman-42.zip`; upload steps are documented in the bundle's
`INSTRUCTIONS.txt` and the root README. This is the one requirement left
to a manual human step.
