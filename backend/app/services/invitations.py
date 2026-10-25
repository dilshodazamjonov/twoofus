"""Single-use, short-lived partner invitations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import AppError, Conflict
from app.core.security import hash_token, new_token
from app.models import Invitation, MemberRole, RoomMember, SharePreference, User
from app.services.accounts import validate_new_account


class InvitationInvalid(AppError):
    # One code for unknown, expired, revoked and used invitations: no oracle.
    status_code = 400
    code = "invitation_invalid"
    message = "This invitation link is invalid or has expired."


@dataclass(frozen=True, slots=True)
class CreatedInvitation:
    token: str
    expires_at: datetime


def _pending(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        Invitation.consumed_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > now,
    )


async def _member_count(db: AsyncSession, room_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(RoomMember).where(RoomMember.room_id == room_id)
        )
    ).scalar_one()


async def create_invitation(
    db: AsyncSession, ctx: AppContext, *, room_id: uuid.UUID, owner_id: uuid.UUID
) -> CreatedInvitation:
    if await _member_count(db, room_id) >= 2:
        raise Conflict("Your room already has two members.", code="room_full")
    now = ctx.clock()
    # Only one live invitation at a time: issuing a new one revokes the old.
    await db.execute(
        update(Invitation)
        .where(Invitation.room_id == room_id, *_pending(now))
        .values(revoked_at=now)
    )
    token = new_token()
    expires_at = now + timedelta(hours=ctx.settings.invite_ttl_hours)
    db.add(
        Invitation(
            room_id=room_id,
            created_by_user_id=owner_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return CreatedInvitation(token=token, expires_at=expires_at)


async def current_invitation(
    db: AsyncSession, ctx: AppContext, room_id: uuid.UUID
) -> Invitation | None:
    return (
        await db.execute(
            select(Invitation)
            .where(Invitation.room_id == room_id, *_pending(ctx.clock()))
            .order_by(Invitation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def revoke_pending(db: AsyncSession, ctx: AppContext, room_id: uuid.UUID) -> bool:
    now = ctx.clock()
    result = await db.execute(
        update(Invitation)
        .where(Invitation.room_id == room_id, *_pending(now))
        .values(revoked_at=now)
    )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


async def inspect_invitation(
    db: AsyncSession, ctx: AppContext, token: str
) -> tuple[Invitation, str]:
    """Return the pending invitation and the inviter's display name."""
    row = (
        await db.execute(
            select(Invitation, User.display_name)
            .join(User, User.id == Invitation.created_by_user_id)
            .where(Invitation.token_hash == hash_token(token), *_pending(ctx.clock()))
        )
    ).first()
    if row is None:
        raise InvitationInvalid
    invitation, inviter_name = row
    if await _member_count(db, invitation.room_id) >= 2:
        raise InvitationInvalid
    return invitation, inviter_name


async def accept_invitation(
    db: AsyncSession,
    ctx: AppContext,
    *,
    token: str,
    username: str,
    display_name: str,
    password: str,
) -> User:
    """Consume the invitation and create the partner, atomically.

    The conditional UPDATE ... RETURNING marks the invitation used only if it is
    still pending; the membership insert relies on the (room_id, slot) primary
    key. Both happen in one transaction, so a failure rolls everything back and
    two racing accepts can never both succeed.
    """
    name, display = validate_new_account(username, display_name, password)
    password_hash = await ctx.passwords.hash(password)  # slow: do it before locking rows
    now = ctx.clock()

    consumed = (
        await db.execute(
            update(Invitation)
            .where(Invitation.token_hash == hash_token(token), *_pending(now))
            .values(consumed_at=now)
            .returning(Invitation.id, Invitation.room_id)
        )
    ).first()
    if consumed is None:
        await db.rollback()
        raise InvitationInvalid
    invitation_id, room_id = consumed

    taken = set(
        (await db.execute(select(RoomMember.slot).where(RoomMember.room_id == room_id))).scalars()
    )
    free = [slot for slot in (1, 2) if slot not in taken]
    if not free:
        await db.rollback()
        raise InvitationInvalid

    user = User(
        username=name,
        display_name=display,
        password_hash=password_hash,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise Conflict("That username is taken.", code="username_taken") from None
    try:
        db.add(
            RoomMember(
                room_id=room_id,
                slot=free[0],
                user_id=user.id,
                role=MemberRole.PARTNER.value,
                joined_at=now,
            )
        )
        db.add(SharePreference(user_id=user.id, share_now_playing=False, updated_at=now))
        await db.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(consumed_by_user_id=user.id)
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise InvitationInvalid from None
    return user
