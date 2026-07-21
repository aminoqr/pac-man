"""Milestone 5.3 tests: the distribution builder (subject VII).

Loads ``packaging/make_package.py`` by file path (its directory shares
a name with the PyPI ``packaging`` library, so a plain import would be
ambiguous) and builds into a temp directory -- never the repo's real
``dist/``. Asserts the bundle is complete and runnable-shaped: source
present, launchers + instructions generated, caches pruned, shell
launcher marked executable.
"""

import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_builder() -> ModuleType:
    """Import make_package.py from its path without the name clash."""
    spec = importlib.util.spec_from_file_location(
        "pacman_make_package", REPO_ROOT / "packaging" / "make_package.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_package_produces_a_complete_runnable_zip(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    out_dir = tmp_path / "dist"
    zip_path = builder.build_package(REPO_ROOT, out_dir)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        prefix = f"{builder.PACKAGE_NAME}/"
        # Core runnable pieces are all present.
        for expected in (
            "pac-man.py", "config.json", "requirements.txt",
            builder.WHEEL_NAME, builder.MLX_WHEEL_NAME,
            "scripts/build_mlx.sh",
            "run.sh", "run.bat", "INSTRUCTIONS.txt",
            "pacman/game/engine.py", "pacman/ui/app.py",
            "pacman/ui/shell.py", "pacman/highscore/store.py",
        ):
            assert prefix + expected in names, expected
        # Caches/venv/VCS never ship.
        assert not any("__pycache__" in name for name in names)
        assert not any("/.venv/" in name for name in names)
        assert not any("/.git/" in name for name in names)
        # The shell launcher is marked executable in the archive.
        info = archive.getinfo(prefix + "run.sh")
        assert (info.external_attr >> 16) & 0o111


def test_build_package_fails_loudly_when_a_source_is_missing(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    try:
        builder.build_package(empty_root, empty_root / "dist")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError on an empty repo root")
