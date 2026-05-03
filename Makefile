.PHONY: install test test-lf test-unit test-int watch lint format mypy cov check push pull hooks

PYTHON    := .venv/bin/python
PYTEST    := .venv/bin/pytest
PTW       := .venv/bin/ptw
RUFF      := .venv/bin/ruff
MYPY      := .venv/bin/mypy
PRECOMMIT := .venv/bin/pre-commit

install:
	uv sync --extra dev
	$(PRECOMMIT) install --hook-type pre-commit --hook-type pre-push

hooks:
	$(PRECOMMIT) install --hook-type pre-commit --hook-type pre-push

test:
	$(PYTEST)

test-lf:
	$(PYTEST) --lf

test-unit:
	$(PYTEST) -m 'not integration'

test-int:
	$(PYTEST) -m 'integration and not slow'

test-slow:
	$(PYTEST) -m slow

watch:
	$(PTW) -- --tb=short

lint:
	$(RUFF) check src/ tests/

format:
	$(RUFF) format src/ tests/

mypy:
	$(MYPY) src/

cov:
	$(PYTEST) --cov --cov-report=term-missing

check: lint mypy cov

pull:
	git pull origin main

push: check
	git push origin main
