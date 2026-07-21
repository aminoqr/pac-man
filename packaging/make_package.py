#!/usr/bin/env python3
"""Build a self-contained, runnable distribution zip (subject VII).

Assembles everything a fresh machine needs to play -- the source
package, the entry point, the default config, ``requirements.txt`` and
the bundled maze-generator wheel, plus one-touch launchers and an
INSTRUCTIONS file -- into ``dist/pacman-42.zip``. Pure standard library,
so it needs no build toolchain and regenerates on demand at peer review
(``make package``), which is the subject's explicit requirement.

The zip unpacks to a single ``pacman-42/`` directory; the launcher
inside it creates a local virtualenv, installs the dependencies
(including the bundled wheel), and runs the game. Publishing that build
to itch.io is a manual account step, documented in the generated
INSTRUCTIONS and the project README.
"""

import zipfile
from pathlib import Path

PACKAGE_NAME = "pacman-42"
WHEEL_NAME = "mazegenerator-2.1.0-py3-none-any.whl"
MLX_WHEEL_NAME = "mlx-2.4-py3-none-any.whl"

# Files/dirs copied verbatim into the bundle (relative to the repo root).
SOURCE_ITEMS = (
    "pacman",
    "pac-man.py",
    "config.json",
    "requirements.txt",
    WHEEL_NAME,
    MLX_WHEEL_NAME,
    "scripts",
)

# Directory names pruned while walking (never shipped).
_PRUNED_DIRS = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".venv", ".git"}
)

RUN_SH = """\
#!/usr/bin/env bash
# One-touch launcher (Linux / macOS). Usage: ./run.sh [config.json]
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
exec python pac-man.py "${1:-config.json}"
"""

RUN_BAT = """\
@echo off
REM One-touch launcher (Windows). Usage: run.bat [config.json]
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\\Scripts\\activate.bat
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if "%~1"=="" (python pac-man.py config.json) else (python pac-man.py %1)
"""

INSTRUCTIONS = """\
42 PAC-MAN -- Ghosts! More ghosts!
==================================

HOW TO RUN
----------
Linux / macOS:   ./run.sh
Windows:         run.bat
The launcher creates a local virtual environment, installs the bundled
wheels (Python 3.10+ required), then starts the game. To use a
different configuration:
    ./run.sh my-config.json

GRAPHICS (MiniLibX)
-------------------
The game renders with the 42 MiniLibX (mlx_CLXV). A prebuilt wheel for
Linux x86_64 is bundled and installed automatically. On a different
architecture or OS, rebuild it first with the bundled build script
(needs the MLX build deps: clang, libvulkan-dev, zlib1g-dev,
libxcb1-dev, libxcb-keysyms1-dev, libbsd-dev on Debian/Ubuntu):
    ./scripts/build_mlx.sh
If no graphics display is available, the game prints a textual maze
preview instead of opening a window (it never crashes).

CONTROLS
--------
Move:            Arrow keys or W A S D
Pause menu:      P or Esc
Menus:           Up/Down to move, Enter to select, Esc to back out
Name entry:      type your name (letters/digits/spaces, max 10), Enter

CHEATS (for reviewers)
----------------------
F1  invincibility     F2  freeze ghosts     F3  extra life
F4  speed boost       F5  skip the level

CONFIGURATION (config.json, JSON with '#' comments)
---------------------------------------------------
highscore_filename        where the top-10 table is stored
level                     array of {width, height} per level
lives                     starting lives (default 3)
pacgum                    pac-gum count target (default 42)
points_per_pacgum         score for a pac-gum (default 10)
points_per_super_pacgum   score for a super pac-gum (default 50)
points_per_ghost          score for an edible ghost (default 200)
seed                      level-1 seed (default 42, reproducible)
level_max_time            per-level time limit in seconds (default 90)
Any missing or invalid value falls back to a safe default -- the game
never crashes on a bad config.

PUBLISHING TO ITCH.IO
---------------------
This zip is the uploadable build: create a free (unlisted or private)
project on itch.io, upload pacman-42.zip, mark it as runnable from the
launcher, and note the controls above in the project description.
"""


def _add_file(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    """Write one file into the archive under ``arcname``."""
    archive.write(source, arcname)


def _add_tree(
    archive: zipfile.ZipFile, root: Path, source: Path, prefix: str,
) -> None:
    """Recursively add a directory, pruning caches/venv/VCS dirs."""
    for path in sorted(source.rglob("*")):
        if any(part in _PRUNED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            arcname = f"{prefix}/{path.relative_to(root).as_posix()}"
            _add_file(archive, path, arcname)


def build_package(repo_root: Path, output_dir: Path) -> Path:
    """Assemble the distribution zip and return its path.

    Raises FileNotFoundError if a required source item (notably the
    bundled wheel) is missing, so a broken build fails loudly at
    package time rather than shipping an unrunnable bundle.
    """
    missing = [
        item for item in SOURCE_ITEMS if not (repo_root / item).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"cannot package, missing from repo root: {', '.join(missing)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{PACKAGE_NAME}.zip"

    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for item in SOURCE_ITEMS:
            source = repo_root / item
            if source.is_dir():
                _add_tree(archive, repo_root, source, PACKAGE_NAME)
            else:
                _add_file(archive, source, f"{PACKAGE_NAME}/{item}")
        # Generated launchers + instructions.
        archive.writestr(f"{PACKAGE_NAME}/run.sh", RUN_SH)
        archive.writestr(f"{PACKAGE_NAME}/run.bat", RUN_BAT)
        archive.writestr(f"{PACKAGE_NAME}/INSTRUCTIONS.txt", INSTRUCTIONS)
        # Mark the shell launcher executable inside the archive.
        info = archive.getinfo(f"{PACKAGE_NAME}/run.sh")
        info.external_attr = 0o755 << 16

    return zip_path


def main() -> int:
    """Build the package from the repo root and report where it landed."""
    repo_root = Path(__file__).resolve().parent.parent
    zip_path = build_package(repo_root, repo_root / "dist")
    size_kb = zip_path.stat().st_size / 1024
    print(f"Built {zip_path} ({size_kb:.1f} KiB)")
    print(f"Unzip it and run ./{PACKAGE_NAME}/run.sh to play.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
