"""MLX front-end: window, image-buffer rendering, and the event loop.

The ONLY module that talks to the graphics library (the 42 MiniLibX,
subject IV). It is a thin driver over the platform-neutral
:class:`~pacman.ui.shell.GameShell`: MLX key events are translated into
abstract :class:`~pacman.ui.shell.Action` values and handed to the
shell; the shell owns all screen/FSM logic and the fixed-timestep
simulation clock; this module only draws the shell's state and pumps
MLX's callback-driven loop.

MLX has no shape primitives (only ``mlx_pixel_put`` /
``mlx_string_put`` / image blitting), so the board is rendered by
writing pixels into an off-screen image buffer -- walls and sealed
blocks are cached in a per-level static layer, dynamic entities
(pellets, ghosts, player) are drawn on top each frame -- then blitted
with ``mlx_put_image_to_window``; text (HUD, menus, name entry) is drawn
over it with ``mlx_string_put``.

MLX cannot run headless (the C loop needs a display), so there are no
unit tests in here -- the testable UI logic all lives in the shell.
"""

import logging
import os
import re
import time
from pathlib import Path

from mlx import Mlx

from pacman.ai.ghost import Ghost, GhostMode, GhostPersonality
from pacman.config.loader import Config
from pacman.game.engine import GameState
from pacman.maze.adapter import Direction
from pacman.ui.shell import (
    INSTRUCTIONS_LINES,
    MAIN_MENU_ITEMS,
    PAUSE_MENU_ITEMS,
    Action,
    GameShell,
    Screen,
)

logger = logging.getLogger(__name__)

BOARD_SIZE = 720
HUD_HEIGHT = 48
WIDTH = BOARD_SIZE
HEIGHT = BOARD_SIZE + HUD_HEIGHT

TARGET_FRAME_MS = 16  # ~60 fps render cap; the sim runs at its own rate

# Sprites are drawn this fraction of the tile, centered, so a full-frame
# icon keeps a margin from the walls instead of touching every border.
SPRITE_SCALE = 0.82

# Colors as (r, g, b). Image pixels are packed BGRA (MLX/XCB little
# endian); mlx_string_put takes a packed 0xRRGGBB int.
BACKGROUND = (12, 12, 24)
WALL = (60, 90, 220)
BLOCK = (40, 60, 160)
PELLET = (255, 250, 200)
PLAYER = (255, 210, 0)
# The queued-turn marker. Deliberately not any ghost colour (red/pink/
# cyan/orange), the pellet cream or the player yellow, so a pending
# input is never mistaken for something you can eat or run into.
INTENT = (130, 255, 150)
FRIGHTENED = (40, 80, 255)
EYES = (240, 240, 240)
TEXT = (255, 255, 255)
DIM = (150, 150, 170)
SELECTED = (255, 210, 0)

GHOST_COLORS = {
    GhostPersonality.BLINKY: (255, 40, 40),
    GhostPersonality.PINKY: (255, 150, 200),
    GhostPersonality.INKY: (60, 220, 255),
    GhostPersonality.CLYDE: (255, 160, 40),
}

# X11 keysyms -> navigational Action (see shell.Action). Printable keys
# also yield a character (handled separately) for name entry.
KEYSYM_ACTION = {
    0xFF52: Action.UP, 0x77: Action.UP,        # Up / w
    0xFF54: Action.DOWN, 0x73: Action.DOWN,    # Down / s
    0xFF51: Action.LEFT, 0x61: Action.LEFT,    # Left / a
    0xFF53: Action.RIGHT, 0x64: Action.RIGHT,  # Right / d
    0xFF0D: Action.CONFIRM, 0xFF8D: Action.CONFIRM, 0x20: Action.CONFIRM,
    0xFF1B: Action.BACK,                       # Escape
    0x70: Action.PAUSE,                        # p
    0xFF08: Action.BACKSPACE,                  # BackSpace
    0xFFBE: Action.CHEAT_INVINCIBLE,           # F1
    0xFFBF: Action.CHEAT_FREEZE,               # F2
    0xFFC0: Action.CHEAT_LIFE,                 # F3
    0xFFC1: Action.CHEAT_SPEED,                # F4
    0xFFC2: Action.CHEAT_SKIP,                 # F5
}


def _pack(color: tuple[int, int, int]) -> bytes:
    """Pack an (r, g, b) color into one BGRA image pixel."""
    r, g, b = color
    return bytes((b, g, r, 255))


