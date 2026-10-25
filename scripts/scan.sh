#!/usr/bin/env bash
# Security scans. Read-only: nothing is upgraded
# or rewritten. Every tool is pinned, and the scanners in containers get the
# code read-only. Results go to .scan/ (gitignored); the summary goes to the
# terminal.
#
#   ./scripts/scan.sh            dependency audits, static analysis, secret scans,
#                                Dockerfile/compose checks
#   ./scripts/scan.sh --images   ... plus vulnerability scans of the production
#                                images (built by ./scripts/prod-check.sh, tag "prodcheck")
#
# Needs: uv (Python tools run isolated via uvx), the project's Node, Docker.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/env.sh
source scripts/env.sh
images=0
[[ "${1:-}" == "--images" ]] && images=1

PIP_AUDIT="pip-audit==2.10.1"
BANDIT="bandit==1.9.4"
GITLEAKS="zricethezav/gitleaks:v8.30.1"
SEMGREP="semgrep/semgrep:1.181.1"
HADOLINT="hadolint/hadolint:v2.15.1"
TRIVY="aquasec/trivy:0.76.1"

OUT="$ROOT/.scan"
rm -rf "$OUT" && mkdir -p "$OUT/tree"
results=()
failed=0
run() {
  local name=$1
  shift
  if "$@" >"$OUT/$name.txt" 2>&1; then
    results+=("PASS  $name")
  else
    results+=("FAIL  $name   (details: .scan/$name.txt)")
    failed=1
  fi
}

# What would be committed: tracked + untracked files, minus .gitignore'd ones
# (so backend/.env, databases and node_modules are never copied anywhere).
git ls-files -z --cached --others --exclude-standard | xargs -0 -I{} cp --parents {} "$OUT/tree/" 2>/dev/null

echo "==> Python dependencies (pip-audit, all locked packages incl. dev tools)"
(cd backend && uv export --frozen --format requirements-txt --no-emit-project >"$OUT/requirements.txt")
run pip-audit uvx --from "$PIP_AUDIT" pip-audit --disable-pip --strict -r "$OUT/requirements.txt"

echo "==> Python static analysis (bandit: medium and high severity fail)"
run bandit uvx --from "$BANDIT" bandit -r backend/app -q -ll
run bandit-all-findings sh -c "uvx --from '$BANDIT' bandit -r backend/app -q -f txt || true"

echo "==> Node dependencies (npm audit: runtime, then everything incl. dev tools)"
run npm-audit-runtime sh -c "cd frontend && npm audit --omit=dev --audit-level=low"
run npm-audit-all sh -c "cd frontend && npm audit --audit-level=low"

echo "==> secrets (gitleaks: the working tree as it would be committed, and git history)"
run gitleaks-tree docker run --rm -v "$OUT/tree:/scan:ro" "$GITLEAKS" dir --no-banner --redact -v /scan
run gitleaks-history docker run --rm -v "$ROOT:/repo:ro" "$GITLEAKS" git --no-banner --redact -v /repo

echo "==> static analysis (semgrep: p/default, p/secrets, p/python, p/typescript, p/dockerfile)"
# One rule is excluded on purpose: the uv "dependency cooldown" is applied when
# upgrading (`uv lock --upgrade --exclude-newer "7 days"`);
# pinning it in pyproject.toml would make today's lock unsatisfiable.
run semgrep docker run --rm -v "$OUT/tree:/src:ro" -w /src "$SEMGREP" semgrep scan --metrics=off --error \
  --config p/default --config p/secrets --config p/python --config p/typescript --config p/dockerfile \
  --exclude-rule package_managers.uv.uv-missing-dependency-cooldown.uv-missing-dependency-cooldown \
  --exclude "*.test.ts" --exclude "*.test.tsx" --exclude "tests" --exclude "e2e" --exclude "e2e-prod" .

echo "==> Dockerfiles (hadolint) and deploy configuration (trivy config)"
run hadolint-backend sh -c "docker run --rm -i '$HADOLINT' hadolint - <backend/Dockerfile"
run hadolint-frontend sh -c "docker run --rm -i '$HADOLINT' hadolint - <frontend/Dockerfile"
run trivy-config docker run --rm -v "$OUT/tree:/src:ro" "$TRIVY" config --exit-code 1 --severity HIGH,CRITICAL /src

if [[ $images -eq 1 ]]; then
  echo "==> production images (trivy: HIGH/CRITICAL with a fix available fail)"
  for image in twoofus-api:prodcheck twoofus-web:prodcheck; do
    run "trivy-${image%%:*}" docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$TRIVY" image \
      --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$image"
    run "trivy-${image%%:*}-all" docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$TRIVY" image \
      --scanners vuln --severity LOW,MEDIUM,HIGH,CRITICAL "$image"
  done
fi

rm -rf "$OUT/tree"
echo
printf '%s\n' "${results[@]}"
exit "$failed"
