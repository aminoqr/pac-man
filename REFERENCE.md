# 42 Pacman — The Masterclass Reference

> A theory companion for the "Pacman — Ghosts! More ghosts!" project.
> No implementation code here — only the mathematics, the computer science,
> and the design reasoning you need to build every part yourself.
> Track your build progress in [PLAN.md](PLAN.md).

**Contents**

1. [Graph Theory over Grid Mazes](#1-graph-theory-over-grid-mazes)
2. [Movement, Time, and Collision on a Grid](#2-movement-time-and-collision-on-a-grid)
3. [Classical Pathfinding Mathematics](#3-classical-pathfinding-mathematics)
4. [Ghost AI Determinism](#4-ghost-ai-determinism)
5. [Integrating the `.whl` Component](#5-integrating-the-whl-component)
6. [Glossary and Further Reading](#6-glossary-and-further-reading)

---

## 1. Graph Theory over Grid Mazes

### 1.1 The central idea

A maze *looks* like a picture, but for every algorithm in this project it is a
**graph**: a set of vertices \(V\) and edges \(E\). Formally, the maze is

\[ G = (V, E), \qquad V = \{(x, y) \mid 0 \le x < W,\; 0 \le y < H\} \]

where each **cell** of the grid is a vertex, and an edge \(\{u, v\} \in E\)
exists exactly when \(u\) and \(v\) are side-by-side neighbors **and** no wall
separates them. Three properties of this graph shape everything you will do:

- **Unweighted.** Every step from a cell to a neighbor costs exactly 1. There
  are no "expensive" tiles. This is why BFS alone already finds shortest paths
  (§3.2) — you never need Dijkstra here.
- **Undirected.** If you can walk from \(u\) to \(v\), you can walk back.
  Walls block both directions symmetrically (the generator always clears the
  wall bit on *both* sides of an opening).
- **Sparse.** A vertex has at most 4 neighbors, so
  \(|E| \le 2 \cdot |V|\) — the number of edges is linear in the number of
  cells. This makes \(O(V + E)\) effectively \(O(V)\), i.e. \(O(W \cdot H)\).

The degree \(\deg(v)\) of a cell (its number of open sides) classifies it:

| Degree | Meaning | Relevance |
|---|---|---|
| 0 | isolated cell | the "42" logo blocks (value 15) — not walkable |
| 1 | dead end | eliminated by the generator's braiding pass |
| 2 | corridor / corner | ghosts have no choice: they keep going |
| 3–4 | **intersection** | the only places where AI decisions happen (§4.5) |

This classification is the deep reason ghost AI is cheap: in a corridor a
ghost is *committed*; computation only occurs at vertices of degree ≥ 3.

### 1.2 Coordinate axes — get this right once, forever

Screen-oriented grids use a coordinate system that trips up everyone at least
once, because the **y-axis points down**:

```
      x →  0   1   2   3
    y
    ↓  0  [ ] [ ] [ ] [ ]
       1  [ ] [ ] [ ] [ ]
       2  [ ] [ ] [ ] [ ]
```

- Column index = \(x\), increasing **rightward** (East).
- Row index = \(y\), increasing **downward** (South).
- Moving **North** (up on screen) means \(y \mathrel{-}= 1\), not \(+1\).

The maze data structure is a list of rows, so a cell is addressed as
`grid[y][x]` — **row first, column second**. Mixing up `grid[x][y]` vs
`grid[y][x]` is the single most common bug in grid games; it hides on square
mazes (where \(W = H\)) and explodes on rectangular ones. Defend yourself:

1. Pick **one** convention for your whole codebase (recommend: positions are
   `(x, y)` tuples, arrays indexed `grid[y][x]`) and write it at the top of
   your maze module.
2. Test early with a **non-square** maze (e.g. 9 wide x 5 tall) — index-order
   bugs crash or visibly distort immediately.
3. Be suspicious at every boundary with foreign code — the provided wheel has
   its own convention (§5.4).

### 1.3 Walls as bitmasks — the bounding box of a cell

This project's generator does *not* represent walls as separate "wall tiles".
Instead every cell stores its own four-sided bounding box in the 4 low bits of
an integer — one bit per side:

| Bit | Value | Wall | Blocks movement toward |
|---|---|---|---|
| 0 | 1 | North | the cell above \((x, y-1)\) |
| 1 | 2 | East | the cell to the right \((x+1, y)\) |
| 2 | 4 | South | the cell below \((x, y+1)\) |
| 3 | 8 | West | the cell to the left \((x-1, y)\) |

A cell value is therefore an integer in \([0, 15]\):

- `0` — open on all four sides (a plaza cell).
- `6` = `4 | 2` — walls South and East (a top-left inner corner shape).
- `15` — sealed on all sides. In this generator that means an **isolated
  block**: the cells forming the "42" logo. Treat value 15 as *not walkable*.

Two facts you should prove to yourself on paper:

**Consistency invariant.** For adjacent cells the wall is stored twice — the
East bit of \((x,y)\) and the West bit of \((x+1,y)\) describe the *same*
physical wall, and the generator keeps them synchronized. Your movement test
only ever needs to check the *current* cell's bit.

**The movement predicate.** "Can I move in direction \(d\) from cell \(c\)?"
reduces to a single bitwise AND:

\[ \text{canMove}(c, d) \iff (\text{grid}[c_y][c_x] \;\&\; \text{bit}(d)) = 0 \]

That is: the move is legal iff the bit for that side is **not** set. This is
an \(O(1)\) operation with no lookup tables, no neighbor reads, no bounds
checks (the outer border cells always carry their outward wall bits, so the
bitmask itself acts as the bounding box of the maze — you can never walk off
the edge if you respect the bits).

**Reading a wall byte.** Given value 9: \(9 = 8 + 1 = \text{West} +
\text{North}\). Practice decoding a few by hand; you will read raw maze dumps
constantly while debugging.

### 1.4 The direction enumeration

Every subsystem — input handling, ghost decisions, pathfinding, the wheel's
`shortest_path` string — speaks the language of the four cardinal directions.
Define **one** canonical enumeration and attach to each member everything
anyone will ever ask of it:

| Direction | \(\Delta x\) | \(\Delta y\) | Wall bit | Opposite | Letter |
|---|---|---|---|---|---|
| North | 0 | −1 | 1 | South | `N` |
| East | +1 | 0 | 2 | West | `E` |
| South | 0 | +1 | 4 | North | `S` |
| West | −1 | 0 | 8 | East | `W` |

Why bundle all of this into the enum rather than scattering `if` chains?

- **Movement**: `next = (x + d.dx, y + d.dy)` — one line, no branching.
- **Wall tests**: `cell & d.bit` — the predicate from §1.3.
- **The no-reverse rule** (§4.5) needs `d.opposite` constantly.
- **The wheel's path strings** (`"NEESSW..."`) decode via `d.letter`.

Note the deliberate ordering North, East, South, West = bits 1, 2, 4, 8 —
clockwise from the top, matching the generator. Keep this order in your enum
so the mapping between direction index \(i\) and bit \(2^i\) stays mechanical.

### 1.5 Implicit vs explicit graphs

You never need to *build* an adjacency list. The grid plus the wall bits *is*
the graph, presented **implicitly**: given any vertex, you can enumerate its
neighbors on demand in \(O(1)\) by testing the four direction bits. All the
algorithms in §3 are written against exactly one primitive:

\[ \text{neighbors}(v) = \{\, v + d \mid d \in \text{Directions},\ \text{canMove}(v, d) \,\} \]

This is an important architectural insight: pathfinding code should depend on
a `neighbors` function, not on the grid's storage format. If tomorrow the maze
became hexagonal or 3-D, BFS would not change by one character.

### 1.6 Perfect vs braided mazes — why it matters for gameplay

- A **perfect maze** is a *spanning tree* of the grid graph: it touches every
  cell and contains exactly \(|V| - 1\) edges, hence **no cycles** and exactly
  one simple path between any two cells. Great for puzzles, terrible for
  Pac-Man: a tree is full of dead ends, and a player chased into a dead end
  has no counterplay.
- A **braided (imperfect) maze** adds extra edges, creating **cycles**. The
  provided generator explicitly removes *every* dead end (each degree-1 cell
  gets one extra opening carved), so every corridor is part of a loop and a
  chased player always has an escape route. This project sets
  `perfect=False` for exactly this reason (subject V.4).

Consequence for you: with cycles present, *multiple distinct paths* exist
between two points — which is precisely what makes "shortest" a non-trivial
question and BFS/A* worth implementing.

---

## 2. Movement, Time, and Collision on a Grid

### 2.1 Two clocks: simulation vs rendering

A game has two notions of time. **Render time** is how often you draw;
**simulation time** is how often the world advances. If you couple them
("move the player 2 pixels every frame"), game speed depends on the machine's
frame rate. The standard fix is a **fixed-timestep loop**: accumulate real
elapsed time, and every time the accumulator exceeds a fixed quantum
\(\Delta t\) (e.g. 1/60 s), run exactly one simulation *tick*. All gameplay
speeds — player, ghosts, frightened ghosts — become "moves per tick" or
"ticks per tile", which makes them deterministic and testable.

### 2.2 Tile-quantized movement

Entities logically live on tiles (integers), but move smoothly on screen
(pixels). The classic resolution:

- **Logical position** = the tile \((x, y)\), plus a direction, plus a
  fractional progress \(p \in [0, 1)\) toward the next tile.
- Decisions (turning, wall checks, eating) happen only when \(p\) crosses a
  tile boundary — i.e. at **tile centers**.
- Rendering interpolates: draw at
  \(\text{pixel} = \text{tile} \cdot s + p \cdot d \cdot s\)
  for tile size \(s\) and direction vector \(d\).

Differential speeds fall out naturally: a ghost at 80 % player speed simply
advances its \(p\) by \(0.8\) of the player's increment per tick.

### 2.3 Input buffering (why good Pac-Man "feels" responsive)

If you only accept a turn command at the exact tick the player sits on a tile
center, turning feels unresponsive. The fix: store the *last requested
direction* separately from the *current direction*. At every tile center, try
the requested direction first (if legal, turn), else continue in the current
direction (if legal), else stop. This 3-line policy is the difference between
"clunky" and "arcade-tight".

### 2.4 Timers as countdowns in simulation time

The level timer (`level_max_time`), the frightened-mode countdown, the
scatter/chase wave schedule, the eaten-ghost respawn delay — model all of them
as *tick counters*, not wall-clock reads. This keeps pause trivial (stop
ticking, everything stops coherently) and makes tests deterministic.

### 2.5 Eating pacgums

When the player's logical tile changes, check the tile's contents: pacgum →
remove, `score += X`, decrement the remaining count; super-pacgum → remove,
`score += Y`, trigger frightened mode (§4.6). Win-the-level check is just
`remaining == 0`. Keep the pellet layer as its own grid or set, separate from
the wall grid — different lifetimes, different concerns.

### 2.6 Player–ghost contact, case 1: co-location

The obvious test: after moving everyone in a tick, if a ghost's tile equals
the player's tile → contact. Resolution depends on the ghost's state: normal →
player loses a life and respawns at the center, all ghosts reset; frightened →
ghost is eaten (`score += Z`, ghost enters EATEN and heads home).

### 2.7 Player–ghost contact, case 2: the tile-swap (pass-through) problem

Discrete movement has a notorious blind spot. Suppose in tick \(t\) the player
is at tile \(A\) and a ghost at adjacent tile \(B\), moving toward each other.
After the tick, the player is at \(B\) and the ghost at \(A\): **they swapped
tiles without ever occupying the same one**. A same-tile check misses this,
and the player "phases through" a ghost — the original 1980 arcade game
actually *has* this bug, and players exploited it.

The robust test after each tick checks both conditions:

\[ \text{collide} \iff \big(P_t = G_t\big) \;\lor\; \big(P_t = G_{t-1} \land G_t = P_{t-1}\big) \]

i.e. same tile now, **or** each now stands where the other stood before.
Store previous-tick positions to make this a cheap comparison. If you use
sub-tile fractional positions (§2.2), an alternative is a distance threshold
\(\lVert P - G \rVert < \varepsilon\) in continuous coordinates — but the
swap test is exact, simpler to reason about, and easy to unit-test.

### 2.8 The game state machine (macro level)

Above the maze sits a small finite-state machine for the *application*:
`MENU → PLAYING ⇄ PAUSED`, `PLAYING → LEVEL_WON → PLAYING (next level)`,
`PLAYING → GAME_OVER | VICTORY → NAME_ENTRY → MENU`. Draw it before coding.
Every screen in subject VI.8 is a state; every allowed button is a transition.
Bugs like "the timer keeps running while paused" are, in this framing,
transitions you forgot to define.

---

## 3. Classical Pathfinding Mathematics

### 3.1 The problem statement

Given the maze graph \(G = (V, E)\) (unweighted, undirected, §1.1), a start
vertex \(s\) and goal vertex \(g\): find a path \(s \rightsquigarrow g\),
ideally one of minimum length. Define \(d(u, v)\) = the number of edges on a
shortest path — the *graph distance*. Note immediately that graph distance is
**not** straight-line distance: two cells can be side-by-side across a wall
and yet 30 steps apart through the corridors. This gap between geometric
closeness and topological closeness is the entire subject of heuristics
(§3.5) and the flaw in naive chase AI (§4.5).

### 3.2 Breadth-First Search — the shortest-path workhorse

**Mechanism.** Explore in expanding "rings": first all vertices at distance 1
from \(s\), then all at distance 2, and so on. The data structure that
enforces this order is a **FIFO queue**. Bookkeeping: a *visited* set (never
enqueue a vertex twice) and a *parent* map (each vertex remembers who
discovered it).

```
BFS(s, g):
    queue ← [s];  visited ← {s};  parent[s] ← none
    while queue not empty:
        u ← pop-front(queue)
        if u = g: return reconstruct(parent, g)
        for v in neighbors(u):
            if v ∉ visited:
                visited ← visited ∪ {v};  parent[v] ← u
                push-back(queue, v)
    return no-path
```

**Why it is optimal (the invariant worth memorizing).** At every moment the
queue contains vertices of at most two consecutive distances \(k\) and
\(k+1\), in order. Therefore vertices are *dequeued in non-decreasing distance
order*, so the first time \(g\) is dequeued, no shorter route to it can exist.
On an unweighted graph, BFS *is* Dijkstra with all edge weights equal to 1 —
the FIFO queue plays the role of the priority queue for free.

**Path reconstruction.** Follow `parent` pointers from \(g\) back to \(s\)
and reverse. The parent map is a *BFS tree* rooted at \(s\); paths in it are
shortest paths from \(s\) to everything explored.

**Complexity.** Each vertex enters the queue at most once, each edge is
examined at most twice (once per endpoint):
time \(O(V + E)\), space \(O(V)\) for the visited set, queue, and parents.
On our sparse grid, \(E \le 2V\), so both are \(O(W \cdot H)\).

**Character.** BFS explores a symmetric "flood" around the start — it wastes
effort expanding away from the goal, because it has no idea where the goal
is. That waste is exactly what A* removes.

### 3.3 Depth-First Search — and why it does *not* find shortest paths

**Mechanism.** Identical skeleton, one change: replace the FIFO queue with a
**LIFO stack** (or recursion, which is a hidden stack — prefer the explicit
stack in Python to dodge recursion limits on big mazes). DFS plunges down one
corridor as far as it can before backtracking.

**The crucial negative result.** The stack destroys the distance-ordering
invariant: DFS may reach \(g\) via a wildly circuitous route and report it,
even though a 3-step path existed. On a braided maze (which is full of
cycles, §1.6) DFS paths are typically far from optimal. Construct a small
cyclic example on paper and trace both algorithms until you can *see* this.

**So why learn it?** DFS is the right tool for questions of *existence and
structure* rather than *distance*: is the maze fully connected? (run DFS,
count reached cells) — cycle detection — connected components — and,
historically, maze *generation* itself: the provided wheel carves its maze
with a randomized iterative DFS, which is why its corridors have that long,
winding character.

**Complexity.** Same as BFS: time \(O(V + E)\). Worst-case stack depth is
\(O(V)\) (one long snake corridor). In *huge* implicit graphs DFS can be run
with \(O(\text{depth})\) memory, which is why it survives in domains like
game-tree search, but on grid mazes it holds no space advantage worth the
loss of optimality.

### 3.4 A\* — best-first search with a compass

**The idea.** BFS treats all frontier vertices equally. A\* ranks them:
always expand the vertex that *looks* cheapest overall, where "looks" combines
hard knowledge and an estimate:

\[ f(n) = \underbrace{g(n)}_{\text{exact cost } s \to n} + \underbrace{h(n)}_{\text{estimated cost } n \to g} \]

- \(g(n)\): length of the best known path from start to \(n\) (built up as
  you search, like BFS distances).
- \(h(n)\): the **heuristic** — a cheap formula estimating the remaining
  distance to the goal (§3.5).
- The frontier becomes a **min-priority queue** keyed on \(f\).

```
A*(s, g):
    open ← min-heap {(f=h(s), s)};  gscore[s] ← 0;  closed ← ∅
    while open not empty:
        u ← pop-min(open)
        if u = g: return reconstruct(parent, g)
        if u ∈ closed: continue            # stale heap entry, skip
        closed ← closed ∪ {u}
        for v in neighbors(u):
            tentative ← gscore[u] + 1
            if v ∉ gscore or tentative < gscore[v]:
                gscore[v] ← tentative;  parent[v] ← u
                push(open, (tentative + h(v), v))
```

Note the "push again and skip stale entries" idiom — standard binary heaps
have no efficient decrease-key, so we insert duplicates and discard outdated
ones on pop. Harmless: the first pop of any vertex carries its best \(f\).

**Correctness conditions.** A\* returns a *provably shortest* path if the
heuristic is **admissible** — it never overestimates:
\(h(n) \le d(n, g)\) for all \(n\). If \(h\) is additionally **consistent**
(triangle-inequality-like: \(h(n) \le 1 + h(n')\) for every edge
\(n \to n'\)), then each vertex needs to be expanded at most once and the
closed set is safe. Both heuristics below are admissible *and* consistent on
our grid.

**Two limiting cases give intuition.** With \(h \equiv 0\), A\* *is*
BFS/Dijkstra (pure caution). With \(h\) exact (\(h = d\)), A\* walks straight
along an optimal path expanding almost nothing (pure clairvoyance). Real
heuristics live between, and the better \(h\) approximates \(d\) from below,
the fewer vertices are expanded.

**Complexity.** Worst case, A\* degenerates to expanding everything:
\(O((V + E) \log V)\) time (the \(\log\) from heap operations) and
\(O(V)\) space. Its value is not asymptotic — it is the massive *typical-case*
reduction in expanded vertices. Benchmark it (PLAN.md milestone 3): count
expansions for BFS vs A\* across seeds and see the difference yourself.

### 3.5 The heuristics: Manhattan vs Euclidean

For grid cells \(n = (x_1, y_1)\) and \(g = (x_2, y_2)\):

**Manhattan distance** (a.k.a. taxicab, \(L_1\) norm):

\[ h_M(n) = |x_1 - x_2| + |y_1 - y_2| \]

**Euclidean distance** (straight line, \(L_2\) norm):

\[ h_E(n) = \sqrt{(x_1 - x_2)^2 + (y_1 - y_2)^2} \]

Both are admissible for 4-directional movement, but they are **not equally
good**, and the reasoning is worth internalizing:

1. **Manhattan is the exact distance in an empty (wall-less) grid** with
   4-directional moves: to change \(x\) by \(a\) and \(y\) by \(b\) you need
   at least \(a + b\) unit steps, and that bound is achievable. Walls only
   ever *lengthen* real paths, so \(h_M(n) \le d(n, g)\) always — admissible,
   and as *tight* as any wall-ignorant formula can be.
2. **Euclidean is admissible but strictly weaker here**: by the triangle
   inequality \(h_E \le h_M\) always (with equality only on straight lines).
   A smaller heuristic means less guidance, which means A\* expands *more*
   vertices. Euclidean is the right choice only when the agent can actually
   move diagonally/freely — not our case. Plus it costs a square root per
   evaluation.
3. **Dominance principle.** If two admissible heuristics satisfy
   \(h_1(n) \ge h_2(n)\) everywhere, \(h_1\) is said to *dominate* \(h_2\)
   and A\* with \(h_1\) never expands more vertices (up to tie-breaking).
   Here \(h_M\) dominates \(h_E\): **use Manhattan.**
4. **The over-estimation cliff.** Multiply Manhattan by 1.5 and A\* becomes
   *greedy-ish*: often faster, but the optimality proof collapses and it can
   return longer paths. This trade (weighted A\*) is a real technique — just
   know you are leaving the land of guarantees.

### 3.6 Side-by-side summary

| | BFS | DFS | A\* (Manhattan) |
|---|---|---|---|
| Frontier structure | FIFO queue | LIFO stack | min-heap on \(f = g + h\) |
| Finds shortest path | **yes** (unweighted) | no | **yes** (admissible \(h\)) |
| Time | \(O(V+E)\) | \(O(V+E)\) | \(O((V+E)\log V)\) worst; far less typical |
| Space | \(O(V)\) | \(O(V)\) | \(O(V)\) |
| Exploration shape | uniform flood from \(s\) | one deep probe + backtrack | ellipse stretched toward \(g\) |
| Best use in this project | shortest paths, distance maps | connectivity checks; understanding the generator | fast targeted queries (eaten ghost going home) |

### 3.7 A tool worth knowing: the distance map (single-source BFS)

Run BFS from the *player* without a goal and record every cell's distance:
one \(O(V)\) pass yields \(d(\text{player}, c)\) for **all** cells \(c\).
Ghosts can then make globally informed decisions ("which neighbor decreases
true distance to the player?") by table lookup, with zero per-ghost searches.
This "flow field" technique is how you would upgrade the classic ghost AI
(§4.5) from straight-line scoring to true-path scoring — and it also gives an
exact test for Clyde's 8-tile radius using path distance instead of geometry.

---

## 4. Ghost AI Determinism

### 4.1 The grand design: one algorithm, four personalities

The most beautiful fact about the 1980 ghost AI: **all four ghosts run the
identical decision algorithm.** Their famous personalities emerge from a
single parameter — the *target tile* each one computes. No randomness in
chase, no cheating, no pathfinding even: just deterministic local greedy
steering toward a per-ghost target. The design decomposes as:

```
global mode timer (scatter/chase waves, frightened override)
        │  determines
        ▼
per-ghost TARGET TILE   ←  the ONLY thing that differs between ghosts
        │  consumed by
        ▼
shared intersection rule (§4.5): local greedy step toward target
```

Determinism is a *feature*: identical inputs give identical games, which made
arcade patterns possible and makes your unit tests possible.

### 4.2 The global state machine and its timing waves

Ghost behavior is driven by a global mode, switching on a fixed schedule
measured in simulation time (§2.4). The classic level-1 wave table:

| Phase | Mode | Duration |
|---|---|---|
| 1 | Scatter | 7 s |
| 2 | Chase | 20 s |
| 3 | Scatter | 7 s |
| 4 | Chase | 20 s |
| 5 | Scatter | 5 s |
| 6 | Chase | 20 s |
| 7 | Scatter | 5 s |
| 8 | Chase | forever |

Higher levels shorten the scatter phases (the arcade eventually cut them to
1/60 s — effectively permanent chase). The *rhythm* is the point: periodic
scatter phases release pressure on the player and pull the pack apart so it
must re-converge, creating the game's tension cycle. Two rules complete the
machine:

- **Mode-change reversal.** Every Scatter↔Chase transition forces all ghosts
  to instantly reverse direction. This is the only event that can make a
  ghost turn 180°, and it doubles as the player's audible/visible cue.
- **Frightened is an overlay, not a phase.** Eating a super-pacgum starts a
  separate frightened countdown and *pauses* the wave timer; when frightened
  ends, the wave resumes where it left off.

### 4.3 State machine per ghost

Each ghost also carries a private state interacting with the global mode:

```
            global timer                    global timer
  SCATTER ─────────────────► CHASE ◄───────────────── SCATTER
     ▲  ◄─────────────────────┘
     │            super-pacgum eaten (from either)
     │                        │
     │                        ▼
  (rejoin                FRIGHTENED ── timer expires ──► back to global mode
   global            (slower, random moves,
   mode)              edible)     │ eaten by player
     │                            ▼
     └──── wait ~5–10 s ────── EATEN
           at home corner   (return to home corner)
```

In this project's variant (subject VI.3), an eaten ghost *respawns at its
corner after a while* — the corner plays the role of the arcade's central
ghost house. The EATEN journey home is a perfect consumer for your A\*
implementation (§3.4): the target is fixed, the query is one-off.

### 4.4 The four target formulas

Let \(P\) be Pac-Man's tile and \(\hat{u}\) the unit vector of Pac-Man's
current facing direction. In **scatter mode** every ghost targets its own
home corner — an unreachable-ish fixed point that makes it orbit that corner
(a nice property of the greedy rule + no-reverse rule: unreachable targets
produce patrol loops). In **chase mode**:

**Blinky (red) — "Shadow", the pursuer.**
\[ T_B = P \]
Targets Pac-Man's exact tile. Relentless, and deadly in long corridors. In
the arcade he also speeds up late in a level ("Cruise Elroy" mode, when few
pellets remain) — an optional flourish for your version.

**Pinky (pink) — "Speedy", the ambusher.**
\[ T_P = P + 4\hat{u} \]
Targets the tile **4 ahead of Pac-Man's mouth**. She aims not at you but at
where you are *going*, so Blinky+Pinky form a pincer: one behind, one ahead.
The infamous **overflow quirk**: in the original Z80 code, when Pac-Man faces
*up*, the 16-bit target arithmetic overflowed and produced "4 up **and** 4
left". Reproducing it is optional — but *document* whichever behavior you
choose; determinism you can explain is the goal.

**Inky (cyan) — "Bashful", the flanker.**
The only two-anchor formula. Take the pivot two tiles ahead of Pac-Man,
then reflect Blinky's position through it (i.e. double the vector from
Blinky \(B\) to the pivot):
\[ T_I = B + 2\big((P + 2\hat{u}) - B\big) \]
Consequences worth appreciating: Inky's pressure *depends on Blinky* — when
Blinky is close behind you, Inky's target lands roughly ahead of you
(a second pincer); when Blinky is far, Inky swings wide and unpredictable.
Coupling two ghosts through one formula creates emergent pack behavior with
zero coordination code. (Pinky's up-quirk leaks into the pivot here too, in
the original.)

**Clyde (orange) — "Pokey", the coward.** With \(C\) = Clyde's own tile and
\(S_C\) = his scatter corner:
\[ T_C = \begin{cases} P & \text{if } \lVert C - P \rVert > 8 \text{ tiles} \\ S_C & \text{otherwise} \end{cases} \]
He chases like Blinky from afar but breaks off inside an 8-tile radius,
producing his signature lurking oscillation near the player. (Arcade uses
straight-line distance for the radius; your BFS distance map (§3.7) offers a
smarter, wall-aware variant.) Design role: Clyde guarantees one ghost is
usually *not* on top of you, keeping some corridor of escape open — he is the
difficulty valve.

Crucial subtlety: **target tiles need not be reachable or even inside the
maze.** Pinky's \(P + 4\hat{u}\) may land inside a wall or beyond the border.
Nothing breaks — the target is only ever *compared against*, never traveled
to. Do not "clamp" or "validate" targets; that would change the behavior.

### 4.5 The intersection decision rule — where AI meets the graph

Between intersections a ghost is cargo (§1.1, degree-2 cells). The entire AI
executes at tile centers, and it is strictly local:

1. **Enumerate legal exits**: directions with no wall (§1.3) and **excluding
   the reverse** of the current direction. The no-reverse rule is load-bearing:
   it forbids trembling in place, forces forward commitment, and is what
   makes the mode-change reversal (§4.2) informative.
2. **Score each exit** by the straight-line (Euclidean) distance from the
   *tile the exit leads to* directly to the target tile. Note well: this is
   geometric distance ignoring all walls — the ghosts are greedy and
   near-sighted *by design*. That myopia is a game-design decision: perfect
   path-optimal ghosts (which you could build with §3.7) are measurably less
   fun and less escapable.
3. **Pick the minimum**; break ties with the fixed priority
   **Up > Left > Down > Right**. The tie-break matters for determinism —
   without a fixed order, two runs diverge on the first tie.
4. **Frightened override**: in frightened mode, skip the scoring and pick a
   pseudo-random legal exit (still no reversing). In the arcade even this is
   deterministic (an index into a fixed PRNG table); with a seeded RNG you
   preserve reproducibility.
5. **Dead-end escape hatch**: if the exit set is empty (only the reverse is
   legal), allow the reversal. The braided maze makes this rare, but "rare"
   crashes are still crashes.

A worked example to convince yourself: ghost heading East arrives at a tile
with open exits North, East, South (West is its reverse — excluded). Target is
5 tiles up and 2 right. Squared distances from the three candidate next-tiles
to the target: North \((2)^2 + (4)^2 = 20\), East \((1)^2+(5)^2 = 26\), South
\((2)^2+(6)^2 = 40\). North wins. (Tip: compare *squared* distances — same
ordering, no square roots.)

### 4.6 Frightened mode numerics

When a super-pacgum is eaten: all ghosts reverse, switch to frightened
(blue, slower — e.g. 50–60 % speed), and the frightened timer starts (a
value that classically shrinks with the level, from ~6 s down to 0). Eating
a frightened ghost scores \(Z\) points (config `points_per_ghost`; the
arcade doubled per consecutive ghost — 200, 400, 800, 1600 — an optional,
config-friendly touch). The eaten ghost heads home (§4.3), waits, and rejoins
the current global mode. Classic UX detail: flash the ghosts white for the
final seconds as a warning that immunity is ending.

### 4.7 Why this architecture is worth imitating

The legacy design demonstrates textbook separation of concerns: *when* to
behave (global wave timer) is decoupled from *what* to want (per-ghost target
formula), which is decoupled from *how* to move (shared intersection rule).
Each layer is testable in isolation — you can unit-test Inky's vector math
without a game loop, and the intersection rule with a hand-drawn 5x5 grid.
When the subject says chase behavior "is up to you" (VI.3), this architecture
is the answer that scales from "random ghost" to "full four-personality pack"
without restructuring.

---

## 5. Integrating the `.whl` Component

### 5.1 What a wheel actually is

A `.whl` file is Python's standard **built distribution** format (PEP 427):
a ZIP archive with a strict naming convention —
`mazegenerator-2.1.0-py3-none-any.whl` decodes as *package* `mazegenerator`,
*version* 2.1.0, *Python tag* `py3` (any Python 3), *ABI tag* `none` (no
compiled extensions), *platform* `any` (pure Python). Installing it merely
unpacks the archive into your environment's `site-packages` — no build step,
no code execution. Inside live exactly two kinds of things: the package's
source tree, and a `*.dist-info/` folder holding `METADATA` (the README you
should read first), `RECORD` (file manifest with hashes), and `WHEEL`
(format metadata).

### 5.2 The rules of engagement (subject V.4)

The subject sets hard constraints that should shape your architecture:

- **Use it as-is.** The reviewers will re-install the original wheel, so any
  local modification is wasted and disqualifying. Treat it as a sealed
  third-party dependency.
- **Your loader adapts to their interface, not the opposite.** This is a
  dependency-inversion exercise: build a thin **adapter** (anti-corruption
  layer) that is the *only* module importing the generator. Everything else
  consumes your own maze model. If at evaluation you were handed a different
  group's package with a slightly different API, only the adapter changes.
- **`perfect=False` always** — that flag activates the dead-end-removal
  braiding that makes mazes Pac-Man-playable (§1.6).
- **Failure must be handled cleanly.** The generator can print warnings
  (maze too small for the 42 logo) or report pathfinding failure; your
  adapter should catch exceptions, validate the output shape, and fall back
  or exit with a clear message — never a traceback (subject III.1).

### 5.3 How to inspect a wheel without touching it

A disciplined inspection sequence — all read-only, no reverse-engineering of
internals required, just interface discovery:

1. **List the archive.** Any ZIP tool (or Python's `zipfile` module) shows
   the file layout: here, `mazegenerator/__init__.py`,
   `mazegenerator/mazegenerator.py`, and the `dist-info` trio.
2. **Read `METADATA`.** It embeds the package README: constructor signature,
   properties, wall-bit encoding, changelog. This is your contract document.
3. **Install into an isolated venv** and confirm the import works.
4. **Probe the live API in a REPL**: use `help()` on the class and `dir()` on
   an instance to enumerate the *actual* public surface (`maze`,
   `maze_entry`, `maze_exit`, `shortest_path`, `generate`), and Python's
   `inspect.signature` to read true defaults.
5. **Write characterization experiments** (soon to be pytest fixtures):
   generate small mazes with fixed seeds and *assert what you observe* —
   grid dimensions vs requested size, value ranges (0–15), wall-bit
   consistency between neighbors (§1.3), determinism (same seed → same
   maze), and the semantics of every property.

Step 5 is the professional habit this milestone teaches: **trust the
documentation, verify with experiments, and encode the verified truth as
tests** so a future package update that changes behavior fails loudly in
your suite instead of silently in your game.

### 5.4 The documented interface — and the traps to verify

From the package's own documentation (its `METADATA`), the contract is:

- **Constructor**: `MazeGenerator(size=(w, h), entry_cell=..., exit_cell=...,
  perfect=False, seed=...)`. Note `seed=0` means *fully random*; any
  positive seed is reproducible — so "level 1 uses seed 42, later levels
  random" (subject VI.1) maps to passing 42 first and 0 (or your own random
  positive seeds, better for replayability/debugging) afterwards.
- **`maze`**: `list[list[int]]`, row-major (`maze[y][x]`), each value a
  4-bit wall mask (§1.3); `15` marks the isolated "42"-logo blocks.
- **`maze_entry` / `maze_exit`**: cell coordinate tuples.
- **`shortest_path`**: a string over the alphabet `N E S W` describing the
  entry→exit shortest path — a ready-made **oracle** for validating your own
  BFS/A\* (assert equal lengths; paths may differ, lengths must not).
- **`generate(seed)`**: re-rolls the maze in place — one generator instance
  can serve all your levels.

Traps your characterization tests must pin down (documentation and reality
have been known to disagree in this package's own README — e.g. the stated
default size, the default `exit_cell`, and whether coordinate tuples are
`(row, col)` or `(x, y)` order):

1. **Tuple order of `maze_entry`/`maze_exit`.** Decide experimentally:
   request an asymmetric maze (e.g. 9x5), place the exit at a known corner,
   and check which index matches width and which matches height. Never trust
   a `(a, b)` tuple across a library boundary without such a test.
2. **Grid orientation.** Confirm `maze[0]` is the *top* row by checking that
   border cells of `maze[0]` all have their North bit set.
3. **Warning side-effects.** The generator prints warnings to stdout for
   too-small mazes; decide your minimum playable size accordingly (the 42
   logo needs roughly ≥ 14 cells in each dimension) and clamp config values
   *before* calling it.
4. **`shortest_path` can be `False`** (reported failure) rather than a
   string — your adapter must tolerate a non-string value.

### 5.5 The adapter layer you should design

Conceptually (design, not code): one module owning the import, exposing to
the rest of the game only *your* vocabulary —

- `generate_level(width, height, seed) → MazeModel`, with all generator
  exceptions/oddities converted into your own single, catchable error type
  and all config clamping applied before the call;
- `MazeModel` answering the queries the game actually asks:
  `can_move(cell, direction)`, `neighbors(cell)`, `is_walkable(cell)`,
  `walkable_cells()`, `corners()`, `center()` — the §1 graph interface;
- pellet/spawn placement computed here from the model (pacgums on walkable
  corridor cells, super-pacgums at the 4 corner cells, ghosts at corners,
  player at center — subject VI.1), not scattered through game code.

The test of a good adapter: *no file outside it mentions `mazegenerator`*,
and your pathfinding module (§3) compiles against `neighbors()` with no idea
a wheel exists.

---

## 6. Glossary and Further Reading

**Glossary.**
*Admissible heuristic* — never overestimates true remaining cost; guarantees
A\* optimality. *Braiding* — removing maze dead ends by carving extra
openings, creating cycles. *Characterization test* — a test that records
observed behavior of third-party code as an executable contract.
*Consistent heuristic* — satisfies the edge-wise triangle inequality;
implies admissible and lets A\* close vertices permanently. *Distance map /
flow field* — per-cell shortest distances from one source, from a single BFS.
*Frontier* — the set of discovered-but-unexpanded vertices; its data
structure (queue/stack/heap) *is* the difference between BFS/DFS/A\*.
*Perfect maze* — spanning tree of the grid; unique paths, no cycles.
*Spanning tree* — subgraph touching all vertices with exactly \(|V|-1\)
edges and no cycles. *Target tile* — the cell a ghost steers toward; the
sole personality parameter. *Tick* — one fixed quantum of simulation time.

**Further reading.**

- Jamey Pittman, *The Pac-Man Dossier* — the definitive reverse-engineered
  specification of the original arcade AI, timings, and quirks.
- Cormen, Leiserson, Rivest, Stein, *Introduction to Algorithms* — chapters
  on elementary graph algorithms (BFS/DFS) and shortest paths.
- Russell & Norvig, *Artificial Intelligence: A Modern Approach* — informed
  search, heuristic dominance, and A\* optimality proofs.
- Amit Patel (Red Blob Games) — interactive essays on grids, graph search,
  and A\* heuristics; the best visual intuition builder available.
- Robert Nystrom, *Game Programming Patterns* — game loop, state machine,
  and component patterns used throughout this project.
- PEP 427 — the wheel binary package format specification.
