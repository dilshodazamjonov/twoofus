#!/usr/bin/env bash
# First-run verification from a CLEAN COPY of the repository: exactly the files
# git would commit (tracked + new, minus .gitignore'd ones), in .verify/repo.
# Nothing from this checkout's local state is reused: not backend/.env, not
# backend/.venv, not node_modules, not .tools/node. Package downloads come from
# the uv/npm caches when warm.
#
#   ./scripts/verify.sh           setup.sh, then lint/types/unit+integration tests,
#                                 a production build and the smoke test
#   ./scripts/verify.sh --full    ... plus PostgreSQL, the browser suite (e2e) and
#                                 the production stack (prod-check), all from the copy
#   ./scripts/verify.sh --keep    keep .verify/ afterwards
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
full=0 keep=0
for arg in "$@"; do
  case "$arg" in
    --full) full=1 ;;
    --keep) keep=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

WORK="$ROOT/.verify/repo"
rm -rf "$ROOT/.verify" && mkdir -p "$WORK"
cleanup() {
  local code=$?
  if [[ $keep -eq 0 && $code -eq 0 ]]; then rm -rf "$ROOT/.verify"; fi
  [[ $code -ne 0 ]] && echo "verify FAILED (the copy is kept in $WORK)" >&2
  exit $code
}
trap cleanup EXIT

echo "==> clean copy of the repository into .verify/repo"
(cd "$ROOT" && git ls-files -z --cached --others --exclude-standard | xargs -0 -I{} cp --parents {} "$WORK/")
for local_state in backend/.env backend/.venv backend/data frontend/node_modules .tools; do
  [[ -e "$WORK/$local_state" ]] && { echo "local state leaked into the copy: $local_state" >&2; exit 1; }
done
echo "   $(cd "$WORK" && find . -type f | wc -l) files, no .env, no .venv, no node_modules, no .tools"

cd "$WORK"
echo "==> setup.sh (toolchain, backend/.venv from uv.lock, fresh secrets, migrations, npm ci)"
./scripts/setup.sh
echo "==> test.sh --build $([[ $full -eq 1 ]] && echo --postgres)"
if [[ $full -eq 1 ]]; then ./scripts/test.sh --build --postgres; else ./scripts/test.sh --build; fi
echo "==> smoke.sh"
./scripts/smoke.sh
if [[ $full -eq 1 ]]; then
  echo "==> browser suite (e2e.sh)"
  ./scripts/install-webkit-deps.sh >/dev/null 2>&1 || echo "   (WebKit libraries unavailable: WebKit is skipped)"
  ./scripts/e2e.sh
  echo "==> production stack (prod-check.sh)"
  ./scripts/prod-check.sh
fi
echo "verify passed from a clean copy."
