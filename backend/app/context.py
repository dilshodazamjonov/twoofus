"""Process-wide services, created once per app instance (see app.main)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.passwords import Passwords
from app.core.clock import Clock
from app.core.config import Settings
from app.core.crypto import TokenCipher
from app.core.ratelimit import RateLimiter
from app.core.security import CsrfSigner
from app.providers.registry import ProviderRegistry

if TYPE_CHECKING:
    from app.services.now_playing import NowPlayingService


@dataclass
class AppContext:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cipher: TokenCipher
    csrf: CsrfSigner
    passwords: Passwords
    rate_limiter: RateLimiter
    http: httpx.AsyncClient
    providers: ProviderRegistry
    now_playing: NowPlayingService

    @property
    def session_cookie_name(self) -> str:
        # __Host- prefix: browser enforces Secure, Path=/ and no Domain attribute.
        return "__Host-twoofus_session" if self.settings.secure_cookies else "twoofus_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-twoofus_csrf" if self.settings.secure_cookies else "twoofus_csrf"
