.PHONY: install run seed test lint format migrate

install:
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload --port 8000

seed:
	python -m app.cli seed --file data/dev_dataset.json

test:
	pytest

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check . --fix

migrate:
	python -m app.cli migrate
