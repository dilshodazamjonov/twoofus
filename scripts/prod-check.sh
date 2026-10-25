#!/usr/bin/env bash
# Runs the real production stack (deploy/compose.yaml: Caddy, Next.js, FastAPI,
# PostgreSQL, built from deploy's Dockerfiles with ENVIRONMENT=production) on
# this machine over HTTPS, and checks what a deployment must get right:
# headers, cookies, the authenticated proxy hop, network isolation, client-IP
# handling, limits, the Spotify callback through the proxy, a restart, a backup
# and restore, a browser pass (CSP, service worker) and logs without secrets.
#
# Nothing here is a real deployment: TLS comes from Caddy's internal test CA
# for https://127.0.0.1:8443, secrets are throwaway files, and Spotify is never
# contacted.
#
#   ./scripts/prod-check.sh            run, then remove containers and volumes
#   ./scripts/prod-check.sh --keep     leave the stack running (docker compose -p twoofus-prodcheck ...)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
keep=0
[[ "${1:-}" == "--keep" ]] && keep=1

WORK="$ROOT/.prodcheck"
export COMPOSE_PROJECT_NAME=twoofus-prodcheck
export TWOOFUS_DOMAIN=127.0.0.1 TWOOFUS_TLS=internal
export TWOOFUS_HTTP_PORT=8080 TWOOFUS_HTTPS_PORT=8443 TWOOFUS_PUBLIC_PORT_SUFFIX=:8443
export TWOOFUS_SECRETS_DIR="$WORK/secrets" TWOOFUS_VERSION=prodcheck
export SPOTIFY_CLIENT_ID="prodcheck-placeholder-client-id" YANDEX_ENABLED=true APP_NAME=JustTheTwoOfUs
export TWOOFUS_BACKUP_DIR="$WORK/backups"
ORIGIN="https://127.0.0.1:8443"
PY="$ROOT/backend/.venv/bin/python"
compose() { docker compose -f "$ROOT/deploy/compose.yaml" "$@"; }

echo "==> removing any previous prod-check stack (containers and volumes)"
compose down -v --remove-orphans >/dev/null 2>&1 || true
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in 8080 8443; do
  if port_busy "$port"; then echo "Port $port is in use; stop that first." >&2; exit 1; fi
done

cleanup() {
  local code=$?
  if [[ $keep -eq 0 ]]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
  fi
  [[ $code -ne 0 ]] && echo "prod-check FAILED (logs: docker compose -p $COMPOSE_PROJECT_NAME logs)" >&2
  exit $code
}
trap cleanup EXIT

rm -rf "$WORK" && mkdir -p "$WORK"
echo "==> throwaway secrets (plain files: test only)"
deploy/scripts/secrets.sh init-plain "$WORK/secrets" >/dev/null

echo "==> building production images (no demo UI, no test code)"
compose build >"$WORK/build.log" 2>&1 || { tail -50 "$WORK/build.log"; exit 1; }

echo "==> starting the stack"
compose up -d >"$WORK/up.log" 2>&1 || { cat "$WORK/up.log"; exit 1; }
for _ in $(seq 1 90); do
  compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$WORK/caddy-root.crt" >/dev/null 2>&1 && break
  sleep 1
done
for _ in $(seq 1 90); do
  curl -fsS --cacert "$WORK/caddy-root.crt" -o /dev/null "$ORIGIN/api/v1/ready" 2>/dev/null && break
  sleep 1
done
curl -fsS --cacert "$WORK/caddy-root.crt" "$ORIGIN/api/v1/ready" >/dev/null

echo "==> owner account via the deploy script's CLI (password on stdin)"
OWNER_PASSWORD="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')"
export OWNER_PASSWORD
printf '%s\n' "$OWNER_PASSWORD" | compose exec -T api python -m app.cli.bootstrap_owner \
  --username owner --display-name Owner --password-stdin >/dev/null

echo "==> HTTP checks through Caddy"
"$PY" scripts/prod_check.py --origin "$ORIGIN" --http "http://127.0.0.1:8080" --cacert "$WORK/caddy-root.crt" \
  --project "$COMPOSE_PROJECT_NAME" --compose-file "$ROOT/deploy/compose.yaml"

echo "==> browser pass (Chromium trusting only this run's test CA)"
SPKI="$(compose exec -T caddy sh -c 'cat /data/caddy/certificates/local/127.0.0.1/127.0.0.1.crt' \
  | openssl x509 -pubkey -noout | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | openssl base64)"
(cd frontend && PROD_ORIGIN="$ORIGIN" PROD_SPKI="$SPKI" PROD_OWNER_PASSWORD="$OWNER_PASSWORD" \
  npx playwright test --config playwright.prod.config.ts)

echo "==> logs contain no secrets"
compose logs --no-color >"$WORK/all.log" 2>&1
patterns=("$OWNER_PASSWORD" "state=" "code=")
for name in secret_key token_encryption_keys proxy_shared_secret postgres_password; do
  patterns+=("$(cat "$WORK/secrets/$name")")
done
for pattern in "${patterns[@]}"; do
  if grep -F -q -- "$pattern" "$WORK/all.log"; then
    echo "FAIL a container log contains a secret or an OAuth parameter" >&2
    exit 1
  fi
done
echo "PASS no passwords, secrets, OAuth codes or state values in any container log"
echo "prod-check passed."
