"""Adversarial-safe config loader (PLAN.md Milestone 1.2, subject V.1-3).

The config file is swapped for an unknown one at the defense (subject V.3):
``load_config`` must therefore never raise. Any missing file, invalid JSON,
wrong type, or out-of-range value falls back to a safe default and is logged;
unknown keys are silently ignored. The game always continues.
"""

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_HIGHSCORE_FILENAME = "highscores.json"
DEFAULT_LEVEL_WIDTH = 15
DEFAULT_LEVEL_HEIGHT = 15
DEFAULT_LIVES = 3
DEFAULT_PACGUM = 42
DEFAULT_POINTS_PER_PACGUM = 10
DEFAULT_POINTS_PER_SUPER_PACGUM = 50
DEFAULT_POINTS_PER_GHOST = 200
DEFAULT_SEED = 42
DEFAULT_LEVEL_MAX_TIME = 90


@dataclass
class LevelConfig:
    """One level's maze dimensions."""

    width: int
    height: int


@dataclass
class Config:
    """Fully validated, defaulted game configuration."""

    highscore_filename: str
    level: list[LevelConfig]
    lives: int
    pacgum: int
    points_per_pacgum: int
    points_per_super_pacgum: int
    points_per_ghost: int
    seed: int
    level_max_time: int


def strip_json_comments(text: str) -> str:
    """Strip '#' and '//' line comments and '/* ... */' blocks before parsing.

    Only whole-line comments are recognised (a line whose stripped content
    starts with ``#`` or ``//``); this keeps the stripper a single
    unambiguous pass with no risk of mangling a URL or path inside a JSON
    string value.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    kept_lines = [
        line
        for line in text.splitlines()
        if not line.strip().startswith(("#", "//"))
    ]
    return "\n".join(kept_lines)


def _get_int(
    raw: dict[str, object], key: str, default: int, minimum: int = 0,
) -> int:
    """Read an int config field, clamping to ``default`` if missing/invalid."""
    if key not in raw:
        logger.warning("Config missing %r; using default %r.", key, default)
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        logger.warning(
            "Config %r=%r is invalid (expected int >= %d); using default %r.",
            key, value, minimum, default,
        )
        return default
    if value < minimum:
        logger.warning(
            "Config %r=%r is invalid (expected int >= %d); using default %r.",
            key, value, minimum, default,
        )
        return default
    return value


def _get_str(raw: dict[str, object], key: str, default: str) -> str:
    """Read a non-empty str field, clamping to ``default`` if invalid."""
    if key not in raw:
        logger.warning("Config missing %r; using default %r.", key, default)
        return default
    value = raw[key]
    if not isinstance(value, str) or not value:
        logger.warning(
            "Config %r=%r is invalid (expected non-empty str); using "
            "default %r.", key, value, default,
        )
        return default
    return value


def _get_levels(raw: dict[str, object]) -> list[LevelConfig]:
    """Read the ``level`` array, defaulting/clamping each entry on its own."""
    fallback = [LevelConfig(DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT)]
    if "level" not in raw:
        logger.warning(
            "Config missing 'level'; using default single level %dx%d.",
            DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT,
        )
        return fallback

    value = raw["level"]
    if not isinstance(value, list) or not value:
        logger.warning(
            "Config 'level' must be a non-empty array; using default %dx%d.",
            DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT,
        )
        return fallback

    levels = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            logger.warning(
                "Config 'level[%d]' is not an object; using default %dx%d.",
                index, DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT,
            )
            levels.append(
                LevelConfig(DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT)
            )
            continue
        levels.append(LevelConfig(
            width=_get_int(entry, "width", DEFAULT_LEVEL_WIDTH, minimum=1),
            height=_get_int(entry, "height", DEFAULT_LEVEL_HEIGHT, minimum=1),
        ))
    return levels


def load_config(path: str) -> Config:
    """Load, validate, and default a JSON-with-comments config file.

    Never raises: a missing file, unreadable file, malformed JSON, non-object
    root, wrong-typed field, or out-of-range value each fall back to a safe
    default with a logged warning (unknown keys are ignored without a log,
    per subject V.3). Width/height here are only sanity-checked as positive
    ints; the wheel-specific asymmetric minimum size for the "42" logo insert
    is the maze adapter's concern (PLAN.md Milestone 1.3), not this loader's.
    """
    raw: dict[str, object] = {}
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            text = config_file.read()
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError (a binary/invalid-UTF-8 config file) is a
        # ValueError, not an OSError, so it must be caught explicitly --
        # otherwise an adversarial config crashes the game instead of
        # falling back to defaults (subject V.3, "no traceback").
        logger.warning(
            "Could not read config file %r (%s); using all defaults.",
            path, exc,
        )
        text = ""

    if text:
        try:
            parsed = json.loads(strip_json_comments(text))
        except json.JSONDecodeError as exc:
            logger.warning(
                "Config file %r is not valid JSON (%s); using all defaults.",
                path, exc,
            )
        else:
            if isinstance(parsed, dict):
                raw = parsed
            else:
                logger.warning(
                    "Config root in %r is a %s, not an object; using all "
                    "defaults.", path, type(parsed).__name__,
                )

    return Config(
        highscore_filename=_get_str(
            raw, "highscore_filename", DEFAULT_HIGHSCORE_FILENAME,
        ),
        level=_get_levels(raw),
        lives=_get_int(raw, "lives", DEFAULT_LIVES),
        pacgum=_get_int(raw, "pacgum", DEFAULT_PACGUM),
        points_per_pacgum=_get_int(
            raw, "points_per_pacgum", DEFAULT_POINTS_PER_PACGUM,
        ),
        points_per_super_pacgum=_get_int(
            raw, "points_per_super_pacgum", DEFAULT_POINTS_PER_SUPER_PACGUM,
        ),
        points_per_ghost=_get_int(
            raw, "points_per_ghost", DEFAULT_POINTS_PER_GHOST,
        ),
        seed=_get_int(raw, "seed", DEFAULT_SEED),
        level_max_time=_get_int(
            raw, "level_max_time", DEFAULT_LEVEL_MAX_TIME, minimum=1,
        ),
    )
