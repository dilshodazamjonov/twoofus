#!/usr/bin/env bash
# Dump the database (PostgreSQL custom format) into TWOOFUS_BACKUP_DIR and keep
# the newest TWOOFUS_BACKUP_KEEP files. With TWOOFUS_BACKUP_AGE_RECIPIENT set
# (an age public key) and `age` installed, dumps are encrypted before they touch
# the disk. Provider tokens inside are already encrypted with the app's keys;
# a restore therefore also needs TOKEN_ENCRYPTION_KEYS (back the secrets up too).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
DIR="${TWOOFUS_BACKUP_DIR:-/var/backups/twoofus}"
KEEP="${TWOOFUS_BACKUP_KEEP:-14}"
umask 077
mkdir -p "$DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -n "${TWOOFUS_BACKUP_AGE_RECIPIENT:-}" ]]; then
  out="$DIR/twoofus-$stamp.dump.age"
  docker compose exec -T db pg_dump -U twoofus -d twoofus --format=custom \
    | age -r "$TWOOFUS_BACKUP_AGE_RECIPIENT" -o "$out.partial"
else
  out="$DIR/twoofus-$stamp.dump"
  docker compose exec -T db pg_dump -U twoofus -d twoofus --format=custom >"$out.partial"
fi
mv "$out.partial" "$out"
echo "backup written: $out ($(du -h "$out" | cut -f1))"
ls -1t "$DIR"/twoofus-*.dump* 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f --
