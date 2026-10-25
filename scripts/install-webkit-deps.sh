#!/usr/bin/env bash
# Optional, for the WebKit (Safari engine) end-to-end tests on Debian/Ubuntu
# without sudo: downloads the handful of shared libraries Playwright's WebKit
# needs (apt-get download, no root) and unpacks them into .tools/webkit-deps.
# Nothing is installed system-wide. With sudo you can instead run
# `sudo npx playwright install-deps webkit`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.tools/webkit-deps"
PACKAGES=(libavif16 libevent-2.1-7t64 libflite1 libmanette-0.2-0 libdav1d7 libgav1-2 libhidapi-hidraw0 libyuv0)
mkdir -p "$DEST/debs"
(cd "$DEST/debs" && apt-get download "${PACKAGES[@]}")
for deb in "$DEST"/debs/*.deb; do dpkg-deb -x "$deb" "$DEST/root"; done
echo "WebKit libraries unpacked into $DEST/root (used by scripts/playwright-webkit.sh)."
