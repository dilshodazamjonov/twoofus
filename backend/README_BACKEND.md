# Two of Us: backend

FastAPI + Pydantic v2 + SQLAlchemy 2 (async) + Alembic. Python ≥ 3.12, managed
with uv (`backend/.venv`, locked in `uv.lock`).

```bash
uv sync                                       # create/refresh .venv
uv run python -m app.cli.keys --init-env      # create .env with fresh secrets
uv run alembic upgrade head                   # migrate
uv run python -m app.cli.bootstrap_owner      # create the owner (password prompt)
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --reload
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

See `../docs/ARCHITECTURE.md`, `../docs/INTEGRATIONS.md`, `../docs/SECURITY.md`
and `../docs/LOCAL_SETUP.md`.
