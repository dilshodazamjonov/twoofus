"""Login, logout, session introspection, CSRF token issuance, setup status."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Ctx, Db, OptionalAuth, client_ip
from app.auth.sessions import (
    clear_session_cookie,
    create_session,
    revoke_session,
    set_csrf_cookie,
    set_session_cookie,
)
from app.context import AppContext
from app.core.errors import AppError
from app.core.ratelimit import LOGIN_PER_IP, LOGIN_PER_USERNAME
from app.models import RoomMember, User
from app.schemas.auth import (
    CsrfOut,
    LoginIn,
    SessionOut,
    SetupStatusOut,
    UserOut,
)
from app.services import accounts

router = APIRouter(tags=["auth"])


class InvalidCredentials(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Wrong username or password."


def user_out(user: User, membership: RoomMember) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=membership.role,  # type: ignore[arg-type]  # constrained by a CHECK
    )


async def start_session(
    db: AsyncSession,
    ctx: AppContext,
    response: Response,
    user: User,
    previous_session_id: uuid.UUID | None = None,
) -> SessionOut:
    """Issue a brand-new session (never reuse one: prevents session fixation)."""
    if previous_session_id is not None:
        await revoke_session(db, ctx, previous_session_id)
    session, token = await create_session(db, ctx, user.id)
    membership = (
        await db.execute(select(RoomMember).where(RoomMember.user_id == user.id))
    ).scalar_one()
    await db.commit()
    set_session_cookie(response, ctx, token, session.expires_at)
    csrf = ctx.csrf.issue(str(session.id))
    set_csrf_cookie(response, ctx, csrf)
    return SessionOut(
        authenticated=True,
        user=user_out(user, membership),
        session_expires_at=session.expires_at,
        csrf_token=csrf,
    )


def ensure_csrf_token(request: Request, response: Response, ctx: AppContext, binding: str) -> str:
    """Keep the browser's CSRF token while it is still valid for ``binding``.

    Issuing a new value on every read would race with writes already in
    flight (their header would no longer match the cookie). A new token is
    minted only when there is none, or it belongs to another session.
    """
    current = request.cookies.get(ctx.csrf_cookie_name, "")
    token = current if current and ctx.csrf.verify(current, binding) else ctx.csrf.issue(binding)
    set_csrf_cookie(response, ctx, token)
    return token


@router.get("/auth/csrf", response_model=CsrfOut, summary="Issue a CSRF token (and cookie)")
async def csrf_token(request: Request, ctx: Ctx, auth: OptionalAuth, response: Response) -> CsrfOut:
    binding = str(auth.session.id) if auth else "anon"
    return CsrfOut(csrf_token=ensure_csrf_token(request, response, ctx, binding))


@router.get("/auth/session", response_model=SessionOut, summary="Current user/session")
async def current_session(
    request: Request, ctx: Ctx, auth: OptionalAuth, response: Response
) -> SessionOut:
    if auth is None:
        stale = request.cookies.get(ctx.session_cookie_name) is not None
        if stale:
            clear_session_cookie(response, ctx)
        token = ensure_csrf_token(request, response, ctx, "anon")
        return SessionOut(authenticated=False, csrf_token=token, session_expired=stale)
    token = ensure_csrf_token(request, response, ctx, str(auth.session.id))
    return SessionOut(
        authenticated=True,
        user=user_out(auth.user, auth.membership),
        session_expires_at=auth.session.expires_at,
        csrf_token=token,
    )


@router.post("/auth/login", response_model=SessionOut, summary="Sign in")
async def login(
    body: LoginIn, request: Request, response: Response, ctx: Ctx, db: Db, auth: OptionalAuth
) -> SessionOut:
    ctx.rate_limiter.check(f"login:ip:{client_ip(request)}", LOGIN_PER_IP)
    ctx.rate_limiter.check(
        f"login:user:{accounts.normalize_username(body.username)}", LOGIN_PER_USERNAME
    )
    user = await accounts.authenticate(db, ctx, body.username, body.password)
    if user is None:
        raise InvalidCredentials
    return await start_session(
        db, ctx, response, user, previous_session_id=auth.session.id if auth else None
    )


@router.post("/auth/logout", response_model=SessionOut, summary="Sign out (revokes the session)")
async def logout(ctx: Ctx, db: Db, auth: OptionalAuth, response: Response) -> SessionOut:
    if auth is not None:
        await revoke_session(db, ctx, auth.session.id)
        await db.commit()
    clear_session_cookie(response, ctx)
    token = ctx.csrf.issue("anon")
    set_csrf_cookie(response, ctx, token)
    return SessionOut(authenticated=False, csrf_token=token)


@router.get("/setup/status", response_model=SetupStatusOut, summary="Is the owner set up?")
async def setup_status(db: Db) -> SetupStatusOut:
    # The owner is created on the server with `python -m app.cli.bootstrap_owner`;
    # the sign-in page uses this to explain a fresh, not-yet-initialised install.
    return SetupStatusOut(owner_exists=await accounts.owner_exists(db))
