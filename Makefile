# Convenience targets (Linux / macOS / WSL). Each one wraps a script in scripts/
# or a command you can also run by hand; see docs/LOCAL_SETUP.md.
SHELL := /usr/bin/env bash

.PHONY: help setup dev test test-all smoke lint format migrate owner keys

help:
	@echo "make setup     - install toolchain/deps, create backend/.env, migrate"
	@echo "make owner     - create the owner account (interactive password prompt)"
	@echo "make dev       - run FastAPI :8000 + Next.js :3000 (open http://127.0.0.1:3000)"
	@echo "make test      - backend lint/types/tests + frontend lint/types"
	@echo "make test-all  - test + next build + backend suite on PostgreSQL (Docker)"
	@echo "make smoke     - isolated end-to-end smoke test through the Next.js proxy"
	@echo "make format    - auto-format backend code"
	@echo "make migrate   - apply database migrations"
	@echo "make keys      - print freshly generated secrets"

setup:
	./scripts/setup.sh

owner:
	cd backend && uv run python -m app.cli.bootstrap_owner

dev:
	./scripts/dev.sh

test:
	./scripts/test.sh

test-all:
	./scripts/test.sh --build --postgres

smoke:
	./scripts/smoke.sh

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	source scripts/env.sh && cd frontend && npm run lint && npm run typecheck

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .

migrate:
	cd backend && uv run alembic upgrade head

keys:
	cd backend && uv run python -m app.cli.keys
