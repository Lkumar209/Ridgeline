.PHONY: install check lint fmt typecheck test fetch fetch-dev

install:
	uv sync

check: lint typecheck test

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest -m "not network"

fetch:
	uv run ridgeline fetch-data

fetch-dev:
	uv run ridgeline fetch-data --dev-subset
