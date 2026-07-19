# ---------------------------------------------------------------------------
# 42 Pacman - project Makefile (PLAN.md Milestone 1.1)
# ---------------------------------------------------------------------------

VENV        := .venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip

CONFIG      ?= config.json

MYPY_FLAGS  := --warn-return-any --warn-unused-ignores --ignore-missing-imports \
               --disallow-untyped-defs --check-untyped-defs

.PHONY: install run debug lint lint-strict clean

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) pac-man.py $(CONFIG)

debug:
	$(PYTHON) -m pdb pac-man.py $(CONFIG)

lint:
	$(PYTHON) -m flake8 .
	$(PYTHON) -m mypy . $(MYPY_FLAGS)

lint-strict:
	$(PYTHON) -m mypy . --strict

clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	rm -rf .mypy_cache .pytest_cache
