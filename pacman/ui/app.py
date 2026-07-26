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
from pacman.highscore.store import TOP_N, HighscoreEntry
from pacman.maze.adapter import Direction
from pacman.ui import font
from pacman.ui.shell import (
    INSTRUCTION_CHEATS,
    INSTRUCTION_RULES,
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
# Letters and icons are outlined rather than sat on a slab of colour, so
# they stay legible over the menu artwork without hiding it.
OUTLINE = (0, 0, 0)

# The eight directions an outline is stamped in, before the glyph or
# sprite itself is drawn on top.
_OUTLINE_OFFSETS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0), (1, 0),
    (-1, 1), (0, 1), (1, 1),
)

GHOST_COLORS = {
    GhostPersonality.BLINKY: (255, 40, 40),
    GhostPersonality.PINKY: (255, 150, 200),
    GhostPersonality.INKY: (60, 220, 255),
    GhostPersonality.CLYDE: (255, 160, 40),
}

# -- "How to play" page palette ------------------------------------------
# This screen gets its own dark, high-contrast page (not the busy menu
# artwork) so every control reads cleanly. Keys are drawn as bevelled
# caps: movement keys glow Pac-Man yellow, secondary keys arcade blue,
# cheat keys the intent green -- the same colour language as in-game.
INSTRUCT_BG = (8, 8, 20)          # blacker than the game background
INSTRUCT_HEADING = (120, 200, 255)  # section labels
KEY_SHADOW = (2, 2, 8)            # drop shadow under a keycap
KEY_FACE = (30, 32, 60)           # dark keycap face
KEY_FACE_HI = (52, 56, 96)        # top bevel highlight of a keycap
MOVE_ACCENT = PLAYER              # movement keys wear Pac-Man yellow
KEY_ACCENT = (90, 120, 230)       # secondary keys (P / ESC) arcade blue
CHEAT_ACCENT = INTENT             # cheat keys share the intent green
# Rank accents on the High-Scores page, first place down. Deliberately
# the How-to-Play page's own three accents rather than gold/silver/
# bronze, so both info pages speak one colour language.
RANK_ACCENTS = (MOVE_ACCENT, KEY_ACCENT, CHEAT_ACCENT)
# Ranks past the podium: clearly subordinate, but still bright enough to
# read against the near-black page (the keycap face itself is far too
# dark for a rim and a numeral).
RANK_PLAIN = (112, 118, 165)
# Which sprite stands in for each rule icon on the How-to-Play page.
RULE_ICON_SPRITES = {
    "ghost": ["ghost_blinky_east_1", "ghost_blinky_east", "ghost_blinky"],
    "pacman": ["pacman_east_1", "pacman_east", "full_pacman", "pacman"],
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

# Artwork stretched behind the menu/info screens, if present.
MENU_BACKGROUND = "menu_background"

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
            tuple[str, int, int], list[tuple[int, int, bytes]]
        ] = {}
        self._death_frame_count: int | None = None
        # Whether the menu artwork is present; when it is, the UI drops
        # its own title/credit (the picture supplies them).
        self._has_art = False
        # Resize guard: MLX's Vulkan swapchain cannot survive a window
        # resize (it dies with "can't get next sw image", uncatchable in
        # Python). The maximize button triggers exactly that, so on any
        # configure event we rebuild the window at the fixed size --
        # snapping the resize back instead of crashing. Debounced so the
        # rebuild's own configure events don't loop.
        self._rebuilding = False
        self._last_rebuild = 0.0

    # -- Lifecycle -----------------------------------------------------

    def setup(self) -> None:
        """Open a display-sized window, allocate the buffer, load sprites."""
        self.mlx_ptr = self.mlx.mlx_init()
        self._resolve_geometry()
        self._last_rebuild = time.monotonic()
        self._create_surface()
        self._load_sprites()

    def _create_surface(self) -> None:
        """Create the window + off-screen image and register its hooks.

        Split out so the resize guard (:meth:`_on_configure`) can rebuild
        a fresh window/swapchain at the fixed size. Every hook lives on
        the window, so they are all re-registered here; the static layer
        is invalidated because the new image is a different buffer.
        """
        self.win_ptr = self.mlx.mlx_new_window(
            self.mlx_ptr, self.width, self.height, "42 Pac-Man",
        )
        self.img_ptr = self.mlx.mlx_new_image(
            self.mlx_ptr, self.width, self.height,
        )
        self.buffer, _bpp, self.size_line, _fmt = (
            self.mlx.mlx_get_data_addr(self.img_ptr)
        )
        self._static_for = None  # new buffer -> rebuild the static layer
        self.mlx.mlx_hook(self.win_ptr, 2, 1, self._on_key, None)  # KeyPress
        self.mlx.mlx_hook(self.win_ptr, 33, 0, self._on_close, None)  # close
        # 22 = ConfigureNotify, StructureNotifyMask = 1 << 17.
        self.mlx.mlx_hook(self.win_ptr, 22, 1 << 17, self._on_configure, None)

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
        """Set up the window and run the blocking event loop."""
        self.setup()
        self.mlx.mlx_loop_hook(self.mlx_ptr, self._on_loop, None)
        self._last_ms = time.monotonic() * 1000
        self.mlx.mlx_loop(self.mlx_ptr)
        return 0

    def _on_configure(self, _param: object) -> None:
        """Rebuild the window on a resize so MLX never crashes.

        ConfigureNotify fires on both moves and resizes; MLX gives no new
        size to tell them apart, and only a resize breaks the swapchain.
        So on either we rebuild the window at the fixed size: a resize is
        snapped back, a move is harmless. Debounced (and guarded against
        re-entry) so the fresh window's own configure events don't loop.
        """
        now = time.monotonic()
        if self._rebuilding or now - self._last_rebuild < 0.5:
            return
        self._rebuilding = True
        try:
            self.mlx.mlx_destroy_image(self.mlx_ptr, self.img_ptr)
            self.mlx.mlx_destroy_window(self.mlx_ptr, self.win_ptr)
            self._create_surface()
        finally:
            self._last_rebuild = time.monotonic()
            self._rebuilding = False

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
        if self._rebuilding:  # window/image being replaced -- don't draw
            return
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
            elif self.shell.banner_text is not None:
                self._draw_banner(self.shell.banner_text)
            else:
                self._draw_eat_score()
        self.mlx.mlx_put_image_to_window(
            self.mlx_ptr, self.win_ptr, self.img_ptr, 0, 0,
        )

    # -- Text -----------------------------------------------------------

    def _text(self, x: int, y: int, text: str,
              color: tuple[int, int, int], scale: int,
              outline: bool = False) -> None:
        """Draw ``text`` into the image with its top-left at (x, y).

        With ``outline`` the glyphs are stamped in :data:`OUTLINE` eight
        ways first, so the letters keep a hard edge over busy artwork
        without needing a panel behind them.
        """
        blocks = list(font.runs(text, scale))
        if outline:
            edge = max(1, scale // 2)
            for ox, oy in _OUTLINE_OFFSETS:
                dx, dy = ox * edge, oy * edge
                for bx, by, bw, bh in blocks:
                    self._rect(x + bx + dx, y + by + dy, bw, bh, OUTLINE)
        for bx, by, bw, bh in blocks:
            self._rect(x + bx, y + by, bw, bh, color)

    def _text_center(self, y: int, text: str,
                     color: tuple[int, int, int], scale: int,
                     outline: bool = False) -> None:
        """Draw ``text`` horizontally centered in the window."""
        self._text((self.width - font.text_width(text, scale)) // 2, y,
                   text, color, scale, outline)

    # -- Menu / info screens ---------------------------------------------

    def _draw_menu_screen(self) -> None:
        """Background, frame and credit shared by every non-game screen."""
        # How-to-Play and High Scores each get the same dark,
        # self-contained page layout rather than text over the busy
        # artwork, which the small print was getting lost in.
        if self.shell.screen is Screen.INSTRUCTIONS:
            self._has_art = False
            self._draw_instructions()
            return
        if self.shell.screen is Screen.HIGHSCORES:
            self._has_art = False
            self._draw_highscores()
            return
        self._has_art = self._draw_background()
        if not self._has_art:
            self._fill(BACKGROUND)
        self._draw_main_menu()
        # The artwork carries its own title and credit; drawing ours on
        # top of it would only double up.
        if not self._has_art:
            self._draw_credit()

    def _draw_background(self) -> bool:
        """Fill the window with the menu artwork; False if it is absent.

        Stretched to the whole window and cached as runs, so the cost is
        paid once rather than every frame. Menu text is drawn over it
        with a dark scrim behind each block so it stays readable.
        """
        runs = self._scaled_runs(MENU_BACKGROUND, self.width, self.height)
        if runs is None:
            return False
        assert self.buffer is not None
        for dy, dx0, run in runs:
            if not (0 <= dy < self.height):
                continue
            off = dy * self.size_line + dx0 * 4
            self.buffer[off:off + len(run)] = run
        return True

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
        if not self._has_art:  # the artwork already says "PACMAN"
            self._text_center(y, "PAC-MAN", PLAYER, title_scale, True)
            y += font.text_height(title_scale) + self.ui * 4
            self._text_center(y, "GHOSTS!  MORE GHOSTS!", DIM, self.ui, True)

        # Selection list, centered as a block so the marker has room.
        item_scale = self.ui * 2
        step = font.text_height(item_scale) + self.ui * 7
        widest = max(font.text_width(i, item_scale) for i in MAIN_MENU_ITEMS)
        left = (self.width - widest) // 2
        y = self.height // 3 + self.ui * 6
        for index, item in enumerate(MAIN_MENU_ITEMS):
            chosen = index == self.shell.menu_index
            self._text(left, y, item, SELECTED if chosen else TEXT,
                       item_scale, True)
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
        drawn = name is not None and self._blit_sprite_px(
            name, cx, y, size, outline=True,
        )
        if not drawn:
            self._text(cx, y, ">", SELECTED, scale, True)

    def _draw_score_preview(self, y: int) -> None:
        """Top few scores under the menu, so the board is visible at once."""
        self._text_center(y, "- HIGH SCORES -", DIM, self.ui, True)
        y += font.text_height(self.ui) + self.ui * 3
        for line in self.shell.highscore_lines()[:5]:
            self._text_center(y, line, TEXT, self.ui, True)
            y += font.text_height(self.ui) + self.ui * 2

    # -- Shared info-page furniture --------------------------------------

    def _draw_page_title(self, title: str) -> int:
        """Centred page title over its accent underline; returns the y
        just below it.

        Shared by How-to-Play and High Scores so both pages open exactly
        the same way.
        """
        s = self.ui
        title_scale = s * 3
        y = max(s * 6, self.height // 20)
        self._text_center(y, title, PLAYER, title_scale, True)
        y += font.text_height(title_scale) + s * 3
        dw = font.text_width(title, title_scale) + s * 24
        self._rect(self.width // 2 - dw // 2, y, dw, max(2, s), KEY_ACCENT)
        return y + s * 9

    def _draw_page_footer(self) -> int:
        """The shared "go back" line; returns its y so callers can
        balance whatever sits above it."""
        s = self.ui
        y = self.height - s * 5 - font.text_height(s)
        self._text_center(y, "PRESS ENTER OR ESC TO GO BACK", DIM, s, True)
        return y

    # -- High scores page --------------------------------------------------

    def _draw_highscores(self) -> None:
        """The leaderboard, in the How-to-Play page's theme.

        Same furniture as the controls page -- near-black backdrop,
        yellow title over an accent underline, an arcade-blue section
        label, the chase strip and the same footer -- so the two info
        screens read as one family. Each row reuses the keycap shape as
        a rank badge, which is what ties the table to the keyboard
        diagram visually.
        """
        self._fill(INSTRUCT_BG)
        s = self.ui
        cx = self.width // 2
        y = self._draw_page_title("HIGH SCORES")

        self._section_label(cx, y, f"TOP {TOP_N} - ALL TIME")
        y += font.text_height(s) + s * 6

        footer_y = self._draw_page_footer()
        strip = font.text_height(s * 2) + s * 6
        chase_top = footer_y - strip - s * 5

        entries = self.shell.highscores.entries
        if entries:
            self._draw_score_table(cx, y, chase_top - s * 4, entries)
        else:
            self._text_center((y + chase_top) // 2,
                              "NO HIGH SCORES YET - BE THE FIRST!",
                              TEXT, max(2, s), True)
        self._draw_chase_strip(cx, chase_top, strip)

    def _draw_score_table(self, center_x: int, top: int, bottom: int,
                          entries: list[HighscoreEntry]) -> None:
        """Rank badge + name + right-aligned score, one row per entry.

        The row pitch is divided out of the space actually left between
        the header and the chase strip, so a full table of ten never
        runs into the footer on a short window and a table of two does
        not float in the middle of nowhere.
        """
        s = self.ui
        scale = max(2, s)
        rank_scale = max(2, s * 2)
        ranks = [str(index + 1) for index in range(len(entries))]
        height = font.text_height(rank_scale) + s * 3
        # Every badge takes the width of the widest rank, so a two-digit
        # "10" is not squeezed out of its cap and the name column still
        # starts on one line.
        width = max(height,
                    max(font.text_width(r, rank_scale) for r in ranks) + s * 6)
        pitch = max(height + s * 2,
                    min(height + s * 8, (bottom - top) // len(entries)))

        # One shared column grid: the widest name and the widest score
        # decide it, so the numbers line up in a true right-aligned
        # column instead of drifting with each name's length.
        gap, col_gap = s * 6, s * 12
        name_w = max(font.text_width(e.name.upper(), scale) for e in entries)
        score_w = max(font.text_width(str(e.score), scale) for e in entries)
        left = center_x - (width + gap + name_w + col_gap + score_w) // 2
        name_x = left + width + gap
        score_right = name_x + name_w + col_gap + score_w
        # Nudge the block down off the header, but only a little: a full
        # ten rows then sit centred in their space, while a table of two
        # still flows from the top of the page instead of floating in
        # the middle of it.
        block = pitch * (len(entries) - 1) + height
        top += min(max(0, (bottom - top - block) // 2), s * 10)

        for index, entry in enumerate(entries):
            accent = (RANK_ACCENTS[index] if index < len(RANK_ACCENTS)
                      else RANK_PLAIN)
            y = top + index * pitch
            self._keycap(left, y, width, height, accent,
                         glyph=ranks[index], scale=rank_scale)
            text_y = y + (height - font.text_height(scale)) // 2
            self._text(name_x, text_y, entry.name.upper(),
                       TEXT if index < len(RANK_ACCENTS) else DIM,
                       scale, True)
            score = str(entry.score)
            self._text(score_right - font.text_width(score, scale), text_y,
                       score, accent, scale, True)

    # -- "How to play" page ----------------------------------------------

    def _keycap(self, x: int, y: int, w: int, h: int,
                accent: tuple[int, int, int], glyph: str = "",
                arrow: Direction | None = None, scale: int = 1) -> None:
        """One bevelled keyboard cap with a glowing accent rim.

        A drop shadow, an ``accent`` rim, a dark face and a top bevel
        line give it depth; the content is either a centred ``glyph`` or
        a rendered ``arrow`` (one of the four directions), both in
        ``accent`` so the live controls pop against the dark page.
        """
        r = max(3, min(w, h) // 5)
        edge = max(2, min(w, h) // 14)
        self._round_rect(x + edge, y + edge, w, h, r, KEY_SHADOW)
        self._round_rect(x, y, w, h, r, accent)
        fw, fh, fr = w - 2 * edge, h - 2 * edge, max(2, r - edge)
        self._round_rect(x + edge, y + edge, fw, fh, fr, KEY_FACE)
        self._rect(x + edge + fr, y + edge * 2, fw - 2 * fr,
                   max(2, h // 12), KEY_FACE_HI)
        cx, cy = x + w // 2, y + h // 2
        if arrow is not None:
            a = max(4, min(w, h) // 4)
            self._arrow(cx + arrow.dx * (a // 2), cy + arrow.dy * (a // 2),
                        arrow, a, accent)
        elif glyph:
            self._text(cx - font.text_width(glyph, scale) // 2,
                       cy - font.text_height(scale) // 2, glyph, accent,
                       scale)

    def _key_cluster(self, center_x: int, top: int, k: int, gap: int,
                     accent: tuple[int, int, int], letters: str = "") -> None:
        """A four-key inverted-T cluster (arrow keys, or a W/A/S/D set).

        ``letters`` (top, left, down, right) picks lettered caps; empty
        draws directional arrows instead. Both share the classic layout
        so the two options read as the same shape.
        """
        step = k + gap
        # (col offset, row offset) for up, left, down, right.
        slots = ((0, 0), (-1, 1), (0, 1), (1, 1))
        arrows = (Direction.NORTH, Direction.WEST,
                  Direction.SOUTH, Direction.EAST)
        for index, (dc, dr) in enumerate(slots):
            x = center_x + dc * step - k // 2
            y = top + dr * step
            if letters:
                self._keycap(x, y, k, k, accent, glyph=letters[index],
                             scale=max(2, self.ui * 2))
            else:
                self._keycap(x, y, k, k, accent, arrow=arrows[index])

    def _labelled_key(self, center_x: int, top: int, w: int, h: int,
                      label: str, caption: str,
                      accent: tuple[int, int, int]) -> None:
        """A single cap centred on ``center_x`` with a caption beneath it."""
        self._keycap(center_x - w // 2, top, w, h, accent, glyph=label,
                     scale=max(2, self.ui * 2))
        cap_scale = max(1, self.ui)
        self._text(center_x - font.text_width(caption, cap_scale) // 2,
                   top + h + self.ui * 2, caption, DIM, cap_scale)

    def _draw_instructions(self) -> None:
        """The How-to-Play page: a keyboard diagram over a dark page.

        Deliberately not the menu artwork -- a near-black page keeps the
        controls legible. Everything is centred and sized from ``self.ui``
        so it fills any window the same way.
        """
        self._fill(INSTRUCT_BG)
        s = self.ui
        cx = self.width // 2
        k = font.text_height(s * 2) + s * 8   # keycap edge

        y = self._draw_page_title("HOW TO PLAY")

        # -- MOVE: arrow cluster  OR  W/A/S/D cluster --------------------
        self._section_label(cx, y, "MOVE")
        y += font.text_height(s) + s * 5
        gap = max(3, s * 2)
        span = (k + gap) * 3          # a cluster's full width
        left_cx = cx - span // 2 - k
        right_cx = cx + span // 2 + k
        self._key_cluster(left_cx, y, k, gap, MOVE_ACCENT)
        self._key_cluster(right_cx, y, k, gap, MOVE_ACCENT, letters="WASD")
        mid = y + (2 * k + gap) // 2
        self._text(cx - font.text_width("OR", s * 2) // 2,
                   mid - font.text_height(s * 2) // 2, "OR", TEXT, s * 2)
        y += 2 * k + gap + s * 8

        # -- PAUSE / BACK ------------------------------------------------
        wide = k * 2
        row_gap = s * 12
        group = wide + row_gap + wide
        self._labelled_key(cx - group // 2 + wide // 2, y, wide, k,
                           "P", "PAUSE", KEY_ACCENT)
        self._labelled_key(cx + group // 2 - wide // 2, y, wide, k,
                           "ESC", "BACK", KEY_ACCENT)
        y += k + font.text_height(s) + s * 10

        # -- CHEATS ------------------------------------------------------
        self._section_label(cx, y, "CHEATS - FOR REVIEWERS")
        y += font.text_height(s) + s * 5
        self._draw_cheat_row(cx, y, k)
        y += k + font.text_height(s) + s * 10

        # -- GOAL legend + a decorative chase strip ----------------------
        legend_bottom = self._draw_rule_legend(cx, y, k)
        footer_y = self._draw_page_footer()
        # Centre the chase strip in whatever space is left below the
        # legend so the bottom never feels either crammed or hollow.
        chase_top = max(legend_bottom + s * 4,
                        (legend_bottom + footer_y - k) // 2)
        chase_top = min(chase_top, footer_y - k - s * 4)
        self._draw_chase_strip(cx, chase_top, k)

    def _section_label(self, center_x: int, y: int, text: str) -> None:
        """A small arcade-blue heading centred over a section."""
        self._text(center_x - font.text_width(text, self.ui) // 2, y,
                   text, INSTRUCT_HEADING, self.ui, True)

    def _draw_cheat_row(self, center_x: int, top: int, k: int) -> None:
        """The F1-F5 caps in a row, each with its caption beneath it.

        The pitch is stretched to the widest caption so the labels sit
        cleanly under their own key instead of colliding.
        """
        s = self.ui
        cap_scale = max(1, s - 1)
        widest = max(font.text_width(c, cap_scale) for _, c in
                     INSTRUCTION_CHEATS)
        step = max(k + s * 6, widest + s * 4)
        start = center_x - (step * len(INSTRUCTION_CHEATS)) // 2 + step // 2
        for index, (key, caption) in enumerate(INSTRUCTION_CHEATS):
            kx = start + index * step
            self._keycap(kx - k // 2, top, k, k, CHEAT_ACCENT, glyph=key,
                         scale=max(2, s * 2))
            self._text(kx - font.text_width(caption, cap_scale) // 2,
                       top + k + s * 2, caption, DIM, cap_scale)

    def _draw_rule_legend(self, center_x: int, top: int, k: int) -> int:
        """The goal/rules lines, each stamped with its icon; returns the
        y just past the last line so the caller can balance the space
        below it."""
        s = self.ui
        icon = int(k * 0.8)
        scale = max(2, s)
        line_h = max(icon, font.text_height(scale)) + s * 4
        gap = s * 5
        widest = max(font.text_width(text, scale) for _, text in
                     INSTRUCTION_RULES)
        left = center_x - (icon + gap + widest) // 2
        y = top
        for kind, text in INSTRUCTION_RULES:
            self._draw_rule_icon(kind, left, y, icon)
            self._text(left + icon + gap,
                       y + (icon - font.text_height(scale)) // 2,
                       text, TEXT, scale, True)
            y += line_h
        return y

    def _draw_rule_icon(self, kind: str, x: int, y: int, size: int) -> None:
        """Draw the little icon that opens a rule line."""
        cx, cy = x + size // 2, y + size // 2
        if kind == "pellet":
            self._disc_color(cx, cy, max(2, size // 6), PELLET)
            return
        if kind == "super":
            self._disc_color(cx, cy, max(3, size // 3), PELLET)
            return
        names = RULE_ICON_SPRITES.get(kind, [])
        name = self._first_loaded(names)
        if name is None or not self._blit_sprite_px(name, x, y, size):
            color = (GHOST_COLORS[GhostPersonality.BLINKY]
                     if kind == "ghost" else PLAYER)
            self._disc_color(cx, cy, size // 3, color)

    def _draw_chase_strip(self, center_x: int, top: int, size: int) -> None:
        """Pac-Man leading the four ghosts -- the classic attract motif."""
        gap = size + self.ui * 6
        actors = [
            self._first_loaded(["pacman_east_1", "pacman_east",
                                "full_pacman", "pacman"]),
        ]
        for personality in GhostPersonality:
            name = personality.name.lower()
            actors.append(self._first_loaded(
                [f"ghost_{name}_east_1", f"ghost_{name}_east",
                 f"ghost_{name}"]))
        start = center_x - (gap * (len(actors) - 1)) // 2 - size // 2
        for index, sprite in enumerate(actors):
            if sprite is not None:
                self._blit_sprite_px(sprite, start + index * gap, top, size)

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
        # Anchored to the window, not the board: the board is a centred
        # square, so both strings were being squeezed into its span --
        # colliding over the time readout on a wide screen -- while the
        # margins either side of it sat empty.
        self._text(self.ui * 2, y, text, TEXT, self.ui)
        hint = "P PAUSE   F1-F5 CHEATS"
        self._text(self.width - self.ui * 2
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
                       item_scale, True)
            if chosen:
                self._draw_marker(left, y, item_scale)
            y += font.text_height(item_scale) + self.ui * 7

    def _draw_eat_score(self) -> None:
        """Show what a caught ghost scored, over the spot it was caught.

        Only while the engine's eat pause holds everything still, which
        is what gives the number time to be read (arcade behaviour).
        """
        if self.shell.session is None:
            return
        state = self.shell.session.state
        if state.eaten_ticks <= 0:
            return
        tile, ox, oy = self._geometry(state)
        cx = ox + state.last_eat_cell[0] * tile + tile // 2
        cy = oy + state.last_eat_cell[1] * tile + tile // 2
        text = str(state.last_eat_score)
        scale = max(2, self.ui)
        self._text(cx - font.text_width(text, scale) // 2,
                   cy - font.text_height(scale) // 2,
                   text, EYES, scale, True)

    def _draw_banner(self, text: str) -> None:
        """An interstitial word over the still board (READY! and friends).

        Deliberately no dimming veil: the arcade leaves the maze fully
        visible so you can read the board during the pause. The message
        sits just below the middle, clear of the player's spawn.
        """
        scale = self.ui * 3
        y = self.board_y + self.board // 2 + font.text_height(scale)
        width = font.text_width(text, scale)
        pad = self.ui * 4
        self._rect((self.width - width) // 2 - pad, y - pad,
                   width + 2 * pad, font.text_height(scale) + 2 * pad,
                   BACKGROUND)
        self._text_center(y, text, SELECTED, scale)

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
        """Render background + walls + sealed blocks once for this level.

        Walls use the arcade "blue tube" style: instead of a flat line on
        the cell boundary, every corridor traces a line inset from each
        of its wall edges, so a wall shared by two corridors becomes two
        parallel lines and corners round off -- all derived from the wall
        bitmask, no artwork needed.
        """
        self._fill(BACKGROUND)
        adapter = state.adapter
        tile, ox, oy = self._geometry(state)
        thick = max(2, tile // 7)
        radius = thick // 2
        for y in range(adapter.height):
            for x in range(adapter.width):
                left, top = ox + x * tile, oy + y * tile
                if not adapter.is_walkable(x, y):
                    self._rect(left, top, tile, tile, BLOCK)
                    continue
                moves = adapter.get_valid_moves(x, y)
                right, bottom = left + tile, top + tile
                if Direction.NORTH not in moves:
                    self._wall_line(left, top, right, top, radius)
                if Direction.SOUTH not in moves:
                    self._wall_line(left, bottom, right, bottom, radius)
                if Direction.WEST not in moves:
                    self._wall_line(left, top, left, bottom, radius)
                if Direction.EAST not in moves:
                    self._wall_line(right, top, right, bottom, radius)
        assert self.buffer is not None
        self._static_layer = bytearray(self.buffer)
        self._static_for = id(state.adapter)

    def _wall_line(self, x0: int, y0: int, x1: int, y1: int,
                   radius: int) -> None:
        """Draw one wall as a rounded stroke centred on a cell edge.

        A single line, ``2*radius+1`` thick, with a filled disc at each
        end. That is all the wall logic needs: collinear edges share an
        endpoint so their discs and bars merge into a continuous line;
        two edges meeting at a cell corner share a disc, which rounds the
        corner; and an isolated wall edge is just a bar with two rounded
        caps -- so every wall reads the same, with no doubling, no
        floating pills, and no neighbour look-ups.
        """
        if y0 == y1:  # horizontal edge
            self._rect(x0, y0 - radius, x1 - x0, 2 * radius + 1, WALL)
        else:  # vertical edge
            self._rect(x0 - radius, y0, 2 * radius + 1, y1 - y0, WALL)
        self._disc(x0, y0, radius)
        self._disc(x1, y1, radius)

    def _disc(self, cx: int, cy: int, radius: int) -> None:
        """Fill a solid wall-coloured circle (rounds a wall joint or end)."""
        self._disc_color(cx, cy, radius, WALL)

    def _disc_color(self, cx: int, cy: int, radius: int,
                    color: tuple[int, int, int]) -> None:
        """Fill a solid circle of ``color`` centred on (cx, cy)."""
        for dy in range(-radius, radius + 1):
            dx = int((radius * radius - dy * dy) ** 0.5)
            self._rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

    def _round_rect(self, x: int, y: int, w: int, h: int, radius: int,
                    color: tuple[int, int, int]) -> None:
        """Fill a rectangle with rounded corners (a cross plus 4 discs)."""
        r = max(0, min(radius, w // 2, h // 2))
        if r == 0:
            self._rect(x, y, w, h, color)
            return
        self._rect(x + r, y, w - 2 * r, h, color)
        self._rect(x, y + r, w, h - 2 * r, color)
        for cx, cy in ((x + r, y + r), (x + w - 1 - r, y + r),
                       (x + r, y + h - 1 - r), (x + w - 1 - r, y + h - 1 - r)):
            self._disc_color(cx, cy, r, color)

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

        self._draw_spawn_markers(state, tile, ox, oy)
        for cell in state.pacgum_cells:
            dot(cell[0], cell[1], max(1, tile // 10), PELLET)
        for cell in state.super_pacgum_cells:
            dot(cell[0], cell[1], max(3, tile // 4), PELLET)
        # Ghosts stay on screen through the caught hold (so you see who
        # got you), then vanish once the dying animation itself begins.
        hide_ghosts = state.dying_ticks > 0 and not state.is_caught_hold
        for ghost in [] if hide_ghosts else state.ghosts:
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

        A catch shows in two beats: during the caught hold he keeps his
        normal facing sprite, frozen, so it registers; then the dying
        frames play once, in order, across the animation portion of the
        pause -- however many were drawn.
        """
        if state.dying_ticks > 0:
            if state.is_caught_hold:
                facing = DIR_NAME[state.player_direction]
                return [f"pacman_{facing}_1", f"pacman_{facing}",
                        "full_pacman", "pacman"]
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
        """The dying frame for how far the animation has progressed.

        Mapped across the animation portion only (after the caught hold),
        so the frames span the whole spin rather than being rushed.
        """
        frames = self._death_frames()
        if frames == 0:
            return "full_pacman"
        anim = max(1, state.death_anim_ticks)
        elapsed = max(0, anim - state.dying_ticks)
        index = min(frames, elapsed * frames // anim + 1)
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
                        size: int, outline: bool = False) -> bool:
        """Composite sprite ``name`` at a pixel position; True if drawn.

        The pixel-space entry point (menus use it for the selection
        marker); returns False when the sprite is not loaded so callers
        can fall back. Runs are clipped to the image bounds. With
        ``outline`` the silhouette is stamped in :data:`OUTLINE` eight
        ways first, matching the outlined lettering beside it.
        """
        runs = self._scaled_runs(name, size, size)
        if runs is None:
            return False
        assert self.buffer is not None
        if outline:
            edge = max(1, size // 12)
            for ox, oy in _OUTLINE_OFFSETS:
                for dy, dx0, run in runs:
                    self._rect(left + dx0 + ox * edge,
                               top + dy + oy * edge,
                               len(run) // 4, 1, OUTLINE)
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

    def _scaled_runs(self, name: str, width: int,
                     height: int) -> list[tuple[int, int, bytes]] | None:
        """Nearest-neighbor-scale a sprite to width x height as runs.

        Each run is ``(dy, dx_start, bytes)`` -- a horizontal span of
        adjacent non-transparent pixels, packed once and cached, so a
        frame just slice-copies a handful of runs per entity. Non-square
        scaling is what lets the menu artwork stretch to fill the window
        while sprites stay square.
        """
        sprite = self.sprites.get(name)
        if sprite is None:
            return None
        cached = self._sprite_runs.get((name, width, height))
        if cached is not None:
            return cached
        src_w, src_h, grid = sprite
        runs: list[tuple[int, int, bytes]] = []
        for dy in range(height):
            row = grid[dy * src_h // height]
            dx = 0
            while dx < width:
                if row[dx * src_w // width] is None:
                    dx += 1
                    continue
                start, chunk = dx, bytearray()
                while dx < width:
                    pixel = row[dx * src_w // width]
                    if pixel is None:
                        break
                    chunk += _pack(pixel)
                    dx += 1
                runs.append((dy, start, bytes(chunk)))
        self._sprite_runs[(name, width, height)] = runs
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
            # Clear of the sprite entirely. An arrow widens BACKWARD from
            # its apex, so an apex on the tile edge buried the body under
            # Pac-Man (who fills SPRITE_SCALE of the tile) and the marker
            # effectively disappeared. Push the apex a whole half-tile
            # further out, size it up, and outline it so it reads against
            # both the maze and the player.
            marker = max(5, tile // 6)
            edge = tile // 2 + marker
            ax = cx + queued.dx * edge
            ay = cy + queued.dy * edge
            self._arrow(ax, ay, queued, marker + 1, OUTLINE)
            self._arrow(ax, ay, queued, marker, INTENT)

    def _draw_spawn_markers(self, state: GameState, tile: int,
                            ox: int, oy: int) -> None:
        """Ring each ghost's home corner in that ghost's own colour.

        Shows at a glance whose corner is whose -- where a ghost scatters
        back to and where its eyes return when eaten. Drawn as a hollow
        square under everything else so it never reads as something
        edible.
        """
        thickness = max(1, tile // 14)
        inset = tile // 6
        span = tile - 2 * inset
        for ghost in state.ghosts:
            hx, hy = ghost.home_corner
            color = GHOST_COLORS[ghost.personality]
            left = ox + hx * tile + inset
            top = oy + hy * tile + inset
            self._rect(left, top, span, thickness, color)
            self._rect(left, top + span - thickness, span, thickness, color)
            self._rect(left, top, thickness, span, color)
            self._rect(left + span - thickness, top, thickness, span, color)

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

    ``KeyboardInterrupt`` (Ctrl+C) is deliberately *not* swallowed here:
    it is a ``BaseException``, so the bare ``except Exception`` below
    lets it propagate to the entry point, which prints a clean
    "Interrupted." line and exits 130.
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
