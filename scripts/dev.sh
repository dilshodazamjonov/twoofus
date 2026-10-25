#!/usr/bin/env bash
# Start FastAPI (127.0.0.1:8000) and Next.js (127.0.0.1:3000) together.
# Ctrl+C stops both. Open http://127.0.0.1:3000 (not "localhost": cookies are
# per-host, and Spotify only accepts 127.0.0.1 loopback redirect URIs).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
export NEXT_TELEMETRY_DISABLED=1
# Job control: every background server gets its own process group, so cleanup
# can stop the whole tree (the npm/npx/uv wrapper *and* the server it spawned).
set -m
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in 8000 3000; do
  if port_busy "$port"; then
    echo "Port $port is already in use. Stop that process first (another dev server?)." >&2
    exit 1
  fi
done

(cd backend && uv run alembic upgrade head)

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
  cd backend
  # --proxy-headers: trust X-Forwarded-For only from the local Next.js proxy.
  # --no-access-log: our own request log omits query strings (OAuth codes).
  exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log \
    --reload --reload-dir app
) &
pids+=($!)

(cd frontend && exec npm run dev) &
pids+=($!)

echo "Backend  http://127.0.0.1:8000/api/v1/docs (dev only)"
echo "App      http://127.0.0.1:3000"
wait -n
