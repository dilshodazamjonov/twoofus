#!/usr/bin/env bash
# End-to-end smoke test THROUGH THE NEXT.JS PROXY using the DEMO provider.
#
# Fully isolated: temporary secrets + SQLite DB under .smoke/, ports 8100/3100,
# frontend built into frontend/.next-smoke. It never reads backend/.env, never
# touches your dev database or frontend/.next, and uses no third-party
# credentials. Spotify is configured with an obvious placeholder client id so
# the authorize URL and the callback path can be exercised; Spotify itself is
# never contacted. Yandex is disabled (it would call the real Yandex OAuth).
#
#   ./scripts/smoke.sh          run, then delete .smoke/ on success
#   ./scripts/smoke.sh --keep   keep .smoke/ (logs, database) for inspection
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

WORK="$ROOT/.smoke"
BACK_PORT=8100
FRONT_PORT=3100
ORIGIN="http://127.0.0.1:${FRONT_PORT}"
PY="$ROOT/backend/.venv/bin/python"
# Job control: every background server gets its own process group, so cleanup
# can stop the whole tree (the npm/npx/uv wrapper *and* the server it spawned).
set -m
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$BACK_PORT" "$FRONT_PORT"; do
  if port_busy "$port"; then
    echo "Port $port is already in use (a leftover server?). Stop it first." >&2
    exit 1
  fi
done
rm -rf "$WORK" && mkdir -p "$WORK"

export TWOOFUS_ENV_FILE=""  # ignore backend/.env entirely
export ENVIRONMENT=development LOG_LEVEL=INFO APP_NAME="JustTheTwoOfUs"
export PUBLIC_APP_URL="$ORIGIN"
export DATABASE_URL="sqlite+aiosqlite:///${WORK}/smoke.db"
export SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
export TOKEN_ENCRYPTION_KEYS="$(cd backend && "$PY" -c 'from app.core.crypto import generate_key; print(generate_key())')"
export DEMO_MODE=true YANDEX_ENABLED=false
# The API accepts only requests that carry this (added by the Next.js proxy).
export PROXY_SHARED_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SPOTIFY_CLIENT_ID="smoke-test-placeholder-not-a-real-client-id"
export SPOTIFY_REDIRECT_URI="${ORIGIN}/api/v1/providers/spotify/callback"
export NEXT_TELEMETRY_DISABLED=1
export SMOKE_OWNER_PASSWORD="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"

pids=()
cleanup() {
  local code=$?
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$ROOT/frontend/.next-smoke"
  if [[ $code -eq 0 && $keep -eq 0 ]]; then
    rm -rf "$WORK"
  else
    echo "Logs and database kept in $WORK"
  fi
}
trap cleanup EXIT

wait_for() {
  local url=$1
  for _ in $(seq 1 90); do
    curl -fsS -o /dev/null "$url" 2>/dev/null && return 0
    sleep 1
  done
  echo "timed out waiting for $url" >&2
  return 1
}

echo "==> migrations (isolated SQLite)"
(cd backend && uv run --frozen alembic upgrade head >"$WORK/migrate.log" 2>&1)

echo "==> owner bootstrap via the real CLI (--password-stdin)"
(cd backend && printf '%s\n' "$SMOKE_OWNER_PASSWORD" | uv run --frozen python -m app.cli.bootstrap_owner \
  --username smokeowner --display-name "Smoke Owner" --password-stdin)

echo "==> backend on 127.0.0.1:${BACK_PORT}"
(cd backend && exec uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port "$BACK_PORT" \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log >"$WORK/backend.log" 2>&1) &
pids+=($!)
wait_for "http://127.0.0.1:${BACK_PORT}/api/v1/health"  # liveness needs no proxy secret

echo "==> frontend production build (proxy -> :${BACK_PORT}) and next start on :${FRONT_PORT}"
(cd frontend && NEXT_DIST_DIR=.next-smoke BACKEND_INTERNAL_URL="http://127.0.0.1:${BACK_PORT}" TWOOFUS_DEMO_UI=1 \
  npm run build >"$WORK/frontend-build.log" 2>&1)
(cd frontend && NEXT_DIST_DIR=.next-smoke TWOOFUS_PROXY_SECRET="$PROXY_SHARED_SECRET" \
  exec npx next start --hostname 127.0.0.1 --port "$FRONT_PORT" >"$WORK/frontend.log" 2>&1) &
pids+=($!)
wait_for "${ORIGIN}/api/v1/health"

echo "==> authenticated flow through the proxy"
"$PY" scripts/smoke_test.py --origin "$ORIGIN" --backend "http://127.0.0.1:${BACK_PORT}"

if grep -E -q "auth-code|state=|code=|${SMOKE_OWNER_PASSWORD}|${PROXY_SHARED_SECRET}" "$WORK/backend.log" "$WORK/frontend.log"; then
  echo "FAIL backend log contains a secret-looking value" >&2
  exit 1
fi
echo "PASS logs contain no OAuth codes, state values, passwords or the proxy secret"