def _int_color(color: tuple[int, int, int]) -> int:
    """Pack an (r, g, b) color into a 0xRRGGBB int for mlx_string_put."""
    r, g, b = color
    return (r << 16) | (g << 8) | b


# Where sprite icons live (repo-root/assets/sprites), and the names the
# renderer looks for. Each is optional -- a missing/broken file falls
# back to the drawn shape, so icons can be added one at a time.
SPRITE_DIR = Path(__file__).resolve().parents[2] / "assets" / "sprites"
SPRITE_NAMES = (
    "pacman", "blinky", "pinky", "inky", "clyde", "frightened", "eyes",
)

# A parsed sprite: pixel rows, each pixel an (r, g, b) or None (clear).
Pixel = tuple[int, int, int] | None
Sprite = tuple[int, int, list[list[Pixel]]]  # width, height, rows

# Minimal X11 color-name table for XPM `c <name>` entries (ImageMagick
# emits these alongside #RRGGBB); unknown names fall back to magenta so a
# gap is obvious rather than silently wrong.
NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "orange": (255, 165, 0), "pink": (255, 192, 203),
}


def _parse_xpm_color(token: str) -> Pixel:
    """Turn an XPM color token into an (r, g, b) or None (transparent)."""
    low = token.lower()
    if low == "none":
        return None
    if token.startswith("#"):
        hexits = token[1:]
        if len(hexits) == 3:  # #RGB shorthand
            r, g, b = (int(c * 2, 16) for c in hexits)
            return (r, g, b)
        step = len(hexits) // 3  # #RRGGBB or #RRRRGGGGBBBB
        return (int(hexits[0:2], 16), int(hexits[step:step + 2], 16),
                int(hexits[2 * step:2 * step + 2], 16))
    return NAMED_COLORS.get(low, (255, 0, 255))


def parse_xpm(text: str) -> Sprite:
    """Parse XPM text into (width, height, pixel rows).

    Handles the subset the game needs: the ``"cols rows ncolors cpp"``
    header, a color table (``<chars> c <color>`` where color is
    ``#RRGGBB``, an X11 name, or ``None`` for transparent), and the pixel
    rows. Supports multi-character-per-pixel and a space used as a color
    key. Raises ValueError on anything malformed so the caller can skip
    the file and fall back to the drawn shape.
    """
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    if not strings:
        raise ValueError("no XPM string literals")
    cols, rows, ncolors, cpp = (int(n) for n in strings[0].split()[:4])
    color_lines = strings[1:1 + ncolors]
    pixel_lines = strings[1 + ncolors:1 + ncolors + rows]
    if len(color_lines) != ncolors or len(pixel_lines) != rows:
        raise ValueError("truncated XPM body")

    palette: dict[str, Pixel] = {}
    for line in color_lines:
        key = line[:cpp]
        tokens = line[cpp:].split()
        color = "None"
        if "c" in tokens:
            color = tokens[tokens.index("c") + 1]
        palette[key] = _parse_xpm_color(color)

    grid: list[list[Pixel]] = []
    for line in pixel_lines:
        grid.append([palette.get(line[i:i + cpp]) for i in
                     range(0, cols * cpp, cpp)])
    return cols, rows, grid


def keysym_to_action(keysym: int) -> tuple[Action | None, str]:
    """Translate an X11 keysym into a (nav action, typed char) pair.

    The action drives menus/steering; the char feeds name entry. A
    printable keysym (0x20-0x7E) yields its character; keys that are
    both navigational and printable (W/A/S/D, space) yield both, and the
    shell picks per screen.
    """
    action = KEYSYM_ACTION.get(keysym)
    char = chr(keysym) if 0x20 <= keysym <= 0x7E else ""
    return action, char


