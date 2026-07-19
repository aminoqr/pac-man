"""Unit tests for pacman.config.loader (PLAN.md Milestone 1.2).

Covers the row set the milestone calls for: valid config, missing file,
invalid JSON, wrong types, out-of-range values, and unknown keys. The
config is adversarial input (subject V.3) -- every case here must return a
usable Config and must never raise.
"""

import json
import logging
from pathlib import Path

import pytest

from pacman.config.loader import (
    DEFAULT_HIGHSCORE_FILENAME,
    DEFAULT_LEVEL_HEIGHT,
    DEFAULT_LEVEL_WIDTH,
    DEFAULT_LEVEL_MAX_TIME,
    DEFAULT_LIVES,
    DEFAULT_PACGUM,
    DEFAULT_SEED,
    LevelConfig,
    load_config,
    strip_json_comments,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_config(tmp_path: Path, text: str) -> str:
    """Write ``text`` to a config file under ``tmp_path``; return its path."""
    path = tmp_path / "config.json"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_valid_config_is_parsed_verbatim(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps({
        "highscore_filename": "scores.json",
        "level": [{"width": 21, "height": 11}],
        "lives": 5,
        "pacgum": 10,
        "points_per_pacgum": 1,
        "points_per_super_pacgum": 2,
        "points_per_ghost": 3,
        "seed": 7,
        "level_max_time": 60,
    }))

    config = load_config(path)

    assert config.highscore_filename == "scores.json"
    assert config.level == [LevelConfig(21, 11)]
    assert config.lives == 5
    assert config.pacgum == 10
    assert config.points_per_pacgum == 1
    assert config.points_per_super_pacgum == 2
    assert config.points_per_ghost == 3
    assert config.seed == 7
    assert config.level_max_time == 60


def test_missing_file_falls_back_to_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    missing_path = str(tmp_path / "does_not_exist.json")

    with caplog.at_level(logging.WARNING):
        config = load_config(missing_path)

    assert config.lives == DEFAULT_LIVES
    assert config.pacgum == DEFAULT_PACGUM
    assert config.highscore_filename == DEFAULT_HIGHSCORE_FILENAME
    assert config.level == [LevelConfig(
        DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT)]
    assert any(
        "Could not read config file" in message for message in caplog.messages
    )


def test_invalid_json_falls_back_to_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = write_config(tmp_path, "{not valid json,,,")

    with caplog.at_level(logging.WARNING):
        config = load_config(path)

    assert config.lives == DEFAULT_LIVES
    assert config.seed == DEFAULT_SEED
    assert any("not valid JSON" in message for message in caplog.messages)


def test_non_object_json_root_falls_back_to_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps([1, 2, 3]))

    config = load_config(path)

    assert config.lives == DEFAULT_LIVES
    assert config.pacgum == DEFAULT_PACGUM


def test_wrong_types_fall_back_field_by_field(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps({
        "lives": "three",
        "pacgum": 10,
        "level": "not-a-list",
        "seed": True,
    }))

    config = load_config(path)

    assert config.lives == DEFAULT_LIVES
    assert config.pacgum == 10
    assert config.level == [LevelConfig(
        DEFAULT_LEVEL_WIDTH, DEFAULT_LEVEL_HEIGHT)]
    assert config.seed == DEFAULT_SEED


def test_out_of_range_values_clamp_to_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps({
        "lives": -1,
        "level": [{"width": 0, "height": -5}],
        "level_max_time": 0,
    }))

    config = load_config(path)

    assert config.lives == DEFAULT_LIVES
    assert config.level[0].width == DEFAULT_LEVEL_WIDTH
    assert config.level[0].height == DEFAULT_LEVEL_HEIGHT
    assert config.level_max_time == DEFAULT_LEVEL_MAX_TIME


def test_zero_lives_is_a_valid_edge_case_not_clamped(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps({"lives": 0}))

    config = load_config(path)

    assert config.lives == 0


def test_seed_zero_is_valid_and_means_fully_random(tmp_path: Path) -> None:
    path = write_config(tmp_path, json.dumps({"seed": 0}))

    config = load_config(path)

    assert config.seed == 0


def test_unknown_keys_are_silently_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = write_config(tmp_path, json.dumps({
        "lives": 4,
        "totally_unknown_key": "surprise",
    }))

    with caplog.at_level(logging.WARNING):
        config = load_config(path)

    assert config.lives == 4
    assert not hasattr(config, "totally_unknown_key")
    assert not any(
        "totally_unknown_key" in message for message in caplog.messages
    )


def test_multiple_levels_are_each_validated_independently(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path, json.dumps({
        "level": [
            {"width": 15, "height": 15},
            {"width": -1, "height": 20},
            "not-a-dict",
        ],
    }))

    config = load_config(path)

    assert len(config.level) == 3
    assert config.level[0].width == 15 and config.level[0].height == 15
    assert config.level[1].width == DEFAULT_LEVEL_WIDTH
    assert config.level[1].height == 20
    assert config.level[2].width == DEFAULT_LEVEL_WIDTH
    assert config.level[2].height == DEFAULT_LEVEL_HEIGHT


@pytest.mark.parametrize("comment_line", [
    "# a hash comment",
    "// a slash comment",
    "  # indented hash comment",
])
def test_strip_json_comments_removes_line_comments(comment_line: str) -> None:
    text = f'{{\n{comment_line}\n"lives": 3\n}}'

    stripped = strip_json_comments(text)

    assert comment_line not in stripped
    assert '"lives": 3' in stripped


def test_strip_json_comments_removes_block_comments() -> None:
    text = '{\n/* a block\n   comment */\n"lives": 3\n}'

    stripped = strip_json_comments(text)

    assert "block" not in stripped
    assert '"lives": 3' in stripped


def test_sample_repo_config_json_loads_cleanly() -> None:
    """The repo-root config.json used by `make run` must parse cleanly."""
    config = load_config(str(REPO_ROOT / "config.json"))

    assert config.lives == 3
    assert config.seed == 42
    assert len(config.level) == 2
