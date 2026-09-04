.PHONY: check test lint type imports fmt integration
check: lint type imports test
lint:
	uv run ruff check .
	uv run ruff format --check .
fmt:
	uv run ruff format .
	uv run ruff check --fix .
type:
	uv run mypy .
imports:
	uv run lint-imports
test:
	uv run pytest
integration:
	uv run pytest -m integration
