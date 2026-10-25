"""Server-managed sessions: creation, lookup (with idle expiry and periodic
token rotation), revocation, and the matching cookies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from starlette.responses import Response

from app.context import AppContext
from app.core.security import hash_token, new_token
from app.models import AuthSession, RoomMember, User

_TOUCH_INTERVAL = timedelta(seconds=60)
# How long the token replaced by a rotation keeps working. Requests that were
# already in flight with the old cookie (two polls racing, a slow network)
# would otherwise fail with 401 and sign the person out.
ROTATION_GRACE = timedelta(minutes=2)


@dataclass
class ResolvedSession:
    session: AuthSession
    user: User
    membership: RoomMember
    rotated_token: str | None  # set when the token was rotated during this request


async def create_session(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID
) -> tuple[AuthSession, str]:
    now = ctx.clock()
    token = new_token()
    session = AuthSession(
        user_id=user_id,
        token_hash=hash_token(token),
        created_at=now,
        rotated_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=ctx.settings.session_ttl_days),
    )
    db.add(session)
    await db.flush()
    return session, token


async def resolve_session(
    db: AsyncSession, ctx: AppContext, raw_token: str
) -> ResolvedSession | None:
    if not raw_token or len(raw_token) > 128:
        return None
    now = ctx.clock()
    presented = hash_token(raw_token)
    row = (
        await db.execute(
            select(AuthSession, User, RoomMember)
            .join(User, User.id == AuthSession.user_id)
            .join(RoomMember, RoomMember.user_id == User.id)
            .where(
                or_(
                    AuthSession.token_hash == presented,
                    and_(
                        AuthSession.previous_token_hash == presented,
                        AuthSession.rotated_at > now - ROTATION_GRACE,
                    ),
                ),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
    ).first()
    if row is None:
        return None
    session, user, membership = row
    if session.last_seen_at < now - timedelta(days=ctx.settings.session_idle_days):
        session.revoked_at = now
        await db.commit()
        return None

    rotated: str | None = None
    changed = False
    if session.token_hash == presented and session.rotated_at < now - timedelta(
        hours=ctx.settings.session_rotate_hours
    ):
        rotated = await _rotate(db, session, presented, now)
        changed = True
    if session.last_seen_at < now - _TOUCH_INTERVAL:
        session.last_seen_at = now
        changed = True
    if changed:
        await db.commit()
    return ResolvedSession(session=session, user=user, membership=membership, rotated_token=rotated)


async def _rotate(
    db: AsyncSession, session: AuthSession, presented: str, now: datetime
) -> str | None:
    """Swap in a new token, unless a concurrent request has just rotated it.

    The conditional UPDATE lets exactly one of several simultaneous requests
    win; the others keep using the old token, which the grace period covers.
    Only the winner's response sets a new cookie.
    """
    token = new_token()
    won = (
        await db.execute(
            update(AuthSession)
            .where(AuthSession.id == session.id, AuthSession.token_hash == presented)
            .values(token_hash=hash_token(token), previous_token_hash=presented, rotated_at=now)
            .returning(AuthSession.id)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if won is None:
        return None
    # Mirror the UPDATE on the loaded object without scheduling another write.
    set_committed_value(session, "token_hash", hash_token(token))
    set_committed_value(session, "previous_token_hash", presented)
    set_committed_value(session, "rotated_at", now)
    return token


async def revoke_session(db: AsyncSession, ctx: AppContext, session_id: uuid.UUID) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=ctx.clock())
    )


async def revoke_all_sessions(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=ctx.clock())
    )


async def active_sessions(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID
) -> list[AuthSession]:
    """The member's live sessions, most recently used first."""
    now = ctx.clock()
    rows = await db.execute(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            AuthSession.last_seen_at > now - timedelta(days=ctx.settings.session_idle_days),
        )
        .order_by(AuthSession.last_seen_at.desc())
    )
    return list(rows.scalars())


async def revoke_user_session(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> bool:
    """Revoke one of the member's own sessions; False if there is no such session."""
    revoked = (
        await db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == session_id,
                AuthSession.user_id == user_id,  # never someone else's session
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=ctx.clock())
            .returning(AuthSession.id)
        )
    ).scalar_one_or_none()
    return revoked is not None


async def revoke_other_sessions(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, keep_session_id: uuid.UUID
) -> int:
    revoked = await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.id != keep_session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=ctx.clock())
        .returning(AuthSession.id)
    )
    # The ids this UPDATE ... RETURNING changed (there is no SELECT to count instead).
    revoked_ids = revoked.scalars().all()
    return len(revoked_ids)


def _max_age(expires_at: datetime, now: datetime) -> int:
    return max(0, int((expires_at - now).total_seconds()))


def set_session_cookie(
    response: Response, ctx: AppContext, token: str, expires_at: datetime
) -> None:
    response.set_cookie(
        ctx.session_cookie_name,
        token,
        max_age=_max_age(expires_at, ctx.clock()),
        path="/",
        secure=ctx.settings.secure_cookies,
        httponly=True,
        samesite="lax",  # sent on top-level navigation back from the OAuth provider
    )


def clear_session_cookie(response: Response, ctx: AppContext) -> None:
    response.delete_cookie(
        ctx.session_cookie_name,
        path="/",
        secure=ctx.settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )


def set_csrf_cookie(response: Response, ctx: AppContext, token: str) -> None:
    response.set_cookie(
        ctx.csrf_cookie_name,
        token,
        max_age=ctx.settings.session_ttl_days * 86400,
        path="/",
        secure=ctx.settings.secure_cookies,
        httponly=False,  # double-submit: the frontend echoes it in X-CSRF-Token
        samesite="strict",
    )
