"""Milestone 5.2 tests: the persistent highscore table (subject V.5).

Covers the robustness contract (missing/corrupt/wrong-shaped files
never raise, salvage what is valid), the validation rules (names max
10 chars alphanumeric+spaces, non-negative integer scores), top-10
capping with stable tie-ordering, and a save->load round-trip. File
tests use pytest's tmp_path so nothing touches the real leaderboard.
"""

import json
from pathlib import Path

from pacman.highscore.store import (
    DEFAULT_NAME,
    MAX_NAME_LENGTH,
    TOP_N,
    HighscoreEntry,
    HighscoreTable,
    sanitize_name,
)


def test_sanitize_name_trims_filters_and_truncates() -> None:
    assert sanitize_name("  Ada Lovelace  ") == "Ada Lovela"  # 10 chars
    assert sanitize_name("h@ck!er#42") == "hcker42"  # symbols dropped
    assert sanitize_name("bob") == "bob"
    assert len(sanitize_name("x" * 50)) == MAX_NAME_LENGTH


def test_sanitize_name_falls_back_when_nothing_survives() -> None:
    assert sanitize_name("") == DEFAULT_NAME
    assert sanitize_name("!!!@@@") == DEFAULT_NAME
    assert sanitize_name("   ") == DEFAULT_NAME


def test_add_keeps_only_the_top_ten_by_score() -> None:
    table = HighscoreTable()
    for score in range(1, 16):  # 15 entries, ascending
        assert table.add(f"P{score}", score * 10)
    entries = table.entries
    assert len(entries) == TOP_N
    scores = [entry.score for entry in entries]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 150 and scores[-1] == 60  # top 10 of 15 kept


def test_qualifies_reflects_open_slots_then_the_cutoff() -> None:
    table = HighscoreTable()
    assert table.qualifies(0)  # empty board: any score fits
    for i in range(TOP_N):
        table.add("x", 100 + i)  # fills 100..109
    assert not table.qualifies(100)  # equal to the cutoff: no
    assert not table.qualifies(50)
    assert table.qualifies(110)  # strictly beats the lowest: yes


def test_add_rejects_invalid_scores() -> None:
    table = HighscoreTable()
    assert not table.add("neg", -5)
    assert not table.add("boolean", True)  # bools are not scores
    assert not table.add("floaty", 3.5)  # type: ignore[arg-type]
    assert table.entries == []


def test_add_sanitizes_the_name_on_the_way_in() -> None:
    table = HighscoreTable()
    table.add("  Ro@bert The Great ", 42)
    assert table.entries[0] == HighscoreEntry("Robert The", 42)


def test_equal_scores_keep_insertion_order() -> None:
    table = HighscoreTable()
    table.add("first", 100)
    table.add("second", 100)
    names = [entry.name for entry in table.entries]
    assert names == ["first", "second"]  # stable: earlier stays higher


def test_load_missing_file_returns_empty_table(tmp_path: Path) -> None:
    missing = str(tmp_path / "does-not-exist.json")
    table = HighscoreTable.load(missing)
    assert table.entries == []


def test_load_corrupt_json_returns_empty_table(tmp_path: Path) -> None:
    path = _write(tmp_path, "not-json-at-all {{{")
    assert HighscoreTable.load(path).entries == []


def test_load_wrong_root_type_returns_empty_table(tmp_path: Path) -> None:
    path = _write(tmp_path, json.dumps({"name": "x", "score": 1}))
    assert HighscoreTable.load(path).entries == []


def test_load_binary_garbage_returns_empty_table(tmp_path: Path) -> None:
    """Invalid UTF-8 bytes decode-fail during read(); must not crash.

    Regression: UnicodeDecodeError is a ValueError, not an OSError, so
    it slipped past the original except clauses (subject V.5).
    """
    path = str(tmp_path / "hs.json")
    with open(path, "wb") as handle:
        handle.write(b"\xff\xfe not \x80\x81 utf-8")
    assert HighscoreTable.load(path).entries == []


def test_load_salvages_valid_rows_and_skips_junk(tmp_path: Path) -> None:
    payload = [
        {"name": "good", "score": 500},
        {"name": "neg", "score": -1},          # invalid score -> skip
        {"name": 123, "score": 10},            # non-str name -> skip
        {"score": 10},                          # missing name -> skip
        "totally wrong",                        # not an object -> skip
        {"name": "h@x", "score": 20},          # name gets sanitized
    ]
    path = _write(tmp_path, json.dumps(payload))
    table = HighscoreTable.load(path)
    assert [(e.name, e.score) for e in table.entries] == [
        ("good", 500), ("hx", 20),
    ]


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    table = HighscoreTable()
    table.add("alice", 300)
    table.add("bob", 150)
    path = str(tmp_path / "hs.json")
    assert table.save(path)
    reloaded = HighscoreTable.load(path)
    assert reloaded.entries == table.entries


def test_save_reports_failure_without_raising(tmp_path: Path) -> None:
    # A path whose parent is a file, not a directory: unwritable.
    blocker = _write(tmp_path, "x")
    table = HighscoreTable()
    table.add("a", 1)
    assert table.save(blocker + "/nested.json") is False


def _write(tmp_path: Path, text: str) -> str:
    """Write ``text`` to a temp file and return its path."""
    path = str(tmp_path / "hs.json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
