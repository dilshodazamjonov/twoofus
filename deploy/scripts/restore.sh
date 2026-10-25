#!/usr/bin/env bash
# Restore a backup made by backup.sh into the running stack's database.
#   ./deploy/scripts/restore.sh /var/backups/twoofus/twoofus-20261025T033000Z.dump
#   (an .age file needs TWOOFUS_BACKUP_AGE_IDENTITY=/path/to/age-key.txt)
# Everyone is signed out afterwards only if the dump predates their session.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
file="${1:?usage: restore.sh BACKUP_FILE}"
[[ -r $file ]] || { echo "cannot read $file" >&2; exit 1; }
answer="${TWOOFUS_RESTORE_CONFIRM:-}"  # non-interactive use (scripts/prod-check.sh)
[[ -n $answer ]] || read -r -p "This REPLACES the current database with $file. Type 'restore' to continue: " answer
[[ $answer == restore ]] || { echo "cancelled"; exit 1; }
echo "==> stopping the API and web app (the database keeps running)"
docker compose stop api web
if [[ $file == *.age ]]; then
  age -d -i "${TWOOFUS_BACKUP_AGE_IDENTITY:?set TWOOFUS_BACKUP_AGE_IDENTITY}" "$file"
else
  cat "$file"
fi | docker compose exec -T db pg_restore -U twoofus -d twoofus --clean --if-exists --no-owner --exit-on-error
echo "==> migrating to this version's schema and starting again"
docker compose run --rm migrate
docker compose up -d --no-build api web
echo "Restored. Check: curl -fsS https://\$TWOOFUS_DOMAIN/api/v1/ready"
