#!/bin/sh
# Hands the proxy secret (a mounted secret file, never an image layer or a
# NEXT_PUBLIC_ variable) to the Next.js server, which adds it to requests it
# forwards to the API. Then runs the standalone server as PID 1's child-free exec.
set -eu
if [ -r /run/secrets/proxy_shared_secret ]; then
  TWOOFUS_PROXY_SECRET="$(cat /run/secrets/proxy_shared_secret)"
  export TWOOFUS_PROXY_SECRET
fi
exec node server.js
