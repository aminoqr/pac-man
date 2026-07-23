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
from pacman.ui import font
from pacman.ui.shell import (
    INSTRUCTIONS_LINES,
    MAIN_MENU_ITEMS,
    PAUSE_MENU_ITEMS,
    Action,
    GameShell,
    Screen,
)

logger = logging.getLogger(__name__)

# The window fills the display (queried at startup); these are only the
# fallbacks for when the screen size cannot be read. SCREEN_MARGIN_H
# leaves room for the window manager's title bar so a screen-sized
# window is not clipped off the bottom.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
MIN_WIDTH = 900
MIN_HEIGHT = 640
SCREEN_MARGIN_H = 80

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
# Menu chrome: a faint panel behind text blocks, the framing border, and
# the corner credit.
PANEL = (22, 22, 46)
BORDER = (60, 90, 220)
CREDIT = (120, 120, 150)

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


# Where sprite icons live (repo-root/assets). Every .xpm in there is
# loaded under its filename stem; what gets drawn is chosen by a
# candidate list per entity (direction + animation frame first, then
# ever-simpler fallbacks, finally the drawn shape). That way icons can
# be added one at a time and each one starts being used immediately.
SPRITE_DIR = Path(__file__).resolve().parents[2] / "assets"

# How long each animation frame is held, in milliseconds.
ANIM_PERIOD_MS = 110

# Direction -> the word used in sprite filenames (matches the Direction
# enum's own names, which is how the artwork is labelled).
DIR_NAME = {
    Direction.NORTH: "north",
    Direction.SOUTH: "south",
    Direction.EAST: "east",
    Direction.WEST: "west",
}

