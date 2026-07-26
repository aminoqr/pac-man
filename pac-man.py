#!/usr/bin/env python3
"""42 Pacman entry point.

Usage: pac-man.py <config.json>
"""

import logging
import sys

from pacman.config.loader import Config, load_config
from pacman.game.engine import parse_grid_map
from pacman.maze.adapter import MazeAdapter, MazeAdapterError

logger = logging.getLogger(__name__)


def build_level_one(config: Config) -> MazeAdapter:
    """Generate level 1's maze from the config's first level entry.

    Level 1 always uses the configured seed (subject VI.1: fixed seed
    42 for reproducibility). Only used by the textual fallback below;
    the real game builds its levels through GameSession.
    """
    first_level = config.level[0]
    adapter = MazeAdapter(first_level.width, first_level.height, config.seed)
    adapter.load_wheel_maze()
    return adapter


def print_level_preview(config: Config) -> int:
    """Textual fallback when no game window can be opened.

    Keeps `make run` meaningful on headless machines (CI, ssh): prints
    the generated level-1 maze and its placement summary instead of
    failing -- never a traceback (subject III.1).
    """
    try:
        adapter = build_level_one(config)
    except MazeAdapterError as exc:
        print(f"Could not generate the maze: {exc}", file=sys.stderr)
        return 1

    level = parse_grid_map(adapter)
    print(adapter.render_ascii())
    print()
    print(f"Size: {adapter.width}x{adapter.height} (seed={config.seed})")
    print(f"Player spawn: {level.player_spawn}")
    print(f"Ghost spawns: {level.ghost_spawns}")
    print(f"Pacgums: {len(level.pacgum_cells)}, "
          f"super-pacgums: {len(level.super_pacgum_cells)}")
    return 0


def main(argv: list[str]) -> int:
    """Parse CLI args, load the config, and launch the game.

    Exactly one argument (the config path) is accepted (subject V.1);
    any other arg count prints a usage message to stderr and returns a
    nonzero status instead of raising. The MLX windowed game is the
    normal path; a machine without a display (or without MLX built)
    degrades to the ASCII preview. MazeAdapterError is the only
    exception the maze layer may raise (REFERENCE.md §5.5) and MLX
    errors stay inside run_game -- no traceback may ever reach the
    player (subject III.1). Ctrl+C (``KeyboardInterrupt``) is caught
    here and at the ``__main__`` gate, printing a clean line and
    returning 130 instead of a stack dump.
    """
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <config.json>", file=sys.stderr)
        return 1

    config = load_config(argv[1])

    try:
        from pacman.ui.app import run_game
    except ImportError as exc:
        logger.warning("MLX unavailable (%s); textual fallback.", exc)
        return print_level_preview(config)

    try:
        exit_code = run_game(config)
    except MazeAdapterError as exc:
        print(f"Could not generate the maze: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # Ctrl+C during the windowed loop: treat as a clean quit, not a
        # crash. Exit 130 is the Unix convention for SIGINT.
        print("\nInterrupted.", file=sys.stderr)
        return 130
    if exit_code != 0:
        # No window (headless/driver failure): degrade, don't die.
        return print_level_preview(config)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(message)s",
    )
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        # Covers Ctrl+C during config load / ASCII preview / anything
        # outside the run_game try above -- never a traceback
        # (subject III.1).
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
