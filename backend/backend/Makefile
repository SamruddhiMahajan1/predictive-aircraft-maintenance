.PHONY: help install migrate seed run test lint typecheck check clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:            ## editable install with dev extras
	pip install -e ".[dev]"

migrate:            ## apply migrations
	alembic upgrade head

seed:               ## idempotent seed (safe to re-run)
	python -m app.seed.run

run:                ## dev server (single worker: the replay engine is in-process)
	uvicorn app.main:app --reload --workers 1

test:               ## full suite (needs a reachable PostgreSQL)
	pytest -q

test-unit:          ## pure domain tests, no database
	pytest tests/unit -q

lint:               ## ruff
	ruff check app tests scripts

typecheck:          ## mypy --strict on the pure layers
	mypy app/core app/domain app/ml

check: lint typecheck test   ## everything CI runs

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache seed_reconciliation.log
