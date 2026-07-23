# Sprites (icons)

The game loads every **`.xpm`** in this folder at startup, keyed by its
filename. Draw icons as PNGs (transparent background), drop them here,
then run `./scripts/png_to_xpm.sh` to convert them.

XPM (not PNG) is what the renderer reads: it scales each sprite to the
current tile size and blends its transparency over the walls/pellets,
which MLX's plain image-blit cannot do, and XPM is plain text with a
built-in transparent color (`c None`).

## Naming

Directions are `north` / `south` / `east` / `west`. Animation frames are
`_1` / `_2`. All lowercase.

| Files | Count | Used for |
|---|---|---|
| `pacman_<dir>_1`, `pacman_<dir>_2` | 8 | Pac-Man moving, 2 chomp frames per direction |
| `full_pacman` | 1 | mouth shut — the third frame of the chomp cycle |
| `pacman_death_1` … `pacman_death_N` | 11 | dying animation, played in order |
| `ghost_<name>_<dir>_1/_2` | 32 | the 4 ghosts (`blinky`, `pinky`, `inky`, `clyde`) |
| `frightened_1`, `frightened_2` | 2 | any ghost while edible (no direction) |
| `floating_eyes_<dir>` | 4 | an eaten ghost returning home |

**58 files total.**

## How they are chosen

Each entity has a candidate list, best match first, ending in a drawn
shape. So a missing file never breaks anything — it just falls back:

```
pacman        full_pacman / pacman_<dir>_<phase>  ->  pacman_<dir>_1
              ->  pacman_<dir>  ->  pacman  ->  yellow square
ghost         ghost_<name>_<dir>_<frame>  ->  ..._1  ->  ghost_<name>
              ->  <name>  ->  colored square
frightened    frightened_<frame>  ->  frightened_1  ->  frightened
eaten         floating_eyes_<dir>  ->  floating_eyes  ->  eyes
dying         pacman_death_<n>  (n from how far the death pause has run)
```

Icons are square with a transparent background; any size works (they are
scaled to the tile), and these are 11x11.
