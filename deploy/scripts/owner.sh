#!/usr/bin/env bash
# Create the owner account inside the running stack (asks for the password,
# which is never echoed, logged or passed on a command line).
#   ./deploy/scripts/owner.sh            create the owner (once)
#   ./deploy/scripts/owner.sh reset NAME reset a member's password (signs them out everywhere)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" == "reset" ]]; then
  exec docker compose exec api python -m app.cli.reset_password --username "${2:?usage: owner.sh reset USERNAME}"
fi
exec docker compose exec api python -m app.cli.bootstrap_owner
