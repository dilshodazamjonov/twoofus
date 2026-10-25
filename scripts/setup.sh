#!/usr/bin/env bash
# Idempotent local setup for Linux, macOS and WSL. Safe to re-run.
#   - Node.js: uses a native Node >= 20.9 if present, else installs a
#     checksum-verified project-local copy into .tools/node (no sudo).
#   - Backend: uv creates backend/.venv from the locked uv.lock.
#   - Creates backend/.env with fresh random secrets if it does not exist.
#   - Applies database migrations; installs frontend deps from package-lock.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e '
    const [maj, min] = process.versions.node.split(".").map(Number);
    const native = ["linux", "darwin"].includes(process.platform);
    process.exit(native && (maj > 20 || (maj === 20 && min >= 9)) ? 0 : 1);
  ' >/dev/null 2>&1
}

# shellcheck source=scripts/env.sh
source scripts/env.sh
if ! node_ok; then
  echo "==> No native Node.js >= 20.9 on PATH; installing a project-local copy"
  ./scripts/install-node.sh
  source scripts/env.sh
fi
echo "==> Node $(node --version) ($(command -v node))"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required for the Python backend: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

echo "==> Backend: creating backend/.venv from uv.lock"
(cd backend && uv sync --frozen)

echo "==> Backend: backend/.env"
(cd backend && uv run python -m app.cli.keys --init-env)

echo "==> Backend: database migrations"
(cd backend && uv run alembic upgrade head)

echo "==> Frontend: npm ci (package-lock.json)"
(cd frontend && NEXT_TELEMETRY_DISABLED=1 npm ci --no-audit --no-fund)

cat <<'EOF'

Setup complete.
  1. Create the owner (once):  cd backend && uv run python -m app.cli.bootstrap_owner
  2. Start both servers:       ./scripts/dev.sh
  3. Open (exactly this host): http://127.0.0.1:3000
EOF
