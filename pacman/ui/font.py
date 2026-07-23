"""A tiny 5x7 bitmap font for the arcade-styled UI.

Pure data plus geometry helpers -- no graphics library, so it is
testable on its own and the renderer stays the only MLX consumer.

Why a hand-rolled font at all? MLX's ``mlx_string_put`` draws straight
onto the *window*, which forces a second pass after the frame image is
blitted; the blit wipes the previous text and the compositor can present
in between, so on-screen text visibly flickers. Rendering glyphs into
the frame buffer instead makes every frame a single atomic blit -- no
flicker -- and gives the chunky pixel look the game wants at any size.

Each glyph is 7 rows of 5 bits, MSB = leftmost pixel. Characters are
laid out on a 6-pixel pitch (5 wide + 1 blank) times the scale.
"""

from typing import Iterator

GLYPH_W = 5
GLYPH_H = 7
SPACING = 1  # blank columns between glyphs, in unscaled pixels

# Uppercase-only, arcade style; lowercase is folded to uppercase.
GLYPHS: dict[str, tuple[int, ...]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01111),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "J": (0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b11011, 0b10001),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
    "0": (0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111),
    "3": (0b11111, 0b00010, 0b00100, 0b00010, 0b00001, 0b10001, 0b01110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110),
    "6": (0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100),
    ".": (0, 0, 0, 0, 0, 0b01100, 0b01100),
    ",": (0, 0, 0, 0, 0, 0b00100, 0b01000),
    ":": (0, 0b00100, 0b00100, 0, 0b00100, 0b00100, 0),
    "-": (0, 0, 0, 0b01110, 0, 0, 0),
    "_": (0, 0, 0, 0, 0, 0, 0b11111),
    "!": (0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0, 0b00100),
    "?": (0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0, 0b00100),
    "'": (0b00100, 0b00100, 0, 0, 0, 0, 0),
    "&": (0b01100, 0b10010, 0b10100, 0b01000, 0b10101, 0b10010, 0b01101),
    "/": (0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000),
    "(": (0b00010, 0b00100, 0b01000, 0b01000, 0b01000, 0b00100, 0b00010),
    ")": (0b01000, 0b00100, 0b00010, 0b00010, 0b00010, 0b00100, 0b01000),
    "<": (0b00010, 0b00100, 0b01000, 0b10000, 0b01000, 0b00100, 0b00010),
    ">": (0b01000, 0b00100, 0b00010, 0b00001, 0b00010, 0b00100, 0b01000),
    "+": (0, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0),
    "=": (0, 0, 0b11111, 0, 0b11111, 0, 0),
    "*": (0, 0b10101, 0b01110, 0b11111, 0b01110, 0b10101, 0),
}

_MISSING = GLYPHS["?"]


def glyph(char: str) -> tuple[int, ...]:
    """The 7 row-bitmasks for ``char`` (uppercased; '?' if unknown)."""
    return GLYPHS.get(char.upper(), _MISSING)


def text_width(text: str, scale: int) -> int:
    """Rendered pixel width of ``text`` at ``scale`` (no trailing gap)."""
    if not text:
        return 0
    return len(text) * (GLYPH_W + SPACING) * scale - SPACING * scale


def text_height(scale: int) -> int:
    """Rendered pixel height of one line at ``scale``."""
    return GLYPH_H * scale


def runs(text: str, scale: int) -> Iterator[tuple[int, int, int, int]]:
    """Yield ``(x, y, w, h)`` filled blocks for ``text`` at ``scale``.

    Consecutive set bits in a glyph row are merged into one block, so a
    caller fills a handful of rectangles per character instead of one
    per pixel. Coordinates are relative to the text's top-left corner.
    """
    pitch = (GLYPH_W + SPACING) * scale
    for index, char in enumerate(text):
        origin_x = index * pitch
        for row, bits in enumerate(glyph(char)):
            if not bits:
                continue
            col = 0
            while col < GLYPH_W:
                if not bits & (1 << (GLYPH_W - 1 - col)):
                    col += 1
                    continue
                start = col
                while col < GLYPH_W and bits & (1 << (GLYPH_W - 1 - col)):
                    col += 1
                yield (origin_x + start * scale, row * scale,
                       (col - start) * scale, scale)
