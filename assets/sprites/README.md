# Sprites (icons)

Put the game's icons here as **`.xpm`** files. The renderer loads any of
the names below that exist and draws them in place of the plain colored
shapes; a missing file just falls back to the shape, so you can add
icons one at a time.

## Format: XPM (not PNG)

MLX can load PNG *and* XPM, but this game uses **XPM** because:
- the renderer scales each sprite to the current tile size (tiles are
  ~28–48 px depending on the maze) and blends its transparency over the
  walls/pellets — which MLX's plain image-blit can't do; and
- XPM is plain text with a built-in transparent color (`c None`), so it
  parses without any extra dependency.

You draw/find icons as PNGs (easy) and convert them to XPM (one command).

## Expected files

| File | Used for |
|------|----------|
| `pacman.xpm` | the player |
| `blinky.xpm` | red ghost |
| `pinky.xpm` | pink ghost |
| `inky.xpm` | cyan ghost |
| `clyde.xpm` | orange ghost |
| `frightened.xpm` | any ghost while edible (blue) |
| `eyes.xpm` | an eaten ghost returning home |
| `pacgum.xpm` *(optional)* | normal pellet |
| `super_pacgum.xpm` *(optional)* | power pellet |

## Rules for the images

- **Square**, with a **transparent background** (so only the character
  shows, not a box around it).
- Recommended size **32×32 px** (any square size works; it's scaled to
  the tile). Keep it simple, flat-color pixel art — few colors keeps the
  XPM small and crisp.

## How to make them

1. Draw or download the icon as a **PNG with a transparent background**.
   Free tools: [Piskel](https://www.piskelapp.com) (browser, pixel art),
   Aseprite, or GIMP. Or grab CC0 sprites from opengameart.org.
2. Drop the PNGs in this folder (`assets/sprites/`).
3. Convert them all to XPM:
   ```bash
   ./scripts/png_to_xpm.sh
   ```
   (needs ImageMagick: `sudo apt-get install imagemagick`). This keeps
   the transparent background as XPM's `c None`.

That's it — run the game and the icons appear.
