#!/usr/bin/env bash
# Lint, type-check and test everything. No real provider credentials needed.
#   ./scripts/test.sh              backend (SQLite) + frontend lint/typecheck
#   ./scripts/test.sh --build      ... plus a production `next build`
#   ./scripts/test.sh --postgres   ... plus the backend suite on a throwaway
#                                  PostgreSQL 18 container (needs Docker)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
export NEXT_TELEMETRY_DISABLED=1

build=0
postgres=0
for arg in "$@"; do
  case "$arg" in
    --build) build=1 ;;
    --postgres) postgres=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

echo "==> backend: ruff (lint + format check)"
(cd backend && uv run ruff check . && uv run ruff format --check .)
echo "==> backend: mypy --strict"
(cd backend && uv run mypy)
echo "==> backend: pytest (SQLite)"
(cd backend && uv run pytest -q -W error::ResourceWarning --cov=app --cov-report=term:skip-covered)

if [[ $postgres == 1 ]]; then
  name="twoofus-pg-test-$$"
  password="$(openssl rand -hex 16)"
  echo "==> backend: pytest (PostgreSQL 18 in Docker container $name)"
  docker run -d --rm --name "$name" -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB=twoofus_test \
    -p 127.0.0.1:55433:5432 postgres:18-alpine >/dev/null
  trap 'docker stop "$name" >/dev/null 2>&1 || true' EXIT
  for _ in $(seq 1 60); do
    docker exec "$name" pg_isready -U postgres -d twoofus_test >/dev/null 2>&1 && break
    sleep 1
  done
  (cd backend && TWOOFUS_TEST_DATABASE_URL="postgresql+psycopg://postgres:${password}@127.0.0.1:55433/twoofus_test" \
    uv run pytest -q -W error::ResourceWarning)
fi

echo "==> frontend: eslint + tsc"
(cd frontend && npm run lint && npm run typecheck)
if [[ $build == 1 ]]; then
  echo "==> frontend: next build"
  (cd frontend && npm run build)
fi
echo "All checks passed."
