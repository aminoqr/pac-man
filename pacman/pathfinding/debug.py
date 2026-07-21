"""Debug overlay: draw a search path onto the ASCII maze render.

PLAN.md Milestone 3's optional last checkbox. The adapter's
``render_ascii()`` is the project's primary debugging tool (PLAN.md
§1.3); this module post-processes its canvas to show the current path
of a selected ghost (or any SearchResult) without the algorithms in
search.py knowing anything about rendering.

Canvas geometry (mirrors MazeAdapter.render_ascii): the canvas is
(2*height+1) rows by (2*width+1) columns; cell (x, y) sits at row
2y+1, column 2x+1, and the wall slot BETWEEN two adjacent cells is
the arithmetic midpoint of their canvas positions -- marking it too
makes the path read as one connected line through the carved openings.
"""

from typing import Protocol

from pacman.pathfinding.graph import Cell

PATH_MARK = "*"
START_MARK = "S"
GOAL_MARK = "G"


class SupportsAsciiRender(Protocol):
    """Anything that can draw itself as ASCII -- MazeAdapter qualifies.

    A second small Protocol (rather than reusing graph.MazeGraph)
    because rendering is a different capability than adjacency; the
    package still imports nothing from the maze layer.
    """

    def render_ascii(self) -> str:
        """The '#'/'.'/' ' canvas this module overlays onto."""
        ...


def render_path_ascii(maze: SupportsAsciiRender, path: list[Cell]) -> str:
    """Overlay ``path`` on the maze's ASCII render and return the result.

    Path cells become '*', the endpoints 'S' and 'G', and the opening
    between each consecutive pair is starred too so the line reads as
    continuous. An empty path returns the render untouched; a
    single-cell path (start == goal) shows 'S'. Feeding cells that lie
    outside the maze is a caller bug and fails loudly (IndexError) --
    this is a debugging tool, silent clipping would hide the very bugs
    it exists to expose.
    """
    canvas = [list(row) for row in maze.render_ascii().splitlines()]
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        canvas[2 * ay + 1][2 * ax + 1] = PATH_MARK
        canvas[ay + by + 1][ax + bx + 1] = PATH_MARK
    if path:
        goal_x, goal_y = path[-1]
        canvas[2 * goal_y + 1][2 * goal_x + 1] = GOAL_MARK
        start_x, start_y = path[0]
        canvas[2 * start_y + 1][2 * start_x + 1] = START_MARK
    return "\n".join("".join(row) for row in canvas)
