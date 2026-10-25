"""The signed-in member: profile, sharing consent, account deletion."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import Auth, Ctx, Db
from app.api.routes.auth import user_out
from app.auth.sessions import clear_session_cookie, set_csrf_cookie
from app.core.config import SHARING_NOTICE_VERSION
from app.core.errors import AppError
from app.core.ratelimit import SENSITIVE_PER_USER
from app.models import SharePreference
from app.schemas.auth import UserOut
from app.schemas.me import DeleteAccountIn, ProfileIn, SharingIn, SharingOut
from app.services import accounts, sharing
from app.services.provider_auth import get_connection

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
async def update_me(body: ProfileIn, db: Db, auth: Auth) -> UserOut:
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


@router.delete("/me", status_code=204, summary="Delete my account and all my data")
async def delete_me(
    body: DeleteAccountIn, response: Response, ctx: Ctx, db: Db, auth: Auth
) -> Response:
    ctx.rate_limiter.check(f"sensitive:user:{auth.user.id}", SENSITIVE_PER_USER)
    if not await ctx.passwords.verify(auth.user.password_hash, body.password):
        raise WrongPassword
    conn = await get_connection(db, auth.user.id)
    if conn is not None:
        ctx.now_playing.evict(conn.id)
    await accounts.delete_account(db, ctx, auth.user.id)
    out = Response(status_code=204)
    clear_session_cookie(out, ctx)
    set_csrf_cookie(out, ctx, ctx.csrf.issue("anon"))
    return out
