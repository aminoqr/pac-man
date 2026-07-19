"""Unit tests for pacman.game.engine.parse_grid_map (PLAN.md Milestone 1.3).

Entity placement pass (subject VI.1): super-pacgums/ghost spawns in the 4
corners, player at center, pacgums on the rest of the reachable maze
(including the player's own start tile, matching the classic arcade
convention of a pellet sitting under Pac-Man's spawn).
"""

from pacman.game.engine import parse_grid_map
from pacman.maze.adapter import MazeAdapter


def test_parse_grid_map_places_entities_per_subject_vi_1() -> None:
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()

    level = parse_grid_map(adapter)

    assert level.player_spawn == adapter.center()
    assert level.ghost_spawns == adapter.corners()
    assert level.super_pacgum_cells == set(adapter.corners())
    # pacgums and super-pacgums never overlap the same cell.
    assert not (level.pacgum_cells & level.super_pacgum_cells)
    # every pacgum cell must actually be walkable.
    assert all(adapter.is_walkable(x, y) for x, y in level.pacgum_cells)
    # the corners themselves never double as ordinary pacgum cells.
    assert level.super_pacgum_cells.isdisjoint(level.pacgum_cells)


def test_parse_grid_map_pacgums_match_reachable_non_corner_cells() -> None:
    adapter = MazeAdapter(15, 15, seed=42)
    adapter.load_wheel_maze()

    level = parse_grid_map(adapter)

    reachable = {level.player_spawn}
    frontier = [level.player_spawn]
    while frontier:
        cell = frontier.pop()
        for neighbor in adapter.neighbors(*cell):
            if neighbor not in reachable:
                reachable.add(neighbor)
                frontier.append(neighbor)

    assert level.pacgum_cells == reachable - level.super_pacgum_cells


def test_parse_grid_map_is_deterministic_for_the_same_seed() -> None:
    first_adapter = MazeAdapter(15, 15, seed=42)
    first_adapter.load_wheel_maze()
    second_adapter = MazeAdapter(15, 15, seed=42)
    second_adapter.load_wheel_maze()

    first_level = parse_grid_map(first_adapter)
    second_level = parse_grid_map(second_adapter)

    assert first_level == second_level
