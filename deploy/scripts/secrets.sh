#!/usr/bin/env bash
# Deployment secrets for deploy/compose.yaml. Values are generated here, on the
# server, from the kernel's CSPRNG; they are never printed or sent anywhere.
#
#   sudo ./secrets.sh init              generate any missing secret and store it
#                                       ENCRYPTED with systemd-creds in
#                                       /etc/credstore.encrypted/ (host key, TPM2 if present)
#   sudo ./secrets.sh stage DIR         (systemd unit only) copy the credentials systemd
#                                       decrypted for the unit into DIR (RAM, tmpfs)
#   ./secrets.sh init-plain DIR         plain files in DIR: local test runs ONLY
#   sudo ./secrets.sh rotate NAME       replace one secret
set -euo pipefail

STORE=/etc/credstore.encrypted
PREFIX=twoofus-
NAMES=(secret_key token_encryption_keys proxy_shared_secret postgres_password database_url)
SECRET_GID=10001  # the group the containers read secrets with (deploy/compose.yaml)

rand_urlsafe() { openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }

# Prints one freshly generated value for NAME (database_url needs the password).
generate() {
  case "$1" in
    secret_key) rand_urlsafe 48 ;;
    token_encryption_keys) openssl rand 32 | openssl base64 -A | tr '+/' '-_' | tr -d '=' ;;
    proxy_shared_secret) rand_urlsafe 36 ;;
    postgres_password) openssl rand -hex 24 ;;
    database_url) printf 'postgresql+psycopg://twoofus:%s@db:5432/twoofus' "$2" ;;
    *) echo "unknown secret $1" >&2; return 1 ;;
  esac
}

need_root() { [[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }; }

case "${1:-}" in
  init)
    need_root
    command -v systemd-creds >/dev/null || { echo "systemd-creds not found (systemd >= 250 needed)" >&2; exit 1; }
    install -d -m 0700 "$STORE"
    password=""
    for name in "${NAMES[@]}"; do
      target="$STORE/$PREFIX$name"
      if [[ -e $target ]]; then
        echo "kept     $target"
        [[ $name == postgres_password ]] && password="$(systemd-creds decrypt --name="$PREFIX$name" "$target" -)"
        continue
      fi
      value="$(generate "$name" "$password")"
      [[ $name == postgres_password ]] && password="$value"
      printf '%s' "$value" | systemd-creds encrypt --name="$PREFIX$name" - "$target"
      chmod 0600 "$target"
      echo "created  $target (encrypted)"
    done
    unset password value
    ;;
  stage)
    need_root
    dir="${2:?usage: secrets.sh stage DIR}"
    : "${CREDENTIALS_DIRECTORY:?only for the systemd unit (LoadCredentialEncrypted=)}"
    install -d -m 0750 -o root -g "$SECRET_GID" "$dir"
    for name in "${NAMES[@]}"; do
      install -m 0440 -o root -g "$SECRET_GID" "$CREDENTIALS_DIRECTORY/$name" "$dir/$name"
    done
    ;;
  init-plain)
    dir="${2:?usage: secrets.sh init-plain DIR}"
    umask 077
    mkdir -p "$dir"
    password="$(generate postgres_password)"
    for name in "${NAMES[@]}"; do
      [[ -e $dir/$name ]] && continue
      if [[ $name == postgres_password ]]; then printf '%s' "$password" >"$dir/$name"
      else generate "$name" "$password" >"$dir/$name"; fi
    done
    # Readable by the containers' secrets group only (and the owner).
    chmod 0750 "$dir" && chmod 0440 "$dir"/*
    chgrp -R "$SECRET_GID" "$dir" 2>/dev/null || chmod 0444 "$dir"/*  # no sudo: test runs only
    echo "plain test secrets in $dir (never use these for a real deployment)"
    ;;
  rotate)
    need_root
    name="${2:?usage: secrets.sh rotate NAME}"
    case "$name" in
      secret_key|proxy_shared_secret) ;;
      *) echo "rotate $name by hand (it needs data migration)" >&2; exit 1 ;;
    esac
    printf '%s' "$(generate "$name")" | systemd-creds encrypt --name="$PREFIX$name" - "$STORE/$PREFIX$name"
    echo "rotated $name; now: sudo systemctl restart twoofus"
    ;;
  *)
    sed -n '2,15p' "$0"; exit 2 ;;
esac
