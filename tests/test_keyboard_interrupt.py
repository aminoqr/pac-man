"""Ctrl+C must exit cleanly -- never a traceback (subject III.1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_entry() -> ModuleType:
    """Import pac-man.py by path (hyphenated name is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "pacman_entry", REPO_ROOT / "pac-man.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_returns_130_on_keyboard_interrupt_during_game(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C inside run_game prints 'Interrupted.' and exits 130."""
    entry = _load_entry()
    config = tmp_path / "config.json"
    config.write_text('{"lives": 3}\n')

    def boom(_cfg: object) -> int:
        raise KeyboardInterrupt

    fake_app = ModuleType("pacman.ui.app")
    fake_app.run_game = boom  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"pacman.ui.app": fake_app}):
        code = entry.main([str(REPO_ROOT / "pac-man.py"), str(config)])

    assert code == 130
    assert "Interrupted." in capsys.readouterr().err


def test_run_game_does_not_swallow_keyboard_interrupt() -> None:
    """run_game's broad except Exception must let Ctrl+C propagate.

    KeyboardInterrupt is a BaseException, not an Exception -- this
    pins that contract so a future 'except BaseException' cannot
    quietly turn Ctrl+C into a textual maze preview.
    """
    from pacman.config.loader import load_config
    from pacman.ui.app import run_game

    config = load_config(str(REPO_ROOT / "config.json"))

    with patch("pacman.ui.app.has_display", return_value=True), \
         patch("pacman.ui.app.MlxApp") as mlx_app:
        mlx_app.return_value.run.side_effect = KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            run_game(config)
