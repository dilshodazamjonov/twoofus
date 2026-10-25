# Source this file (do not execute it):   source scripts/env.sh
# Puts the project-local Node.js (.tools/node, see scripts/install-node.sh)
# first on PATH when present, so `node`/`npm` resolve to native Linux/macOS
# binaries instead of e.g. the Windows npm that WSL exposes via /mnt/c.
_twoofus_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
if [[ -x "$_twoofus_root/.tools/node/bin/node" ]]; then
  case ":$PATH:" in
    *":$_twoofus_root/.tools/node/bin:"*) ;;
    *) export PATH="$_twoofus_root/.tools/node/bin:$PATH" ;;
  esac
fi
unset _twoofus_root
