# ---------------------------------------------------------------------------
# 42 Pacman - project Makefile (PLAN.md Milestone 1.1)
# ---------------------------------------------------------------------------

VENV        := .venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip

CONFIG      ?= config.json

MYPY_FLAGS  := --warn-return-any --warn-unused-ignores --ignore-missing-imports \
               --disallow-untyped-defs --check-untyped-defs

.PHONY: install run debug lint lint-strict test package mlx clean

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# Rebuild the MiniLibX Python wheel from source (only needed when the
# vendored Linux-x86_64 wheel does not match this machine). Requires the
# MLX build deps: clang libvulkan-dev zlib1g-dev libxcb1-dev
# libxcb-keysyms1-dev libbsd-dev.
mlx:
	./scripts/build_mlx.sh

run:
	$(PYTHON) pac-man.py $(CONFIG)

debug:
	$(PYTHON) -m pdb pac-man.py $(CONFIG)

lint:
	$(PYTHON) -m flake8 .
	$(PYTHON) -m mypy . $(MYPY_FLAGS)

lint-strict:
	$(PYTHON) -m flake8 .
	$(PYTHON) -m mypy . --strict

test:
	$(PYTHON) -m pytest

package:
	$(PYTHON) packaging/make_package.py

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf .mypy_cache .pytest_cache dist
