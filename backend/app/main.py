"""FastAPI application factory.

Run locally (behind the Next.js same-origin proxy):
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers \
        --forwarded-allow-ips 127.0.0.1 --no-access-log

In production the API sits behind Caddy (deploy/), see docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from argon2 import PasswordHasher
from fastapi import FastAPI

from app.api.router import API_PREFIX, api_router
from app.auth.passwords import Passwords
from app.context import AppContext
from app.core.clock import Clock, utcnow
from app.core.config import ConfigError, Settings, get_settings
from app.core.crypto import TokenCipher
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodyLimitMiddleware, ProxyAuthMiddleware, RequestLogMiddleware
from app.core.ratelimit import RateLimiter
from app.core.security import CsrfSigner
from app.db.session import create_engine, create_session_factory
from app.providers.registry import build_http_client, build_registry
from app.providers.yandex import YandexGateway
from app.services.maintenance import cleanup_loop
from app.services.now_playing import NowPlayingService

logger = logging.getLogger("app")

_DOCS_PATHS = (f"{API_PREFIX}/docs", f"{API_PREFIX}/openapi.json")
# Liveness stays reachable without the proxy secret (container health checks).
_PROXY_OPEN_PATHS = frozenset({f"{API_PREFIX}/health"})


def build_context(
    settings: Settings,
    *,
    clock: Clock = utcnow,
    yandex_gateway: YandexGateway | None = None,
    password_hasher: PasswordHasher | None = None,
) -> AppContext:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    cipher = TokenCipher(settings.encryption_keys())
    http = build_http_client(settings)
    providers = build_registry(settings, http, clock, yandex_gateway=yandex_gateway)
    now_playing = NowPlayingService(
        settings=settings,
        providers=providers,
        cipher=cipher,
        session_factory=session_factory,
        clock=clock,
    )
    return AppContext(
        settings=settings,
        clock=clock,
        engine=engine,
        session_factory=session_factory,
        cipher=cipher,
        csrf=CsrfSigner(settings.secret_key.get_secret_value()),
        passwords=Passwords(password_hasher),
        rate_limiter=RateLimiter(),
        http=http,
        providers=providers,
        now_playing=now_playing,
    )


async def close_context(ctx: AppContext) -> None:
    await ctx.http.aclose()
    await ctx.engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock = utcnow,
    yandex_gateway: YandexGateway | None = None,
    password_hasher: PasswordHasher | None = None,
    run_background_tasks: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format or "text")
    ctx = build_context(
        settings, clock=clock, yandex_gateway=yandex_gateway, password_hasher=password_hasher
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = (
            asyncio.create_task(cleanup_loop(ctx.session_factory, ctx.clock))
            if run_background_tasks
            else None
        )
        logger.info(
            "%s backend started (env=%s, providers=%s, proxy_auth=%s)",
            settings.app_name,
            settings.environment,
            ",".join(sorted(ctx.providers.available())) or "none",
            "on" if settings.proxy_shared_secret is not None else "off",
        )
        if settings.upstream_override:
            logger.warning(
                "TEST MODE: Spotify/Yandex calls go to the local fake at %s, not the real "
                "services (PROVIDER_UPSTREAM_OVERRIDE)",
                settings.upstream_override,
            )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await close_context(ctx)

    show_docs = settings.environment != "production"
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description="Private now-playing companion for exactly two people.",
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json" if show_docs else None,
        docs_url=f"{API_PREFIX}/docs" if show_docs else None,
        redoc_url=None,
    )
    app.state.ctx = ctx
    install_error_handlers(app)
    app.include_router(api_router)

    # Added innermost first: the request log wraps everything, so refusals by
    # the proxy check or the body limit are logged (and get security headers).
    app.add_middleware(BodyLimitMiddleware)
    if settings.proxy_shared_secret is not None:
        app.add_middleware(
            ProxyAuthMiddleware,
            secret=settings.proxy_shared_secret.get_secret_value(),
            open_paths=_PROXY_OPEN_PATHS,
        )
    app.add_middleware(RequestLogMiddleware, skip_security_headers=_DOCS_PATHS)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn app.main:app` builds the app lazily, so importing this module
    # (e.g. in tests or Alembic) does not require a configured environment.
    if name == "app":
        try:
            application = create_app()
        except ConfigError as exc:
            raise SystemExit(str(exc)) from None
        globals()["app"] = application
        return application
    raise AttributeError(name)
