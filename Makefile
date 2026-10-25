# Convenience targets (Linux / macOS / WSL). Each one wraps a script in scripts/
# or a command you can also run by hand.
SHELL := /usr/bin/env bash

.PHONY: help setup dev test test-all smoke e2e prod-check scan verify lint format migrate owner keys

help:
	@echo "make setup     - install toolchain/deps, create backend/.env, migrate"
	@echo "make owner     - create the owner account (interactive password prompt)"
	@echo "make dev       - run FastAPI :8000 + Next.js :3000 (open http://127.0.0.1:3000)"
	@echo "make test      - backend lint/types/tests + frontend lint/types/unit tests"
	@echo "make test-all  - test + next build + backend suite on PostgreSQL (Docker)"
	@echo "make smoke     - isolated end-to-end smoke test through the Next.js proxy"
	@echo "make e2e       - Playwright browser tests against isolated servers (DEMO data)"
	@echo "make prod-check - the production stack (Docker, Caddy, PostgreSQL) over HTTPS, locally"
	@echo "make scan      - dependency audits, static analysis, secret and config scans"
	@echo "make verify    - everything from a clean copy of the repository (verify.sh --full)"
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

e2e:
	./scripts/e2e.sh

prod-check:
	./scripts/prod-check.sh

scan:
	./scripts/scan.sh --images

verify:
	./scripts/verify.sh --full

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	source scripts/env.sh && cd frontend && npm run lint && npm run typecheck

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .

migrate:
	cd backend && uv run alembic upgrade head

keys:
	cd backend && uv run python -m app.cli.keys
