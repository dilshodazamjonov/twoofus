"""Login, logout, session introspection, CSRF token issuance, owner setup."""

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
from app.core.errors import AppError, NotFound
from app.core.ratelimit import BOOTSTRAP_PER_IP, LOGIN_PER_IP, LOGIN_PER_USERNAME
from app.core.security import tokens_equal
from app.models import RoomMember, User
from app.schemas.auth import (
    CsrfOut,
    LoginIn,
    OwnerSetupIn,
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


@router.get("/auth/csrf", response_model=CsrfOut, summary="Issue a CSRF token (and cookie)")
async def csrf_token(ctx: Ctx, auth: OptionalAuth, response: Response) -> CsrfOut:
    token = ctx.csrf.issue(str(auth.session.id) if auth else "anon")
    set_csrf_cookie(response, ctx, token)
    return CsrfOut(csrf_token=token)


@router.get("/auth/session", response_model=SessionOut, summary="Current user/session")
async def current_session(ctx: Ctx, auth: OptionalAuth, response: Response) -> SessionOut:
    if auth is None:
        token = ctx.csrf.issue("anon")
        set_csrf_cookie(response, ctx, token)
        return SessionOut(authenticated=False, csrf_token=token)
    token = ctx.csrf.issue(str(auth.session.id))
    set_csrf_cookie(response, ctx, token)
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
async def setup_status(ctx: Ctx, db: Db) -> SetupStatusOut:
    exists = await accounts.owner_exists(db)
    return SetupStatusOut(
        owner_exists=exists,
        web_bootstrap_enabled=ctx.settings.bootstrap_token is not None and not exists,
    )


@router.post(
    "/setup/owner",
    response_model=SessionOut,
    status_code=201,
    summary="One-time owner creation, only when BOOTSTRAP_TOKEN is configured",
)
async def setup_owner(
    body: OwnerSetupIn, request: Request, response: Response, ctx: Ctx, db: Db
) -> SessionOut:
    configured = ctx.settings.bootstrap_token
    if configured is None:
        raise NotFound  # the endpoint does not exist unless explicitly enabled
    ctx.rate_limiter.check(f"bootstrap:ip:{client_ip(request)}", BOOTSTRAP_PER_IP)
    if not tokens_equal(body.bootstrap_token, configured.get_secret_value()):
        raise AppError("Invalid bootstrap token.", code="invalid_bootstrap_token")
    user = await accounts.create_owner(
        db, ctx, username=body.username, display_name=body.display_name, password=body.password
    )
    response.status_code = 201
    return await start_session(db, ctx, response, user)