# Highest ``pacman_death_<n>`` frame the renderer will look for.
MAX_DEATH_FRAMES = 16

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
        # Window/layout geometry, finalized in setup() from the display.
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.hud_h = 56
        self.board = 720          # square play area, centered
        self.board_x = 0
        self.board_y = 0
        self.ui = 2               # base pixel-font scale
        self.size_line = DEFAULT_WIDTH * 4
        self._static_layer: bytearray | None = None
        self._static_for: int | None = None
        self._last_ms = 0.0
        self.sprites: dict[str, Sprite] = {}
        # Cache of scaled opaque pixel-runs per (sprite, tile size), so a
        # sprite is scaled and RLE-compressed once, not every frame.
        self._sprite_runs: dict[
            tuple[str, int], list[tuple[int, int, bytes]]
        ] = {}
        self._death_frame_count: int | None = None

    # -- Lifecycle -----------------------------------------------------

    def setup(self) -> None:
        """Open a display-sized window, allocate the buffer, load sprites."""
        self.mlx_ptr = self.mlx.mlx_init()
        self._resolve_geometry()
        self.win_ptr = self.mlx.mlx_new_window(
            self.mlx_ptr, self.width, self.height, "42 Pac-Man",
        )
        self.img_ptr = self.mlx.mlx_new_image(
            self.mlx_ptr, self.width, self.height,
        )
        self.buffer, _bpp, self.size_line, _fmt = (
            self.mlx.mlx_get_data_addr(self.img_ptr)
        )
        self._load_sprites()

    def _resolve_geometry(self) -> None:
        """Size the window to the display and derive the layout from it.

        The play area is the largest centered square that fits above the
        HUD, so the maze stays square (pillar-boxed on a wide screen);
        the font scale is derived from the height so text keeps its
        proportions on any display. A failed screen query just falls back
        to the default window size rather than aborting.
        """
        screen_w, screen_h = DEFAULT_WIDTH, DEFAULT_HEIGHT
        try:
            _ret, screen_w, screen_h = self.mlx.mlx_get_screen_size(
                self.mlx_ptr,
            )
        except Exception as exc:  # any MLX/driver oddity -> defaults
            logger.warning("Could not read screen size (%s); windowed.", exc)
        self.width = max(MIN_WIDTH, int(screen_w))
        self.height = max(MIN_HEIGHT, int(screen_h) - SCREEN_MARGIN_H)
        self.ui = max(2, self.height // 260)
        self.hud_h = max(48, font.text_height(self.ui) + 6 * self.ui)
        self.board = min(self.width, self.height - self.hud_h)
        self.board_x = (self.width - self.board) // 2
        self.board_y = 0

    def _load_sprites(self) -> None:
        """Load every ``assets/sprites/*.xpm`` under its filename stem.

        A malformed file is logged and skipped -- the entity then falls
        back through its candidate list to a drawn shape, so the game
        never depends on the icons being present or valid.
        """
        if not SPRITE_DIR.is_dir():
            return
        for path in sorted(SPRITE_DIR.glob("*.xpm")):
            try:
                self.sprites[path.stem] = parse_xpm(path.read_text())
            except (OSError, ValueError, IndexError) as exc:
                logger.warning("Could not load sprite %s: %s", path, exc)

    def _anim_frame(self) -> int:
        """Which of the two animation variants is showing right now."""
        ticks = int(time.monotonic() * 1000) // ANIM_PERIOD_MS
        return 1 if ticks % 2 == 0 else 2

    def _player_anim_phase(self) -> int:
        """Pac-Man's 3-phase chomp: 0 = mouth shut, then the two opens.

        The closed frame is the shared ``full_pacman`` circle, so the
        cycle reads as a real chomp (shut -> part -> wide) instead of
        flicking between two open mouths.
        """
        ticks = int(time.monotonic() * 1000) // ANIM_PERIOD_MS
        return int(ticks % 3)

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
        x1, y1 = min(x + w, self.width), min(y + h, self.height)
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

    _MENU_SCREENS = (Screen.MAIN_MENU, Screen.INSTRUCTIONS, Screen.HIGHSCORES)

    def draw(self) -> None:
        """Render one frame of the shell's current screen.

        EVERYTHING -- board, sprites and text alike -- is composed into
        the off-screen image and blitted once. Drawing text separately
        onto the window (``mlx_string_put``) is what made the menus
        flicker: each frame's blit wiped the text before it was redrawn,
        so any frame presented in between showed none of it.
        """
        if self.shell.screen in self._MENU_SCREENS:
            self._draw_menu_screen()
        else:  # PLAYING / PAUSED / NAME_ENTRY all show the board.
            self._draw_game()
            self._draw_hud()
            if self.shell.screen is Screen.PAUSED:
                self._draw_pause_overlay()
            elif self.shell.screen is Screen.NAME_ENTRY:
                self._draw_name_overlay()
        self.mlx.mlx_put_image_to_window(
            self.mlx_ptr, self.win_ptr, self.img_ptr, 0, 0,
        )

    # -- Text -----------------------------------------------------------

    def _text(self, x: int, y: int, text: str,
              color: tuple[int, int, int], scale: int) -> None:
        """Draw ``text`` into the image with its top-left at (x, y)."""
        for bx, by, bw, bh in font.runs(text, scale):
            self._rect(x + bx, y + by, bw, bh, color)

    def _text_center(self, y: int, text: str,
                     color: tuple[int, int, int], scale: int) -> None:
        """Draw ``text`` horizontally centered in the window."""
        self._text((self.width - font.text_width(text, scale)) // 2, y,
                   text, color, scale)

    # -- Menu / info screens ---------------------------------------------

    def _draw_menu_screen(self) -> None:
        """Background, frame and credit shared by every non-game screen."""
        self._fill(BACKGROUND)
        self._draw_frame()
        if self.shell.screen is Screen.MAIN_MENU:
            self._draw_main_menu()
        elif self.shell.screen is Screen.INSTRUCTIONS:
            self._draw_info_page("HOW TO PLAY", INSTRUCTIONS_LINES)
        else:
            self._draw_info_page("HIGH SCORES",
                                 self.shell.highscore_lines())
        self._draw_credit()

    def _draw_frame(self) -> None:
        """A thin arcade border inset from the window edge."""
        pad = self.ui * 4
        thick = max(2, self.ui)
        self._rect(pad, pad, self.width - 2 * pad, thick, BORDER)
        self._rect(pad, self.height - pad - thick,
                   self.width - 2 * pad, thick, BORDER)
        self._rect(pad, pad, thick, self.height - 2 * pad, BORDER)
        self._rect(self.width - pad - thick, pad, thick,
                   self.height - 2 * pad, BORDER)

    def _draw_credit(self) -> None:
        """The authors, in the bottom-right corner."""
        scale = max(1, self.ui - 1)
        text = "MADE BY AMIN & DAGEM"
        pad = self.ui * 4 + self.ui * 3
        self._text(self.width - pad - font.text_width(text, scale),
                   self.height - pad - font.text_height(scale),
                   text, CREDIT, scale)

    def _draw_main_menu(self) -> None:
        """Title, the sprite-marked selection list, and a score preview."""
        title_scale = self.ui * 3
        y = self.height // 8
        self._text_center(y, "PAC-MAN", PLAYER, title_scale)
        y += font.text_height(title_scale) + self.ui * 4
        self._text_center(y, "GHOSTS!  MORE GHOSTS!", DIM, self.ui)

        # Selection list, centered as a block so the marker has room.
        item_scale = self.ui * 2
        step = font.text_height(item_scale) + self.ui * 7
        widest = max(font.text_width(i, item_scale) for i in MAIN_MENU_ITEMS)
        left = (self.width - widest) // 2
        y = self.height // 3 + self.ui * 6
        for index, item in enumerate(MAIN_MENU_ITEMS):
            chosen = index == self.shell.menu_index
            self._text(left, y, item, SELECTED if chosen else TEXT,
                       item_scale)
            if chosen:
                self._draw_marker(left, y, item_scale)
            y += step

        self._draw_score_preview(y + self.ui * 4)

    def _draw_marker(self, left: int, y: int, scale: int) -> None:
        """Point at the highlighted item with Pac-Man (or a chevron)."""
        size = font.text_height(scale)
        cx = left - size - self.ui * 4
        name = self._first_loaded(
            ["pacman_east_1", "pacman_east", "full_pacman", "pacman"]
        )
        if name is None or not self._blit_sprite_px(name, cx, y, size):
            self._text(cx, y, ">", SELECTED, scale)

    def _draw_score_preview(self, y: int) -> None:
        """Top few scores under the menu, so the board is visible at once."""
        self._text_center(y, "- HIGH SCORES -", DIM, self.ui)
        y += font.text_height(self.ui) + self.ui * 3
        for line in self.shell.highscore_lines()[:5]:
            self._text_center(y, line, TEXT, self.ui)
            y += font.text_height(self.ui) + self.ui * 2

    def _draw_info_page(self, title: str, lines: tuple[str, ...]) -> None:
        """A titled page of centered lines (instructions / highscores)."""
        title_scale = self.ui * 2
        y = self.height // 10
        self._text_center(y, title, PLAYER, title_scale)
        y += font.text_height(title_scale) + self.ui * 8
        for line in lines:
            self._text_center(y, line, TEXT, self.ui)
            y += font.text_height(self.ui) + self.ui * 3
        self._text_center(self.height - self.ui * 20,
                          "PRESS ENTER OR ESC TO GO BACK", DIM, self.ui)

    # -- In-game HUD and overlays ----------------------------------------

    def _draw_game(self) -> None:
        if self.shell.session is None:
            self._fill(BACKGROUND)
            return
        self._blit_static_layer(self.shell.session.state)
        self._draw_dynamic(self.shell.session.state)

    def _draw_hud(self) -> None:
        """Score / lives / level / time strip under the board."""
        if self.shell.session is None:
            return
        state = self.shell.session.state
        top = self.board_y + self.board
        self._rect(0, top, self.width, self.height - top, PANEL)
        self._rect(0, top, self.width, max(1, self.ui // 2), BORDER)
        text = (f"SCORE {state.score}    LIVES {state.lives}    "
                f"LEVEL {self.shell.session.level_number}    "
                f"TIME {state.seconds_remaining}")
        y = top + (self.height - top - font.text_height(self.ui)) // 2
        self._text(self.board_x + self.ui * 2, y, text, TEXT, self.ui)
        hint = "P PAUSE   F1-F5 CHEATS"
        self._text(self.width - self.board_x - self.ui * 2
                   - font.text_width(hint, max(1, self.ui - 1)),
                   y, hint, DIM, max(1, self.ui - 1))

    def _veil(self) -> None:
        """Darken the board so an overlay reads clearly over it."""
        step = 2  # every other row -> a cheap 50% scrim
        for y in range(self.board_y, self.board_y + self.board, step):
            self._rect(self.board_x, y, self.board, 1, BACKGROUND)

    def _draw_pause_overlay(self) -> None:
        self._veil()
        title_scale = self.ui * 3
        y = self.board_y + self.board // 4
        self._text_center(y, "PAUSED", PLAYER, title_scale)
        y += font.text_height(title_scale) + self.ui * 10
        item_scale = self.ui * 2
        widest = max(font.text_width(i, item_scale) for i in PAUSE_MENU_ITEMS)
        left = (self.width - widest) // 2
        for index, item in enumerate(PAUSE_MENU_ITEMS):
            chosen = index == self.shell.pause_index
            self._text(left, y, item, SELECTED if chosen else TEXT,
                       item_scale)
            if chosen:
                self._draw_marker(left, y, item_scale)
            y += font.text_height(item_scale) + self.ui * 7

    def _draw_name_overlay(self) -> None:
        self._veil()
        title_scale = self.ui * 3
        y = self.board_y + self.board // 5
        title = "VICTORY!" if self.shell.final_won else "GAME OVER"
        self._text_center(y, title, PLAYER, title_scale)
        y += font.text_height(title_scale) + self.ui * 8
        self._text_center(y, f"FINAL SCORE  {self.shell.final_score}",
                          TEXT, self.ui * 2)
        y += font.text_height(self.ui * 2) + self.ui * 10
        self._text_center(y, "ENTER YOUR NAME", DIM, self.ui)
        y += font.text_height(self.ui) + self.ui * 5
        self._text_center(y, self.shell.name_buffer + "_", SELECTED,
                          self.ui * 2)
        y += font.text_height(self.ui * 2) + self.ui * 8
        self._text_center(y, "LETTERS DIGITS SPACES - MAX 10 - ENTER SAVES",
                          DIM, max(1, self.ui - 1))

    # -- Board rendering into the image buffer -------------------------

    def _geometry(self, state: GameState) -> tuple[int, int, int]:
        """Tile size and pixel origin of the maze inside the play area."""
        adapter = state.adapter
        tile = max(4, min(self.board // adapter.width,
                          self.board // adapter.height))
        ox = self.board_x + (self.board - tile * adapter.width) // 2
        oy = self.board_y + (self.board - tile * adapter.height) // 2
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
        # Ghosts vanish while Pac-Man dies, as in the arcade -- nothing
        # should be moving or crowding the frame during the animation.
        dying = state.dying_ticks > 0
        for ghost in [] if dying else state.ghosts:
            fx, fy = state.ghost_render_pos(ghost)
            name = self._first_loaded(self._ghost_sprite(ghost))
            if name is None or not self._blit_sprite(name, fx, fy,
                                                     tile, ox, oy):
                dot(fx, fy, max(3, tile // 3), self._ghost_color(ghost))
        px, py = state.player_render_pos()
        radius = max(3, tile // 3)
        name = self._first_loaded(self._player_sprite(state))
        drawn = name is not None and self._blit_sprite(name, px, py,
                                                       tile, ox, oy)
        if not drawn:
            dot(px, py, radius, PLAYER)
        # A directional sprite already shows which way he faces, so the
        # extra nose would only clutter it; the queued-turn cue stays.
        self._draw_player_heading(state, px, py, tile, ox, oy, radius,
                                  show_nose=not drawn)

    def _ghost_sprite(self, ghost: Ghost) -> list[str]:
        """Candidate sprite names for a ghost, best match first.

        Eaten ghosts are just eyes looking where they travel; frightened
        ghosts share one blue set regardless of heading; otherwise it is
        the personality's own directional, animated set.
        """
        facing = DIR_NAME[ghost.direction]
        frame = self._anim_frame()
        if ghost.mode is GhostMode.EATEN:
            return [f"floating_eyes_{facing}", "floating_eyes", "eyes"]
        if ghost.mode is GhostMode.FRIGHTENED:
            return [f"frightened_{frame}", "frightened_1", "frightened"]
        name = ghost.personality.name.lower()
        return [f"ghost_{name}_{facing}_{frame}", f"ghost_{name}_{facing}_1",
                f"ghost_{name}_{facing}", f"ghost_{name}", name]

    def _player_sprite(self, state: GameState) -> list[str]:
        """Candidate sprite names for Pac-Man, best match first.

        While the death pause runs, the dying frames take over: the
        elapsed fraction of the pause picks the frame, so the sequence
        plays once, in order, however many frames were drawn.
        """
        if state.dying_ticks > 0:
            return [self._death_sprite(state)]
        facing = DIR_NAME[state.player_direction]
        phase = self._player_anim_phase()
        if phase == 0:  # mouth shut: the shared full circle
            return ["full_pacman", f"pacman_{facing}_1",
                    f"pacman_{facing}", "pacman"]
        return [f"pacman_{facing}_{phase}", f"pacman_{facing}_1",
                f"pacman_{facing}", "full_pacman", "pacman"]

    def _death_frames(self) -> int:
        """How many ``pacman_death_<n>`` frames are actually loaded."""
        if self._death_frame_count is None:
            count = 0
            for index in range(1, MAX_DEATH_FRAMES + 1):
                if f"pacman_death_{index}" not in self.sprites:
                    break
                count = index
            self._death_frame_count = count
        return self._death_frame_count

    def _death_sprite(self, state: GameState) -> str:
        """The dying frame for how far the death pause has progressed."""
        frames = self._death_frames()
        if frames == 0:
            return "full_pacman"
        total = max(1, state.death_pause_ticks)
        elapsed = total - state.dying_ticks
        index = min(frames, elapsed * frames // total + 1)
        return f"pacman_death_{index}"

    def _first_loaded(self, candidates: list[str]) -> str | None:
        """The first candidate that actually has a sprite loaded."""
        for name in candidates:
            if name in self.sprites:
                return name
        return None

    def _blit_sprite(self, name: str, fx: float, fy: float,
                     tile: int, ox: int, oy: int) -> bool:
        """Composite sprite ``name`` centered on cell (fx, fy); True if drawn.

        Returns False when no such sprite is loaded, so the caller draws
        its fallback shape. The sprite is scaled to SPRITE_SCALE of the
        tile and centered on the cell, its transparent pixels skipped, so
        it blends over walls/pellets with a margin from the borders.
        """
        size = max(4, int(tile * SPRITE_SCALE))
        center_x = ox + fx * tile + tile / 2
        center_y = oy + fy * tile + tile / 2
        return self._blit_sprite_px(name, int(center_x - size / 2),
                                    int(center_y - size / 2), size)

    def _blit_sprite_px(self, name: str, left: int, top: int,
                        size: int) -> bool:
        """Composite sprite ``name`` at a pixel position; True if drawn.

        The pixel-space entry point (menus use it for the selection
        marker); returns False when the sprite is not loaded so callers
        can fall back. Runs are clipped to the image bounds.
        """
        runs = self._scaled_runs(name, size)
        if runs is None:
            return False
        assert self.buffer is not None
        for dy, dx0, run in runs:
            y = top + dy
            if not (0 <= y < self.height):
                continue
            x = left + dx0
            run_px = len(run) // 4
            if x < 0:  # clip left
                cut = -x
                if cut >= run_px:
                    continue
                run, x, run_px = run[cut * 4:], 0, run_px - cut
            if x + run_px > self.width:  # clip right
                keep = self.width - x
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
        tile: int, ox: int, oy: int, radius: int, show_nose: bool = True,
    ) -> None:
        """Point a nose the way Pac-Man moves, and flag a queued turn.

        Two separate facts, because they answer different questions. The
        yellow nose just off the body is where he IS going -- skipped
        (``show_nose=False``) when a directional sprite already says so.
        The green marker at the tile edge is where he WILL go -- the
        buffered press, which only fires once he reaches a center.
        Showing the queued one is what makes a 90-degree turn feel
        acknowledged rather than swallowed: the input is visibly accepted
        the instant it is pressed, even though the corner has to wait.
        """
        cx = int(ox + px * tile + tile // 2)
        cy = int(oy + py * tile + tile // 2)
        size = max(3, tile // 9)
        facing = state.player_direction
        if show_nose:
            reach = radius + max(1, tile // 24) + size
            self._arrow(cx + facing.dx * reach, cy + facing.dy * reach,
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
