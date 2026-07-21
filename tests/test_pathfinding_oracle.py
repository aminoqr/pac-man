"""Milestone 3 gate: the wheel's own solver as oracle (PLAYBOOK §7.1).

For 50 seeds x 3 sizes (two of them non-square -- the y-axis bug
trap), our BFS and A* must agree with each other AND with the length
of the wheel's 'NESW' ``shortest_path`` string between the wheel's
entry (0, 0) and exit (width-1, height-1) -- the defaults
``load_wheel_maze`` leaves in place. Lengths, not paths: a braided
maze has many optimal routes. A seed where the wheel reports no path
must skip cleanly (the adapter converts that ``False`` into
``MazeAdapterError``; any OTHER exception escaping the sweep is a
real failure), and a floor on the checked count guards against the
oracle silently skipping everything.

The sweep runs once per module and feeds every test below.
"""

from dataclasses import dataclass

import pytest

from pacman.maze.adapter import MazeAdapter, MazeAdapterError
from pacman.pathfinding.search import (
    SearchResult,
    astar_path,
    bfs_path,
    dfs_path,
)
from tests.mazes import assert_legal_path

SIZES = ((14, 10), (21, 15), (25, 25))
SEEDS = range(1, 51)
MINIMUM_CHECKED = 100


@dataclass(frozen=True)
class SweepRecord:
    """One seed's maze plus all three search results, entry -> exit."""

    adapter: MazeAdapter
    label: str
    reference: int
    bfs: SearchResult
    astar: SearchResult
    dfs: SearchResult
    entry: tuple[int, int]
    exit_cell: tuple[int, int]


@pytest.fixture(scope="module")
def sweep() -> list[SweepRecord]:
    """Generate every (size, seed) maze once and search it three ways."""
    records = []
    for width, height in SIZES:
        for seed in SEEDS:
            adapter = MazeAdapter(width, height, seed)
            adapter.load_wheel_maze()
            try:
                reference = adapter.reference_path_length()
            except MazeAdapterError:
                continue  # wheel found no path: skip cleanly (§7.1)
            entry, exit_cell = (0, 0), (width - 1, height - 1)
            records.append(SweepRecord(
                adapter=adapter,
                label=f"{width}x{height} seed={seed}",
                reference=reference,
                bfs=bfs_path(adapter, entry, exit_cell),
                astar=astar_path(adapter, entry, exit_cell),
                dfs=dfs_path(adapter, entry, exit_cell),
                entry=entry,
                exit_cell=exit_cell,
            ))
    assert len(records) >= MINIMUM_CHECKED, "oracle sweep mostly skipped"
    return records


def test_bfs_and_astar_lengths_match_the_wheel(
    sweep: list[SweepRecord],
) -> None:
    """The §7.1 equality: len(bfs) == len(astar) == len(shortest_path)."""
    for record in sweep:
        assert record.bfs.step_count == record.reference, record.label
        assert record.astar.step_count == record.reference, record.label


def test_all_paths_are_legal_and_simple(sweep: list[SweepRecord]) -> None:
    for record in sweep:
        for result in (record.bfs, record.astar, record.dfs):
            assert result.path is not None, record.label
            assert_legal_path(
                record.adapter, result.path, record.entry, record.exit_cell,
            )


def test_astar_never_expands_more_nodes_than_bfs(
    sweep: list[SweepRecord],
) -> None:
    """Milestone 3 acceptance criterion, on every query -- the search.py
    docstring proves WHY this is a theorem, not a tendency.
    """
    for record in sweep:
        assert record.astar.expanded <= record.bfs.expanded, record.label


def test_dfs_is_legal_but_generally_not_shortest(
    sweep: list[SweepRecord],
) -> None:
    """DFS never beats BFS, and on cycle-rich braided mazes it loses
    outright most of the time (measured: 144 of 150 seeds) --
    REFERENCE.md §3.3's negative result observed on real mazes.
    """
    strictly_longer = 0
    for record in sweep:
        assert record.dfs.step_count >= record.bfs.step_count, record.label
        if record.dfs.step_count > record.bfs.step_count:
            strictly_longer += 1
    assert strictly_longer >= len(sweep) // 2
