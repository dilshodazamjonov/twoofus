#!/usr/bin/env bash
# Lint, type-check and test everything. No real provider credentials needed.
#   ./scripts/test.sh              backend (SQLite) + frontend lint/types/unit tests
#   ./scripts/test.sh --build      ... plus a production `next build`
#   ./scripts/test.sh --postgres   ... plus the backend suite on a throwaway
#                                  PostgreSQL 18 container (needs Docker)
#   ./scripts/test.sh --e2e        ... plus the Playwright browser tests (scripts/e2e.sh)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
export NEXT_TELEMETRY_DISABLED=1

build=0
postgres=0
e2e=0
for arg in "$@"; do
  case "$arg" in
    --build) build=1 ;;
    --postgres) postgres=1 ;;
    --e2e) e2e=1 ;;
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

echo "==> frontend: API types match the backend's OpenAPI document"
(cd frontend && npm run --silent api:check)
echo "==> frontend: eslint + tsc"
(cd frontend && npm run lint && npm run typecheck)
echo "==> frontend: vitest (unit + component tests)"
(cd frontend && npm test)
if [[ $build == 1 ]]; then
  echo "==> frontend: next build"
  (cd frontend && npm run build)
fi
if [[ $e2e == 1 ]]; then
  echo "==> browser end-to-end tests (isolated servers)"
  ./scripts/e2e.sh
fi
echo "All checks passed."
