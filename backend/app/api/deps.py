"""FastAPI dependencies: context, DB session, authentication, CSRF."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import ResolvedSession, resolve_session, set_session_cookie
from app.context import AppContext
from app.core.errors import CsrfFailed, Forbidden, NotAuthenticated
from app.core.security import tokens_equal
from app.models import MemberRole

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


async def get_db(ctx: Ctx) -> AsyncIterator[AsyncSession]:
    async with ctx.session_factory() as session:
        yield session


Db = Annotated[AsyncSession, Depends(get_db)]


async def optional_auth(
    request: Request, response: Response, ctx: Ctx, db: Db
) -> ResolvedSession | None:
    raw = request.cookies.get(ctx.session_cookie_name)
    if not raw:
        return None
    resolved = await resolve_session(db, ctx, raw)
    if resolved is not None and resolved.rotated_token is not None:
        set_session_cookie(response, ctx, resolved.rotated_token, resolved.session.expires_at)
    return resolved


OptionalAuth = Annotated[ResolvedSession | None, Depends(optional_auth)]


async def require_auth(auth: OptionalAuth) -> ResolvedSession:
    if auth is None:
        raise NotAuthenticated
    return auth


Auth = Annotated[ResolvedSession, Depends(require_auth)]


async def require_owner(auth: Auth) -> ResolvedSession:
    if auth.membership.role != MemberRole.OWNER.value:
        raise Forbidden("Only the room owner can do that.", code="owner_only")
    return auth


Owner = Annotated[ResolvedSession, Depends(require_owner)]


def client_ip(request: Request) -> str:
    # uvicorn rewrites request.client from X-Forwarded-For only for proxies
    # listed in --forwarded-allow-ips (the local Next.js server by default).
    return request.client.host if request.client else "unknown"


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return origin.lower()
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}".lower()
    return None


async def csrf_protect(request: Request, ctx: Ctx, auth: OptionalAuth) -> None:
    """Origin check + signed double-submit token on every state-changing request."""
    if request.method in SAFE_METHODS:
        return
    origin = _request_origin(request)
    if origin is None or origin not in ctx.settings.allowed_origins:
        raise CsrfFailed(code="csrf_origin_mismatch")
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(ctx.csrf_cookie_name, "")
    binding = str(auth.session.id) if auth is not None else "anon"
    if header and cookie and tokens_equal(header, cookie) and ctx.csrf.verify(header, binding):
        return
    if auth is None and request.cookies.get(ctx.session_cookie_name):
        # A stale session cookie: tell the client to sign in again instead of
        # reporting a confusing CSRF failure.
        raise NotAuthenticated(
            "Your session has expired. Please sign in again.", code="session_expired"
        )
    raise CsrfFailed
