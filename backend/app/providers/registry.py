"""Builds the provider adapters that the current configuration allows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.core.config import Settings
from app.models.enums import ProviderName
from app.providers.base import PlaybackProvider
from app.providers.demo import DemoProvider
from app.providers.spotify import SpotifyProvider
from app.providers.yandex import LibraryYandexGateway, YandexGateway, YandexProvider


@dataclass
class ProviderRegistry:
    spotify: SpotifyProvider | None = None
    yandex: YandexProvider | None = None
    demo: DemoProvider | None = None
    _by_name: dict[ProviderName, PlaybackProvider] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for provider in (self.spotify, self.yandex, self.demo):
            if provider is not None:
                self._by_name[provider.name] = provider

    def get(self, name: str) -> PlaybackProvider | None:
        try:
            return self._by_name.get(ProviderName(name))
        except ValueError:
            return None

    def available(self) -> frozenset[ProviderName]:
        return frozenset(self._by_name)


def build_registry(
    settings: Settings,
    http: httpx.AsyncClient,
    clock: Callable[[], datetime],
    *,
    yandex_gateway: YandexGateway | None = None,
) -> ProviderRegistry:
    spotify = (
        SpotifyProvider(
            http,
            client_id=settings.spotify_client_id,
            redirect_uri=settings.spotify_redirect_uri,
            clock=clock,
            upstream_override=settings.upstream_override,
        )
        if settings.spotify_configured
        else None
    )
    yandex = (
        YandexProvider(
            yandex_gateway
            or LibraryYandexGateway(
                timeout_seconds=settings.provider_timeout_seconds,
                http=http,
                upstream_override=settings.upstream_override,
            ),
            app_name=settings.app_name,
            web_base=settings.yandex_music_web_base,
            clock=clock,
        )
        if settings.yandex_enabled
        else None
    )
    demo = DemoProvider(clock) if settings.demo_mode else None
    return ProviderRegistry(spotify=spotify, yandex=yandex, demo=demo)


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(settings.provider_timeout_seconds, connect=5.0)
    return httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        headers={"User-Agent": "TwoOfUs/0.1 (+private two-person app)"},
        follow_redirects=False,
    )
