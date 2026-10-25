#!/usr/bin/env bash
# Installs a project-local, checksum-verified Node.js LTS into .tools/node
# (Linux/macOS, no sudo, no shell-profile changes). Skip this entirely if you
# already have a native Node.js >= 20.9 on PATH (e.g. via nvm, fnm, apt, brew).
#
# Why this exists: inside WSL the PATH often contains the *Windows* npm
# (/mnt/c/Program Files/nodejs), which installs win32 native binaries and
# breaks Next.js on the Linux filesystem.
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-v24.22.1}"   # Active LTS "Krypton" as of 2026-10
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.tools/node"

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) echo "Unsupported OS $(uname -s); install Node.js manually." >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=x64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "Unsupported CPU $(uname -m); install Node.js manually." >&2; exit 1 ;;
esac

if [[ -x "$DEST/bin/node" ]] && [[ "$("$DEST/bin/node" --version)" == "$NODE_VERSION" ]]; then
  echo "Node $NODE_VERSION already installed at $DEST"
  exit 0
fi

name="node-$NODE_VERSION-$os-$arch"
tarball="$name.tar.xz"
base="https://nodejs.org/dist/$NODE_VERSION"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $base/$tarball"
curl -fsSL "$base/$tarball" -o "$tmp/$tarball"
curl -fsSL "$base/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
(cd "$tmp" && grep " $tarball\$" SHASUMS256.txt | sha256sum -c -)

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xJf "$tmp/$tarball" -C "$DEST" --strip-components=1
echo "Installed $("$DEST/bin/node" --version) at $DEST"
echo "Use it in this shell with:  source scripts/env.sh"
