#!/usr/bin/env bash
# Container entrypoint on Render (deploy/render/Dockerfile): migrate, start the
# API on loopback, then the Next.js server on Render's $PORT. If either one
# exits, the container exits and Render restarts it.
set -euo pipefail
export PUBLIC_APP_URL="${PUBLIC_APP_URL:-${RENDER_EXTERNAL_URL:?not running on Render: set PUBLIC_APP_URL}}"
export SPOTIFY_REDIRECT_URI="${SPOTIFY_REDIRECT_URI:-$PUBLIC_APP_URL/api/v1/providers/spotify/callback}"
export TWOOFUS_PROXY_SECRET="${PROXY_SHARED_SECRET:?}"

cd /app
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --no-server-header &
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)" 2>/dev/null; do
  sleep 0.5
done
(cd web && HOSTNAME=0.0.0.0 PORT="${PORT:-10000}" exec node server.js) &
wait -n
exit 1