class MlxApp:
    """Owns the MLX window/image and drives the shell each loop tick."""

    def __init__(self, config: Config) -> None:
        self.shell = GameShell(config)
        self.mlx = Mlx()
        self.mlx_ptr: int | None = None
        self.win_ptr: int | None = None
        self.img_ptr: int | None = None
        self.buffer: memoryview | None = None
        self.size_line = WIDTH * 4
        self._static_layer: bytearray | None = None
        self._static_for: int | None = None
        self._last_ms = 0.0
        self.sprites: dict[str, Sprite] = {}
        # Cache of scaled opaque pixel-runs per (sprite, tile size), so a
        # sprite is scaled and RLE-compressed once, not every frame.
        self._sprite_runs: dict[
            tuple[str, int], list[tuple[int, int, bytes]]
        ] = {}

    # -- Lifecycle -----------------------------------------------------

    def setup(self) -> None:
        """Open the window, allocate the image buffer, load sprite icons."""
        self.mlx_ptr = self.mlx.mlx_init()
        self.win_ptr = self.mlx.mlx_new_window(
            self.mlx_ptr, WIDTH, HEIGHT, "42 Pac-Man",
        )
        self.img_ptr = self.mlx.mlx_new_image(self.mlx_ptr, WIDTH, HEIGHT)
        self.buffer, _bpp, self.size_line, _fmt = (
            self.mlx.mlx_get_data_addr(self.img_ptr)
        )
        self._load_sprites()

    def _load_sprites(self) -> None:
        """Load any ``assets/sprites/<name>.xpm`` that exist; skip the rest.

        A missing or malformed file is logged and skipped -- the entity
        then renders as its drawn shape, so the game never depends on the
        icons being present or valid.
        """
        for name in SPRITE_NAMES:
            path = SPRITE_DIR / f"{name}.xpm"
            if not path.exists():
                continue
            try:
                self.sprites[name] = parse_xpm(path.read_text())
            except (OSError, ValueError, IndexError) as exc:
                logger.warning("Could not load sprite %s: %s", path, exc)

    def run(self) -> int:
        """Register the MLX hooks and run the blocking event loop."""
        self.setup()
        self.mlx.mlx_hook(self.win_ptr, 2, 1, self._on_key, None)  # KeyPress
        self.mlx.mlx_hook(self.win_ptr, 33, 0, self._on_close, None)  # close
        self.mlx.mlx_loop_hook(self.mlx_ptr, self._on_loop, None)
        self._last_ms = time.monotonic() * 1000
        self.mlx.mlx_loop(self.mlx_ptr)
        return 0

    # -- MLX callbacks -------------------------------------------------

    def _on_key(self, keysym: int, _param: object) -> None:
        action, char = keysym_to_action(keysym)
        self.shell.dispatch(action, char)
        if not self.shell.running:
            self.mlx.mlx_loop_exit(self.mlx_ptr)

    def _on_close(self, _param: object) -> None:
        self.shell.running = False
        self.mlx.mlx_loop_exit(self.mlx_ptr)

    def _on_loop(self, _param: object) -> None:
        now = time.monotonic() * 1000
        elapsed = now - self._last_ms
        if elapsed < TARGET_FRAME_MS:
            return
        self._last_ms = now
        self.shell.advance(elapsed)
        if not self.shell.running:
            self.mlx.mlx_loop_exit(self.mlx_ptr)
            return
        self.draw()

    # -- Image-buffer primitives ---------------------------------------

    def _fill(self, color: tuple[int, int, int]) -> None:
        """Fill the whole image buffer with one color."""
        assert self.buffer is not None
        self.buffer[:] = _pack(color) * (len(self.buffer) // 4)

    def _rect(
        self, x: int, y: int, w: int, h: int, color: tuple[int, int, int],
    ) -> None:
        """Fill an axis-aligned rectangle, clipped to the image bounds."""
        assert self.buffer is not None
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, WIDTH), min(y + h, HEIGHT)
        if x1 <= x0 or y1 <= y0:
            return
        row = _pack(color) * (x1 - x0)
        for py in range(y0, y1):
            start = py * self.size_line + x0 * 4
            self.buffer[start:start + len(row)] = row

    def _arrow(self, cx: int, cy: int, direction: Direction, size: int,
               color: tuple[int, int, int]) -> None:
        """Filled triangle with its apex at (cx, cy), pointing ``direction``.

        Built from ``_rect`` slabs (the image layer has no polygon
        primitive): each step back from the apex widens the slab by one
        pixel either side, across for a horizontal arrow and down for a
        vertical one.
        """
        for i in range(size):
            ax = cx - direction.dx * i
            ay = cy - direction.dy * i
            if direction.dx:
                self._rect(ax, ay - i, 1, 2 * i + 1, color)
            else:
                self._rect(ax - i, ay, 2 * i + 1, 1, color)

    # -- Rendering -----------------------------------------------------

    _TEXT_SCREENS = (Screen.MAIN_MENU, Screen.INSTRUCTIONS, Screen.HIGHSCORES)

    def draw(self) -> None:
        """Render one frame of the shell's current screen.

        The image layer holds the board (or a plain background for the
        menu/info screens); text is layered over the blit as a second
        pass, since ``mlx_string_put`` draws onto the window directly.
        """
        if self.shell.screen in self._TEXT_SCREENS:
            self._fill(BACKGROUND)
        else:  # PLAYING / PAUSED / NAME_ENTRY all show the board.
            self._draw_game()
        self.mlx.mlx_put_image_to_window(
            self.mlx_ptr, self.win_ptr, self.img_ptr, 0, 0,
        )
        self._draw_overlays()

    def _string(self, x: int, y: int, color: tuple[int, int, int],
                text: str) -> None:
        """Draw a line of text on the window at (x, y)."""
        self.mlx.mlx_string_put(
            self.mlx_ptr, self.win_ptr, x, y, _int_color(color), text,
        )

    def _center_x(self, text: str) -> int:
        """Rough centered x for a monospace-ish 6px glyph width."""
        return max((WIDTH - len(text) * 6) // 2, 8)

    def _draw_game(self) -> None:
        if self.shell.session is None:
            self._fill(BACKGROUND)
            return
        self._blit_static_layer(self.shell.session.state)
        self._draw_dynamic(self.shell.session.state)

    def _draw_overlays(self) -> None:
        """Text drawn on the window after the image blit."""
        if self.shell.screen is Screen.MAIN_MENU:
            self._string(self._center_x("PAC-MAN"), 90, PLAYER, "PAC-MAN")
            for i, item in enumerate(MAIN_MENU_ITEMS):
                mark = "> " if i == self.shell.menu_index else "  "
                color = SELECTED if i == self.shell.menu_index else TEXT
                self._string(self._center_x(mark + item), 220 + 40 * i,
                             color, mark + item)
            self._string(self._center_x("Highscores"), 430, DIM, "Highscores")
            for r, line in enumerate(self.shell.highscore_lines()[:5]):
                self._string(self._center_x(line), 460 + 22 * r, DIM, line)
        elif self.shell.screen is Screen.INSTRUCTIONS:
            self._draw_text_overlay("Instructions", INSTRUCTIONS_LINES)
        elif self.shell.screen is Screen.HIGHSCORES:
            self._draw_text_overlay(
                "Highscores", self.shell.highscore_lines(),
            )
        elif self.shell.screen is Screen.PLAYING:
            self._draw_hud()
        elif self.shell.screen is Screen.PAUSED:
            self._draw_hud()
            self._draw_pause_overlay()
        elif self.shell.screen is Screen.NAME_ENTRY:
            self._draw_hud()
            self._draw_name_overlay()

    def _draw_text_overlay(self, title: str, lines: tuple[str, ...]) -> None:
        self._string(self._center_x(title), 70, PLAYER, title)
        for r, line in enumerate(lines):
            self._string(self._center_x(line), 170 + 30 * r, TEXT, line)

    def _draw_pause_overlay(self) -> None:
        self._string(self._center_x("PAUSED"), 300, PLAYER, "PAUSED")
        for i, item in enumerate(PAUSE_MENU_ITEMS):
            mark = "> " if i == self.shell.pause_index else "  "
            color = SELECTED if i == self.shell.pause_index else TEXT
            self._string(self._center_x(mark + item), 360 + 40 * i,
                         color, mark + item)

    def _draw_name_overlay(self) -> None:
        title = "VICTORY!" if self.shell.final_won else "GAME OVER"
        self._string(self._center_x(title), 250, PLAYER, title)
        score = f"Final score: {self.shell.final_score}"
        self._string(self._center_x(score), 300, TEXT, score)
        self._string(self._center_x("Enter your name:"), 350, DIM,
                     "Enter your name:")
        caret = self.shell.name_buffer + "_"
        self._string(self._center_x(caret), 390, SELECTED, caret)
        hint = "letters/digits/spaces (max 10) - Enter to save"
        self._string(self._center_x(hint), 440, DIM, hint)

    def _draw_hud(self) -> None:
        if self.shell.session is None:
            return
        state = self.shell.session.state
        hud = (
            f"Score: {state.score}   Lives: {state.lives}   "
            f"Level: {self.shell.session.level_number}   "
            f"Time: {state.seconds_remaining}"
        )
        self._string(12, BOARD_SIZE + 22, TEXT, hud)

    # -- Board rendering into the image buffer -------------------------

    def _geometry(self, state: GameState) -> tuple[int, int, int]:
        adapter = state.adapter
        tile = max(4, min(BOARD_SIZE // adapter.width,
                          BOARD_SIZE // adapter.height))
        ox = (BOARD_SIZE - tile * adapter.width) // 2
        oy = (BOARD_SIZE - tile * adapter.height) // 2
        return tile, ox, oy

    def _blit_static_layer(self, state: GameState) -> None:
        """Copy the cached walls/blocks layer, rebuilding on level change."""
        assert self.buffer is not None
        if self._static_for != id(state.adapter):
            self._build_static_layer(state)
        assert self._static_layer is not None
        self.buffer[:] = self._static_layer

    def _build_static_layer(self, state: GameState) -> None:
        """Render background + walls + sealed blocks once for this level."""
        self._fill(BACKGROUND)
        adapter = state.adapter
        tile, ox, oy = self._geometry(state)
        thickness = max(1, tile // 12)
        for y in range(adapter.height):
            for x in range(adapter.width):
                left, top = ox + x * tile, oy + y * tile
                if not adapter.is_walkable(x, y):
                    self._rect(left, top, tile, tile, BLOCK)
                    continue
                moves = adapter.get_valid_moves(x, y)
                if Direction.NORTH not in moves:
                    self._rect(left, top, tile, thickness, WALL)
                if Direction.SOUTH not in moves:
                    self._rect(left, top + tile - thickness, tile,
                               thickness, WALL)
                if Direction.WEST not in moves:
                    self._rect(left, top, thickness, tile, WALL)
                if Direction.EAST not in moves:
                    self._rect(left + tile - thickness, top, thickness,
                               tile, WALL)
        assert self.buffer is not None
        self._static_layer = bytearray(self.buffer)
        self._static_for = id(state.adapter)

    def _draw_dynamic(self, state: GameState) -> None:
        """Draw pellets (fixed) and the smoothly-moving ghosts + player.

        Pellets sit on their tiles. Both the player and the ghosts are
        drawn at the exact sub-tile position the ENGINE holds, so no
        sprite ever trails the simulation: the previous approach glided
        toward a tile the engine had already reached, which lagged a full
        move period behind reality, cut diagonally across corners on a
        turn, and let a ghost look a tile away from the player it had
        just caught.
        """
        tile, ox, oy = self._geometry(state)

        def dot(fx: float, fy: float, size: int,
                color: tuple[int, int, int]) -> None:
            cx = int(ox + fx * tile + tile // 2)
            cy = int(oy + fy * tile + tile // 2)
            self._rect(cx - size, cy - size, size * 2, size * 2, color)

        for cell in state.pacgum_cells:
            dot(cell[0], cell[1], max(1, tile // 10), PELLET)
        for cell in state.super_pacgum_cells:
            dot(cell[0], cell[1], max(3, tile // 4), PELLET)
        for ghost in state.ghosts:
            fx, fy = state.ghost_render_pos(ghost)
            if not self._blit_sprite(self._ghost_sprite(ghost), fx, fy,
                                     tile, ox, oy):
                dot(fx, fy, max(3, tile // 3), self._ghost_color(ghost))
        px, py = state.player_render_pos()
        radius = max(3, tile // 3)
        if not self._blit_sprite("pacman", px, py, tile, ox, oy):
            dot(px, py, radius, PLAYER)
        self._draw_player_heading(state, px, py, tile, ox, oy, radius)

    def _ghost_sprite(self, ghost: Ghost) -> str:
        """The sprite name for a ghost given its current mode."""
        if ghost.mode is GhostMode.EATEN:
            return "eyes"
        if ghost.mode is GhostMode.FRIGHTENED:
            return "frightened"
        return ghost.personality.name.lower()

    def _blit_sprite(self, name: str, fx: float, fy: float,
                     tile: int, ox: int, oy: int) -> bool:
        """Composite sprite ``name`` centered on cell (fx, fy); True if drawn.

        Returns False when no such sprite is loaded, so the caller draws
        its fallback shape. The sprite is scaled to SPRITE_SCALE of the
        tile and centered on the cell, its transparent pixels skipped, so
        it blends over walls/pellets with a margin from the borders.
        """
        size = max(4, int(tile * SPRITE_SCALE))
        runs = self._scaled_runs(name, size)
        if runs is None:
            return False
        assert self.buffer is not None
        center_x = ox + fx * tile + tile / 2
        center_y = oy + fy * tile + tile / 2
        left = int(center_x - size / 2)
        top = int(center_y - size / 2)
        for dy, dx0, run in runs:
            y = top + dy
            if not (0 <= y < HEIGHT):
                continue
            x = left + dx0
            run_px = len(run) // 4
            if x < 0:  # clip left
                cut = -x
                if cut >= run_px:
                    continue
                run, x, run_px = run[cut * 4:], 0, run_px - cut
            if x + run_px > WIDTH:  # clip right
                keep = WIDTH - x
                if keep <= 0:
                    continue
                run = run[:keep * 4]
            off = y * self.size_line + x * 4
            self.buffer[off:off + len(run)] = run
        return True

    def _scaled_runs(self, name: str,
                     size: int) -> list[tuple[int, int, bytes]] | None:
        """Nearest-neighbor-scale a sprite to ``size`` px as opaque runs.

        Each run is ``(dy, dx_start, bytes)`` -- a horizontal span of
        adjacent non-transparent pixels, packed once and cached, so a
        frame just slice-copies a handful of runs per entity.
        """
        sprite = self.sprites.get(name)
        if sprite is None:
            return None
        cached = self._sprite_runs.get((name, size))
        if cached is not None:
            return cached
        src_w, src_h, grid = sprite
        runs: list[tuple[int, int, bytes]] = []
        for dy in range(size):
            row = grid[dy * src_h // size]
            dx = 0
            while dx < size:
                if row[dx * src_w // size] is None:
                    dx += 1
                    continue
                start, chunk = dx, bytearray()
                while dx < size:
                    pixel = row[dx * src_w // size]
                    if pixel is None:
                        break
                    chunk += _pack(pixel)
                    dx += 1
                runs.append((dy, start, bytes(chunk)))
        self._sprite_runs[(name, size)] = runs
        return runs

    def _draw_player_heading(
        self, state: GameState, px: float, py: float,
        tile: int, ox: int, oy: int, radius: int,
    ) -> None:
        """Point a nose the way Pac-Man moves, and flag a queued turn.

        Two separate facts, because they answer different questions. The
        yellow nose just off the body is where he IS going. The green
        marker at the tile edge is where he WILL go -- the buffered
        press, which only fires once he reaches a center. Showing the
        queued one is what makes a 90-degree turn feel acknowledged
        rather than swallowed: the input is visibly accepted the instant
        it is pressed, even though the corner itself has to wait.
        """
        cx = int(ox + px * tile + tile // 2)
        cy = int(oy + py * tile + tile // 2)
        size = max(3, tile // 9)
        nose = radius + max(1, tile // 24) + size
        facing = state.player_direction
        self._arrow(cx + facing.dx * nose, cy + facing.dy * nose,
                    facing, size, PLAYER)
        queued = state.buffered_direction
        if queued is not None and queued is not facing:
            edge = tile // 2 - 1
            self._arrow(cx + queued.dx * edge, cy + queued.dy * edge,
                        queued, size, INTENT)

    def _ghost_color(self, ghost: Ghost) -> tuple[int, int, int]:
        if ghost.mode is GhostMode.EATEN:
            return EYES
        if ghost.mode is GhostMode.FRIGHTENED:
            return FRIGHTENED
        return GHOST_COLORS[ghost.personality]


def has_display() -> bool:
    """Whether a graphics display MLX can attach to appears available.

    MLX's C layer *segfaults* (uncatchable in Python) when it cannot
    reach a display, so this cheap env check must gate ``mlx_init``:
    with neither X11 (DISPLAY) nor Wayland (WAYLAND_DISPLAY) set, we
    never call into MLX and let the caller fall back to text instead of
    crashing (subject IV: "no crash!").
    """
    return bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def run_game(config: Config) -> int:
    """Launch the windowed game; never let a traceback (or crash) escape.

    Subject III.1 / IV: a headless machine (no display) is detected up
    front (MLX would otherwise segfault), and any other MLX/Vulkan
    failure is caught and reported as one clean line with a nonzero exit
    code, so the caller can fall back to the textual preview.
    """
    if not has_display():
        logger.warning("No graphics display detected; textual fallback.")
        return 1
    try:
        return MlxApp(config).run()
    except Exception as exc:  # MLX failures surface many ways; catch all.
        logger.error("Could not open the game window: %s", exc)
        print(f"Could not open the game window: {exc}")
        return 1
