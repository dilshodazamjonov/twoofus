"""Owner bootstrap, login, profile and account deletion."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import password_problem
from app.context import AppContext
from app.core.errors import AppError, Conflict
from app.models import MemberRole, Room, RoomMember, SharePreference, User

USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{2,31}")


class InvalidInput(AppError):
    status_code = 422
    code = "invalid_input"


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_new_account(username: str, display_name: str, password: str) -> tuple[str, str]:
    """Validate and normalise new-account input; raise InvalidInput on problems."""
    name = normalize_username(username)
    if not USERNAME_RE.fullmatch(name):
        raise InvalidInput(
            "Usernames are 3-32 characters: letters, digits, '.', '_' or '-', "
            "starting with a letter or digit.",
            code="invalid_username",
        )
    display = " ".join(display_name.split())
    if not 1 <= len(display) <= 40:
        raise InvalidInput("Display names are 1-40 characters.", code="invalid_display_name")
    problem = password_problem(password, username=name)
    if problem:
        raise InvalidInput(problem, code="weak_password")
    return name, display


async def owner_exists(db: AsyncSession) -> bool:
    count = (
        await db.execute(
            select(func.count())
            .select_from(RoomMember)
            .where(RoomMember.role == MemberRole.OWNER.value)
        )
    ).scalar_one()
    return count > 0


async def create_owner(
    db: AsyncSession, ctx: AppContext, *, username: str, display_name: str, password: str
) -> User:
    """Create the single room and its owner. Fails if any user already exists."""
    name, display = validate_new_account(username, display_name, password)
    if (await db.execute(select(func.count()).select_from(User))).scalar_one() > 0:
        raise Conflict("This instance already has an owner.", code="already_bootstrapped")
    password_hash = await ctx.passwords.hash(password)
    now = ctx.clock()
    room = Room(created_at=now)
    user = User(
        username=name,
        display_name=display,
        password_hash=password_hash,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add_all([room, user])
    try:
        await db.flush()
        db.add(
            RoomMember(
                room_id=room.id, slot=1, user_id=user.id, role=MemberRole.OWNER.value, joined_at=now
            )
        )
        db.add(SharePreference(user_id=user.id, share_now_playing=False, updated_at=now))
        await db.commit()
    except IntegrityError:
        # The singleton room constraint lost a race with a concurrent bootstrap.
        await db.rollback()
        raise Conflict("This instance already has an owner.", code="already_bootstrapped") from None
    return user


async def authenticate(
    db: AsyncSession, ctx: AppContext, username: str, password: str
) -> User | None:
    user = (
        await db.execute(select(User).where(User.username == normalize_username(username)))
    ).scalar_one_or_none()
    # Always run one Argon2 verification so timing does not reveal unknown users.
    ok = await ctx.passwords.verify(user.password_hash if user else None, password)
    if not ok or user is None:
        return None
    if ctx.passwords.needs_rehash(user.password_hash):
        user.password_hash = await ctx.passwords.hash(password)
        await db.flush()
    return user


async def update_display_name(db: AsyncSession, user: User, display_name: str) -> User:
    display = " ".join(display_name.split())
    if not 1 <= len(display) <= 40:
        raise InvalidInput("Display names are 1-40 characters.", code="invalid_display_name")
    user.display_name = display
    await db.commit()
    return user


async def delete_account(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> None:
    """Delete a member and everything that belongs to them.

    Sessions, provider credentials, pending authorisations, share preferences
    and invitations they created are removed by ON DELETE CASCADE. If the owner
    leaves, the partner becomes owner (so they can invite again or delete the
    room); if the room ends up empty it is deleted too.
    """
    membership = (
        await db.execute(select(RoomMember).where(RoomMember.user_id == user_id))
    ).scalar_one()
    room_id, was_owner = membership.room_id, membership.role == MemberRole.OWNER.value

    await db.execute(delete(User).where(User.id == user_id))
    remaining = (
        (await db.execute(select(RoomMember).where(RoomMember.room_id == room_id))).scalars().all()
    )
    if not remaining:
        await db.execute(delete(Room).where(Room.id == room_id))
    elif was_owner:
        await db.execute(
            update(RoomMember)
            .where(RoomMember.room_id == room_id, RoomMember.user_id == remaining[0].user_id)
            .values(role=MemberRole.OWNER.value)
        )
    await db.commit()
