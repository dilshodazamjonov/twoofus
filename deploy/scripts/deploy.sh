#!/usr/bin/env bash
# Build the images, run migrations and (re)start the stack, then wait until the
# public URL answers /api/v1/ready. Run on the server from the repository:
#   ./deploy/scripts/deploy.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ -f .env ]] || { echo "deploy/.env is missing: cp deploy/.env.example deploy/.env and edit it" >&2; exit 1; }
set -a; source .env; set +a
TWOOFUS_VERSION="$(git rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
export TWOOFUS_VERSION
echo "==> building images (version $TWOOFUS_VERSION)"
docker compose build --pull
if systemctl list-unit-files twoofus.service >/dev/null 2>&1 && systemctl is-enabled --quiet twoofus; then
  echo "==> restarting the systemd unit (migrations run before the API starts)"
  sudo systemctl restart twoofus
else
  echo "==> starting with docker compose (no systemd unit installed)"
  docker compose up -d --no-build --remove-orphans
fi
url="https://${TWOOFUS_DOMAIN}${TWOOFUS_PUBLIC_PORT_SUFFIX:-}/api/v1/ready"
echo "==> waiting for $url"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "$url"; then echo "Ready."; exit 0; fi
  sleep 5
done
echo "Not ready after 5 minutes. Look at: docker compose logs --tail=100 api caddy" >&2
exit 1
