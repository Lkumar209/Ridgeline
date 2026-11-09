.PHONY: install check lint fmt typecheck test evals fetch fetch-dev rank serve demo

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

# M6 eval set against the mock client (offline). Live: uv run ridgeline evals --live
evals:
	uv run ridgeline evals

fetch:
	uv run ridgeline fetch-data

fetch-dev:
	uv run ridgeline fetch-data --dev-subset

rank:
	uv run ridgeline rank

serve:
	uv run ridgeline serve

# Fresh clone to a running map: download data (~30 MB), simulate and rank, then serve.
demo: fetch rank serve
