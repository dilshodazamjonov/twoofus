#!/usr/bin/env bash
# Launches Playwright's headless WebKit (the engine behind Safari) with the few
# system libraries that scripts/install-webkit-deps.sh unpacked into
# .tools/webkit-deps, so WebKit tests run without sudo. Used as WebKit's
# executablePath by frontend/playwright.config.ts when that folder exists.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
WEBKIT_DIR="$(ls -d "$BROWSERS"/webkit-* 2>/dev/null | sort -V | tail -1)"
MB="$WEBKIT_DIR/minibrowser-wpe"
if [[ ! -x "$MB/bin/MiniBrowser" ]]; then
  echo "Playwright WebKit not found. Run: cd frontend && npx playwright install webkit" >&2
  exit 1
fi
export WEBKIT_EXEC_PATH="$MB/bin"
export WEBKIT_INJECTED_BUNDLE_PATH="$MB/lib"
export WEBKIT_INSPECTOR_RESOURCES_PATH="$MB/share"
export WEBKIT_FORCE_COMPLEX_TEXT=1
export LD_LIBRARY_PATH="$MB/lib:$MB/sys/lib:$ROOT/.tools/webkit-deps/root/usr/lib/x86_64-linux-gnu"
exec "$MB/bin/MiniBrowser" "$@"
