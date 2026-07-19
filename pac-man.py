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

    Level 1 always uses the configured seed (subject VI.1: fixed seed 42
    for reproducibility); later levels switching to random seeds is a
    Milestone 4 concern (level progression), not this bootstrap step.
    """
    first_level = config.level[0]
    adapter = MazeAdapter(first_level.width, first_level.height, config.seed)
    adapter.load_wheel_maze()
    return adapter


def main(argv: list[str]) -> int:
    """Parse CLI args, load the config, and generate/print level 1's maze.

    Exactly one argument (the config path) is accepted (subject V.1); any
    other arg count prints a usage message to stderr and returns a nonzero
    status instead of raising (subject III.1: no traceback may ever reach
    the player). Maze-generator failures are likewise caught and reported
    cleanly -- MazeAdapterError is the only exception the maze layer is
    allowed to raise (REFERENCE.md §5.5), so this is the one catch site
    the whole game loop eventually needs.
    """
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <config.json>", file=sys.stderr)
        return 1

    config = load_config(argv[1])
    print(f"Loaded config: {config}")

    try:
        adapter = build_level_one(config)
    except MazeAdapterError as exc:
        print(f"Could not generate the maze: {exc}", file=sys.stderr)
        return 1

    level = parse_grid_map(adapter)
    print()
    print(adapter.render_ascii())
    print()
    print(f"Size: {adapter.width}x{adapter.height} (seed={config.seed})")
    print(f"Player spawn: {level.player_spawn}")
    print(f"Ghost spawns: {level.ghost_spawns}")
    print(f"Pacgums: {len(level.pacgum_cells)}, "
          f"super-pacgums: {len(level.super_pacgum_cells)}")
    print(f"Wheel reference path length (entry->exit): "
          f"{adapter.reference_path_length()}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(message)s",
    )
    sys.exit(main(sys.argv))
