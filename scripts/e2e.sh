#!/usr/bin/env bash
# Browser end-to-end tests (Playwright) against isolated servers.
#
# Like scripts/smoke.sh this never touches backend/.env, your dev database or
# frontend/.next: temporary secrets and SQLite live in .e2e/, the backend runs
# on :8200 and a production build of the frontend on :3200. No real Spotify or
# Yandex account is used: the backend's real provider code talks to a local
# fake of both services on :8300 (backend/tests/fakes/providers.py), and the
# browser's trip to accounts.spotify.com is answered by that fake too.
#
#   ./scripts/e2e.sh                    run all browser tests
#   ./scripts/e2e.sh --serve            only start the servers (explore at http://127.0.0.1:3200)
#   ./scripts/e2e.sh --keep             keep .e2e/ (logs, database) afterwards
#   ./scripts/e2e.sh -- --project=iphone-webkit   extra arguments go to Playwright
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh

keep=0 serve=0
playwright_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) keep=1 ;;
    --serve) serve=1 keep=1 ;;
    --) shift; playwright_args=("$@"); break ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

WORK="$ROOT/.e2e"
BACK_PORT=8200
FRONT_PORT=3200
FAKE_PORT=8300
ORIGIN="http://127.0.0.1:${FRONT_PORT}"
PY="$ROOT/backend/.venv/bin/python"
set -m  # each server in its own process group, so cleanup stops the whole tree
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$BACK_PORT" "$FRONT_PORT" "$FAKE_PORT"; do
  if port_busy "$port"; then
    echo "Port $port is already in use (a leftover server?). Stop it first." >&2
    exit 1
  fi
done
rm -rf "$WORK" && mkdir -p "$WORK"

export TWOOFUS_ENV_FILE=""  # ignore backend/.env entirely
export ENVIRONMENT=development LOG_LEVEL=INFO APP_NAME="JustTheTwoOfUs"
export PUBLIC_APP_URL="$ORIGIN"
export DATABASE_URL="sqlite+aiosqlite:///${WORK}/e2e.db"
export SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
export TOKEN_ENCRYPTION_KEYS="$(cd backend && "$PY" -c 'from app.core.crypto import generate_key; print(generate_key())')"
export DEMO_MODE=true YANDEX_ENABLED=true
export SPOTIFY_CLIENT_ID="e2e-fake-spotify-client-id"
export SPOTIFY_REDIRECT_URI="${ORIGIN}/api/v1/providers/spotify/callback"
# Real adapters, fake far end (local tests only; the backend refuses this in production).
export PROVIDER_UPSTREAM_OVERRIDE="http://127.0.0.1:${FAKE_PORT}"
export NOW_PLAYING_TTL_SECONDS=2 PROVIDER_TIMEOUT_SECONDS=2
# The API only answers requests carrying this; the Next.js proxy adds it.
export PROXY_SHARED_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export E2E_FAKE_PROVIDERS="http://127.0.0.1:${FAKE_PORT}" E2E_SPOTIFY_CLIENT_ID="$SPOTIFY_CLIENT_ID"
export NEXT_TELEMETRY_DISABLED=1
export E2E_BASE_URL="$ORIGIN"
export E2E_OWNER_USERNAME="alex"
export E2E_OWNER_NAME="Alex"
export E2E_OWNER_PASSWORD="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"

pids=()
cleanup() {
  local code=$?
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$ROOT/frontend/.next-e2e"
  if [[ $code -eq 0 && $keep -eq 0 ]]; then
    rm -rf "$WORK"
  else
    echo "Logs and database kept in $WORK"
  fi
}
trap cleanup EXIT

wait_for() {
  for _ in $(seq 1 90); do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    sleep 1
  done
  echo "timed out waiting for $1" >&2
  return 1
}

echo "==> migrations + owner (isolated SQLite in .e2e/)"
(cd backend && uv run --frozen alembic upgrade head >"$WORK/migrate.log" 2>&1)
(cd backend && printf '%s\n' "$E2E_OWNER_PASSWORD" | uv run --frozen python -m app.cli.bootstrap_owner \
  --username "$E2E_OWNER_USERNAME" --display-name "$E2E_OWNER_NAME" --password-stdin >/dev/null)

echo "==> fake Spotify/Yandex on 127.0.0.1:${FAKE_PORT}"
(cd backend && exec uv run --frozen python -m tests.fakes.providers --port "$FAKE_PORT" \
  --spotify-client-id "$SPOTIFY_CLIENT_ID" --spotify-redirect "$SPOTIFY_REDIRECT_URI" \
  --device-interval 2 >"$WORK/fake-providers.log" 2>&1) &
pids+=($!)
wait_for "http://127.0.0.1:${FAKE_PORT}/_control/state"

echo "==> backend on 127.0.0.1:${BACK_PORT}"
(cd backend && exec uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port "$BACK_PORT" \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log >"$WORK/backend.log" 2>&1) &
pids+=($!)
wait_for "http://127.0.0.1:${BACK_PORT}/api/v1/health"

echo "==> frontend production build + next start on 127.0.0.1:${FRONT_PORT}"
(cd frontend && NEXT_DIST_DIR=.next-e2e BACKEND_INTERNAL_URL="http://127.0.0.1:${BACK_PORT}" TWOOFUS_DEMO_UI=1 \
  npm run build >"$WORK/frontend-build.log" 2>&1)
(cd frontend && NEXT_DIST_DIR=.next-e2e BACKEND_INTERNAL_URL="http://127.0.0.1:${BACK_PORT}" \
  TWOOFUS_PROXY_SECRET="$PROXY_SHARED_SECRET" \
  exec npx next start --hostname 127.0.0.1 --port "$FRONT_PORT" >"$WORK/frontend.log" 2>&1) &
pids+=($!)
wait_for "${ORIGIN}/api/v1/health"

if [[ $serve -eq 1 ]]; then
  echo "Serving on ${ORIGIN}  (owner: ${E2E_OWNER_USERNAME}; password in ${WORK}/owner-password)"
  umask 077 && printf '%s\n' "$E2E_OWNER_PASSWORD" >"$WORK/owner-password"
  wait -n
  exit 0
fi

echo "==> Playwright"
if [[ -d "$ROOT/.tools/webkit-deps/root" ]]; then
  # WebKit runs with project-local libraries (scripts/install-webkit-deps.sh);
  # Playwright's host check would only miss an unused GStreamer media plugin.
  export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1
fi
(cd frontend && npx playwright test "${playwright_args[@]}")

# Fake provider tokens look like BQ-fake-…, AQ-fake-…, y0_fake_…: none may be logged.
if grep -E -q "${E2E_OWNER_PASSWORD}|${PROXY_SHARED_SECRET}|state=|code=|BQ-fake-|AQ-fake-|y0_fake_" \
  "$WORK/backend.log" "$WORK/frontend.log"; then
  echo "FAIL a log contains a secret-looking value" >&2
  exit 1
fi
echo "PASS logs contain no passwords, provider tokens, OAuth codes, state values or the proxy secret"
