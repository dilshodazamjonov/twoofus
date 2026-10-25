"""Values the frontend and backend must agree on (checked from source)."""

from __future__ import annotations

import re

from app.core.config import BACKEND_DIR
from app.core.middleware import PROXY_AUTH_HEADER
from app.providers.urls import SPOTIFY_ARTWORK_HOSTS, YANDEX_ARTWORK_HOSTS

FRONTEND_SRC = BACKEND_DIR.parent / "frontend" / "src"


def test_csp_allows_exactly_the_artwork_hosts_the_backend_lets_through() -> None:
    source = (FRONTEND_SRC / "lib" / "csp.ts").read_text(encoding="utf-8")
    match = re.search(r"ARTWORK_HOSTS = \[([^\]]*)\]", source)
    assert match is not None
    frontend_hosts = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert frontend_hosts == {*SPOTIFY_ARTWORK_HOSTS, *YANDEX_ARTWORK_HOSTS}


def test_the_proxy_adds_the_header_the_api_checks() -> None:
    source = (FRONTEND_SRC / "proxy.ts").read_text(encoding="utf-8")
    assert f'PROXY_AUTH_HEADER = "{PROXY_AUTH_HEADER}"' in source
    manifest = (FRONTEND_SRC / "app" / "manifest.webmanifest" / "route.ts").read_text("utf-8")
    assert f'"{PROXY_AUTH_HEADER}"' in manifest
