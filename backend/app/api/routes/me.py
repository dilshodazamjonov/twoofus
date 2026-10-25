"""The signed-in member: profile, sharing consent, sessions, account deletion."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import Auth, Ctx, Db
from app.api.routes.auth import user_out
from app.auth.sessions import (
    active_sessions,
    clear_session_cookie,
    revoke_other_sessions,
    revoke_user_session,
    set_csrf_cookie,
)
from app.core.config import SHARING_NOTICE_VERSION
from app.core.errors import AppError, Conflict, NotFound
from app.core.ratelimit import SENSITIVE_PER_USER, SETTINGS_PER_USER
from app.models import SharePreference
from app.schemas.auth import UserOut
from app.schemas.me import (
    DeleteAccountIn,
    ProfileIn,
    RevokedOut,
    SessionInfoOut,
    SessionsOut,
    SharingIn,
    SharingOut,
)
from app.services import accounts, sharing
from app.services.provider_auth import get_connection, revoke_at_provider, stored_grant

router = APIRouter(tags=["me"])


class WrongPassword(AppError):
    status_code = 403
    code = "wrong_password"
    message = "That password is not correct."


def sharing_out(pref: SharePreference) -> SharingOut:
    return SharingOut(
        share_now_playing=pref.share_now_playing,
        current_notice_version=SHARING_NOTICE_VERSION,
        notice_version_acknowledged=pref.notice_version_acknowledged,
        acknowledged_at=pref.acknowledged_at,
        updated_at=pref.updated_at,
    )


@router.get("/me", response_model=UserOut, summary="Current member")
async def me(auth: Auth) -> UserOut:
    return user_out(auth.user, auth.membership)


@router.patch("/me", response_model=UserOut, summary="Update display name")
async def update_me(body: ProfileIn, ctx: Ctx, db: Db, auth: Auth) -> UserOut:
    ctx.rate_limiter.check(f"settings:user:{auth.user.id}", SETTINGS_PER_USER)
    user = await accounts.update_display_name(db, auth.user, body.display_name)
    return user_out(user, auth.membership)


@router.get("/me/sharing", response_model=SharingOut, summary="My sharing consent")
async def get_sharing(ctx: Ctx, db: Db, auth: Auth) -> SharingOut:
    return sharing_out(await sharing.get_preference(db, ctx, auth.user.id))


@router.put(
    "/me/sharing",
    response_model=SharingOut,
    summary="Turn 'Share my now-playing' on or off (takes effect immediately)",
)
async def put_sharing(body: SharingIn, ctx: Ctx, db: Db, auth: Auth) -> SharingOut:
    ctx.rate_limiter.check(f"settings:user:{auth.user.id}", SETTINGS_PER_USER)
    pref = await sharing.set_sharing(
        db,
        ctx,
        auth.user.id,
        enabled=body.share_now_playing,
        acknowledged_notice_version=body.acknowledged_notice_version,
    )
    if not pref.share_now_playing:
        conn = await get_connection(db, auth.user.id)
        if conn is not None:
            ctx.now_playing.evict(conn.id)
    return sharing_out(pref)


@router.get("/me/sessions", response_model=SessionsOut, summary="Where I am signed in")
async def my_sessions(ctx: Ctx, db: Db, auth: Auth) -> SessionsOut:
    # Only timestamps: no IP address or device details are ever stored.
    rows = await active_sessions(db, ctx, auth.user.id)
    return SessionsOut(
        sessions=[
            SessionInfoOut(
                id=row.id,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                current=row.id == auth.session.id,
            )
            for row in rows
        ]
    )


@router.post(
    "/me/sessions/revoke-others",
    response_model=RevokedOut,
    summary="Sign out everywhere except this device",
)
async def revoke_others(ctx: Ctx, db: Db, auth: Auth) -> RevokedOut:
    revoked = await revoke_other_sessions(
        db, ctx, user_id=auth.user.id, keep_session_id=auth.session.id
    )
    await db.commit()
    return RevokedOut(revoked=revoked)


@router.delete(
    "/me/sessions/{session_id}", status_code=204, summary="Sign out one of my other devices"
)
async def revoke_one(session_id: uuid.UUID, ctx: Ctx, db: Db, auth: Auth) -> Response:
    if session_id == auth.session.id:
        raise Conflict("Use “Sign out” to leave this device.", code="current_session")
    if not await revoke_user_session(db, ctx, user_id=auth.user.id, session_id=session_id):
        raise NotFound  # also for other people's sessions: no oracle
    await db.commit()
    return Response(status_code=204)


@router.delete("/me", status_code=204, summary="Delete my account and all my data")
async def delete_me(
    body: DeleteAccountIn, response: Response, ctx: Ctx, db: Db, auth: Auth
) -> Response:
    ctx.rate_limiter.check(f"sensitive:user:{auth.user.id}", SENSITIVE_PER_USER)
    if not await ctx.passwords.verify(auth.user.password_hash, body.password):
        raise WrongPassword
    conn = await get_connection(db, auth.user.id)
    grant = stored_grant(ctx, conn) if conn is not None else None
    if conn is not None:
        ctx.now_playing.evict(conn.id)
    await accounts.delete_account(db, ctx, auth.user.id)
    await revoke_at_provider(ctx, grant)  # best effort, after everything local is gone
    out = Response(status_code=204)
    clear_session_cookie(out, ctx)
    set_csrf_cookie(out, ctx, ctx.csrf.issue("anon"))
    return out
