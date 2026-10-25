"""Allow-listing of URLs that reach the browser (artwork <img> and link-outs)."""

from __future__ import annotations

from urllib.parse import urlsplit

SPOTIFY_ARTWORK_HOSTS = ("scdn.co", "spotifycdn.com")
SPOTIFY_LINK_HOSTS = ("open.spotify.com",)
YANDEX_ARTWORK_HOSTS = ("yandex.net",)
YANDEX_LINK_HOSTS = ("music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz")


def _host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in allowed)


def safe_https_url(url: object, allowed_hosts: tuple[str, ...]) -> str | None:
    """Return ``url`` if it is an https URL on an allowed host, else ``None``."""
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    if parts.port not in (None, 443):
        return None
    if not _host_allowed(host, allowed_hosts):
        return None
    return parts.geturl()
