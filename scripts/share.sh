#!/usr/bin/env bash
# Share the app from this computer for free through a temporary Cloudflare
# tunnel (https://<random>.trycloudflare.com). Runs a production build against
# your local backend and database. The link changes on every run and works only
# while this script runs. Ctrl+C stops everything.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
export NEXT_TELEMETRY_DISABLED=1 NEXT_DIST_DIR=.next-share
WEB_PORT="${WEB_PORT:-3000}"
API_PORT="${API_PORT:-8000}"
export BACKEND_INTERNAL_URL="http://127.0.0.1:$API_PORT"
CLOUDFLARED="$ROOT/.tools/cloudflared/cloudflared"
LOG="$(mktemp)"
set -m
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$API_PORT" "$WEB_PORT"; do
  if port_busy "$port"; then
    echo "Port $port is already in use. Stop ./scripts/dev.sh first." >&2
    exit 1
  fi
done

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -f "$LOG"
}
trap cleanup INT TERM EXIT

"$CLOUDFLARED" tunnel --no-autoupdate --url "http://127.0.0.1:$WEB_PORT" >"$LOG" 2>&1 &
pids+=($!)
URL=""
for _ in $(seq 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [[ -n "$URL" ]] && break
  sleep 1
done
if [[ -z "$URL" ]]; then
  echo "The tunnel did not start:" >&2
  cat "$LOG" >&2
  exit 1
fi

(cd backend && uv run alembic upgrade head)
echo "Building the app (about a minute)..."
(cd frontend && TWOOFUS_DEMO_UI=0 npm run build >/dev/null)

(
  cd backend
  export PUBLIC_APP_URL="$URL" SPOTIFY_REDIRECT_URI="$URL/api/v1/providers/spotify/callback" DEMO_MODE=false
  exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
    --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
) &
pids+=($!)
(cd frontend && exec npx next start --hostname 127.0.0.1 --port "$WEB_PORT") &
pids+=($!)

echo
echo "Share this link: $URL"
echo "Spotify only: add $URL/api/v1/providers/spotify/callback"
echo "as a Redirect URI in the Spotify dashboard (it changes every run)."
echo "Ctrl+C stops it."
wait -n
